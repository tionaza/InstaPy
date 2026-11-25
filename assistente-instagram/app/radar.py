"""Radar de público: hashtags e concorrentes (somente leitura, API oficial).

Não curte nem comenta sozinho. Gera uma lista de publicações relevantes com
sugestão de comentário para VOCÊ interagir manualmente pelo app do Instagram.
"""
import logging

from . import ai, graph
from .db import db, get_config

log = logging.getLogger("radar")


def _suggestion(caption: str) -> str | None:
    cfg = get_config()
    if cfg.get("usar_ia") != "1":
        return None
    return ai.suggest(
        cfg.get("contexto_ia", "")
        + " Agora você escreve um comentário público, genuíno e útil, sem autopromoção, "
        "sem oferecer serviços e sem pedir contato.",
        "comentario_em_publicacao_de_terceiro",
        caption or "",
    )


def _save_item(source_id: int, m: dict) -> bool:
    with db() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO radar_items(source_id, media_id, permalink, caption, like_count, "
            "comments_count, timestamp) VALUES (?,?,?,?,?,?,?)",
            (source_id, m.get("id"), m.get("permalink"), (m.get("caption") or "")[:1000],
             m.get("like_count"), m.get("comments_count"), m.get("timestamp")),
        )
        if cur.rowcount:
            sug = _suggestion(m.get("caption", ""))
            if sug:
                c.execute("UPDATE radar_items SET suggestion=? WHERE id=?", (sug, cur.lastrowid))
            return True
    return False


def run_once() -> dict:
    with db() as c:
        sources = [dict(r) for r in c.execute("SELECT * FROM radar_sources WHERE active=1")]
    stats = {"novos": 0, "erros": []}
    for s in sources:
        try:
            if s["kind"] == "hashtag":
                media = graph.hashtag_recent_media(s["value"].lstrip("#"))
            else:
                snap = graph.competitor_snapshot(s["value"].lstrip("@"))
                media = snap.get("media", {}).get("data", [])
                if media:
                    likes = [m.get("like_count") or 0 for m in media]
                    comms = [m.get("comments_count") or 0 for m in media]
                    with db() as c:
                        c.execute(
                            "INSERT INTO competitor_stats(username, followers_count, media_count, "
                            "avg_likes, avg_comments) VALUES (?,?,?,?,?)",
                            (s["value"], snap.get("followers_count"), snap.get("media_count"),
                             sum(likes) / len(likes), sum(comms) / len(comms)),
                        )
            for m in media:
                stats["novos"] += _save_item(s["id"], m)
        except Exception as exc:  # noqa: BLE001
            log.warning("Radar falhou para %s: %s", s["value"], exc)
            stats["erros"].append(f"{s['value']}: {exc}")
    return stats
