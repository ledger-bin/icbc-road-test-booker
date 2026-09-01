"""
Steps through ICBC's booking flow for a single chosen appointment,
including the phone/email verification-code step.

Verified live against the real site (via debug/ dumps from actual runs)
all the way through submitting the verification code. A real run showed
that a *wrong* code gets visibly rejected ("We don't recognize that
code", submit button stays disabled) rather than erroring out -- so
success is never assumed from the click alone. See
check_for_incorrect_code_error() and verify_booking_succeeded(), which
main.py's attempt_booking() uses to confirm against the site itself
(via "Your upcoming appointments") before ever reporting "booked".

Every step dumps a screenshot + HTML to debug/ regardless of outcome, so
a wrong guess is easy to diagnose.
"""

import re
import time
from datetime import datetime
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from driver_utils.utils import dump_debug_info, safe_click, wait_for_page_to_load

# --- Verified against the live site ---
REVIEW_APPOINTMENT_BUTTON_XPATH = '//button[normalize-space(.)="Review Appointment"]'
NEXT_ON_CONFIRM_DIALOG_XPATH = (
    '//button[normalize-space(.)="Next" and contains(@class,"collapsible-action-button")]'
)
# Distinct from the office-list ".back-button" -- this Cancel belongs to
# the "Would you like to book this appointment?" / verification dialogs.
CANCEL_CONFIRM_DIALOG_XPATH = (
    '//button[normalize-space(.)="Cancel" and contains(@class,"collapsible-action-button")]'
)

# --- Verified against the live site (from a real run's debug dump) ---
SEND_CODE_BUTTON_XPATH = '//button[normalize-space(.)="Send"]'

CODE_INPUT_XPATH_CANDIDATES = [
    '//input[@formcontrolname="otpField"]',  # exact match, seen live
    '//input[@aria-label="code"]',  # exact match, seen live
    '//input[contains(translate(@aria-label, "CODE", "code"), "code")]',
    '//input[@type="tel"]',
]

# The real label is "Submit code and book appointment", but it also
# carries this semantic class -- prefer the class since it's less likely
# to break on copy tweaks than matching the full sentence.
SUBMIT_CODE_BUTTON_CSS_SELECTOR = ".submit-code-button"

# Verified against the live site: shown when a wrong/expired code is
# submitted (the submit button itself stays visibly disabled in that case
# too, but this text is the clearest, most explicit signal).
INCORRECT_CODE_ERROR_TEXT = "We don't recognize that code"

# Verified against the live site (tab label on the booking page).
YOUR_UPCOMING_APPOINTMENTS_TAB_XPATH = '//*[normalize-space(text())="Your upcoming appointments"]'
NO_UPCOMING_APPOINTMENTS_TEXT = "No upcoming appointments"
BOOK_AN_APPOINTMENT_TAB_XPATH = '//*[normalize-space(text())="Book an appointment"]'

# Verified against the live site (from a real search_failed debug dump,
# captured on "Your upcoming appointments" once a booking existed):
# each field is a "label"/"content" div pair, e.g.
#   <div class="label">Appointment date</div>
#   <div class="content">November 5th, 2026</div>
RESCHEDULE_BUTTON_XPATH = '//button[normalize-space(.)="Reschedule appointment"]'
APPOINTMENT_DATE_CONTENT_XPATH = (
    '//div[@class="label" and normalize-space(text())="Appointment date"]'
    '/following-sibling::div[@class="content"][1]'
)

# NOT verified against the live DOM -- the "Are you sure you would like to
# reschedule...Yes/No" dialog was only seen in a manual screenshot, not one
# of our own debug dumps. If this fails, check debug/reschedule_confirm_*
# for the real markup.
RESCHEDULE_CONFIRM_YES_XPATH = '//button[normalize-space(.)="Yes"]'


def pick_nearest_appointment(matched_appointments: List[Dict]) -> Dict:
    """Returns the earliest appointment (by date, then start time)."""
    def sort_key(appt):
        return (appt['appointmentDt']['date'], appt['startTm'])
    return sorted(matched_appointments, key=sort_key)[0]


