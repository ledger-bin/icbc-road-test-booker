# ICBC road test appointment watcher

Watches Richmond driver licensing (Lansdowne Centre mall) for a road test
slot earlier than whatever's currently booked, and reschedules to it
automatically the moment one appears — no booking exists yet, it books
fresh instead. Controlled live over Telegram: pause it, resume it, ask it
to check right now, or just check the current status, all from your
phone. Runs forever, checking every ~7-12 minutes, until stopped.

Originally adapted from
[omar2535/ICBC-roadtest-availability-notifier](https://github.com/omar2535/ICBC-roadtest-availability-notifier),
substantially rewritten since (current Selenium API, live "Your upcoming
appointments" reads instead of local bookkeeping, full auto-booking with
email-verified codes, and this Telegram bot interface).

## How it works, in short

Every check: reads the current booking's date live off ICBC's site (never
stored locally) → searches for anything better within
`[earliest acceptable date, current booking date)` → if found, clicks
through ICBC's Reschedule flow, reads the verification code from email
automatically, and confirms it against "Your upcoming appointments" before
ever reporting success → sends a Telegram update → keeps going. Nothing
stops it short of you pausing it or Ctrl+C — there's always potentially
something even earlier to find.

Built to survive being left running for weeks unattended: every click has
a JS-click fallback for when a third-party survey popup intercepts it (ICBC
shows one occasionally), a silent session expiry gets a quiet re-login
instead of an alarming alert, and every step dumps a screenshot + HTML to
`debug/` on failure so a future ICBC site change is easy to diagnose
instead of a silent failure.

## Running it locally

1. Install dependencies (Python 3.14+, [uv](https://docs.astral.sh/uv/)):

   ```sh
   uv sync
   ```

   You'll also need Google Chrome installed (Selenium drives it via
   `webdriver-manager`, which downloads a matching chromedriver
   automatically).

2. Set up your secrets:

   ```sh
   cp .env.example .env
   ```

   Then edit `.env` (gitignored, never committed) — see **Configuration**
   below for what each value means and how to get it.

3. Run it:

   ```sh
   uv run main.py
   ```

   Leave it running in a terminal, or use `caffeinate -i uv run main.py`
   on a Mac so it won't pause when the lid closes. For a genuinely
   unattended multi-day/week run, deploy it instead — see **Deploying to
   the cloud** below.

## Configuration

`CONFIG.py` itself is safe to commit — it holds no secret values, only
variable *names* it reads from the environment (via `.env` locally, or
your cloud platform's environment variable settings when deployed).

**Required** (see `.env.example`):

| Variable | What it is |
|---|---|
| `DRIVERS_LAST_NAME`, `LICENCE_NUMBER`, `KEYWORD` | Same three things used to log in on the ICBC site itself |
| `VERIFICATION_EMAIL_ADDRESS`, `VERIFICATION_EMAIL_APP_PASSWORD` | The mailbox ICBC sends the verification code to, and a Gmail [app password](https://myaccount.google.com/apppasswords) for it (needs 2FA enabled) — read automatically via IMAP, no human step |
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) — see **Setting up the Telegram bot** below |
| `TELEGRAM_AUTHORIZED_CHAT_IDS` | Comma-separated chat id(s) allowed to control the bot and receive updates — see below |

**Optional** (sensible defaults if omitted — see `.env.example`):
`DEBUG` (false), `PERIODIC_DELAY` / `PERIODIC_DELAY_JITTER_SECONDS` (check
interval, default ~7-12 min), `VERIFICATION_TIMEOUT_SECONDS` (how long to
wait for ICBC's code email before giving up on that slot, default 120s),
`SEND_EMAIL_NOTIF` and the `EMAIL_*` variables (an optional secondary
notification channel — Telegram is the primary interface and always on).

**Non-secret preferences** live directly in `CONFIG.py` (edit and
redeploy, no env var needed): `LOCATION` / `ICBC_CENTER` (which office),
`PREFERRED_DAYS` / `PREFERRED_TIMES` (defaults: any day, any time),
`PREFERRED_AFTER_DATE` (the hard floor — never book earlier than this;
currently set for her specific retest-eligibility date; the actual live
floor used on any check is whichever is later between this and tomorrow
in Pacific time, so it can't go stale or offer a same-day slot).

## Setting up the Telegram bot

1. Message **[@BotFather](https://t.me/BotFather)**, send `/newbot`,
   follow the prompts. It gives you a **bot token**
   (`123456789:AAExample-Token`) — that's `TELEGRAM_BOT_TOKEN`.
2. Have whoever should control the bot open a chat with it (search its
   username, tap **Start**) and send it any message.
3. Find their **chat id**: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser (after
   they've sent that message) and look for `"chat":{"id":...}` in the
   response.
4. Put that number in `TELEGRAM_AUTHORIZED_CHAT_IDS`. Add more,
   comma-separated, to authorize multiple people (e.g. both you and your
   sister) — anyone *not* in this list gets a polite "this bot is
   private" refusal instead of being able to control it.

## Using the bot (for the end user — no code, just Telegram)

Open the chat with the bot in Telegram. Every message it sends carries
buttons that adapt to whether it's currently running or paused:

- **Watching**: **⏸ Pause**, **🔄 Check Now**, **ℹ️ Status**
- **Paused**: just **▶️ Resume**

What each does:

- **⏸ Pause** — stops checking until resumed. Nothing on the ICBC side is
  touched while paused.
- **▶️ Resume** — starts checking again.
- **🔄 Check Now** — checks immediately instead of waiting for the next
  scheduled check, and always messages back with the result (found
  something better / nothing better right now / already at the floor).
- **ℹ️ Status** — current booking date, whether it's watching or paused,
  and when it last checked.

The same also work as typed commands (`/pause`, `/resume`, `/status`,
`/checknow`) if that's ever easier than tapping.

You'll get a message automatically whenever it books or reschedules to
something earlier, or if it hits a genuine error it's retrying from
(routine ICBC session expiry is handled silently — no alert — since it's
not a real problem).

## Deploying to the cloud

This needs to run continuously (a persistent process, holding a Chrome
session and an IMAP/Telegram connection open) — that rules out
serverless/request-response platforms like Vercel. **Render's
["Background Worker"](https://render.com/docs/background-workers)**
service type is built for exactly this shape of app, and packaging here
is plain Docker, so it also works unmodified on Railway, Fly.io, a VPS,
or any other Docker-capable host. Currently deployed on Render.

**Render, step by step:**

1. Push this repo to GitHub (`.env` never leaves your machine — it's
   gitignored — so nothing secret goes with it).
2. On [render.com](https://render.com): **New** → **Background Worker** →
   connect the GitHub repo.
3. Runtime: **Docker**. Leave **Docker Build Context Directory** as `.`,
   but set **Dockerfile Path** explicitly to `./Dockerfile` (it doesn't
   reliably auto-fill). Leave **Docker Command** and **Pre-Deploy
   Command** empty — the `Dockerfile`'s own `CMD` is what should run.
4. Under **Environment**, add every variable from `.env.example` with
   your real values (same names as local `.env`).
5. Deploy. Check the logs for the startup line
   (`Logged in. Watching '...' ...`) and the welcome message arriving in
   Telegram.

Two things you'll see in the logs that are expected, not bugs:
- A `Telegram getUpdates conflict (likely an overlapping deploy)` line
  right after a redeploy — Render briefly runs the old and new container
  at once, and Telegram only allows one outstanding connection per bot
  token. Resolves itself within seconds.
- `ICBC session expired -- logging back in...` every so often — routine
  on ICBC's end (its login sessions have an absolute, not just an
  inactivity, timeout), handled automatically.

**Local Docker test** (recommended before deploying, or any time you
change something Selenium-related — this is how every fix in this
project has actually been verified, not just assumed):

```sh
docker compose up --build
```

reads the same `.env` file. `docker compose down` to stop it.

## Notes / limitations

- This targets **road test** appointments specifically. It won't help
  with knowledge tests or general driver-licensing office bookings —
  those are a different flow on the same site.
- No CAPTCHA has been encountered historically, but ICBC could change
  that at any time — if login starts failing unexpectedly, that's the
  first thing to check (run locally with `DEBUG=true` to watch it
  happen in a visible browser window).
- ICBC occasionally shows a third-party Qualtrics survey popup that can
  sit on top of the page and intercept a click — every click in this
  project falls back to a JS-executed click when that happens
  (`driver_utils/utils.py`'s `safe_click`), so it isn't fatal.
- Every step dumps a screenshot + HTML to `debug/` regardless of
  success/failure, so a selector mismatch after a future ICBC site
  change is easy to diagnose rather than a silent failure.
- Secrets (ICBC login, IMAP app password, bot token) live only in your
  local `.env` or your cloud platform's environment variable settings —
  never commit `.env`, and never paste its contents into a chat or issue
  tracker.
