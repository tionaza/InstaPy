"""Sugestões de resposta com Claude (opcional). Sem chave, retorna None."""
import logging

import httpx

from .config import settings

log = logging.getLogger("ai")


def suggest(context: str, kind: str, text: str) -> str | None:
    if not settings.anthropic_api_key:
        return None
    prompt = (
        f"Tipo: {kind}\nMensagem recebida: {text}\n\n"
        "Escreva apenas a resposta, em até 3 frases curtas, sem aspas."
    )
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": 300,
                "system": context,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        r.raise_for_status()
        parts = r.json().get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("Falha ao gerar sugestão com IA: %s", exc)
        return None
