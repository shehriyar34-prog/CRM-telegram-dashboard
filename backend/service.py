import re
import json
import time
import html
import requests
import threading
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List

from .config import settings
from .logger import activity_logger

PKT = timezone(timedelta(hours=5))
PAID_STATUSES = ("pending", "cleared")


class CRMTelegramService:
    def __init__(self):
        # Service lifecycle
        self.state: str = "STOPPED"  # STOPPED, STARTING, RUNNING, STOPPING, ERROR
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # HTTP Sessions
        self.panel = requests.Session()
        self.telegram = requests.Session()

        # State tracking (matching original script)
        self.seen = set()
        self.client_of_number: Dict[str, str] = {}
        self.client_display: Dict[str, str] = {}
        self.last_client_refresh: float = 0
        self.clients_enabled: bool = True
        self.update_offset: Optional[int] = None
        self.webhook_warned: bool = False
        self.last_daily_date = None
        self._last_panel_request_time: float = 0

        # Live metrics & monitoring
        self.start_time: Optional[datetime] = None
        self.last_poll_time: Optional[str] = None
        self.last_sms_time: Optional[str] = None
        self.total_sms_detected: int = 0
        self.total_sms_forwarded: int = 0
        self.total_errors: int = 0
        self.last_error_message: Optional[str] = None

        # Health statuses
        self.telegram_status: Dict[str, Any] = {
            "status": "UNKNOWN",
            "last_checked": None,
            "details": None,
            "bot_username": None,
        }
        self.crm_status: Dict[str, Any] = {
            "status": "UNKNOWN",
            "last_checked": None,
            "details": None,
            "clients_count": 0,
            "numbers_count": 0,
        }

        # Recent forwarded SMS for live dashboard display
        self.recent_sms: deque = deque(maxlen=100)

    # ====================== Status & Diagnostics ======================

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status of service, CRM and Telegram connections."""
        uptime_seconds = 0
        if self.start_time and self.state == "RUNNING":
            uptime_seconds = int((datetime.now(PKT) - self.start_time).total_seconds())

        return {
            "state": self.state,
            "uptime_seconds": uptime_seconds,
            "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S") if self.start_time else None,
            "last_poll_time": self.last_poll_time,
            "last_sms_time": self.last_sms_time,
            "total_sms_detected": self.total_sms_detected,
            "total_sms_forwarded": self.total_sms_forwarded,
            "total_errors": self.total_errors,
            "last_error_message": self.last_error_message,
            "seen_messages_count": len(self.seen),
            "clients_loaded": len(self.client_display),
            "assigned_numbers_loaded": len(self.client_of_number),
            "clients_enabled": self.clients_enabled,
            "telegram": self.telegram_status,
            "crm": self.crm_status,
        }

    def test_telegram_connection(self) -> Dict[str, Any]:
        """Actively tests connection to Telegram Bot API and target chat."""
        token = settings.bot_token.strip()
        chat_id = settings.chat_id.strip()

        if not token:
            res = {"success": False, "message": "BOT_TOKEN is not configured."}
            self.telegram_status = {"status": "DISCONNECTED", "last_checked": datetime.now(PKT).strftime("%H:%M:%S"), "details": res["message"]}
            return res

        now_str = datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S")
        try:
            # 1. Test getMe
            r = self.telegram.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
            if not r.ok:
                msg = f"HTTP {r.status_code}: {r.json().get('description', 'Unknown error')}"
                self.telegram_status = {"status": "ERROR", "last_checked": now_str, "details": msg}
                return {"success": False, "message": msg}

            bot_info = r.json().get("result", {})
            bot_username = bot_info.get("username", "")

            # 2. Test getChat if chat_id is set
            chat_title = None
            if chat_id:
                chat_resp = self.telegram.get(
                    f"https://api.telegram.org/bot{token}/getChat",
                    params={"chat_id": chat_id},
                    timeout=15,
                )
                if chat_resp.ok:
                    cdata = chat_resp.json().get("result", {})
                    chat_title = cdata.get("title") or cdata.get("username") or str(chat_id)

            self.telegram_status = {
                "status": "CONNECTED",
                "last_checked": now_str,
                "details": f"Connected as @{bot_username}" + (f" -> Chat: {chat_title}" if chat_title else ""),
                "bot_username": bot_username,
                "chat_title": chat_title,
            }
            activity_logger.success(f"Telegram connected successfully as @{bot_username}", "TELEGRAM")
            return {
                "success": True,
                "bot_username": bot_username,
                "chat_title": chat_title,
                "message": f"Connected as @{bot_username}",
            }
        except Exception as e:
            err_msg = f"Network or connection error: {str(e)}"
            self.telegram_status = {"status": "ERROR", "last_checked": now_str, "details": err_msg}
            activity_logger.error(f"Telegram connection failed: {err_msg}", "TELEGRAM")
            return {"success": False, "message": err_msg}

    def test_crm_connection(self) -> Dict[str, Any]:
        """Actively tests connection to the SMS CRM Panel."""
        base_url = settings.panel_base.strip()
        token = settings.panel_token.strip()

        if not token:
            res = {"success": False, "message": "PANEL_TOKEN is not configured."}
            self.crm_status = {"status": "DISCONNECTED", "last_checked": datetime.now(PKT).strftime("%H:%M:%S"), "details": res["message"]}
            return res

        now_str = datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S")
        try:
            start_t = time.time()
            r = self.panel.get(
                f"{base_url}/messages",
                params={"limit": 5},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            latency_ms = int((time.time() - start_t) * 1000)

            if not r.ok:
                msg = f"HTTP {r.status_code} from panel API."
                self.crm_status = {"status": "ERROR", "last_checked": now_str, "details": msg}
                return {"success": False, "message": msg}

            data = r.json()
            records_count = len(data.get("records", []))
            self.crm_status = {
                "status": "CONNECTED",
                "last_checked": now_str,
                "latency_ms": latency_ms,
                "details": f"Online (Latency: {latency_ms}ms, returned {records_count} recent messages)",
            }
            activity_logger.success(f"CRM Panel reachable ({latency_ms}ms, {records_count} messages)", "CRM")
            return {
                "success": True,
                "latency_ms": latency_ms,
                "messages_sample": records_count,
                "message": f"Connected to CRM Panel ({latency_ms}ms)",
            }
        except Exception as e:
            err_msg = f"CRM Panel connection failed: {str(e)}"
            self.crm_status = {"status": "ERROR", "last_checked": now_str, "details": err_msg}
            activity_logger.error(err_msg, "CRM")
            return {"success": False, "message": err_msg}

    # ====================== Panel Helpers (Original Logic) ======================

    def panel_get(self, path: str, params: Optional[dict] = None) -> dict:
        # Enforce rate-limit safety gap (at least 1.5s between calls to stay under 40 requests/min)
        elapsed = time.time() - self._last_panel_request_time
        if elapsed < 1.5:
            time.sleep(1.5 - elapsed)
        self._last_panel_request_time = time.time()

        r = self.panel.get(
            f"{settings.panel_base}{path}",
            params=params,
            headers={"Authorization": f"Bearer {settings.panel_token}"},
            timeout=settings.panel_timeout,
        )
        r.raise_for_status()
        return r.json()

    def fetch_messages(self) -> List[dict]:
        return self.panel_get("/messages", {"limit": settings.messages_per_poll}).get("records", [])

    def fetch_all_numbers(self) -> List[dict]:
        """All numbers you hold (needs the Extended API). Keyset paginated."""
        records, after = [], None
        while not self._stop_event.is_set():
            params = {"limit": 500}
            if after:
                params["after"] = after
            data = self.panel_get("/numbers", params)
            records.extend(data.get("records", []))
            after = data.get("nextCursor")
            if not after:
                break
            time.sleep(1.2)  # stay under 1 request/second
        return records

    def refresh_clients(self):
        """Loads number -> client from /numbers and client names from /clients (Extended API, agent accounts)."""
        if not self.clients_enabled:
            return
        try:
            names = {}
            for c in self.panel_get("/clients", {"limit": 500}).get("clients", []):
                names[c.get("username")] = c.get("name") or c.get("username")
            time.sleep(1.2)
            mapping = {}
            for rec in self.fetch_all_numbers():
                if rec.get("client"):
                    mapping[str(rec["number"])] = rec["client"]

            self.client_display.clear()
            self.client_display.update(names)
            self.client_of_number.clear()
            self.client_of_number.update(mapping)
            self.last_client_refresh = time.time()
            msg = f"Client list loaded: {len(mapping)} assigned numbers, {len(names)} clients."
            activity_logger.info(msg, "CRM")
        except requests.HTTPError as e:
            code = e.response.status_code
            if code == 403:
                self.clients_enabled = False
                activity_logger.warning("Client names unavailable: Extended API or agent access is not enabled for your account.", "CRM")
            elif code == 429:
                activity_logger.warning("Client refresh rate-limited, will try again later.", "CRM")
                self.last_client_refresh = time.time()
            else:
                activity_logger.error(f"Client refresh HTTP error: {code}", "CRM")
                self.last_client_refresh = time.time()
        except (requests.ConnectionError, requests.Timeout):
            activity_logger.warning("Client refresh failed (network timeout). Will try again later.", "CRM")
            self.last_client_refresh = time.time()
        except Exception as e:
            activity_logger.error(f"Client refresh error: {type(e).__name__}: {str(e)}", "CRM")
            self.last_client_refresh = time.time()

    def get_client(self, rec: dict) -> str:
        number = str(rec.get("number"))
        if number in settings.client_by_number:
            return settings.client_by_number[number]
        username = self.client_of_number.get(number)
        if username:
            name = self.client_display.get(username)
            if name and name != username:
                return f"{name} ({username})"
            return username
        return "Unassigned"

    @staticmethod
    def record_key(rec: dict) -> str:
        return f"{rec.get('time')}|{rec.get('number')}|{rec.get('content')}"

    @staticmethod
    def extract_code(text: str) -> str:
        m = re.search(r"code\D{0,3}(\d{4,8})", text, re.I) or re.search(r"\b(\d{4,8})\b", text)
        return m.group(1) if m else "N/A"

    # ====================== Telegram Helpers (Original Logic) ======================

    def send_text(self, text: str) -> bool:
        """Sends HTML text to the channel (split if too long). Returns True if everything was delivered."""
        chunks, current = [], ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > 3800:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current.strip():
            chunks.append(current)

        for chunk in chunks:
            try:
                r = self.telegram.post(
                    f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                    data={"chat_id": settings.chat_id, "text": chunk, "parse_mode": "HTML"},
                    timeout=settings.telegram_timeout,
                )
            except (requests.ConnectionError, requests.Timeout):
                activity_logger.warning("Telegram unreachable (network problem). Will retry...", "TELEGRAM")
                return False

            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 5)
                activity_logger.warning(f"Telegram rate limit, waiting {wait}s...", "TELEGRAM")
                time.sleep(wait)
                return False
            if r.status_code == 404:
                activity_logger.error("Telegram error 404: BOT_TOKEN is wrong. Copy the full token from BotFather.", "TELEGRAM")
                return False
            if r.status_code in (400, 403):
                desc = r.json().get("description", "")
                activity_logger.error(f"Telegram error {r.status_code}: {desc}. Check CHAT_ID and bot admin rights.", "TELEGRAM")
                return False
            if not r.ok:
                activity_logger.error(f"Telegram error: {r.status_code}", "TELEGRAM")
                return False
        return True

    def send(self, rec: dict) -> bool:
        """Forwards one SMS record to Telegram."""
        content = rec.get("content", "")
        client_name = self.get_client(rec)
        extracted_code = self.extract_code(content)

        text = (
            f"📩 <b>{html.escape(str(rec.get('cli', 'Unknown')))}</b>\n"
            f"👤 Client: <b>{html.escape(client_name)}</b>\n"
            f"📞 <code>{html.escape(str(rec.get('number', '')))}</code>\n"
            f"🔑 Code: <code>{html.escape(extracted_code)}</code>\n"
            f"🌍 {html.escape(str(rec.get('range', '')))}\n"
            f"🕒 {html.escape(str(rec.get('time', '')))}\n\n"
            f"<i>{html.escape(content)}</i>"
        )
        delivered = self.send_text(text)
        if delivered:
            # Append to recent SMS for dashboard view
            self.recent_sms.appendleft({
                "cli": str(rec.get("cli", "Unknown")),
                "client": client_name,
                "number": str(rec.get("number", "")),
                "code": extracted_code,
                "range": str(rec.get("range", "")),
                "time": str(rec.get("time", "")),
                "content": content,
                "forwarded_at": datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S"),
            })
        return delivered

    # ====================== Number Health Report (Original Logic) ======================

    @staticmethod
    def parse_time(value):
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def to_decimal(value):
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return Decimal(0)

    @staticmethod
    def short_time(dt):
        return dt.astimezone(PKT).strftime("%d %b %H:%M")

    def build_report(self, days: int) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        time.sleep(1.2)  # keep a gap after the normal message poll
        msgs = self.panel_get(
            "/messages",
            {"from": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 1000},
        ).get("records", [])
        truncated = len(msgs) >= 1000
        numbers = None
        try:
            time.sleep(1.2)
            numbers = self.fetch_all_numbers()
        except requests.HTTPError as e:
            if e.response.status_code != 403:
                raise

        per = defaultdict(lambda: {"count": 0, "paid": 0, "payout": Decimal(0),
                                   "last": None, "statuses": Counter()})
        status_count = Counter()
        cli_count = Counter()
        payout_total = Decimal(0)

        for m in msgs:
            n = str(m.get("number"))
            s = m.get("status", "unknown")
            d = per[n]
            d["count"] += 1
            d["statuses"][s] += 1
            status_count[s] += 1
            cli_count[m.get("cli", "Unknown")] += 1
            try:
                t = self.parse_time(m.get("time"))
                if d["last"] is None or t > d["last"]:
                    d["last"] = t
            except ValueError:
                pass
            if s in PAID_STATUSES:
                d["paid"] += 1
                p = self.to_decimal(m.get("payout"))
                d["payout"] += p
                payout_total += p

        paid_msgs = sum(status_count[s] for s in PAID_STATUSES)
        unpaid_msgs = len(msgs) - paid_msgs

        lines = [f"📊 <b>Number report - last {days} day(s)</b>", ""]
        lines.append(f"✉️ Messages: <b>{len(msgs)}</b> (paying {paid_msgs}, not paying {unpaid_msgs})")
        lines.append(f"💰 Payout (pending + cleared): <b>{payout_total.quantize(Decimal('0.0001'))}</b>")
        lines.append(f"📞 Numbers that received SMS: <b>{len(per)}</b>")
        if truncated:
            lines.append("⚠️ 1000 message limit reached, counts may be partial. Try a shorter period.")

        if numbers is not None:
            status_totals = Counter(str(n.get("status", "unknown")) for n in numbers)
            lines.append("")
            lines.append(f"🗂 Numbers you hold: <b>{len(numbers)}</b> (" +
                         ", ".join(f"{html.escape(k)} {v}" for k, v in status_totals.most_common()) + ")")
            silent = [str(n["number"]) for n in numbers
                      if str(n.get("status", "")).lower() == "active" and str(n["number"]) not in per]
            lines.append(f"😴 Active but silent (no SMS in period): <b>{len(silent)}</b>")
            for n in silent[:15]:
                c_name = self.get_client({"number": n})
                lines.append(f"  • <code>{html.escape(n)}</code>" +
                             (f" - {html.escape(c_name)}" if c_name != "Unassigned" else ""))
            if len(silent) > 15:
                lines.append(f"  ... and {len(silent) - 15} more")
        else:
            lines.append("")
            lines.append("ℹ️ Number list unavailable (Extended API is not enabled), so silent numbers cannot be listed.")

        if unpaid_msgs:
            lines.append("")
            lines.append("🚫 <b>Why messages are not paying</b>")
            for s, c in status_count.most_common():
                if s not in PAID_STATUSES:
                    lines.append(f"  • {html.escape(str(s))}: {c}")

        nopay = [(n, d) for n, d in per.items() if d["paid"] == 0]
        if nopay:
            nopay.sort(key=lambda x: -x[1]["count"])
            lines.append("")
            lines.append(f"⛔ Numbers with SMS but nothing paid: <b>{len(nopay)}</b>")
            for n, d in nopay[:10]:
                reason = d["statuses"].most_common(1)[0][0]
                lines.append(f"  • <code>{html.escape(n)}</code> - {d['count']} SMS, {html.escape(str(reason))}")
            if len(nopay) > 10:
                lines.append(f"  ... and {len(nopay) - 10} more")

        if per:
            lines.append("")
            lines.append("🏆 <b>Top numbers</b>")
            top = sorted(per.items(), key=lambda x: (-x[1]["count"], x[0]))[:10]
            for n, d in top:
                seen_at = self.short_time(d["last"]) if d["last"] else "?"
                lines.append(f"  • <code>{html.escape(n)}</code> - {d['count']} SMS, paid {d['paid']}, "
                             f"{d['payout'].quantize(Decimal('0.0001'))}, last {seen_at}")

        if cli_count:
            lines.append("")
            lines.append("📱 <b>By service</b>")
            for cli, c in cli_count.most_common(8):
                lines.append(f"  • {html.escape(str(cli))}: {c}")

        lines.append("")
        lines.append("Times are Pakistan time (UTC+5).")
        return "\n".join(lines)

    def run_report(self, days: int, send_telegram: bool = True) -> str:
        activity_logger.info(f"Generating number health report for last {days} day(s)...", "REPORT")
        if send_telegram:
            self.send_text(f"⏳ Building report for the last {days} day(s)...")
        try:
            text = self.build_report(days)
            if send_telegram:
                self.send_text(text)
            activity_logger.success(f"Report for {days} day(s) generated successfully.", "REPORT")
            return text
        except requests.HTTPError as e:
            code = e.response.status_code
            text = ("Report failed: the panel is rate limiting requests, try again in a minute."
                    if code == 429 else f"Report failed: panel error {code}.")
        except (requests.ConnectionError, requests.Timeout):
            text = "Report failed: the panel could not be reached."
        except Exception as e:
            text = f"Report failed: {type(e).__name__}."

        activity_logger.error(text, "REPORT")
        if send_telegram:
            self.send_text(text)
        return text

    # ====================== Telegram Commands (/report) ======================

    @staticmethod
    def is_report_chat(chat: dict) -> bool:
        if str(chat.get("id")) == str(settings.chat_id):
            return True
        username = chat.get("username")
        return bool(username) and f"@{username}".lower() == str(settings.chat_id).lower()

    def init_updates(self):
        """Skip old commands so a restart does not re-run past /report requests."""
        try:
            r = self.telegram.get(
                f"https://api.telegram.org/bot{settings.bot_token}/getUpdates",
                params={"offset": -1, "timeout": 0},
                timeout=settings.telegram_timeout,
            )
            result = r.json().get("result", []) if r.ok else []
            if result:
                self.update_offset = result[-1]["update_id"] + 1
        except Exception:
            pass

    def check_commands(self):
        params = {"timeout": 0, "allowed_updates": json.dumps(["message", "channel_post"])}
        if self.update_offset:
            params["offset"] = self.update_offset
        try:
            r = self.telegram.get(
                f"https://api.telegram.org/bot{settings.bot_token}/getUpdates",
                params=params,
                timeout=settings.telegram_timeout,
            )
        except (requests.ConnectionError, requests.Timeout):
            return

        if r.status_code == 409:
            if not self.webhook_warned:
                activity_logger.warning("Commands disabled: a webhook is set for this bot. Remove it to use /report.", "TELEGRAM")
                self.webhook_warned = True
            return

        if not r.ok:
            return

        for u in r.json().get("result", []):
            self.update_offset = u["update_id"] + 1
            msg = u.get("channel_post") or u.get("message")
            if not msg or not self.is_report_chat(msg.get("chat", {})):
                continue
            parts = (msg.get("text") or "").strip().split()
            if not parts or parts[0].split("@")[0].lower() != "/report":
                continue

            days = settings.report_default_days
            if len(parts) > 1 and parts[1].isdigit():
                days = max(1, min(int(parts[1]), settings.report_max_days))
            activity_logger.info(f"Report requested via Telegram command: {days} day(s)", "TELEGRAM")
            self.run_report(days)

    def check_daily_report(self):
        if settings.daily_report_hour_pkt is None:
            return
        now = datetime.now(PKT)
        if now.hour == settings.daily_report_hour_pkt and self.last_daily_date != now.date():
            self.last_daily_date = now.date()
            activity_logger.info("Executing scheduled daily report.", "SERVICE")
            self.run_report(1)

    # ====================== Background Service Worker ======================

    def _worker_loop(self):
        activity_logger.info("Service worker loop starting...", "SERVICE")
        self.state = "RUNNING"
        self.start_time = datetime.now(PKT)

        # 1. Startup phase: initialize seen set from current panel messages
        startup_retries = 0
        while not self._stop_event.is_set():
            try:
                records = self.fetch_messages()
                for rec in records:
                    self.seen.add(self.record_key(rec))
                activity_logger.success(f"Started. Ignoring {len(self.seen)} existing messages. Waiting for new SMS...", "SERVICE")
                self.crm_status["status"] = "CONNECTED"
                self.crm_status["last_checked"] = datetime.now(PKT).strftime("%H:%M:%S")
                break
            except requests.HTTPError as e:
                self.total_errors += 1
                self.last_error_message = f"Panel error at startup: {e.response.status_code}"
                activity_logger.error(self.last_error_message, "CRM")
                if e.response.status_code == 429:
                    wait_sec = int(e.response.headers.get("Retry-After", 10))
                    self._stop_event.wait(wait_sec)
                else:
                    self._stop_event.wait(10)
            except (requests.ConnectionError, requests.Timeout):
                self.total_errors += 1
                self.last_error_message = "Panel unreachable at startup"
                activity_logger.warning("Panel unreachable at startup, retrying in 10 seconds...", "CRM")
                self._stop_event.wait(10)
            except Exception as e:
                self.total_errors += 1
                self.last_error_message = f"Startup error: {type(e).__name__}"
                activity_logger.error(self.last_error_message, "SERVICE")
                self._stop_event.wait(10)

            startup_retries += 1
            if startup_retries >= 5 and self._stop_event.is_set():
                break

        if self._stop_event.is_set():
            self.state = "STOPPED"
            activity_logger.info("Service worker stopped before completion.", "SERVICE")
            return

        # 2. Refresh clients and init updates
        self.refresh_clients()
        self.init_updates()
        activity_logger.info("Tip: post /report (or /report 7) in the channel to get a number health report.", "TELEGRAM")

        # 3. Main polling loop
        while not self._stop_event.is_set():
            try:
                self.last_poll_time = datetime.now(PKT).strftime("%H:%M:%S")

                # Periodic client refresh
                if self.clients_enabled and time.time() - self.last_client_refresh > settings.client_refresh_seconds:
                    self.refresh_clients()

                # Fetch messages (Panel lists newest first, reverse to send oldest first)
                records = self.fetch_messages()
                self.total_sms_detected += len(records)
                self.crm_status["status"] = "CONNECTED"

                for rec in reversed(records):
                    if self._stop_event.is_set():
                        break

                    key = self.record_key(rec)
                    if key in self.seen:
                        continue

                    if self.send(rec):
                        self.seen.add(key)
                        self.total_sms_forwarded += 1
                        self.last_sms_time = datetime.now(PKT).strftime("%H:%M:%S")
                        client_str = self.get_client(rec)
                        activity_logger.success(
                            f"Sent SMS: {rec.get('cli')} -> {rec.get('number')} | {client_str}",
                            "SERVICE",
                            {"cli": rec.get("cli"), "number": rec.get("number"), "client": client_str}
                        )
                    else:
                        activity_logger.warning("Failed forwarding message to Telegram. Will retry next poll.", "SERVICE")
                        break

                # Memory management for seen set
                if len(self.seen) > 5000:
                    self.seen.clear()
                    for rec in self.fetch_messages():
                        self.seen.add(self.record_key(rec))

                # Check Telegram commands and daily report
                self.check_commands()
                self.check_daily_report()

            except requests.HTTPError as e:
                code = e.response.status_code
                if code == 429:
                    wait_sec = int(e.response.headers.get("Retry-After", 10))
                    activity_logger.warning(
                        f"Panel rate-limit reached (HTTP 429). Pausing requests for {wait_sec}s cooldown...",
                        "CRM"
                    )
                    self.crm_status["status"] = "RATE_LIMITED"
                    self._stop_event.wait(wait_sec)
                else:
                    self.total_errors += 1
                    self.last_error_message = f"Panel HTTP error: {code}"
                    activity_logger.error(self.last_error_message, "CRM")
                    self.crm_status["status"] = "ERROR"
            except (requests.ConnectionError, requests.Timeout):
                self.total_errors += 1
                self.last_error_message = "Panel unreachable (connection error/timeout)"
                activity_logger.warning("Panel unreachable, retrying...", "CRM")
                self.crm_status["status"] = "OFFLINE"
                self._stop_event.wait(10)
            except Exception as e:
                self.total_errors += 1
                self.last_error_message = f"Loop error: {type(e).__name__}: {str(e)}"
                activity_logger.error(self.last_error_message, "SERVICE")

            # Sleep interval
            self._stop_event.wait(settings.poll_seconds)

        self.state = "STOPPED"
        activity_logger.info("Service worker loop terminated gracefully.", "SERVICE")

    # ====================== Service Controls ======================

    def start(self) -> Dict[str, Any]:
        """Starts the background worker service."""
        with self._lock:
            if self.state in ("RUNNING", "STARTING"):
                return {"success": False, "message": "Service is already running."}

            self._stop_event.clear()
            self.state = "STARTING"
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="CRMTelegramWorker")
            self._thread.start()
            activity_logger.info("Service start command issued.", "SERVICE")
            return {"success": True, "message": "Service started successfully."}

    def stop(self) -> Dict[str, Any]:
        """Stops the background worker service."""
        with self._lock:
            if self.state in ("STOPPED", "STOPPING"):
                return {"success": False, "message": "Service is already stopped."}

            self.state = "STOPPING"
            self._stop_event.set()
            activity_logger.info("Service stop command issued. Waiting for thread to finish...", "SERVICE")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self.state = "STOPPED"
        return {"success": True, "message": "Service stopped successfully."}

    def restart(self) -> Dict[str, Any]:
        """Restarts the background worker service with current settings."""
        activity_logger.info("Restarting service...", "SERVICE")
        self.stop()
        time.sleep(1)
        return self.start()


# Global singleton instance
service = CRMTelegramService()
