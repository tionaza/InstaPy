"""Banco SQLite simples (arquivo em volume Docker)."""
import os
import sqlite3
from contextlib import contextmanager

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT 'ambos',      -- comentario | direct | ambos
    keywords TEXT NOT NULL,                     -- separadas por vírgula
    reply TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                         -- comentario | direct
    external_id TEXT UNIQUE,                    -- id do comentário ou mid da mensagem
    sender_id TEXT, username TEXT, media_id TEXT, text TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER REFERENCES events(id),
    kind TEXT NOT NULL,                         -- responder_comentario | responder_direct | direct_privado
    target_id TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT,                                -- regra | padrao | ia
    status TEXT NOT NULL DEFAULT 'pendente',    -- pendente | enviado | simulado | rejeitado | erro
    error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    done_at TEXT
);
CREATE TABLE IF NOT EXISTS radar_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                         -- hashtag | concorrente
    value TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS radar_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES radar_sources(id),
    media_id TEXT UNIQUE, permalink TEXT, caption TEXT,
    like_count INTEGER, comments_count INTEGER, timestamp TEXT,
    suggestion TEXT,
    status TEXT NOT NULL DEFAULT 'novo',        -- novo | feito | ignorado
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS competitor_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT, followers_count INTEGER, media_count INTEGER,
    avg_likes REAL, avg_comments REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

DEFAULT_CONFIG = {
    "modo_comentario": "aprovacao",   # automatico | aprovacao | desligado
    "modo_direct": "aprovacao",
    "usar_ia": "0",
    "resposta_padrao_comentario": "Obrigado pelo comentário! Enviamos mais informações no seu Direct. 🙂",
    "resposta_padrao_direct": (
        "Olá! Obrigado pelo contato com o escritório Santos Nazaré Advocacia. "
        "Recebemos sua mensagem e em breve um(a) advogado(a) retornará. "
        "Se preferir, conte brevemente sua dúvida por aqui."
    ),
    "direct_privado_em_comentario": "0",
    "contexto_ia": (
        "Escritório de advocacia brasileiro. Responda em português, de forma cordial, "
        "informativa e sóbria. Não prometa resultados, não cite valores de honorários, "
        "não dê parecer jurídico sobre o caso concreto e convide a pessoa a continuar a "
        "conversa pelo Direct ou agendar atendimento."
    ),
}


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as c:
        c.executescript(SCHEMA)
        for k, v in DEFAULT_CONFIG.items():
            c.execute("INSERT OR IGNORE INTO config(key, value) VALUES (?, ?)", (k, v))


def get_config() -> dict:
    with db() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM config")}


def set_config(values: dict) -> None:
    with db() as c:
        for k, v in values.items():
            c.execute("INSERT OR REPLACE INTO config(key, value) VALUES (?, ?)", (k, v))
