'''Interactive Telegram bot interface: status pushes plus live control
(pause/resume/check now/status) via typed commands or inline buttons.

Runs as a background thread (poll_commands) alongside the main watch
loop, coordinating through a shared BotState. Only chat ids listed in
CONFIG.TELEGRAM_AUTHORIZED_CHAT_IDS can issue commands or receive
messages -- anyone else messaging the bot gets a polite refusal.
'''

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests

from CONFIG import TELEGRAM_AUTHORIZED_CHAT_IDS, TELEGRAM_BOT_TOKEN

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

NOT_AUTHORIZED_TEXT = "🔒 Sorry, this bot is private."

WELCOME_TEXT = (
    "👋 <b>Hi! I'm watching for an earlier ICBC road test appointment.</b>\n\n"
    "I check automatically and message you whenever I book or reschedule "
    "to something earlier. You're always in control:\n\n"
    "⏸ <b>Pause</b> — stop checking for a while\n"
    "▶️ <b>Resume</b> — start checking again\n"
    "🔄 <b>Check Now</b> — check right away instead of waiting\n"
    "ℹ️ <b>Status</b> — see what's currently booked"
)


@dataclass
class BotState:
    """Shared between the main watch loop (writer of check results,
    reader of paused/check_now) and the bot's polling thread (writer of
    paused/check_now, reader of everything for /status)."""

    paused: bool = False
    check_now_requested: bool = False
    has_checked: bool = False  # distinguishes "haven't looked yet" from a
                                # confirmed "no appointment" -- current_appointment_date
                                # is None in both cases, but only means something once
                                # has_checked is True
    current_appointment_date: Optional[str] = None
    last_check_at: Optional[datetime] = None
    last_result: str = "Just started -- checking for the first time now..."
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_paused(self, value: bool):
        with self._lock:
            self.paused = value

    def is_paused(self) -> bool:
        with self._lock:
            return self.paused

    def request_check_now(self):
        with self._lock:
            self.check_now_requested = True

    def consume_check_now(self) -> bool:
        with self._lock:
            if self.check_now_requested:
                self.check_now_requested = False
                return True
            return False

    def record_check(self, current_appointment_date: Optional[str], result_text: str):
        with self._lock:
            self.has_checked = True
            self.current_appointment_date = current_appointment_date
            self.last_check_at = datetime.now()
            self.last_result = result_text


def format_status_card(state: BotState) -> str:
    if state.is_paused():
        status_line = "⏸ <b>Paused</b> — tap ▶️ Resume to continue"
    else:
        status_line = "🟢 <b>Watching</b>"

    if not state.has_checked:
        current = "Checking now..."
    else:
        current = state.current_appointment_date or "None currently booked"
    last_check = state.last_check_at.strftime("%b %d, %I:%M %p") if state.last_check_at else "not yet"

    return (
        "🚗 <b>ICBC Road Test Watcher</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"{status_line}\n"
        f"📅 Current booking: <b>{current}</b>\n"
        f"🕐 Last checked: {last_check}\n"
        f"📝 {state.last_result}\n"
        "━━━━━━━━━━━━━━━━━━━"
    )


def _build_keyboard(state: BotState) -> dict:
    if state.is_paused():
        return {"inline_keyboard": [[{"text": "▶️ Resume", "callback_data": "resume"}]]}
    return {
        "inline_keyboard": [
            [
                {"text": "⏸ Pause", "callback_data": "pause"},
                {"text": "🔄 Check Now", "callback_data": "checknow"},
            ],
            [{"text": "ℹ️ Status", "callback_data": "status"}],
        ]
    }


def _send(chat_id: str, text: str, state: Optional[BotState] = None):
    """Sends one message, with a couple of quick retries on transient
    failures. Telegram's API occasionally has latency spikes (measured
    ~0.6s typical, but occasionally 15s+ on the same network) -- a single
    attempt with a tight timeout would silently drop the message on one
    of those spikes rather than actually failing to send. Retries are
    intentionally short (this blocks the caller) -- for the main watch
    loop that's fine, a message is worth a few seconds' wait.
    """
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if state is not None:
        payload["reply_markup"] = json.dumps(_build_keyboard(state))

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(f"{API_BASE}/sendMessage", data=payload, timeout=20)
            if response.ok:
                return
            print(f"(!) Telegram send failed for {chat_id}: {response.status_code} {response.text}")
        except requests.RequestException as e:
            print(f"(!) Telegram send attempt {attempt}/{attempts} failed for {chat_id}: {e}")

        if attempt < attempts:
            time.sleep(2 * attempt)  # 2s, then 4s

    print(f"(!) Telegram send to {chat_id} failed after {attempts} attempts -- giving up on this message.")


