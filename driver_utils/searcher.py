"""
Functions for the search page
"""

import time
import json
from typing import Dict, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement

from CONFIG import LOCATION
from CONSTANTS import GET_AVAILABLE_APPOINTMENTS
from driver_utils.utils import (
    filter_perf_logs,
    get_all_elements_of_web_element,
    safe_click,
    wait_for_page_to_load,
)

"""Class selectors"""
ICBC_LOCATION_RESULTS_CLASS = "results-title"
ICBC_LOCATION_DEPARTMENT_NAME_CLASS = "department-title"

"""CSS SELECTORS (formcontrolname, not the numeric mat-input-N id -- that
id comes from an Angular-wide auto-incrementing counter, so its value
depends on how many Material components mounted earlier in the session.
It happened to be "mat-input-3" reached fresh right after login, but
reaching this same field via Reschedule -> Yes (several more components
deep into the same SPA session) landed on a different number. formcontrolname
is semantic and was confirmed identical in both cases.)"""
LOCATION_FIELD_CSS_SELECTOR = 'input[formcontrolname="finishedAutocomplete"]'

"""XPATH SELECTORS (text-based via string-value, so it matches regardless
of whether the label is a direct text node or nested in a child <span>,
which varies across this site's older Material buttons vs. its newer
plain-HTML ones)"""
SEARCH_BUTTON_XPATH = '//button[normalize-space(.)="Search"]'

"""CSS SELECTORS"""
ICBC_LOCATION_RESULTS_CSS_SELECTOR = ".results-title.ng-star-inserted"
# Labelled "Cancel" on-screen, but its class says what it actually does:
# dismisses the dates dialog and returns to the office list.
ICBC_LOCATION_RESULTS_PAGE_BACK_BUTTON_CSS_SELECTOR = ".back-button"


def search_for_bookings(driver: webdriver.Chrome):
    """Searches for bookings based on config

    Args:
        driver (webdriver.Chrome): Webdriver
    """

    # Wait for the page to load
    wait_for_page_to_load(driver, By.CSS_SELECTOR, LOCATION_FIELD_CSS_SELECTOR)

    # Enter location into the form
    location_field = driver.find_element(By.CSS_SELECTOR, LOCATION_FIELD_CSS_SELECTOR)
    location_field.send_keys(LOCATION)

    # Have to manually add delay and some inputs to display autocomplete box
    time.sleep(1)
    safe_click(driver, location_field)
    location_field.send_keys(Keys.SPACE)
    location_field.send_keys(Keys.BACK_SPACE)

    # Get autocomplete box. Same reasoning as LOCATION_FIELD_CSS_SELECTOR
    # above -- don't hardcode a numeric mat-autocomplete-N id, read the
    # input's own aria-owns instead, which Angular keeps pointed at
    # whatever the real live panel id actually is.
    time.sleep(1)
    autocomplete_panel_id = location_field.get_attribute("aria-owns")
    if not autocomplete_panel_id:
        raise Exception(
            "Location field has no aria-owns attribute -- can't find its "
            "autocomplete panel. The site's markup may have changed."
        )
    autocomplete: WebElement = driver.find_element(By.ID, autocomplete_panel_id)

    # Grab autocomplete results and click on the first one
    time.sleep(1)
    autocomplete_results = get_all_elements_of_web_element(autocomplete)
    if len(autocomplete_results) == 0:
        raise Exception(f"No location found for: {LOCATION}")
    safe_click(driver, autocomplete_results[0])

    # Click the search button
    safe_click(driver, driver.find_element(By.XPATH, SEARCH_BUTTON_XPATH))


def parse_icbc_locations_results(driver: webdriver.Chrome) -> Dict[str, WebElement]:
    """Parses the ICBC location results page into a lookup of center name -> element

    Args:
        driver (webdriver.Chrome): Webdriver

    Returns:
        Dict[str, WebElement]: Map of ICBC center name to its clickable result element
    """

    # Wait for page to load
    wait_for_page_to_load(driver, By.CLASS_NAME, ICBC_LOCATION_RESULTS_CLASS)

    # Grab each office's title element directly, rather than the results
    # container as a whole. The container also wraps section headers
    # ("Nearest location:" / "Other nearby locations:"), so indexing into
    # its direct children (as the original approach did) resolves to one
    # oversized wrapper div spanning every office -- clicking its center
    # then lands on whichever office happens to be there, not the one
    # actually being looked up.
    title_elements = driver.find_elements(By.CLASS_NAME, ICBC_LOCATION_DEPARTMENT_NAME_CLASS)

    # Convert to dictionary with key of location name and webelement values
    results_dict = {}
    for title_element in title_elements:
        key = title_element.text.strip()
        results_dict[key] = title_element

    return results_dict


def read_availability_from_open_dialog(driver: webdriver.Chrome) -> List[Dict]:
    """Reads the getAvailableAppointments XHR response for whichever
    office's dates dialog is currently open (after clicking a location
    card -- the search flow is identical for a fresh booking and a
    reschedule; reschedule just enters it via a different button).

    Args:
        driver (webdriver.Chrome): Chrome web driver

    Returns:
        List[Dict]: List of availability objects
    """
    logs_raw = driver.get_log("performance")
    logs = [json.loads(lr["message"])["message"] for lr in logs_raw]

    # Filter for the endpoint we are querying for; bail out (empty) if it
    # didn't fire rather than crashing the whole run
    matching_logs = filter_perf_logs(logs, GET_AVAILABLE_APPOINTMENTS)
    if not matching_logs:
        return []

    # Use the most recent matching response
    log = matching_logs[-1]
    response_body = driver.execute_cdp_cmd(
        "Network.getResponseBody", {"requestId": log["params"]["requestId"]}
    )

    # Return the body which contains availabilities
    return json.loads(response_body["body"])


def get_icbc_location_availability(
    driver: webdriver.Chrome, element: WebElement
) -> List[Dict]:
    """Clicks a location card to open its dates dialog, then reads its
    availability.

    Args:
        driver (webdriver.Chrome): Chrome web driver
        element (WebElement): Clickable element that brings driver to availability page

    Returns:
        List[Dict]: List of availability objects
    """
    safe_click(driver, element)
    time.sleep(3)
    return read_availability_from_open_dialog(driver)


def click_back_to_location_results_page(driver: webdriver.Chrome):
    """Clicks the back button on the ICBC results page

    Args:
        driver (webdriver.Chrome): Chrome web driver
    """
    safe_click(driver, driver.find_element(By.CSS_SELECTOR, ICBC_LOCATION_RESULTS_PAGE_BACK_BUTTON_CSS_SELECTOR))
