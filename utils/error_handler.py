"""
utils/error_handler.py — retry logic + error logging
Uses tenacity for exponential backoff. Errors are saved to SQLite for learning.
"""
import functools
import traceback
from typing import Callable, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


def with_retry(
    max_attempts: int | None = None,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator: retry a function with exponential backoff.
    Usage:
        @with_retry(max_attempts=3)
        async def call_linkedin(): ...
    """
    attempts = max_attempts or settings.max_retries

    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(
                multiplier=1,
                min=settings.retry_delay_seconds,
                max=60,
            ),
            retry=retry_if_exception_type(exceptions),
            before_sleep=before_sleep_log(logger, log_level=20),  # INFO
            reraise=True,
        )
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def format_error_for_user(error: Exception) -> str:
    """Convert a raw exception into a clean, user-friendly Telegram message."""
    error_map = {
        "ConnectionError": "Could not reach the service. Please try again shortly.",
        "TimeoutError": "The request timed out. The service may be slow.",
        "AuthenticationError": "Authentication failed. Check the credentials in settings.",
        "RateLimitError": "Rate limit hit. Please wait a moment and try again.",
    }
    error_type = type(error).__name__
    return error_map.get(
        error_type,
        f"Something went wrong ({error_type}). I'll log this and try again.",
    )


async def log_error_to_db(
    user_id: int,
    task: str,
    error: Exception,
    db_path: str = "./data/agent.db",
) -> None:
    """Persist errors to SQLite so we can learn from patterns."""
    import aiosqlite
    import json
    from datetime import datetime

    error_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "task": task,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "traceback": traceback.format_exc(),
    }

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO error_log (user_id, task, error_type, error_message, traceback, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                error_data["user_id"],
                error_data["task"],
                error_data["error_type"],
                error_data["error_message"],
                error_data["traceback"],
                error_data["timestamp"],
            ),
        )
        await db.commit()

    logger.error(
        "task_failed",
        user_id=user_id,
        task=task,
        error=str(error),
    )