def send_to_all(text: str, state: Optional[BotState] = None):
    """Sends a plain status/notification push to every authorized chat id
    (with the current control keyboard attached, if state is given)."""
    for chat_id in TELEGRAM_AUTHORIZED_CHAT_IDS:
        _send(chat_id, text, state)


def _answer_callback(callback_query_id: str, text: str = ""):
    try:
        requests.post(
            f"{API_BASE}/answerCallbackQuery",
            data={"callback_query_id": callback_query_id, "text": text},
            timeout=10,
        )
    except requests.RequestException:
        pass  # cosmetic only (clears the button's loading spinner) -- not worth retrying


def _handle_command(command: str, chat_id: str, state: BotState):
    if command in ("pause", "stop"):
        state.set_paused(True)
        _send(chat_id, "⏸ <b>Paused.</b> I'll stop checking until you resume.", state)
    elif command in ("resume", "continue"):
        state.set_paused(False)
        _send(chat_id, "▶️ <b>Resumed!</b> Back to checking.", state)
    elif command in ("checknow", "check"):
        if state.is_paused():
            _send(chat_id, "I'm paused right now -- resume first, then I'll check.", state)
        else:
            state.request_check_now()
            _send(chat_id, "🔄 Checking now — I'll message you with the result shortly.")
    elif command == "start":
        _send(chat_id, WELCOME_TEXT, state)
    elif command in ("status", "help", ""):
        _send(chat_id, format_status_card(state), state)
    else:
        _send(chat_id, "Not sure what you mean. Try /status, /pause, or /resume.", state)


def _handle_update(update: dict, state: BotState):
    callback = update.get("callback_query")
    if callback:
        chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
        _answer_callback(callback.get("id", ""))
        if chat_id not in TELEGRAM_AUTHORIZED_CHAT_IDS:
            _send(chat_id, NOT_AUTHORIZED_TEXT)
            return
        _handle_command((callback.get("data") or "").strip().lower(), chat_id, state)
        return

    message = update.get("message")
    if not message:
        return
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()
    if not text:
        return
    if chat_id not in TELEGRAM_AUTHORIZED_CHAT_IDS:
        _send(chat_id, NOT_AUTHORIZED_TEXT)
        return
    command = text.lower().lstrip("/").split()[0] if text.startswith("/") else text.lower()
    _handle_command(command, chat_id, state)


def _get_updates(offset: Optional[int], timeout: int) -> list:
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    response = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=timeout + 15)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise Exception(f"Telegram getUpdates failed: {data}")
    return data["result"]


def poll_commands(state: BotState, stop_event: threading.Event):
    """Long-polls for incoming commands/button presses forever (meant to
    run in a background daemon thread). Flushes any backlog on startup so
    old messages sent before this run started are never replayed."""
    offset = None
    try:
        backlog = _get_updates(offset=None, timeout=1)
        if backlog:
            offset = max(u["update_id"] for u in backlog) + 1
    except Exception as e:
        print(f"(!) Telegram: couldn't flush backlog on startup: {e}")

    while not stop_event.is_set():
        try:
            updates = _get_updates(offset=offset, timeout=20)
        except Exception as e:
            if "409" in str(e):
                # Expected during a rolling deploy: the old and new
                # container briefly overlap, and Telegram only allows one
                # outstanding long-poll per bot token -- resolves itself
                # within seconds once the old container's connection
                # actually drops. Not a real problem.
                print(f"(i) Telegram getUpdates conflict (likely an overlapping deploy) -- retrying: {e}")
            else:
                print(f"(!) Telegram polling error: {e}")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            try:
                _handle_update(update, state)
            except Exception as e:
                print(f"(!) Telegram: error handling update: {e}")
