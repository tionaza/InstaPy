"""Assistente de Instagram — webhooks oficiais da Meta + painel web."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from . import engine, radar
from .config import settings
from .db import db, get_config, init_db, set_config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
log = logging.getLogger("app")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic()


async def _radar_loop():
    while True:
        await asyncio.sleep(settings.radar_interval_min * 60)
        try:
            await asyncio.to_thread(radar.run_once)
        except Exception as exc:  # noqa: BLE001
            log.warning("Radar: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    task = (
        asyncio.create_task(_radar_loop()) if settings.radar_interval_min > 0 else None
    )
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="Assistente Instagram",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


def admin(creds: HTTPBasicCredentials = Depends(security)) -> str:
    if not settings.admin_password:
        raise HTTPException(503, "Defina ADMIN_PASSWORD no arquivo .env")
    ok = secrets.compare_digest(
        creds.username, settings.admin_user
    ) and secrets.compare_digest(creds.password, settings.admin_password)
    if not ok:
        raise HTTPException(
            401, "Não autorizado", headers={"WWW-Authenticate": "Basic"}
        )
    return creds.username


def back(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


# ---------------------------------------------------------------- webhooks
@app.get("/health")
def health():
    return {"ok": True, "dry_run": settings.dry_run}


@app.get("/webhook", response_class=PlainTextResponse)
def webhook_verify(request: Request):
    q = request.query_params
    if (
        q.get("hub.mode") == "subscribe"
        and settings.verify_token
        and secrets.compare_digest(q.get("hub.verify_token", ""), settings.verify_token)
    ):
        return q.get("hub.challenge", "")
    raise HTTPException(403, "Token inválido")


@app.post("/webhook")
async def webhook_receive(request: Request, tasks: BackgroundTasks):
    body = await request.body()
    if not engine.verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "Assinatura inválida")
    tasks.add_task(engine.handle_webhook, await request.json())
    return {"ok": True}


# ---------------------------------------------------------------- painel
@app.get("/")
def painel(request: Request, _=Depends(admin)):
    with db() as c:
        pendentes = c.execute(
            "SELECT a.*, e.text AS original, e.username FROM actions a "
            "LEFT JOIN events e ON e.id=a.event_id WHERE a.status='pendente' ORDER BY a.id DESC"
        ).fetchall()
        historico = c.execute(
            "SELECT a.*, e.text AS original, e.username FROM actions a "
            "LEFT JOIN events e ON e.id=a.event_id WHERE a.status!='pendente' "
            "ORDER BY a.id DESC LIMIT 50"
        ).fetchall()
        totais = {
            r["status"]: r["n"]
            for r in c.execute("SELECT status, COUNT(*) n FROM actions GROUP BY status")
        }
    return templates.TemplateResponse(
        request,
        "painel.html",
        {
            "pendentes": pendentes,
            "historico": historico,
            "totais": totais,
            "s": settings,
        },
    )


@app.post("/acoes/{aid}/aprovar")
def aprovar(aid: int, text: str = Form(...), _=Depends(admin)):
    with db() as c:
        c.execute(
            "UPDATE actions SET text=? WHERE id=? AND status='pendente'",
            (text.strip(), aid),
        )
    engine.execute(aid)
    return back("/")


@app.post("/acoes/{aid}/rejeitar")
def rejeitar(aid: int, _=Depends(admin)):
    with db() as c:
        c.execute(
            "UPDATE actions SET status='rejeitado', done_at=CURRENT_TIMESTAMP WHERE id=?",
            (aid,),
        )
    return back("/")


@app.get("/regras")
def regras(request: Request, _=Depends(admin)):
    with db() as c:
        rows = c.execute("SELECT * FROM rules ORDER BY id").fetchall()
    return templates.TemplateResponse(
        request, "regras.html", {"regras": rows, "s": settings}
    )


@app.post("/regras")
def nova_regra(
    channel: str = Form(...),
    keywords: str = Form(...),
    reply: str = Form(...),
    _=Depends(admin),
):
    with db() as c:
        c.execute(
            "INSERT INTO rules(channel, keywords, reply) VALUES (?,?,?)",
            (channel, keywords.strip(), reply.strip()),
        )
    return back("/regras")


@app.post("/regras/{rid}/excluir")
def excluir_regra(rid: int, _=Depends(admin)):
    with db() as c:
        c.execute("DELETE FROM rules WHERE id=?", (rid,))
    return back("/regras")


@app.get("/configuracoes")
def configuracoes(request: Request, _=Depends(admin)):
    return templates.TemplateResponse(
        request, "config.html", {"cfg": get_config(), "s": settings}
    )


@app.post("/configuracoes")
async def salvar_config(request: Request, _=Depends(admin)):
    form = await request.form()
    keys = [
        "modo_comentario",
        "modo_direct",
        "resposta_padrao_comentario",
        "resposta_padrao_direct",
        "contexto_ia",
    ]
    values = {k: str(form.get(k, "")).strip() for k in keys}
    values["usar_ia"] = "1" if form.get("usar_ia") else "0"
    values["direct_privado_em_comentario"] = (
        "1" if form.get("direct_privado_em_comentario") else "0"
    )
    set_config(values)
    return back("/configuracoes")


@app.get("/radar")
def radar_view(request: Request, _=Depends(admin)):
    with db() as c:
        fontes = c.execute(
            "SELECT * FROM radar_sources ORDER BY kind, value"
        ).fetchall()
        itens = c.execute(
            "SELECT i.*, s.value AS fonte FROM radar_items i JOIN radar_sources s ON s.id=i.source_id "
            "WHERE i.status='novo' ORDER BY i.id DESC LIMIT 60"
        ).fetchall()
        concorrentes = c.execute(
            "SELECT * FROM competitor_stats WHERE id IN "
            "(SELECT MAX(id) FROM competitor_stats GROUP BY username) ORDER BY username"
        ).fetchall()
    return templates.TemplateResponse(
        request,
        "radar.html",
        {
            "fontes": fontes,
            "itens": itens,
            "concorrentes": concorrentes,
            "s": settings,
        },
    )


@app.post("/radar/fontes")
def nova_fonte(kind: str = Form(...), value: str = Form(...), _=Depends(admin)):
    value = value.strip().lstrip("#@").lower()
    if value:
        with db() as c:
            c.execute(
                "INSERT OR IGNORE INTO radar_sources(kind, value) VALUES (?,?)",
                (kind, value),
            )
    return back("/radar")


@app.post("/radar/fontes/{sid}/excluir")
def excluir_fonte(sid: int, _=Depends(admin)):
    with db() as c:
        c.execute("DELETE FROM radar_items WHERE source_id=?", (sid,))
        c.execute("DELETE FROM radar_sources WHERE id=?", (sid,))
    return back("/radar")


@app.post("/radar/executar")
async def executar_radar(_=Depends(admin)):
    await asyncio.to_thread(radar.run_once)
    return back("/radar")


@app.post("/radar/itens/{iid}/{status}")
def marcar_item(iid: int, status: str, _=Depends(admin)):
    if status not in ("feito", "ignorado"):
        raise HTTPException(400)
    with db() as c:
        c.execute("UPDATE radar_items SET status=? WHERE id=?", (status, iid))
    return back("/radar")
