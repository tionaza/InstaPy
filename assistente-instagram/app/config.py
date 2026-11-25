"""Configuração lida das variáveis de ambiente (arquivo .env)."""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "sim", "yes", "on")


class Settings:
    # Meta / Instagram Graph API (Facebook Login for Business)
    graph_version = os.getenv("GRAPH_VERSION", "v21.0")
    graph_base = os.getenv("GRAPH_BASE", "https://graph.facebook.com")
    page_id = os.getenv("FB_PAGE_ID", "")
    ig_user_id = os.getenv("IG_USER_ID", "")
    access_token = os.getenv("PAGE_ACCESS_TOKEN", "")
    app_secret = os.getenv("META_APP_SECRET", "")
    verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "")

    # Painel
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    # Comportamento
    dry_run = _bool("DRY_RUN", True)  # True = registra mas NÃO envia nada ao Instagram
    max_auto_per_hour = int(os.getenv("MAX_AUTO_PER_HOUR", "30"))
    radar_interval_min = int(os.getenv("RADAR_INTERVAL_MIN", "180"))

    # IA opcional (Claude) para sugerir respostas
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    db_path = os.getenv("DB_PATH", "/data/assistente.db")


settings = Settings()
