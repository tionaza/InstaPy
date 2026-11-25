import importlib
from types import SimpleNamespace as NS

import pytest


class FakeClient:
    user_id = "1"

    def __init__(self):
        self.comments = [NS(pk=10, text="antigo", user=NS(pk=5, username="velho"))]
        self.threads = []

    def user_medias(self, uid, amount=0):
        return [NS(id=f"m{uid}", caption_text="Post sobre INSS")]

    def media_comments(self, mid, amount=0):
        return self.comments if mid == "m1" else []

    def direct_threads(self, amount=20, selected_filter=None):
        return list(self.threads)

    def direct_pending_inbox(self, amount=10):
        return []

    def user_id_from_username(self, u):
        return "777"

    def user_followers(self, uid, amount=0):
        return {str(i): NS(username=f"seg{i}") for i in range(100, 110)}

    def hashtag_medias_recent(self, name, amount=20):
        return []

    def user_info(self, pk):
        return NS(is_private=pk == "100")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DRY_RUN", "true")
    import app.config, app.db, app.engine, app.robo  # noqa: E401

    for m in (app.config, app.db, app.engine, app.robo):
        importlib.reload(m)
    app.db.init_db()
    app.db.set_config(
        {
            "hora_inicio": "0",
            "hora_fim": "24",
            "robo_ativo": "1",
            "modo_comentario": "automatico",
            "modo_direct": "automatico",
            "chance_comentar": "100",
            "limite_curtidas_dia": "5",
            "limite_perfis_ciclo": "20",
        }
    )
    fake = FakeClient()
    monkeypatch.setattr(app.robo, "cliente", lambda *a: fake)
    monkeypatch.setattr(app.robo, "espera", lambda cfg: None)
    with app.db.db() as c:
        c.execute(
            "INSERT INTO radar_sources(kind, value) VALUES ('concorrente','rival')"
        )
    return app, fake


def acoes(app):
    with app.db.db() as c:
        return [dict(r) for r in c.execute("SELECT kind, status, text FROM actions")]


def test_primeiro_ciclo_nao_responde_antigos(env):
    app, fake = env
    app.robo.ciclo()
    kinds = [a["kind"] for a in acoes(app)]
    assert "robo_responder_comentario" not in kinds
    # coleta + curtidas respeitando o limite diário
    assert kinds.count("curtir") == 5
    assert all(a["status"] == "simulado" for a in acoes(app) if a["kind"] == "curtir")
    # comentários no público ficam aguardando aprovação por padrão
    assert any(
        a["kind"] == "comentar_publico" and a["status"] == "pendente"
        for a in acoes(app)
    )


def test_responde_novos_comentarios_e_directs(env):
    app, fake = env
    app.robo.ciclo()
    fake.comments.append(NS(pk=11, text="Tenho dúvida", user=NS(pk=6, username="ana")))
    fake.threads = [NS(id=99, messages=[NS(id=500, user_id=6, text="Oi")])]
    app.robo.ciclo()
    app.robo.ciclo()  # não repete
    a = acoes(app)
    resp = [x for x in a if x["kind"] == "robo_responder_comentario"]
    dm = [x for x in a if x["kind"] == "robo_responder_direct"]
    assert len(resp) == 1 and resp[0]["text"].startswith("@ana ")
    assert len(dm) == 1 and dm[0]["status"] == "simulado"


def test_bloqueio_pausa_robo(env):
    app, _ = env

    class FeedbackRequired(Exception):
        pass

    app.robo.tratar_erro(FeedbackRequired("action blocked"))
    assert app.robo.pausado_ate() is not None
    assert app.robo.ciclo().startswith("Pausado")
