import html
import random
import threading
import time
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from CONFIG import (
    ICBC_CENTER,
    PERIODIC_DELAY,
    PERIODIC_DELAY_JITTER_SECONDS,
    PREFERRED_AFTER_DATE,
    PREFERRED_BEFORE_DATE,
    SEND_TELEGRAM_NOTIF,
    VERIFICATION_EMAIL_ADDRESS,
    VERIFICATION_EMAIL_APP_PASSWORD,
    VERIFICATION_METHOD,
    VERIFICATION_TIMEOUT_SECONDS,
)
from CONSTANTS import BOOK_A_ROAD_TEST_HOME
from driver_utils.booker import (
    check_for_incorrect_code_error,
    click_appointment_slot,
    click_book_an_appointment_tab,
    click_next_on_confirm_dialog,
    click_review_appointment,
    enter_verification_code_and_submit,
    get_current_appointment_date,
    pick_nearest_appointment,
    select_verification_method_and_send,
    start_reschedule,
    verify_booking_succeeded,
)
from driver_utils.searcher import (
    click_back_to_location_results_page,
    parse_icbc_locations_results,
    read_availability_from_open_dialog,
    search_for_bookings,
)
from driver_utils.login import perform_login
from driver_utils.startup import startup
from driver_utils.utils import dump_debug_info
from utils.availability_parser import check_available_dates_matches_config
from utils.email_code_reader import get_latest_seen_uid, wait_for_code_email
from utils.notifier import create_auto_booking_status_body, notify_booked, notify_by_telegram
from utils.telegram_bot import BotState, WELCOME_TEXT, poll_commands


class RestartSession(Exception):
    """Raised to abandon the current browser/session and start completely
    fresh, rather than trying to navigate back through several screens to
    a known-good state. Nothing is committed server-side until a
    verification code is actually submitted and confirmed (a reschedule's
    old booking is explicitly "held for you until you confirm your new
    appointment"), so abandoning the session here is safe."""


class SessionExpired(Exception):
    """Raised when ICBC has silently logged the session out mid-run --
    seen live: a long-running check landed back on the pre-login home page
    (same URL/title as before logging in) instead of the logged-in
    "Your upcoming appointments" tab it expected. This is routine
    housekeeping on ICBC's end, not a real technical failure, so it's
    handled distinctly from a generic Exception: a quiet re-login instead
    of an alarming "Hit an error" Telegram alert."""


def log(msg: str):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def sleep_before_next_check(state: BotState) -> bool:
    """Sleeps ~PERIODIC_DELAY seconds, with random jitter (+/-
    PERIODIC_DELAY_JITTER_SECONDS) so checks don't land on a perfectly
    predictable cadence. Interruptible: returns early if paused or if
    "Check Now" was pressed, in ~5s increments, so bot commands feel
    responsive instead of waiting out the full delay.

    Returns True if the wait ended early because "Check Now" was pressed
    (so the caller knows the *next* check was manually requested and
    should message back with a result regardless of outcome -- see
    was_manual_check in run_session()).
    """
    jitter = random.uniform(-PERIODIC_DELAY_JITTER_SECONDS, PERIODIC_DELAY_JITTER_SECONDS)
    delay = max(0.0, PERIODIC_DELAY + jitter)
    log(f"Sleeping {delay:.0f}s before next check.")

    step = 5.0
    remaining = delay
    while remaining > 0:
        if state.consume_check_now():
            log("Check-now requested -- skipping the rest of the wait.")
            return True
        if state.is_paused():
            log("Paused -- skipping the rest of the wait.")
            return False
        time.sleep(min(step, remaining))
        remaining -= step
    return False


PACIFIC_TZ = ZoneInfo("America/Vancouver")


