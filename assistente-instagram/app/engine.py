"""Regras de resposta, fila de aprovação e envio."""
import hashlib
import hmac
import logging
import unicodedata

from . import ai, graph
from .config import settings
from .db import db, get_config

log = logging.getLogger("engine")


def verify_signature(body: bytes, header: str | None) -> bool:
    if not settings.app_secret:
        return False
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower()


def match_rule(text: str, channel: str, rules: list[dict]) -> str | None:
    t = _norm(text)
    for r in rules:
        if not r["active"] or r["channel"] not in (channel, "ambos"):
            continue
        for kw in r["keywords"].split(","):
            kw = _norm(kw.strip())
            if kw and kw in t:
                return r["reply"]
    return None


def build_reply(kind: str, text: str) -> tuple[str, str]:
    """Retorna (texto, origem)."""
    cfg = get_config()
    channel = "comentario" if kind == "comentario" else "direct"
    with db() as c:
        rules = [dict(r) for r in c.execute("SELECT * FROM rules ORDER BY id")]
    hit = match_rule(text, channel, rules)
    if hit:
        return hit, "regra"
    if cfg.get("usar_ia") == "1":
        s = ai.suggest(cfg.get("contexto_ia", ""), channel, text)
        if s:
            return s, "ia"
    return cfg[f"resposta_padrao_{channel}"], "padrao"


def _sent_last_hour() -> int:
    with db() as c:
        return c.execute(
            "SELECT COUNT(*) FROM actions WHERE status IN ('enviado','simulado') "
            "AND done_at >= datetime('now','-1 hour')"
        ).fetchone()[0]


def execute(action_id: int) -> str:
    with db() as c:
        a = dict(c.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone())
    status, error = "enviado", None
    try:
        if settings.dry_run:
            log.info("[DRY_RUN] %s -> %s: %s", a["kind"], a["target_id"], a["text"])
            status = "simulado"
        elif a["kind"] == "responder_comentario":
            graph.reply_to_comment(a["target_id"], a["text"])
        elif a["kind"] == "responder_direct":
            graph.send_direct(a["target_id"], a["text"])
        elif a["kind"] == "direct_privado":
            graph.private_reply_to_comment(a["target_id"], a["text"])
    except Exception as exc:  # noqa: BLE001
        status, error = "erro", str(exc)[:500]
    with db() as c:
        c.execute(
            "UPDATE actions SET status=?, error=?, done_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, error, action_id),
        )
    return status


def _queue(event_id: int, kind: str, target: str, text: str, source: str, mode: str) -> None:
    with db() as c:
        cur = c.execute(
            "INSERT INTO actions(event_id, kind, target_id, text, source) VALUES (?,?,?,?,?)",
            (event_id, kind, target, text, source),
        )
        aid = cur.lastrowid
    if mode == "automatico" and _sent_last_hour() < settings.max_auto_per_hour:
        execute(aid)


def _recently_answered(target: str, hours: int = 12) -> bool:
    with db() as c:
        return c.execute(
            "SELECT 1 FROM actions WHERE kind='responder_direct' AND target_id=? "
            "AND created_at >= datetime('now', ?)",
            (target, f"-{hours} hours"),
        ).fetchone() is not None


def _store_event(kind, ext_id, sender, username, media, text) -> int | None:
    with db() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO events(kind, external_id, sender_id, username, media_id, text) "
            "VALUES (?,?,?,?,?,?)",
            (kind, ext_id, sender, username, media, text),
        )
        return cur.lastrowid if cur.rowcount else None


def handle_webhook(payload: dict) -> int:
    """Processa o JSON do webhook. Retorna quantos eventos novos foram registrados."""
    if payload.get("object") not in ("instagram", "page"):
        return 0
    cfg = get_config()
    new = 0
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            if ch.get("field") != "comments":
                continue
            v = ch.get("value", {})
            sender = v.get("from", {})
            if sender.get("id") == settings.ig_user_id:
                continue  # comentário da própria conta
            ev = _store_event("comentario", v.get("id"), sender.get("id"), sender.get("username"),
                              v.get("media", {}).get("id"), v.get("text", ""))
            if not ev:
                continue
            new += 1
            mode = cfg.get("modo_comentario", "aprovacao")
            if mode == "desligado":
                continue
            text, src = build_reply("comentario", v.get("text", ""))
            _queue(ev, "responder_comentario", v["id"], text, src, mode)
            if cfg.get("direct_privado_em_comentario") == "1":
                _queue(ev, "direct_privado", v["id"], cfg["resposta_padrao_direct"], "padrao",
                       cfg.get("modo_direct", "aprovacao"))
        for m in entry.get("messaging", []):
            msg = m.get("message") or {}
            if not msg or msg.get("is_echo"):
                continue
            sid = m.get("sender", {}).get("id")
            ev = _store_event("direct", msg.get("mid"), sid, None, None, msg.get("text", ""))
            if not ev:
                continue
            new += 1
            mode = cfg.get("modo_direct", "aprovacao")
            if mode == "desligado":
                continue
            text, src = build_reply("direct", msg.get("text", ""))
            if src == "padrao" and _recently_answered(sid):
                continue  # não repete a mensagem padrão na mesma conversa
            _queue(ev, "responder_direct", sid, text, src, mode)
    return new
