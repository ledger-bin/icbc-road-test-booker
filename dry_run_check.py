"""One-off dry run: logs in, reads the current appointment, and reports
what WOULD be booked/rescheduled to under current CONFIG preferences --
WITHOUT touching the actual booking. Sends the result to Telegram (and
prints it), so config/selectors can be sanity-checked before trusting the
real main.py loop with them.

If no appointment matches preferences, it goes one step further as a
structural check ONLY: clicks into a real open slot (any slot -- not
necessarily one you'd actually want) and Review Appointment, to confirm
the "Would you like to book this appointment?" dialog looks like what was
already verified for a fresh booking -- then explicitly clicks Cancel on
THAT dialog and stops. It never clicks "Next", never touches the
verification-method screen, and never starts the email-code flow -- the
actual commit step is entirely untouched. ICBC's own confirmation text
says the existing booking is "held for you until you confirm your new
appointment", so opening/cancelling any of this is safe. Delete/ignore
after use -- not part of the regular watcher.
"""

import time

from CONFIG import ICBC_CENTER, PREFERRED_AFTER_DATE, PREFERRED_BEFORE_DATE
from CONSTANTS import BOOK_A_ROAD_TEST_HOME
from driver_utils.booker import (
    cancel_current_dialog,
    click_appointment_slot,
    click_book_an_appointment_tab,
    click_review_appointment,
    get_current_appointment_date,
    pick_nearest_appointment,
    start_reschedule,
)
from driver_utils.login import perform_login
from driver_utils.searcher import (
    click_back_to_location_results_page,
    parse_icbc_locations_results,
    read_availability_from_open_dialog,
    search_for_bookings,
)
from driver_utils.startup import startup
from driver_utils.utils import dump_debug_info
from utils.availability_parser import check_available_dates_matches_config
from utils.notifier import notify_by_telegram


def log(msg):
    print(f"[dry-run] {msg}", flush=True)


def main():
    driver = startup()
    try:
        driver.get(BOOK_A_ROAD_TEST_HOME)

        try:
            perform_login(driver)
        except Exception:
            dump_debug_info(driver, "dry_run_login_failed")
            raise

        try:
            current_date = get_current_appointment_date(driver)
        except Exception:
            dump_debug_info(driver, "dry_run_get_current_appointment_failed")
            raise
        log(f"Current booking date: {current_date!r}")

        if current_date is not None and current_date <= PREFERRED_AFTER_DATE:
            message = (
                f"🧪 Dry run: current booking ({current_date}) is already at/before "
                f"the earliest acceptable date ({PREFERRED_AFTER_DATE}) — nothing to "
                "search for. (Not confirming anything -- this was a dry run.)"
            )
            log(message)
            notify_by_telegram(message)
            return

        upper_bound = current_date if current_date is not None else PREFERRED_BEFORE_DATE

        # Reschedule and a fresh booking both land on the same kind of
        # search form -- confirmed live that reschedule does NOT
        # auto-open the office's dialog, so the search steps below run
        # either way, just entered differently.
        if current_date is None:
            log("No upcoming appointment -- would search fresh.")
            click_book_an_appointment_tab(driver)
        else:
            log(f"Current booking: {current_date}. Opening reschedule to check for earlier dates (won't confirm)...")
            start_reschedule(driver)

        search_for_bookings(driver)
        location_results = parse_icbc_locations_results(driver)
        if ICBC_CENTER not in location_results:
            raise Exception(
                f"ICBC_CENTER '{ICBC_CENTER}' not found. "
                f"Available: {list(location_results.keys())}"
            )
        location_results[ICBC_CENTER].click()
        time.sleep(3)

        availability = read_availability_from_open_dialog(driver)
        matched = check_available_dates_matches_config(
            availability, after_date=PREFERRED_AFTER_DATE, before_date=upper_bound
        )

        if matched:
            appointment = pick_nearest_appointment(matched)
            message = (
                f"🧪 Dry run: WOULD book/reschedule to "
                f"{appointment['appointmentDt']['date']} ({appointment['appointmentDt']['dayOfWeek']}) "
                f"{appointment['startTm']}–{appointment['endTm']}.\n"
                f"({len(matched)} total matching slot(s) in window {PREFERRED_AFTER_DATE} to {upper_bound}.)\n"
                "Not actually confirming -- this was a dry run."
            )
            log(message)
            notify_by_telegram(message)
        elif availability:
            # No real match -- but as long as SOMETHING is open, click into
            # it purely to verify the confirm-dialog structure, then cancel
            # out before anything that could trigger a verification email.
            test_appointment = pick_nearest_appointment(availability)
            log(
                f"No real match, but verifying dialog structure with a real "
                f"(unwanted) slot: {test_appointment['appointmentDt']['date']} "
                f"{test_appointment['startTm']}-{test_appointment['endTm']}"
            )
            try:
                click_appointment_slot(driver, test_appointment)
                dump_debug_info(driver, "dry_run_verify_slot_selected")

                click_review_appointment(driver)
                dump_debug_info(driver, "dry_run_verify_confirm_dialog")

                cancel_current_dialog(driver)
                dump_debug_info(driver, "dry_run_verify_cancelled")

                message = (
                    f"🧪 Dry run: no matching appointments found in window "
                    f"{PREFERRED_AFTER_DATE} to {upper_bound} ({len(availability)} total slots checked).\n\n"
                    "Extra check: clicked into a real (unwanted) slot "
                    f"({test_appointment['appointmentDt']['date']} "
                    f"{test_appointment['startTm']}) and reached the confirm "
                    "dialog successfully -- structure matches what's already "
                    "verified for booking. Cancelled before Next/verification. "
                    "Not actually confirming anything -- this was a dry run."
                )
            except Exception:
                dump_debug_info(driver, "dry_run_verify_failed")
                message = (
                    f"🧪 Dry run: no matching appointments found in window "
                    f"{PREFERRED_AFTER_DATE} to {upper_bound} ({len(availability)} total slots checked).\n\n"
                    "⚠️ Extra check FAILED: clicking into a real slot to verify "
                    "the confirm-dialog structure hit an error -- check "
                    "debug/dry_run_verify_failed_*.png. Nothing was confirmed/"
                    "booked either way."
                )
                log(message)
                notify_by_telegram(message)
                raise
            log(message)
            notify_by_telegram(message)
        else:
            message = (
                f"🧪 Dry run: no appointments at all right now "
                f"({len(availability)} total slots checked). Not actually "
                "confirming anything -- this was a dry run."
            )
            log(message)
            notify_by_telegram(message)

        # Back out cleanly without booking/confirming anything.
        try:
            click_back_to_location_results_page(driver)
        except Exception:
            dump_debug_info(driver, "dry_run_cleanup_back_failed")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
