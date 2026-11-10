from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

from .config import settings, update_settings
from .logger import activity_logger
from .service import service

router = APIRouter(prefix="/api")


# Request/Response models
class SettingsUpdateRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    telegram_timeout: Optional[int] = None
    panel_token: Optional[str] = None
    panel_base: Optional[str] = None
    panel_timeout: Optional[int] = None
    poll_seconds: Optional[int] = None
    client_refresh_seconds: Optional[int] = None
    messages_per_poll: Optional[int] = None
    report_default_days: Optional[int] = None
    report_max_days: Optional[int] = None
    daily_report_hour_pkt: Optional[Any] = None
    client_by_number: Optional[Dict[str, str]] = None


class GenerateReportRequest(BaseModel):
    days: int = Field(default=1, ge=1, le=30)
    send_telegram: bool = Field(default=False)


@router.get("/status")
def get_service_status():
    """Returns real-time status of service, CRM connection, Telegram connection, and metrics."""
    return {
        "status": "success",
        "data": service.get_status(),
    }


@router.post("/service/start")
def start_service():
    """Starts the background CRM and Telegram polling service."""
    result = service.start()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return {"status": "success", "message": result["message"]}


@router.post("/service/stop")
def stop_service():
    """Stops the background CRM and Telegram polling service."""
    result = service.stop()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return {"status": "success", "message": result["message"]}


@router.post("/service/restart")
def restart_service():
    """Restarts the background CRM and Telegram polling service."""
    result = service.restart()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return {"status": "success", "message": result["message"]}


@router.post("/test/telegram")
def test_telegram_connection():
    """Actively verifies Telegram Bot API connectivity and target chat."""
    result = service.test_telegram_connection()
    return {"status": "success" if result["success"] else "error", "data": result}


@router.post("/test/crm")
def test_crm_connection():
    """Actively verifies CRM Panel API connectivity and response time."""
    result = service.test_crm_connection()
    return {"status": "success" if result["success"] else "error", "data": result}


@router.get("/logs")
def get_logs(
    limit: int = 150,
    min_id: Optional[int] = None,
    level: Optional[str] = None,
    source: Optional[str] = None,
):
    """Fetches recent activity logs filtered by ID, severity level, or component source."""
    # Ensure min_id is integer or None
    actual_min_id = None
    if isinstance(min_id, int):
        actual_min_id = min_id
    elif min_id and str(min_id).isdigit():
        actual_min_id = int(min_id)

    logs = activity_logger.get_logs(limit=limit, min_id=actual_min_id, level=level, source=source)
    return {
        "status": "success",
        "count": len(logs),
        "data": logs,
    }


@router.post("/logs/clear")
def clear_logs():
    """Clears the live log memory buffer."""
    activity_logger.clear()
    activity_logger.info("Activity log buffer cleared by user.", "SYSTEM")
    return {"status": "success", "message": "Log buffer cleared."}


@router.get("/messages/recent")
def get_recent_messages():
    """Returns recent forwarded SMS messages from memory."""
    return {
        "status": "success",
        "data": list(service.recent_sms),
    }


@router.get("/settings")
def get_current_settings():
    """Returns current configuration with masked secrets for safe frontend display."""
    return {
        "status": "success",
        "data": settings.safe_dict(),
        "client_by_number": settings.client_by_number,
    }


@router.post("/settings")
def save_settings(request: SettingsUpdateRequest):
    """Updates configuration settings and saves them to environment variables / files."""
    updates = request.model_dump(exclude_unset=True)
    updated = update_settings(updates)
    activity_logger.info("Configuration settings updated via dashboard.", "SYSTEM")
    return {
        "status": "success",
        "message": "Settings updated successfully.",
        "data": updated.safe_dict(),
    }


@router.post("/report/generate")
def generate_report(req: GenerateReportRequest):
    """Triggers generation of the Number Health Report for specified number of days."""
    try:
        report_text = service.run_report(req.days, send_telegram=req.send_telegram)
        return {
            "status": "success",
            "days": req.days,
            "send_telegram": req.send_telegram,
            "report_html": report_text,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
