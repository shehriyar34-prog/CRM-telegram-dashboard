import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from collections import deque
import threading

PKT = timezone(timedelta(hours=5))

class ActivityLogger:
    def __init__(self, max_entries: int = 1000):
        self.max_entries = max_entries
        self._logs = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._counter = 0

    def log(
        self,
        level: str,
        message: str,
        source: str = "SYSTEM",
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Record an activity log entry."""
        with self._lock:
            self._counter += 1
            now = datetime.now(PKT)
            entry = {
                "id": self._counter,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "iso_time": now.isoformat(),
                "level": level.upper(),
                "source": source.upper(),
                "message": message,
                "details": details or {}
            }
            self._logs.append(entry)
            
            # Print to standard output for local visibility
            print(f"[{entry['timestamp']}] [{entry['level']}] [{entry['source']}] {message}")
            return entry

    def info(self, message: str, source: str = "SYSTEM", details: Optional[Dict[str, Any]] = None):
        return self.log("INFO", message, source, details)

    def success(self, message: str, source: str = "SYSTEM", details: Optional[Dict[str, Any]] = None):
        return self.log("SUCCESS", message, source, details)

    def warning(self, message: str, source: str = "SYSTEM", details: Optional[Dict[str, Any]] = None):
        return self.log("WARNING", message, source, details)

    def error(self, message: str, source: str = "SYSTEM", details: Optional[Dict[str, Any]] = None):
        return self.log("ERROR", message, source, details)

    def get_logs(
        self,
        limit: int = 200,
        min_id: Optional[int] = None,
        level: Optional[str] = None,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve recent logs filtered by id, level, or source."""
        with self._lock:
            logs = list(self._logs)

        if isinstance(min_id, int):
            logs = [entry for entry in logs if entry["id"] > min_id]

        if level:
            lvl = level.upper()
            logs = [entry for entry in logs if entry["level"] == lvl]

        if source:
            src = source.upper()
            logs = [entry for entry in logs if entry["source"] == src]

        # Return latest entries up to limit
        return logs[-limit:]

    def clear(self):
        with self._lock:
            self._logs.clear()

activity_logger = ActivityLogger()
