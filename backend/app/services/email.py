"""Retryable SMTP outbox; ticket transactions never wait for a mail relay."""

import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select

from app.core.config import settings
from app.models.entities import EmailDelivery, Ticket, User, now


def send_assignment(delivery, ticket, recipient):
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient.email
    message["Subject"] = f"IT ticket assigned: {ticket.number}"
    message["Message-ID"] = f"<d2c-assignment-{delivery.id}@{settings.smtp_from.split('@')[-1]}>"
    message.set_content(
        f"An IT ticket has been assigned to you.\n\n"
        f"Ticket: {ticket.number}\nPriority: {ticket.priority.value}\n"
        f"Open the service desk to review the request and SLA:\n"
        f"{settings.public_origin.rstrip('/')}/#/tickets/{ticket.id}\n\n"
        "Please sign in to view the ticket. This mailbox notification does not process replies."
    )
    context = ssl.create_default_context()
    cls = smtplib.SMTP_SSL if settings.smtp_security == "tls" else smtplib.SMTP
    kwargs = {"context": context} if settings.smtp_security == "tls" else {}
    with cls(settings.smtp_host, settings.smtp_port, timeout=15, **kwargs) as smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def deliver_pending(db, sender=None, batch=20):
    if not settings.smtp_enabled:
        return 0
    sender = sender or send_assignment
    processed = 0
    # Commit after each message: lock prevents concurrent workers selecting the same row.
    for _ in range(batch):
        row = db.scalar(
            select(EmailDelivery)
            .where(EmailDelivery.status == "pending", EmailDelivery.available_at <= now())
            .order_by(EmailDelivery.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            db.rollback()
            break
        ticket = db.get(Ticket, row.ticket_id)
        recipient = db.get(User, row.recipient_id)
        if (
            not recipient
            or not recipient.active
            or ticket.deleted
            or ticket.assignee_id != row.recipient_id
        ):
            row.status = "cancelled"
            row.last_error = "Assignment no longer current or account unavailable"
        else:
            row.attempts += 1
            try:
                sender(row, ticket, recipient)
                row.status = "sent"
                row.sent_at = now()
                row.last_error = None
            except Exception as exc:
                # Never persist SMTP response text: it may contain credentials or addresses.
                row.last_error = type(exc).__name__[:100]
                row.available_at = now() + timedelta(seconds=min(3600, 30 * 2**row.attempts))
                if row.attempts >= 5:
                    row.status = "failed"
                logging.warning('{"event":"assignment_email_failed","delivery_id":%d}', row.id)
        db.commit()
        processed += 1
    return processed
