"""Cliente mínimo da Instagram Graph API oficial (Meta).

Só usa endpoints permitidos pela Meta:
- responder comentários feitos nas SUAS publicações;
- responder Directs que as pessoas enviaram para VOCÊ (janela de 24h);
- enviar resposta privada (Direct) a quem comentou na sua publicação;
- buscar publicações públicas por hashtag e métricas públicas de perfis comerciais.
"""
import logging

import httpx

from .config import settings

log = logging.getLogger("graph")


class GraphError(Exception):
    pass


def _url(path: str) -> str:
    return f"{settings.graph_base}/{settings.graph_version}/{path.lstrip('/')}"


def _request(method: str, path: str, **kwargs) -> dict:
    params = kwargs.pop("params", {}) or {}
    params["access_token"] = settings.access_token
    with httpx.Client(timeout=20) as client:
        r = client.request(method, _url(path), params=params, **kwargs)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        raise GraphError(data.get("error", {}).get("message", r.text))
    return data


def reply_to_comment(comment_id: str, message: str) -> dict:
    return _request("POST", f"{comment_id}/replies", data={"message": message})


def send_direct(recipient_igsid: str, message: str) -> dict:
    return _request(
        "POST",
        f"{settings.page_id}/messages",
        json={"recipient": {"id": recipient_igsid}, "message": {"text": message}},
    )


def private_reply_to_comment(comment_id: str, message: str) -> dict:
    """Direct para quem comentou na sua publicação (1 por comentário, até 7 dias)."""
    return _request(
        "POST",
        f"{settings.page_id}/messages",
        json={"recipient": {"comment_id": comment_id}, "message": {"text": message}},
    )


def hashtag_recent_media(tag: str, limit: int = 25) -> list[dict]:
    """Limite da Meta: 30 hashtags diferentes a cada 7 dias por conta."""
    found = _request("GET", "ig_hashtag_search", params={"user_id": settings.ig_user_id, "q": tag})
    if not found.get("data"):
        return []
    hid = found["data"][0]["id"]
    res = _request(
        "GET",
        f"{hid}/recent_media",
        params={
            "user_id": settings.ig_user_id,
            "fields": "id,caption,permalink,like_count,comments_count,timestamp",
            "limit": limit,
        },
    )
    return res.get("data", [])


def competitor_snapshot(username: str) -> dict:
    """Dados públicos de um perfil comercial/criador (não inclui lista de seguidores)."""
    fields = (
        f"business_discovery.username({username})"
        "{username,followers_count,media_count,"
        "media.limit(12){id,caption,permalink,like_count,comments_count,timestamp}}"
    )
    res = _request("GET", settings.ig_user_id, params={"fields": fields})
    return res.get("business_discovery", {})
