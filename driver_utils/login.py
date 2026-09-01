"""
Performs login for the user
"""
from selenium import webdriver
from selenium.webdriver.common.by import By

from CONFIG import DRIVERS_LAST_NAME, KEYWORD, LICENCE_NUMBER
from driver_utils.utils import safe_click, wait_for_page_to_load

'''XPATH SELECTORS (text-based — more resilient to CSS/class re-skins than
class names, which ICBC has changed at least once already)'''
NEXT_BUTTON_XPATH = '//button[normalize-space(text())="Next"]'
SIGN_IN_BUTTON_XPATH = '//button[normalize-space(text())="Sign in"]'

'''XPATH SELECTORS (via aria-label attributes)'''
DRIVER_NAME_INPUT_XPATH = '//input[@aria-label="driver-name"]'
DRIVER_LICENCE_INPUT_XPATH = '//input[@aria-label="driver-licence"]'
KEYWORD_INPUT_XPATH = '//input[@aria-label="keyword"]'

'''CSS SELECTORS'''
AGREE_TO_TERMS_CHECKBOX_CSS_SELECTOR = ".mat-checkbox-inner-container"


def perform_login(driver: webdriver.Chrome):
    """Performs login on the current webpage with the driver

    Args:
        driver (webdriver): webdriver to perform login on
    """

    # Wait for page to load
    wait_for_page_to_load(driver, By.XPATH, NEXT_BUTTON_XPATH)

    # Click the next button on home page to be brought to login form
    safe_click(driver, driver.find_element(By.XPATH, NEXT_BUTTON_XPATH))

    # Wait for page to load
    wait_for_page_to_load(driver, By.XPATH, SIGN_IN_BUTTON_XPATH)

    # Enter login credentials
    driver.find_element(By.XPATH, DRIVER_NAME_INPUT_XPATH).send_keys(DRIVERS_LAST_NAME)
    driver.find_element(By.XPATH, DRIVER_LICENCE_INPUT_XPATH).send_keys(LICENCE_NUMBER)
    driver.find_element(By.XPATH, KEYWORD_INPUT_XPATH).send_keys(KEYWORD)

    # Check the agree to terms checkbox
    safe_click(driver, driver.find_element(By.CSS_SELECTOR, AGREE_TO_TERMS_CHECKBOX_CSS_SELECTOR))

    # Click sign in
    safe_click(driver, driver.find_element(By.XPATH, SIGN_IN_BUTTON_XPATH))
