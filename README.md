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
automatically, and confirms it → sends a Telegram update → keeps going.
Nothing stops it short of you pausing it or Ctrl+C — there's always
potentially something even earlier to find.

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

**Non-secret preferences** live directly in `CONFIG.py` (edit and
redeploy, no env var needed): `LOCATION` / `ICBC_CENTER` (which office),
`PREFERRED_DAYS` / `PREFERRED_TIMES` (defaults: any day, any time),
`PREFERRED_AFTER_DATE` (the hard floor — never book earlier than this;
currently set for her specific retest-eligibility date), `PERIODIC_DELAY`
/ `PERIODIC_DELAY_JITTER_SECONDS` (check interval, currently ~7-12 min).

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

Open the chat with the bot in Telegram. Four buttons appear on every
message it sends:

- **⏸ Pause** — stops checking until resumed. Nothing on the ICBC side is
  touched while paused.
- **▶️ Resume** — starts checking again.
- **🔄 Check Now** — checks immediately instead of waiting for the next
  scheduled check.
- **ℹ️ Status** — current booking date, whether it's watching or paused,
  and when it last checked.

The same also work as typed commands (`/pause`, `/resume`, `/status`,
`/checknow`) if that's ever easier than tapping.

You'll get a message automatically whenever it books or reschedules to
something earlier, or if it hits an error it's retrying from.

## Deploying to the cloud

This needs to run continuously (a persistent process, holding a Chrome
session and an IMAP/Telegram connection open) — that rules out
serverless/request-response platforms like Vercel. **Render's
["Background Worker"](https://render.com/docs/background-workers)**
service type is built for exactly this shape of app, and packaging here
is plain Docker, so it also works unmodified on Railway, Fly.io, a VPS,
or any other Docker-capable host.

**Render, step by step:**

1. Push this repo to GitHub (`.env` never leaves your machine — it's
   gitignored — so nothing secret goes with it).
2. On [render.com](https://render.com): **New** → **Background Worker** →
   connect the GitHub repo.
3. Runtime: **Docker** (it'll find the `Dockerfile` automatically).
4. Under **Environment**, add every variable from `.env.example` with
   your real values (same names, same as local `.env`).
5. Deploy. Check the logs for the startup line
   (`Logged in. Watching '...' ...`) and the welcome message arriving in
   Telegram.

**Local Docker test** (optional, before deploying):

```sh
docker compose up --build
```

reads the same `.env` file. (Not verified in this environment — Docker
wasn't available here to build/run it — so this is the one piece worth
double-checking yourself before trusting a cloud deploy, or just deploy
straight to Render and watch its build/runtime logs for the first run.)

## Notes / limitations

- This targets **road test** appointments specifically. It won't help
  with knowledge tests or general driver-licensing office bookings —
  those are a different flow on the same site.
- No CAPTCHA has been encountered historically, but ICBC could change
  that at any time — if login starts failing unexpectedly, that's the
  first thing to check (run locally with `DEBUG=true` to watch it
  happen in a visible browser window).
- Every step dumps a screenshot + HTML to `debug/` regardless of
  success/failure, so a selector mismatch after a future ICBC site
  change is easy to diagnose rather than a silent failure.
- Secrets (ICBC login, IMAP app password, bot token) live only in your
  local `.env` or your cloud platform's environment variable settings —
  never commit `.env`, and never paste its contents into a chat or issue
  tracker.
