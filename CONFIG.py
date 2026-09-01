"""
GLOBAL CONFIGURATION FILE

Safe to commit -- holds NO secret values. Every secret (ICBC login,
IMAP app password, Telegram bot token/chat ids) is read from environment
variables instead:

  - Locally: copy .env.example to .env and fill it in. python-dotenv
    loads it automatically below.
  - In the cloud (Render, Railway, Fly, etc.): set the same variable
    names in your platform's environment variable settings. .env is
    never used there (it's gitignored, so it never leaves your machine).

Everything else (preferences, timing) is a plain constant below -- not
secret, edit it directly and redeploy.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # loads .env if present; harmless no-op if it's not (cloud)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable {name} is not set. Locally: copy "
            f".env.example to .env and fill it in. In the cloud: set it in "
            f"your platform's environment variables."
        )
    return value


def _bool_env(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in ("1", "true", "yes")


# Set True to run with a visible Chrome window (useful for first-time
# debugging locally). Leave False for normal unattended/cloud runs.
DEBUG = _bool_env("DEBUG", False)

# How often to re-check, in seconds (before jitter). 570 = 9.5 minutes.
PERIODIC_DELAY = int(_env("PERIODIC_DELAY", "570"))

# Random jitter applied to each wait, in seconds: actual delay is
# PERIODIC_DELAY +/- a random value in this range. 570 +/- 150 means each
# check lands somewhere between 7 and 12 minutes after the last one, not
# on a perfectly predictable cadence.
PERIODIC_DELAY_JITTER_SECONDS = int(_env("PERIODIC_DELAY_JITTER_SECONDS", "150"))

# Nothing about a booking is stored locally -- every check reads the
# CURRENT state live from "Your upcoming appointments" on the ICBC site:
#   - No booking yet -> searches fresh within [PREFERRED_AFTER_DATE, PREFERRED_BEFORE_DATE)
#     and books the nearest match.
#   - Already booked  -> searches within [PREFERRED_AFTER_DATE, <the current
#     booking's date>) -- i.e. only something EARLIER than what's already
#     held -- and reschedules to the nearest match via ICBC's "Reschedule
#     appointment" button.
# Either way it keeps running afterward and keeps checking, since there
# could always be something even earlier later on. It's controlled live via
# the Telegram bot (pause/resume/check now) -- see utils/telegram_bot.py.

# Must be "email" -- verification code is read automatically from
# VERIFICATION_EMAIL_ADDRESS's inbox via IMAP, with NO human confirmation
# step. Nothing stops a booking short of this file's settings once a
# match is found. (An earlier version of this script supported "sms" via
# a human relaying the code over Telegram instead -- that orchestration
# was removed from main.py when this switched to full auto-read; the
# pieces still exist in driver_utils/booker.py if that flow is ever
# wanted back, but main.py no longer wires them up.)
VERIFICATION_METHOD = _env("VERIFICATION_METHOD", "email")

# The mailbox ICBC actually sends the code to (must match her ICBC
# account's registered email exactly) -- this is what gets polled via IMAP.
VERIFICATION_EMAIL_ADDRESS = _require_env("VERIFICATION_EMAIL_ADDRESS")

# A Gmail "app password" for VERIFICATION_EMAIL_ADDRESS (requires 2FA
# enabled on that account): https://myaccount.google.com/apppasswords
VERIFICATION_EMAIL_APP_PASSWORD = _require_env("VERIFICATION_EMAIL_APP_PASSWORD")

# How long to wait for ICBC's verification email to arrive before giving
# up on that appointment and restarting to look for another, in seconds.
VERIFICATION_TIMEOUT_SECONDS = int(_env("VERIFICATION_TIMEOUT_SECONDS", "120"))

'''--- ICBC login credentials ---'''

DRIVERS_LAST_NAME = _require_env("DRIVERS_LAST_NAME")
LICENCE_NUMBER = _require_env("LICENCE_NUMBER")
KEYWORD = _require_env("KEYWORD")

'''--- Search preferences (not secret -- edit directly and redeploy) ---'''

# The location typed into ICBC's location search box
LOCATION = "Richmond, BC"

# The exact ICBC center name as shown on the results page after searching
# LOCATION above (has to match exactly, including punctuation/parentheses)
ICBC_CENTER = "Richmond driver licensing (Lansdowne Centre mall)"

# Days of the week that are acceptable (no preference -> all days)
PREFERRED_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Acceptable time windows, as a list of (start, end) 24h strings (no
# preference -> any time)
PREFERRED_TIMES = [("00:00", "23:59")]

# Hard floor: never book/reschedule to anything before this date
# (YYYY-MM-DD), inclusive. She failed her last test recently, so nothing
# before Sept 10, 2026. Once the current booking is at/before this date,
# the watcher idles -- nothing earlier is considered acceptable.
#
# The ACTUAL live floor used on any given check is whichever is later
# between this fixed date and tomorrow (Pacific time) -- see
# compute_effective_after_date() in main.py. That keeps this from going
# stale as real time passes (this runs indefinitely) and guarantees a
# same-day slot is never offered, always at least 1 day's notice.
PREFERRED_AFTER_DATE = "2026-09-10"

# Ceiling used only for a FIRST booking (no appointment yet); once one
# exists, the current booking's own date becomes the ceiling instead (see
# the comment block above -- this field is otherwise unused).
PREFERRED_BEFORE_DATE = "2027-01-01"

'''--- Notifications ---'''

# -- Email (via Gmail SMTP) -- optional, off by default; Telegram is the
# primary interface (see below).
SEND_EMAIL_NOTIF = _bool_env("SEND_EMAIL_NOTIF", False)

email_sender_account = _env("EMAIL_SENDER_ACCOUNT")
email_sender_username = _env("EMAIL_SENDER_USERNAME", email_sender_account)
email_sender_password = _env("EMAIL_SENDER_PASSWORD")
email_smtp_server = _env("EMAIL_SMTP_SERVER", "smtp.gmail.com")
email_smtp_port = int(_env("EMAIL_SMTP_PORT", "587"))
email_recepients = [e.strip() for e in _env("EMAIL_RECIPIENTS").split(",") if e.strip()]
email_subject = "Found available ICBC road test bookings matching preferences!"

# -- Telegram bot -- the primary interface: status updates, and
# interactive control (pause/resume/check now) via utils/telegram_bot.py.
SEND_TELEGRAM_NOTIF = _bool_env("SEND_TELEGRAM_NOTIF", True)

# From @BotFather, looks like "123456789:AAExample-Token"
TELEGRAM_BOT_TOKEN = _require_env("TELEGRAM_BOT_TOKEN")

# Comma-separated chat ids (e.g. "815893142" or "815893142,7836354408").
# ONLY these chat ids can control the bot (pause/resume/status/check now)
# and receive its status pushes -- anyone else messaging it is politely
# refused. See README.md for how to find a chat id.
TELEGRAM_AUTHORIZED_CHAT_IDS = [
    c.strip() for c in _require_env("TELEGRAM_AUTHORIZED_CHAT_IDS").split(",") if c.strip()
]
