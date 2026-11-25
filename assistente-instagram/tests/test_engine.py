import hashlib
import hmac
import importlib
import json

import pytest


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("META_APP_SECRET", "segredo")
    monkeypatch.setenv("WEBHOOK_VERIFY_TOKEN", "tok")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha")
    monkeypatch.setenv("IG_USER_ID", "999")
    monkeypatch.setenv("DRY_RUN", "true")
    import app.config, app.db, app.engine, app.main  # noqa: E401

    for m in (app.config, app.db, app.engine, app.main):
        importlib.reload(m)
    app.db.init_db()
    return app


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"segredo", body, hashlib.sha256).hexdigest()


def test_match_rule_ignora_acentos(app_env):
    rules = [
        {
            "active": 1,
            "channel": "ambos",
            "keywords": "aposentadoria, INSS",
            "reply": "R",
        }
    ]
    assert (
        app_env.engine.match_rule("Quero saber da APOSENTADORÍA", "direct", rules)
        == "R"
    )
    assert app_env.engine.match_rule("olá", "direct", rules) is None


def test_assinatura(app_env):
    body = b'{"a":1}'
    assert app_env.engine.verify_signature(body, sign(body))
    assert not app_env.engine.verify_signature(body, "sha256=errado")


def test_fluxo_webhook(app_env):
    from fastapi.testclient import TestClient

    with TestClient(app_env.main.app) as client:
        r = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "tok",
                "hub.challenge": "123",
            },
        )
        assert r.text == "123"
        app_env.db.set_config({"modo_direct": "automatico"})
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "comments",
                            "value": {
                                "id": "c1",
                                "text": "Como funciona?",
                                "from": {"id": "1", "username": "ana"},
                                "media": {"id": "m1"},
                            },
                        }
                    ],
                    "messaging": [
                        {
                            "sender": {"id": "2"},
                            "message": {"mid": "x1", "text": "Oi"},
                        }
                    ],
                }
            ],
        }
        body = json.dumps(payload).encode()
        r = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": sign(body),
                "content-type": "application/json",
            },
        )
        assert r.status_code == 200
        # repetir o mesmo evento não duplica
        client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": sign(body),
                "content-type": "application/json",
            },
        )
        with app_env.db.db() as c:
            rows = {
                r["kind"]: r["status"]
                for r in c.execute("SELECT kind, status FROM actions")
            }
        assert rows == {
            "responder_comentario": "pendente",
            "responder_direct": "simulado",
        }
        assert client.get("/").status_code == 401
        assert client.get("/", auth=("admin", "senha")).status_code == 200
        for p in ("/regras", "/radar", "/configuracoes", "/robo"):
            assert client.get(p, auth=("admin", "senha")).status_code == 200
        assert (
            client.post(
                "/webhook",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=x"},
            ).status_code
            == 403
        )
