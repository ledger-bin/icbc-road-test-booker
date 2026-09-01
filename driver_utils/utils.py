'''
General utils for the driver
'''

import os
from datetime import datetime
from typing import List
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webelement import WebElement

DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug")


def dump_debug_info(driver: webdriver.Chrome, tag: str) -> None:
    """Saves a screenshot + full page HTML + current URL/title so a headless
    failure can actually be diagnosed instead of just seeing a bare timeout.

    Args:
        driver (webdriver.Chrome): Driver in whatever state it failed in
        tag (str): Short label for the failure point, used in the filenames
    """
    os.makedirs(DEBUG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = os.path.join(DEBUG_DIR, f"{tag}_{ts}.png")
    html_path = os.path.join(DEBUG_DIR, f"{tag}_{ts}.html")

    try:
        current_url = driver.current_url
        title = driver.title
    except Exception as e:
        current_url = title = f"<unavailable: {e}>"

    try:
        driver.save_screenshot(screenshot_path)
    except Exception as e:
        screenshot_path = f"<failed to save: {e}>"

    try:
        with open(html_path, "w") as f:
            f.write(driver.page_source)
    except Exception as e:
        html_path = f"<failed to save: {e}>"

    print(
        f"(debug) [{tag}] url={current_url!r} title={title!r}\n"
        f"(debug) [{tag}] screenshot={screenshot_path}\n"
        f"(debug) [{tag}] html={html_path}",
        flush=True,
    )


def wait_for_page_to_load(driver: webdriver.Chrome, by: By, selector: str, delay: int = 10):
    """Waits for page to load

    Args:
        driver (webdriver.Chrome): Driver
        by (By): Selenium locator strategy
        selector (str): Selector string matching the locator strategy
        delay (int): Delay to wait for before raising Exception. Default of 10 seconds

    """
    try:
        WebDriverWait(driver, delay).until(EC.presence_of_element_located((by, selector)))
    except TimeoutException:
        raise TimeoutException(f"Could not load page in time for delay: {delay}s (waiting on {by}={selector})")


def get_all_elements_of_web_element(element: WebElement) -> List[WebElement]:
    """Gets an array of all subelements of the webelement

    Args:
        element (WebElement): Parent webelement

    Returns:
        List[WebElement]: Array of child webElements
    """
    return element.find_elements(By.XPATH, './*')


def filter_perf_logs(logs, url):
    result = []
    for log in logs:
        if log_filter(log, url):
            result.append(log)
    return result


# Filter for logs
def log_filter(log, url):
    return (
        log["method"] == "Network.responseReceived" and
        log["params"]["response"]["url"] == url
        and "json" in log["params"]["response"]["mimeType"]
    )