def compute_effective_after_date() -> str:
    """The real lower bound for search on any given check: whichever is
    LATER between the configured eligibility floor (PREFERRED_AFTER_DATE,
    a fixed date chosen once) and tomorrow's date in Pacific time (where
    the appointments themselves are -- computed in Pacific specifically
    rather than trusting whatever timezone the host machine happens to be
    in). This runs indefinitely, so PREFERRED_AFTER_DATE would otherwise
    go stale once real time catches up to/past it; this also guarantees a
    same-day slot is never offered, always at least 1 day's notice.
    """
    tomorrow = (datetime.now(PACIFIC_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    return max(PREFERRED_AFTER_DATE, tomorrow)


def attempt_booking(driver, appointment, state: BotState):
    """Attempts to book/reschedule to one appointment, assuming the
    date/time picker dialog for the right office is already open. Reads
    the verification code automatically from email via IMAP -- fully
    automatic, no human confirmation step.

    Returns "booked" (confirmed against "Your upcoming appointments", not
    just assumed from the click) or "timeout" (no code email arrived in
    time). Raises if the code gets rejected, if the booking can't be
    confirmed, or on unexpected technical failures (missing button/field
    etc.) -- in all those cases the caller restarts with a fresh session
    and, since nothing is stored, will simply re-evaluate from scratch
    (including re-picking this same appointment if it's still available).
    """
    click_appointment_slot(driver, appointment)
    dump_debug_info(driver, "01_slot_selected")

    click_review_appointment(driver)
    dump_debug_info(driver, "02_confirm_dialog")

    click_next_on_confirm_dialog(driver)
    dump_debug_info(driver, "03_verification_method_screen")

    # Establish the IMAP baseline *before* triggering the email, so an old
    # code email already sitting in the inbox is never mistaken for this one.
    since_uid = get_latest_seen_uid()

    select_verification_method_and_send(driver, VERIFICATION_METHOD)
    dump_debug_info(driver, "04_code_sent")

    notify_by_telegram(create_auto_booking_status_body(appointment))
    log("Waiting for ICBC's verification email to arrive...")

    code = wait_for_code_email(since_uid, VERIFICATION_TIMEOUT_SECONDS)

    if code is None:
        log("No verification email arrived in time -- skipping this appointment.")
        notify_by_telegram(
            "⏱ ICBC's verification email never arrived in time, skipping that appointment. "
            "Still watching for others.",
            state,
        )
        return "timeout"

    log("Got a code from email, submitting it --")
    enter_verification_code_and_submit(driver, code)
    dump_debug_info(driver, "05_after_code_submit")

    if check_for_incorrect_code_error(driver):
        dump_debug_info(driver, "06_code_rejected")
        raise Exception(
            f"ICBC rejected the verification code we submitted (code={code!r}). "
            "Likely the email-code extraction picked up the wrong number -- "
            "check debug/06_code_rejected_*.png and the raw email."
        )

    # Don't just trust that the click worked -- confirm against the site
    # itself before ever reporting "booked".
    if not verify_booking_succeeded(driver):
        dump_debug_info(driver, "07_booking_not_confirmed")
        raise Exception(
            "Submitted the code with no rejection shown, but no appointment "
            "shows up under 'Your upcoming appointments' either -- treating "
            "this as not booked. Check debug/07_booking_not_confirmed_*.png."
        )

    dump_debug_info(driver, "07_booking_confirmed")
    return "booked"


def run_session(state: BotState):
    """Logs in, then loops forever: read the current booking's date live
    from "Your upcoming appointments" (nothing is stored locally), and
    look for anything matching preferences that's earlier than that (or,
    if there's no booking yet, anything at all within the configured
    window). Books/reschedules to the nearest such slot when found, then
    keeps going -- it never stops on its own, only on Ctrl+C, since
    there's always potentially something even earlier to find.

    Checks state.is_paused() every iteration (set live via the Telegram
    bot) and idles without touching the site at all while paused.

    Raises on any unrecoverable error so the caller can restart with a
    completely fresh browser/session.
    """
    driver = startup()
    try:
        driver.get(BOOK_A_ROAD_TEST_HOME)

        try:
            perform_login(driver)
        except Exception:
            dump_debug_info(driver, "login_failed")
            raise

        log(
            f"Logged in. Watching '{ICBC_CENTER}' for anything from {PREFERRED_AFTER_DATE} "
            f"onward that's earlier than the current booking (or a first booking if none "
            f"exists yet). Checking every {PERIODIC_DELAY}s."
        )

        was_manual_check = False
        while True:
            if state.is_paused():
                state.consume_check_now()  # don't let a stale request fire the instant we resume
                was_manual_check = False
                time.sleep(10)
                continue

            # Catch a "Check Now" press that arrived while we were doing
            # active Selenium work last cycle (not sleeping) -- sleep_before_
            # next_check() only catches one that arrives *during* the sleep.
            was_manual_check = was_manual_check or state.consume_check_now()

            try:
                current_date = get_current_appointment_date(driver)
            except Exception as e:
                dump_debug_info(driver, "get_current_appointment_date_failed")
                if BOOK_A_ROAD_TEST_HOME in driver.current_url:
                    # Bounced back to the pre-login page -- the session
                    # expired, not a real failure. See SessionExpired.
                    raise SessionExpired() from e
                raise

            # Recomputed every check: whichever is later between the fixed
            # eligibility floor and tomorrow (Pacific time) -- so this
            # never goes stale as real time passes, and a same-day slot is
            # never offered.
            effective_after_date = compute_effective_after_date()

            if current_date is not None and current_date <= effective_after_date:
                log(
                    f"Current booking ({current_date}) is already at/before the earliest "
                    f"acceptable date ({effective_after_date}) -- nothing better is possible."
                )
                state.record_check(current_date, "Already at the earliest acceptable date. Idling.")
                if was_manual_check:
                    notify_by_telegram(
                        f"✅ Checked — already at the earliest acceptable date ({current_date}). "
                        "Nothing better is possible right now.",
                        state,
                    )
                was_manual_check = sleep_before_next_check(state)
                continue

            upper_bound = current_date if current_date is not None else PREFERRED_BEFORE_DATE

            # Reschedule and a fresh booking both land on the same kind of
            # search form -- reschedule just gets there via "Reschedule
            # appointment" -> "Yes" instead of the "Book an appointment"
            # tab (confirmed live: reschedule does NOT auto-open the
            # office's dialog, despite earlier assumptions).
            if current_date is None:
                log("No upcoming appointment yet -- searching fresh.")
                try:
                    click_book_an_appointment_tab(driver)
                except Exception:
                    dump_debug_info(driver, "search_failed")
                    raise
            else:
                log(f"Current booking: {current_date}. Looking for something earlier (from {effective_after_date})...")
                try:
                    start_reschedule(driver)
                except Exception:
                    dump_debug_info(driver, "reschedule_start_failed")
                    raise

            try:
                search_for_bookings(driver)
                location_results = parse_icbc_locations_results(driver)
            except Exception:
                dump_debug_info(driver, "search_failed")
                raise

            if ICBC_CENTER not in location_results:
                dump_debug_info(driver, "center_not_found")
                raise Exception(
                    f"ICBC_CENTER '{ICBC_CENTER}' not found on the results page. "
                    f"Available centers were: {list(location_results.keys())}"
                )

            location_results[ICBC_CENTER].click()
            time.sleep(3)
            availability = read_availability_from_open_dialog(driver)

            matched = check_available_dates_matches_config(
                availability, after_date=effective_after_date, before_date=upper_bound
            )

            if matched:
                appointment = pick_nearest_appointment(matched)
                log(
                    f"{'Rescheduling to' if current_date else 'Booking'} nearest matching "
                    f"appointment: {appointment['appointmentDt']['date']} "
                    f"{appointment['startTm']}-{appointment['endTm']}"
                )
                state.record_check(
                    current_date,
                    f"Found a better slot ({appointment['appointmentDt']['date']}) -- booking it now...",
                )
                outcome = attempt_booking(driver, appointment, state)

                if outcome == "booked":
                    log(
                        f"Confirmed: {appointment['appointmentDt']['date']} "
                        f"{appointment['startTm']}-{appointment['endTm']}. Still watching for "
                        f"anything earlier."
                    )
                    state.record_check(
                        appointment['appointmentDt']['date'],
                        f"Booked {appointment['appointmentDt']['date']} "
                        f"{appointment['startTm']}-{appointment['endTm']}. Still watching for anything earlier.",
                    )
                    try:
                        notify_booked(appointment, is_reschedule=current_date is not None, state=state)
                    except Exception:
                        log("Booked/rescheduled OK but failed to send the notification:")
                        traceback.print_exc()
                    was_manual_check = sleep_before_next_check(state)
                    continue
                else:
                    # "timeout" -- verification email never arrived. Restart
                    # with a fresh session rather than navigating back from
                    # wherever this left us.
                    raise RestartSession()
            else:
                log(f"No better slot available right now (window: {effective_after_date} to {upper_bound}).")
                state.record_check(current_date, "No better slot available right now.")
                if was_manual_check:
                    notify_by_telegram(
                        f"✅ Checked — no better slot available right now "
                        f"(window: {effective_after_date} to {upper_bound}).",
                        state,
                    )
                try:
                    click_back_to_location_results_page(driver)
                except Exception:
                    dump_debug_info(driver, "back_button_failed")
                    raise
                was_manual_check = sleep_before_next_check(state)
    finally:
        driver.quit()


def main():
    """Runs the watcher forever, restarting with a clean session on any
    error so a single bad page load or a stale session doesn't kill a
    multi-day run. Never stops on its own -- there's always potentially
    something even earlier to find -- only on Ctrl+C.

    Starts the Telegram bot's command-polling loop in a background thread
    so pause/resume/status/check-now work the whole time this runs,
    independent of the watch loop restarting sessions underneath it.
    """
    if not SEND_TELEGRAM_NOTIF:
        log(
            "SEND_TELEGRAM_NOTIF = True is required in CONFIG.py "
            "(used for status updates -- booking/booked/timeout). Stopping."
        )
        return

    if VERIFICATION_METHOD.strip().lower() != "email":
        log(
            f'Only VERIFICATION_METHOD = "email" is supported right now '
            f'(got "{VERIFICATION_METHOD}") -- main.py always reads the '
            "code via IMAP regardless of this setting. Stopping."
        )
        return

    if not VERIFICATION_EMAIL_ADDRESS or not VERIFICATION_EMAIL_APP_PASSWORD:
        log(
            "VERIFICATION_EMAIL_ADDRESS and VERIFICATION_EMAIL_APP_PASSWORD must be set "
            "in CONFIG.py (needed to read the code via IMAP). Stopping."
        )
        return

    state = BotState()
    stop_event = threading.Event()
    bot_thread = threading.Thread(target=poll_commands, args=(state, stop_event), daemon=True)
    bot_thread.start()

    notify_by_telegram(WELCOME_TEXT, state)

    try:
        while True:
            try:
                run_session(state)
            except SessionExpired:
                log("ICBC session expired -- logging back in...")
                time.sleep(2)
            except RestartSession:
                log("Restarting with a fresh session...")
                time.sleep(5)
            except KeyboardInterrupt:
                log("Stopped by user.")
                break
            except Exception as e:
                log("Session hit an error, restarting from a clean login in 60s:")
                traceback.print_exc()
                notify_by_telegram(
                    f"⚠️ Hit an error, retrying automatically in 60s:\n<code>{html.escape(str(e))}</code>",
                    state,
                )
                time.sleep(60)
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