def _format_date_heading(date_str: str, day_of_week: str) -> str:
    """Formats a date to match ICBC's on-screen heading, e.g.
    "Thursday, November 5th, 2026"."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    day = dt.day
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day_of_week}, {dt.strftime('%B')} {day}{suffix}, {dt.year}"


def _format_time_label(time_str: str) -> str:
    """Formats a 24h "HH:MM" time to match ICBC's on-screen button label,
    e.g. "9:50 AM"."""
    dt = datetime.strptime(time_str, "%H:%M")
    hour12 = dt.hour % 12 or 12
    period = "AM" if dt.hour < 12 else "PM"
    return f"{hour12}:{dt.minute:02d} {period}"


def click_appointment_slot(driver: webdriver.Chrome, appointment: Dict):
    """Finds and clicks the specific date/time slot button matching the
    given appointment, inside the currently-open dates dialog. Scoped to
    the specific date heading first, since the same time can appear under
    more than one date.
    """
    date_heading_text = _format_date_heading(
        appointment['appointmentDt']['date'], appointment['appointmentDt']['dayOfWeek']
    )
    time_label = _format_time_label(appointment['startTm'])

    heading_xpath = f'//*[normalize-space(text())="{date_heading_text}"]'
    heading: WebElement = driver.find_element(By.XPATH, heading_xpath)

    slot_xpath = f'./following::button[normalize-space(.)="{time_label}"][1]'
    slot_button: WebElement = heading.find_element(By.XPATH, slot_xpath)
    safe_click(driver, slot_button)


def click_review_appointment(driver: webdriver.Chrome):
    """Clicks "Review Appointment", which opens the "Would you like to
    book this appointment?" summary dialog."""
    wait_for_page_to_load(driver, By.XPATH, REVIEW_APPOINTMENT_BUTTON_XPATH)
    safe_click(driver, driver.find_element(By.XPATH, REVIEW_APPOINTMENT_BUTTON_XPATH))


def click_next_on_confirm_dialog(driver: webdriver.Chrome):
    """Clicks "Next" on the "Would you like to book this appointment?"
    dialog, which leads to the verification-method screen."""
    wait_for_page_to_load(driver, By.XPATH, NEXT_ON_CONFIRM_DIALOG_XPATH)
    safe_click(driver, driver.find_element(By.XPATH, NEXT_ON_CONFIRM_DIALOG_XPATH))


def cancel_current_dialog(driver: webdriver.Chrome):
    """Backs out of the "Would you like to book this appointment?" dialog
    specifically (before Send has been clicked). Not used on the /no or
    timeout paths during auto-booking -- those abandon the session
    entirely instead of navigating back through several screens (see
    main.py's RestartSession); kept here for reference/manual use."""
    safe_click(driver, driver.find_element(By.XPATH, CANCEL_CONFIRM_DIALOG_XPATH))


def select_verification_method_and_send(driver: webdriver.Chrome, method: str):
    """Selects Email or SMS on the verification-method screen and clicks
    Send. `method` should be "sms" or "email" (case-insensitive).

    NOTE: unverified against the live DOM -- matches on visible label
    text ("SMS (send verification code..." / "Email (send verification
    code..."), which should be resilient to markup/class changes, but
    hasn't been confirmed live. Check debug/ if this fails.
    """
    label = "SMS" if method.strip().lower() == "sms" else "Email"
    method_xpath = f'//*[contains(text(), "{label} (send verification code")]'
    wait_for_page_to_load(driver, By.XPATH, method_xpath)
    safe_click(driver, driver.find_element(By.XPATH, method_xpath))

    safe_click(driver, driver.find_element(By.XPATH, SEND_CODE_BUTTON_XPATH))
    time.sleep(2)  # let the code-entry screen settle


def enter_verification_code_and_submit(driver: webdriver.Chrome, code: str):
    """Enters the verification code into the "Verification Code" field and
    clicks "Submit code and book appointment".

    Raises (with a debug dump) if the input field can't be found -- that
    would mean the screen itself changed shape, not just copy.
    """
    input_field = None
    for xpath in CODE_INPUT_XPATH_CANDIDATES:
        elements = [e for e in driver.find_elements(By.XPATH, xpath) if e.is_displayed()]
        if elements:
            input_field = elements[0]
            break

    if input_field is None:
        dump_debug_info(driver, "code_input_not_found")
        raise Exception(
            "Reached the code-entry screen but couldn't find an input field. "
            "Check debug/code_input_not_found_*.png and update "
            "CODE_INPUT_XPATH_CANDIDATES in driver_utils/booker.py."
        )

    safe_click(driver, input_field)
    input_field.send_keys(code)
    time.sleep(0.5)  # let Angular's form validation enable the submit button

    submit_buttons = driver.find_elements(By.CSS_SELECTOR, SUBMIT_CODE_BUTTON_CSS_SELECTOR)
    if not submit_buttons:
        dump_debug_info(driver, "code_submit_button_not_found")
        raise Exception(
            f'Entered the code but couldn\'t find "{SUBMIT_CODE_BUTTON_CSS_SELECTOR}". '
            "Check debug/code_submit_button_not_found_*.png and update "
            "SUBMIT_CODE_BUTTON_CSS_SELECTOR in driver_utils/booker.py."
        )
    safe_click(driver, submit_buttons[0])


