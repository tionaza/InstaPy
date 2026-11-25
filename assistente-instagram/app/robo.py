"""Robô em modo NÃO OFICIAL (login direto na conta, via instagrapi).

ATENÇÃO: viola os Termos de Uso do Instagram. A conta pode receber bloqueios
temporários ("Action Blocked"), pedidos de verificação ou ser desativada.
As travas abaixo reduzem esse risco, mas não o eliminam:

- limites diários de curtidas e comentários, e um teto de perfis por ciclo;
- intervalos longos e variáveis entre ações e horário de funcionamento;
- pausa automática de 24h em qualquer bloqueio/desafio do Instagram;
- comentários em perfis de terceiros passam por aprovação, por padrão.

Não envia Direct para quem nunca falou com a conta (spam em massa): o Direct
é usado só para responder conversas que a pessoa iniciou.
"""

import logging
import random
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import ai
from .config import settings
from .db import db, get_config, set_config

log = logging.getLogger("robo")
KINDS = {
    "curtir",
    "comentar_publico",
    "robo_responder_comentario",
    "robo_responder_direct",
}
_lock = threading.Lock()
_client = None


# ---------------------------------------------------------------- utilidades
def registrar(nivel: str, msg: str) -> None:
    log.info("%s %s", nivel, msg)
    with db() as c:
        c.execute(
            "INSERT INTO robo_log(nivel, mensagem) VALUES (?,?)", (nivel, msg[:500])
        )
        c.execute(
            "DELETE FROM robo_log WHERE id < (SELECT MAX(id) - 500 FROM robo_log)"
        )


def agora() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def pausado_ate() -> datetime | None:
    v = get_config().get("robo_pausado_ate")
    if not v:
        return None
    dt = datetime.fromisoformat(v)
    return dt if dt > agora() else None


def pausar(horas: float, motivo: str) -> None:
    ate = agora() + timedelta(hours=horas)
    set_config({"robo_pausado_ate": ate.isoformat(timespec="minutes")})
    registrar("PAUSA", f"Robô pausado até {ate:%d/%m %H:%M}: {motivo}")


def em_horario(cfg: dict) -> bool:
    h = agora().hour
    return int(cfg["hora_inicio"]) <= h < int(cfg["hora_fim"])


