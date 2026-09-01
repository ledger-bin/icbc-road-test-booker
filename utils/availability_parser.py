'''Filters raw availability results down to ones matching CONFIG preferences'''

from typing import Dict, List, Optional
from CONFIG import PREFERRED_AFTER_DATE, PREFERRED_BEFORE_DATE, PREFERRED_DAYS, PREFERRED_TIMES
from datetime import datetime

'''Constants'''
DATE_FORMATTER = '%Y-%m-%d'
DATE_AND_TIME_FORMATTER = '%Y-%m-%d %H:%M'


def check_available_dates_matches_config(
    availability, after_date: Optional[str] = None, before_date: Optional[str] = None
) -> List[Dict]:
    """Filters to appointments matching day-of-week/time preferences and
    falling in [after_date, before_date). Both default to the static
    CONFIG bounds, but the auto-book/reschedule loop overrides before_date
    with the currently-booked appointment's date -- "anything earlier than
    what I already have" rather than the fixed config ceiling.
    """
    after_date = after_date if after_date is not None else PREFERRED_AFTER_DATE
    before_date = before_date if before_date is not None else PREFERRED_BEFORE_DATE

    appointments_matching_preferences = []
    for appointment in availability:
        if does_appointment_match_preferences(appointment, after_date, before_date):
            appointments_matching_preferences.append(appointment)
    return appointments_matching_preferences


# Sample object:
# {'appointmentDt': {'dayOfWeek': 'Friday', 'date': '2022-01-07'},
# 'startTm': '14:50', 'endTm': '15:35', 'posId': 275, 'resourceId': 16369,
# 'dlExam': {'code': '5-R-1', 'description': '5-R-ROAD'},
# 'lemgMsgId': 35}
def does_appointment_match_preferences(appointment: Dict, after_date: str, before_date: str) -> bool:
    """Checks if the appointment matches the preference from the config

    Args:
        appointment (Dict): Appointment object
        after_date (str): Only match dates on/after this (YYYY-MM-DD)
        before_date (str): Only match dates strictly before this (YYYY-MM-DD)

    Returns:
        bool: True if appointment matches preference, false otherwise
    """

    day_of_week = appointment['appointmentDt']['dayOfWeek']
    date = appointment['appointmentDt']['date']
    start_time = appointment['startTm']
    end_time = appointment['endTm']

    return (check_day_of_week_in_preferences(day_of_week) and
            check_date_in_preferences(date, after_date, before_date) and
            check_start_and_end_time_in_preferences(date, start_time, end_time))


def check_day_of_week_in_preferences(day_of_week: str) -> bool:
    for day in PREFERRED_DAYS:
        if day.lower() == day_of_week.lower():
            return True
    return False


def check_date_in_preferences(date: str, after_date: str, before_date: str) -> bool:
    available_date = datetime.strptime(date, DATE_FORMATTER)
    after_dt = datetime.strptime(after_date, DATE_FORMATTER)
    before_dt = datetime.strptime(before_date, DATE_FORMATTER)
    return after_dt <= available_date < before_dt


def check_start_and_end_time_in_preferences(date: str, start_time: str, end_time: str) -> bool:
    start_time_date = datetime.strptime(f"{date} {start_time}", DATE_AND_TIME_FORMATTER)
    end_time_date = datetime.strptime(f"{date} {end_time}", DATE_AND_TIME_FORMATTER)

    for time_preference in PREFERRED_TIMES:
        preferred_start_time_date = datetime.strptime(f"{date} {time_preference[0]}", DATE_AND_TIME_FORMATTER)
        preferred_end_time_date = datetime.strptime(f"{date} {time_preference[1]}", DATE_AND_TIME_FORMATTER)
        if start_time_date >= preferred_start_time_date and end_time_date <= preferred_end_time_date:
            return True
    return False
