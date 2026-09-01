"""
Starts up the Chrome webdriver used to drive the ICBC site.
"""
import os

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from CONFIG import DEBUG

# Both set by the Docker image, pointing at the apt-installed Chromium +
# matching chromedriver (apt guarantees they're in lockstep; letting
# webdriver-manager dynamically download+match a driver against an
# apt-installed browser version is less reliable). Left unset locally --
# Selenium finds a normal local Chrome install and webdriver-manager
# downloads a matching driver on its own.
CHROME_BINARY_PATH = os.environ.get("CHROME_BINARY_PATH", "")
CHROMEDRIVER_PATH = os.environ.get("CHROMEDRIVER_PATH", "")


def startup() -> webdriver.Chrome:
    """Starts up chrome web driver.

    Configured to capture performance/network logs (needed to read the
    getAvailableAppointments XHR response) and to run headless unless
    DEBUG is True.

    Returns:
        webdriver.Chrome: chrome web driver
    """
    service = Service(CHROMEDRIVER_PATH) if CHROMEDRIVER_PATH else Service(ChromeDriverManager().install())

    options = Options()
    # Needed so we can read the XHR response bodies via CDP later on
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    if not DEBUG:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # Needed to run as root inside a container, and to avoid crashes from
    # Docker's small default /dev/shm. Harmless outside a container too.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    if CHROME_BINARY_PATH:
        options.binary_location = CHROME_BINARY_PATH

    return webdriver.Chrome(service=service, options=options)
