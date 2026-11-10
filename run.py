import os
import sys
import uvicorn
from pathlib import Path

# Add project directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import settings
from backend.logger import activity_logger

if __name__ == "__main__":
    print("=" * 60)
    print("   CRM & TELEGRAM BOT PROFESSIONAL DASHBOARD HUB   ")
    print("=" * 60)
    print(f" Web Dashboard: http://localhost:{settings.port}")
    print(f" API Docs:      http://localhost:{settings.port}/docs")
    print(f" Polling CRM:   {settings.panel_base}")
    print(f" Telegram Chat: {settings.chat_id}")
    print("=" * 60)

    uvicorn.run(
        "backend.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
