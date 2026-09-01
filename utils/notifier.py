"""Notifies the user when there's an available spot, via whichever channel(s)
are enabled in CONFIG.py. Telegram (the primary channel) is sent through
utils/telegram_bot.py so every push carries the same live control keyboard
and goes to every authorized chat id, consistently."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Optional

from CONFIG import (
    SEND_EMAIL_NOTIF,
    email_sender_account,
    email_sender_username,
    email_sender_password,
    email_smtp_server,
    email_smtp_port,
    email_recepients,
    SEND_TELEGRAM_NOTIF,
)
from utils.telegram_bot import BotState, send_to_all


def notify_booked(appointment: Dict, is_reschedule: bool = False, state: Optional[BotState] = None):
    """Dispatches a "booked/rescheduled an appointment" notification
    through every channel enabled in CONFIG.py. The watcher keeps running
    afterward -- it keeps looking for anything even earlier -- so this is
    a status update, not a "we're done" message."""
    verb = "Rescheduled" if is_reschedule else "Booked"
    if SEND_EMAIL_NOTIF:
        notify_by_email(
            f"{verb} your ICBC road test appointment!",
            create_booked_email_body(appointment, is_reschedule),
        )
    if SEND_TELEGRAM_NOTIF:
        notify_by_telegram(create_booked_telegram_body(appointment, is_reschedule), state)


"""--- Email ---"""


def notify_by_email(subject: str, html_body: str):
    server = smtplib.SMTP(email_smtp_server, email_smtp_port)
    server.starttls()
    server.login(email_sender_username, email_sender_password)

    # For loop, sending emails to all email recipients
    for recipient in email_recepients:
        message = MIMEMultipart("alternative")
        message["From"] = email_sender_account
        message["To"] = recipient
        message["Subject"] = subject
        message.attach(MIMEText(html_body, "html"))
        text = message.as_string()
        server.sendmail(email_sender_account, recipient, text)

    # All emails sent, log out.
    server.quit()


def create_booked_email_body(appointment: Dict, is_reschedule: bool = False) -> str:
    verb = "Rescheduled" if is_reschedule else "Booked"
    body = f"<h1>{verb} your ICBC road test appointment!</h1>"
    body += f"<strong>Date: </strong> {appointment['appointmentDt']['date']} <br>"
    body += f"<strong>Day of week: </strong> {appointment['appointmentDt']['dayOfWeek']} <br>"
    body += f"<strong>Start time: </strong> {appointment['startTm']} <br>"
    body += f"<strong>End time: </strong> {appointment['endTm']} <br>"
    body += "<br>Still watching for anything even earlier. <strong>Please double-check "
    body += "\"Your upcoming appointments\" on the ICBC site to confirm this went through.</strong>"
    return body


"""--- Telegram ---"""


def notify_by_telegram(text: str, state: Optional[BotState] = None):
    """Sends `text` to every authorized chat id (see CONFIG.py), with the
    live control keyboard attached if `state` is given."""
    send_to_all(text, state)


def create_booked_telegram_body(appointment: Dict, is_reschedule: bool = False) -> str:
    verb = "Rescheduled" if is_reschedule else "Booked"
    return (
        f"✅ <b>{verb} your ICBC road test appointment!</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {appointment['appointmentDt']['date']} ({appointment['appointmentDt']['dayOfWeek']})\n"
        f"🕐 {appointment['startTm']}–{appointment['endTm']}\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "Still watching for anything even earlier. Please double-check "
        "\"Your upcoming appointments\" on the ICBC site to confirm this went through."
    )


def create_auto_booking_status_body(appointment: Dict) -> str:
    """A heads-up only when auto-booking starts -- no reply expected or
    possible, the verification code gets read from email and submitted
    automatically."""
    return (
        "⚙️ <b>Found a matching appointment — booking it now</b>\n"
        f"📅 {appointment['appointmentDt']['date']} ({appointment['appointmentDt']['dayOfWeek']})\n"
        f"🕐 {appointment['startTm']}–{appointment['endTm']}\n\n"
        "Reading the verification code from email automatically. No action needed."
    )