def check_for_incorrect_code_error(driver: webdriver.Chrome) -> bool:
    """Returns True if ICBC is currently showing the "We don't recognize
    that code" error -- i.e. the submitted code was wrong or expired.
    """
    time.sleep(1.5)  # let the error banner render if it's going to
    return len(driver.find_elements(By.XPATH, f'//*[contains(text(), "{INCORRECT_CODE_ERROR_TEXT}")]')) > 0


def verify_booking_succeeded(driver: webdriver.Chrome) -> bool:
    """Authoritative check for whether the appointment actually got
    booked: navigates to "Your upcoming appointments" and confirms
    something now shows up there.

    This matters because clicking "submit" doesn't by itself guarantee
    ICBC accepted it -- a real run showed a "Booked!" outcome get reported
    even though the code had been rejected. Verify against the site
    itself rather than trusting the click.
    """
    safe_click(driver, driver.find_element(By.XPATH, YOUR_UPCOMING_APPOINTMENTS_TAB_XPATH))
    time.sleep(2)
    body_text = driver.find_element(By.TAG_NAME, "body").text
    return NO_UPCOMING_APPOINTMENTS_TEXT not in body_text


def get_current_appointment_date(driver: webdriver.Chrome) -> Optional[str]:
    """Reads the currently-booked appointment's date (YYYY-MM-DD) live from
    "Your upcoming appointments", or None if there isn't one.

    This is the live source of truth for the reschedule-to-something-
    earlier loop -- nothing about an existing booking is stored locally;
    every check re-reads it from the site itself.
    """
    # Right after login the browser is still navigating from the login URL
    # to the booking page -- wait for the tab to actually exist rather than
    # racing it (a bare find_element here intermittently fired before the
    # post-login page had finished loading).
    wait_for_page_to_load(driver, By.XPATH, YOUR_UPCOMING_APPOINTMENTS_TAB_XPATH)
    safe_click(driver, driver.find_element(By.XPATH, YOUR_UPCOMING_APPOINTMENTS_TAB_XPATH))
    time.sleep(2)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    if NO_UPCOMING_APPOINTMENTS_TEXT in body_text:
        return None

    date_elements = driver.find_elements(By.XPATH, APPOINTMENT_DATE_CONTENT_XPATH)
    if not date_elements:
        dump_debug_info(driver, "appointment_date_not_parsed")
        raise Exception(
            "On 'Your upcoming appointments' with a booking present, but "
            "couldn't find/parse its date field. Check "
            "debug/appointment_date_not_parsed_*.png and update "
            "APPOINTMENT_DATE_CONTENT_XPATH in driver_utils/booker.py."
        )

    raw = date_elements[0].text.strip()  # e.g. "November 5th, 2026"
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw)
    return datetime.strptime(cleaned, "%B %d, %Y").strftime("%Y-%m-%d")


def click_book_an_appointment_tab(driver: webdriver.Chrome):
    safe_click(driver, driver.find_element(By.XPATH, BOOK_AN_APPOINTMENT_TAB_XPATH))
    time.sleep(1)


def start_reschedule(driver: webdriver.Chrome):
    """Clicks "Reschedule appointment" and confirms "Yes" on the follow-up
    dialog ("Your current booking is held for you until you confirm your
    new appointment" -- so nothing is lost if we back out afterward).

    Lands on a "Re-booking a road test for:" search form -- same shape as
    the fresh-booking search page (confirmed live: no location or dialog
    is pre-filled/opened automatically). The caller still needs to run
    search_for_bookings() + parse_icbc_locations_results() + click the
    office, exactly like a fresh booking.
    """
    safe_click(driver, driver.find_element(By.XPATH, RESCHEDULE_BUTTON_XPATH))

    try:
        wait_for_page_to_load(driver, By.XPATH, RESCHEDULE_CONFIRM_YES_XPATH)
    except Exception:
        dump_debug_info(driver, "reschedule_confirm_dialog_not_found")
        raise
    # This exact click failed live once already -- ICBC's site occasionally
    # shows a third-party Qualtrics survey popup on top of this dialog,
    # intercepting a plain click. safe_click() falls back to a JS click,
    # which bypasses the overlay instead of failing on it.
    safe_click(driver, driver.find_element(By.XPATH, RESCHEDULE_CONFIRM_YES_XPATH))
    time.sleep(3)
