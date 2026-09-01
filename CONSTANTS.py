"""
Constants used throughout the program (not meant to be edited per-user —
see CONFIG.py for the settings you actually change).
"""

# Page URLs
BOOK_A_ROAD_TEST_HOME = "https://onlinebusiness.icbc.com/webdeas-ui/home"

# XHR endpoint ICBC's frontend calls to fetch appointment availability.
# We read this out of the browser's network log rather than calling it
# directly, since it's tied to the logged-in session/cookies.
GET_AVAILABLE_APPOINTMENTS = "https://onlinebusiness.icbc.com/deas-api/v1/web/getAvailableAppointments"
