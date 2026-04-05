"""
agent/tools/email_tool.py — Gmail integration via Google API.

Authentication: OAuth2 with offline access.
First run will open a browser to authorize. Token is saved and auto-refreshed.

Capabilities:
  - read_emails: List recent inbox messages
  - send_email: Compose and send an email
  - search_emails: Search by query (same syntax as Gmail search bar)
"""
import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.tools import tool

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# What permissions we need. Read-only for reading, send for sending.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _get_gmail_service():
    """Authenticate and return Gmail API service. Caches token locally."""
    creds = None
    token_path = settings.gmail_token_path

    # Load existing token if it exists
    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # If credentials are missing or expired, refresh or re-authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.gmail_credentials_path, SCOPES
            )
            # Opens browser for authorization on first run
            creds = flow.run_local_server(port=0)

        # Save the token for next time
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _decode_body(part: dict) -> str:
    """Safely decode a base64-encoded email body part."""
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")


@tool
async def read_emails(max_results: int = 5, label: str = "INBOX") -> str:
    """
    Read recent emails from Gmail inbox.
    Returns sender, subject, date, and a short snippet for each email.

    Use this when user says:
    - 'check my email', 'what emails do I have', 'show my inbox'

    Args:
        max_results: How many emails to fetch (1-20).
        label: Gmail label to read from. Defaults to INBOX.
    """
    try:
        service = _get_gmail_service()
        result = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_results, labelIds=[label])
            .execute()
        )
        messages = result.get("messages", [])
        if not messages:
            return "No emails found in your inbox."

        email_summaries = []
        for msg in messages:
            msg_data = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata",
                     metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in msg_data.get("payload", {}).get("headers", [])
            }
            snippet = msg_data.get("snippet", "")[:150]
            email_summaries.append(
                f"From: {headers.get('From', 'Unknown')}\n"
                f"Subject: {headers.get('Subject', 'No subject')}\n"
                f"Date: {headers.get('Date', 'Unknown')}\n"
                f"Preview: {snippet}\n"
                f"ID: {msg['id']}"
            )

        logger.info("emails_fetched", count=len(email_summaries))
        return "\n\n---\n\n".join(email_summaries)

    except Exception as e:
        logger.error("read_emails_failed", error=str(e))
        raise


@tool
async def send_email(to: str, subject: str, body: str, cc: str = "") -> str:
    """
    Compose and send an email via Gmail.

    Use this when user says:
    - 'send an email to X', 'email Y about Z', 'write and send an email'

    Args:
        to: Recipient email address (e.g. john@example.com).
        subject: Email subject line.
        body: Email body text (plain text).
        cc: Optional CC email address.
    """
    try:
        service = _get_gmail_service()

        message = MIMEMultipart("alternative")
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc

        # Attach plain text and HTML versions
        message.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        logger.info("email_sent", to=to, subject=subject)
        return f"Email sent successfully to {to} with subject '{subject}'."

    except Exception as e:
        logger.error("send_email_failed", to=to, error=str(e))
        raise


@tool
async def search_emails(query: str, max_results: int = 5) -> str:
    """
    Search Gmail using the same syntax as the Gmail search bar.
    Examples: 'from:boss@company.com', 'subject:invoice', 'is:unread'

    Use this when user asks:
    - 'find emails from X', 'search for Y in my email', 'do I have any emails about Z'

    Args:
        query: Gmail search query string.
        max_results: Number of results to return.
    """
    try:
        service = _get_gmail_service()
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = result.get("messages", [])
        if not messages:
            return f"No emails found matching '{query}'."

        summaries = []
        for msg in messages:
            msg_data = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata",
                     metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in msg_data.get("payload", {}).get("headers", [])
            }
            summaries.append(
                f"From: {headers.get('From', 'Unknown')} | "
                f"Subject: {headers.get('Subject', 'None')} | "
                f"Date: {headers.get('Date', 'Unknown')}"
            )

        return f"Found {len(summaries)} emails:\n" + "\n".join(summaries)

    except Exception as e:
        logger.error("search_emails_failed", query=query, error=str(e))
        raise
