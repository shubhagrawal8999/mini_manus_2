"""
agent/tools/google_sheets.py — log every agent action to a Google Sheet.

This gives you a permanent, human-readable audit trail of everything the agent does.
The sheet acts as a command log and can be shared with collaborators.

Setup:
  1. Enable Google Sheets API in Google Cloud Console
  2. Share your target Sheet with the service account email (or use OAuth like Gmail)
  3. Set GOOGLE_SHEET_ID in .env
"""
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.tools import tool
from pathlib import Path

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_sheets_service():
    """Auth + return Sheets API service. Reuses Gmail token if available."""
    creds = None
    token_path = settings.gmail_token_path  # Share token with Gmail

    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.gmail_credentials_path, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


async def _ensure_headers(service, spreadsheet_id: str) -> None:
    """Create header row if the sheet is empty."""
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="A1:F1")
        .execute()
    )
    if not result.get("values"):
        headers = [["Timestamp", "User ID", "Tool", "Action", "Result", "Status"]]
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="A1",
            valueInputOption="RAW",
            body={"values": headers},
        ).execute()


@tool
async def log_to_sheets(
    user_id: int,
    tool_name: str,
    action: str,
    result: str,
    status: str = "success",
) -> str:
    """
    Log an agent action to the Google Sheet activity log.
    This is called automatically after each tool use. Users rarely call this directly.

    Args:
        user_id: Telegram user ID.
        tool_name: Which tool was used (e.g. 'linkedin', 'gmail').
        action: What was done (e.g. 'post published').
        result: Short description of the outcome.
        status: 'success' or 'error'.
    """
    if not settings.google_sheet_id:
        return "Google Sheet ID not configured. Skipping log."

    try:
        service = _get_sheets_service()
        await _ensure_headers(service, settings.google_sheet_id)

        row = [[
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            str(user_id),
            tool_name,
            action,
            result[:500],  # Cap to 500 chars to avoid Sheet cell limits
            status,
        ]]

        service.spreadsheets().values().append(
            spreadsheetId=settings.google_sheet_id,
            range="A:F",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": row},
        ).execute()

        logger.info("sheet_logged", tool=tool_name, action=action)
        return "Logged to Google Sheets."

    except Exception as e:
        logger.error("sheet_log_failed", error=str(e))
        # Don't raise — a logging failure should never crash the agent
        return f"Sheet logging failed (non-critical): {e}"