def feitos_hoje(kind: str) -> int:
    inicio = agora().replace(hour=0, minute=0, second=0).astimezone(ZoneInfo("UTC"))
    with db() as c:
        return c.execute(
            "SELECT COUNT(*) FROM actions WHERE kind=? AND status IN ('enviado','simulado') "
            "AND done_at >= ?",
            (kind, inicio.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()[0]


def espera(cfg: dict) -> None:
    time.sleep(random.uniform(int(cfg["intervalo_min_s"]), int(cfg["intervalo_max_s"])))


def ja_visto(ref: str) -> bool:
    with db() as c:
        cur = c.execute("INSERT OR IGNORE INTO robo_vistos(ref) VALUES (?)", (ref,))
        return cur.rowcount == 0


# ---------------------------------------------------------------- login
def cliente(verification_code: str = ""):
    """Retorna o cliente logado, reaproveitando a sessão salva no volume."""
    global _client
    if _client is not None and not verification_code:
        return _client
    from instagrapi import Client

    if not settings.ig_username or not settings.ig_password:
        raise RuntimeError("Defina IG_USERNAME e IG_PASSWORD no .env")
    cl = Client()
    cl.delay_range = [2, 6]
    cl.set_locale("pt_BR")
    cl.set_country("BR")
    cl.set_timezone_offset(-3 * 3600)
    try:
        cl.load_settings(settings.session_path)
    except FileNotFoundError:
        pass
    code = verification_code
    if not code and settings.ig_totp_secret:
        code = cl.totp_generate_code(settings.ig_totp_secret)
    cl.login(settings.ig_username, settings.ig_password, verification_code=code)
    try:
        cl.get_timeline_feed()  # valida a sessão
    except Exception:  # noqa: BLE001
        cl.relogin()
    cl.dump_settings(settings.session_path)
    _client = cl
    set_config({"robo_status": f"conectado como @{settings.ig_username}"})
    registrar("LOGIN", f"Conectado como @{settings.ig_username}")
    return cl


def tratar_erro(exc: Exception) -> None:
    """Qualquer sinal de bloqueio pausa o robô para proteger a conta."""
    global _client
    nome = type(exc).__name__
    if nome in ("FeedbackRequired", "PleaseWaitFewMinutes", "RateLimitError"):
        pausar(24, f"Instagram limitou as ações ({nome}). Não force, aguarde.")
    elif "Challenge" in nome or nome in (
        "LoginRequired",
        "ClientLoginRequired",
        "TwoFactorRequired",
        "BadPassword",
    ):
        _client = None
        set_config({"robo_status": f"precisa de verificação: {nome}"})
        pausar(
            24,
            f"Login/verificação necessária ({nome}). Abra o app do Instagram, "
            "confirme que foi você e clique em Conectar no painel.",
        )
    else:
        registrar("ERRO", f"{nome}: {exc}")


# ---------------------------------------------------------------- execução de ações
def perform(a: dict) -> None:
    cl = cliente()
    k, alvo, texto = a["kind"], a["target_id"], a["text"]
    if k == "curtir":
        cl.media_like(alvo)
    elif k == "comentar_publico":
        cl.media_comment(alvo, texto)
    elif k == "robo_responder_comentario":
        media_id, comment_pk = alvo.split(":", 1)
        cl.media_comment(media_id, texto, replied_to_comment_id=int(comment_pk))
    elif k == "robo_responder_direct":
        cl.direct_answer(int(alvo), texto)


def _executar(aid: int) -> bool:
    from .engine import execute

    with db() as c:
        row = c.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
    status = execute(aid)
    if status == "erro":
        with db() as c:
            err = c.execute("SELECT error FROM actions WHERE id=?", (aid,)).fetchone()[
                0
            ]
        registrar("ERRO", f"{row['kind']}: {err}")
        return False
    return True


def _criar(kind: str, alvo: str, texto: str, origem: str, ref_text: str = "") -> int:
    from .engine import _store_event

    ev = _store_event(
        "robo", f"{kind}:{alvo}:{time.time()}", None, None, None, ref_text
    )
    with db() as c:
        cur = c.execute(
            "INSERT INTO actions(event_id, kind, target_id, text, source) VALUES (?,?,?,?,?)",
            (ev, kind, alvo, texto, origem),
        )
        return cur.lastrowid


# ---------------------------------------------------------------- etapas do ciclo
def comentario_para(caption: str, cfg: dict) -> tuple[str, str]:
    if cfg.get("usar_ia") == "1":
        from .engine import ai_context

        s = ai.suggest(
            ai_context(cfg)
            + "\n\nAgora escreva um comentário público curto (até 2 frases) numa publicação "
            "de outra pessoa. Seja genuíno e acrescente algo ao assunto, como um bom membro "
            "da comunidade. Nada genérico ('top!'), sem autopromoção, sem oferecer serviços, "
            "sem pedir que chamem no Direct.",
            "comentario_em_publicacao_de_terceiro",
            caption or "(publicação sem legenda)",
        )
        if s:
            return s, "ia"
    modelos = [m.strip() for m in cfg["modelos_comentario"].splitlines() if m.strip()]
    return random.choice(modelos), "modelo"


def coletar_publico(cl, cfg: dict) -> int:
    """Alimenta a tabela 'publico' com seguidores de concorrentes e autores de hashtags."""
    with db() as c:
        fontes = [
            dict(r) for r in c.execute("SELECT * FROM radar_sources WHERE active=1")
        ]
        restantes = c.execute(
            "SELECT COUNT(*) FROM publico WHERE status='novo'"
        ).fetchone()[0]
    if restantes >= 50 or not fontes:
        return 0
    novos = 0
    for f in random.sample(fontes, len(fontes)):
        try:
            if f["kind"] == "concorrente":
                uid = cl.user_id_from_username(f["value"])
                pessoas = cl.user_followers(
                    uid, amount=int(cfg["seguidores_por_concorrente"])
                )
                lista = [(str(pk), u.username) for pk, u in pessoas.items()]
            else:
                medias = cl.hashtag_medias_recent(f["value"], amount=20)
                lista = [(str(m.user.pk), m.user.username) for m in medias]
        except Exception as exc:  # noqa: BLE001
            tratar_erro(exc)
            if pausado_ate():
                return novos
            continue
        with db() as c:
            for pk, un in lista:
                if pk == str(cl.user_id):
                    continue
                cur = c.execute(
                    "INSERT OR IGNORE INTO publico(user_pk, username, origem) VALUES (?,?,?)",
                    (pk, un, f["value"]),
                )
                novos += cur.rowcount
        espera(cfg)
    registrar("PUBLICO", f"{novos} novos perfis no público-alvo")
    return novos


def engajar_publico(cl, cfg: dict) -> None:
    lim_like = int(cfg["limite_curtidas_dia"])
    lim_com = int(cfg["limite_comentarios_dia"])
    with db() as c:
        alvos = c.execute(
            "SELECT * FROM publico WHERE status='novo' ORDER BY RANDOM() LIMIT ?",
            (int(cfg["limite_perfis_ciclo"]),),
        ).fetchall()
    for p in alvos:
        if pausado_ate() or not em_horario(cfg) or feitos_hoje("curtir") >= lim_like:
            return
        status = "feito"
        try:
            info = cl.user_info(p["user_pk"])
            if info.is_private:
                status = "privado"
            else:
                medias = cl.user_medias(p["user_pk"], amount=3)
                for m in medias[: int(cfg["curtidas_por_perfil"])]:
                    if feitos_hoje("curtir") >= lim_like:
                        break
                    aid = _criar("curtir", str(m.id), "", "robo", f"@{p['username']}")
                    if not _executar(aid):
                        break
                    espera(cfg)
                modo = cfg["modo_comentar_publico"]
                if (
                    medias
                    and modo != "desligado"
                    and random.randint(1, 100) <= int(cfg["chance_comentar"])
                    and feitos_hoje("comentar_publico") < lim_com
                ):
                    m = medias[0]
                    texto, origem = comentario_para(m.caption_text, cfg)
                    aid = _criar(
                        "comentar_publico",
                        str(m.id),
                        texto,
                        origem,
                        f"@{p['username']}: {(m.caption_text or '')[:200]}",
                    )
                    if modo == "automatico":
                        _executar(aid)
                        espera(cfg)
        except Exception as exc:  # noqa: BLE001
            status = "erro"
            tratar_erro(exc)
        with db() as c:
            c.execute(
                "UPDATE publico SET status=?, done_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, p["id"]),
            )
        espera(cfg)


def responder_minha_conta(cl, cfg: dict) -> None:
    """Responde comentários nos meus posts e Directs que recebi."""
    from .engine import build_reply

    # Na primeira execução só marca o que já existe, para não responder coisas antigas.
    so_marcar = cfg.get("robo_base_ok") != "1"
    if so_marcar:
        for m in cl.user_medias(cl.user_id, amount=6):
            for com in cl.media_comments(m.id, amount=50):
                ja_visto(f"c:{com.pk}")
        for t in cl.direct_threads(amount=40) + cl.direct_pending_inbox(amount=20):
            for msg in t.messages[:1]:
                ja_visto(f"d:{msg.id}")
        set_config({"robo_base_ok": "1"})
        registrar("INICIO", "Comentários e Directs antigos marcados como vistos")
        return
    if cfg["modo_comentario"] != "desligado":
        for m in cl.user_medias(cl.user_id, amount=6):
            for com in cl.media_comments(m.id, amount=30):
                if str(com.user.pk) == str(cl.user_id) or ja_visto(f"c:{com.pk}"):
                    continue
                texto, origem = build_reply("comentario", com.text)
                texto = f"@{com.user.username} {texto}"
                aid = _criar(
                    "robo_responder_comentario",
                    f"{m.id}:{com.pk}",
                    texto,
                    origem,
                    f"@{com.user.username}: {com.text}",
                )
                if cfg["modo_comentario"] == "automatico":
                    _executar(aid)
                    espera(cfg)
    if cfg["modo_direct"] != "desligado":
        threads = cl.direct_threads(amount=20, selected_filter="unread")
        threads += cl.direct_pending_inbox(amount=10)
        for t in threads:
            if not t.messages:
                continue
            msg = t.messages[0]
            if str(msg.user_id) == str(cl.user_id) or ja_visto(f"d:{msg.id}"):
                continue
            texto, origem = build_reply("direct", msg.text or "")
            if origem == "padrao" and ja_visto(f"dp:{t.id}:{agora():%Y%m%d}"):
                continue  # resposta padrão no máximo 1x por dia na mesma conversa
            aid = _criar(
                "robo_responder_direct", str(t.id), texto, origem, msg.text or ""
            )
            if cfg["modo_direct"] == "automatico":
                _executar(aid)
                espera(cfg)


def ciclo(forcar: bool = False) -> str:
    """Um ciclo completo. Não roda em paralelo consigo mesmo."""
    if not _lock.acquire(blocking=False):
        return "Já existe um ciclo em andamento."
    try:
        cfg = get_config()
        if not forcar and cfg.get("robo_ativo") != "1":
            return "Robô desligado."
        if pausado_ate():
            return f"Pausado até {pausado_ate():%d/%m %H:%M}."
        if not em_horario(cfg):
            return "Fora do horário de funcionamento."
        try:
            cl = cliente()
            responder_minha_conta(cl, cfg)
            if not pausado_ate():
                coletar_publico(cl, cfg)
            if not pausado_ate():
                engajar_publico(cl, cfg)
        except Exception as exc:  # noqa: BLE001
            tratar_erro(exc)
        registrar("CICLO", "Ciclo concluído")
        return "Ciclo concluído."
    finally:
        _lock.release()


def resumo() -> dict:
    cfg = get_config()
    with db() as c:
        publico = {
            r["status"]: r["n"]
            for r in c.execute("SELECT status, COUNT(*) n FROM publico GROUP BY status")
        }
        logs = c.execute("SELECT * FROM robo_log ORDER BY id DESC LIMIT 40").fetchall()
    return {
        "cfg": cfg,
        "pausado_ate": pausado_ate(),
        "curtidas_hoje": feitos_hoje("curtir"),
        "comentarios_hoje": feitos_hoje("comentar_publico"),
        "publico": publico,
        "logs": logs,
        "em_horario": em_horario(cfg),
    }
