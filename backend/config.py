import os
import json
from pathlib import Path
from typing import Optional, Dict
from pydantic import BaseModel
from dotenv import load_dotenv, set_key

# Base directory for the project
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Load existing .env if present
load_dotenv(dotenv_path=ENV_PATH)

class Settings(BaseModel):
    # Telegram settings
    bot_token: str = os.getenv("BOT_TOKEN", "")
    chat_id: str = os.getenv("CHAT_ID", "")
    telegram_timeout: int = int(os.getenv("TELEGRAM_TIMEOUT", "40"))

    # CRM Panel settings
    panel_token: str = os.getenv("PANEL_TOKEN", "")
    panel_base: str = os.getenv("PANEL_BASE", "https://imssms.org/api/v1")
    panel_timeout: int = int(os.getenv("PANEL_TIMEOUT", "40"))

    # Operational settings
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "5"))
    client_refresh_seconds: int = int(os.getenv("CLIENT_REFRESH_SECONDS", "300"))
    messages_per_poll: int = int(os.getenv("MESSAGES_PER_POLL", "50"))

    # Report settings
    report_default_days: int = int(os.getenv("REPORT_DEFAULT_DAYS", "1"))
    report_max_days: int = int(os.getenv("REPORT_MAX_DAYS", "30"))
    daily_report_hour_pkt: Optional[int] = (
        int(os.getenv("DAILY_REPORT_HOUR_PKT"))
        if os.getenv("DAILY_REPORT_HOUR_PKT") and os.getenv("DAILY_REPORT_HOUR_PKT").strip()
        else None
    )

    # Server settings
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    auto_start_service: bool = os.getenv("AUTO_START_SERVICE", "true").lower() in ("true", "1", "yes")

    # Manual client mappings: phone_number -> client_name
    client_by_number: Dict[str, str] = {}

    def mask_secret(self, secret: str) -> str:
        if not secret:
            return ""
        if len(secret) <= 8:
            return "******"
        return f"{secret[:4]}...{secret[-4:]}"

    def safe_dict(self) -> dict:
        """Returns settings with masked secrets for safe frontend transmission."""
        d = self.model_dump()
        d["bot_token_masked"] = self.mask_secret(self.bot_token)
        d["panel_token_masked"] = self.mask_secret(self.panel_token)
        # Keep raw tokens out of standard safe serialization
        d["bot_token"] = self.mask_secret(self.bot_token)
        d["panel_token"] = self.mask_secret(self.panel_token)
        return d

# Global settings instance
settings = Settings()

# Try loading client_by_number from JSON if exists
CLIENT_MAP_FILE = BASE_DIR / "client_map.json"
if CLIENT_MAP_FILE.exists():
    try:
        with open(CLIENT_MAP_FILE, "r", encoding="utf-8") as f:
            settings.client_by_number = json.load(f)
    except Exception:
        settings.client_by_number = {}

def update_settings(updates: dict) -> Settings:
    """Updates global settings and persists changes to .env and files."""
    global settings
    
    # Check if .env exists, if not create it
    if not ENV_PATH.exists():
        ENV_PATH.touch()

    for key, value in updates.items():
        if value is None:
            continue
        
        # Don't overwrite secret with masked string
        if key in ("bot_token", "panel_token") and "..." in str(value):
            continue

        if key == "bot_token" and value:
            settings.bot_token = str(value).strip()
            set_key(str(ENV_PATH), "BOT_TOKEN", settings.bot_token)
        elif key == "chat_id" and value:
            settings.chat_id = str(value).strip()
            set_key(str(ENV_PATH), "CHAT_ID", settings.chat_id)
        elif key == "panel_token" and value:
            settings.panel_token = str(value).strip()
            set_key(str(ENV_PATH), "PANEL_TOKEN", settings.panel_token)
        elif key == "panel_base" and value:
            settings.panel_base = str(value).strip()
            set_key(str(ENV_PATH), "PANEL_BASE", settings.panel_base)
        elif key == "poll_seconds" and value is not None:
            val = max(2, int(value))
            settings.poll_seconds = val
            set_key(str(ENV_PATH), "POLL_SECONDS", str(val))
        elif key == "client_refresh_seconds" and value is not None:
            val = max(30, int(value))
            settings.client_refresh_seconds = val
            set_key(str(ENV_PATH), "CLIENT_REFRESH_SECONDS", str(val))
        elif key == "messages_per_poll" and value is not None:
            val = max(5, int(value))
            settings.messages_per_poll = val
            set_key(str(ENV_PATH), "MESSAGES_PER_POLL", str(val))
        elif key == "report_default_days" and value is not None:
            val = max(1, int(value))
            settings.report_default_days = val
            set_key(str(ENV_PATH), "REPORT_DEFAULT_DAYS", str(val))
        elif key == "report_max_days" and value is not None:
            val = max(1, int(value))
            settings.report_max_days = val
            set_key(str(ENV_PATH), "REPORT_MAX_DAYS", str(val))
        elif key == "daily_report_hour_pkt":
            if value == "" or value is None:
                settings.daily_report_hour_pkt = None
                set_key(str(ENV_PATH), "DAILY_REPORT_HOUR_PKT", "")
            else:
                val = int(value)
                if 0 <= val <= 23:
                    settings.daily_report_hour_pkt = val
                    set_key(str(ENV_PATH), "DAILY_REPORT_HOUR_PKT", str(val))
        elif key == "client_by_number" and isinstance(value, dict):
            settings.client_by_number = value
            with open(CLIENT_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(value, f, indent=2)

    return settings
