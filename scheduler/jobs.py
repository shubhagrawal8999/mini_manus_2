"""
scheduler/jobs.py — APScheduler jobs for automated tasks.

This runs background jobs without needing user input:
- Daily LinkedIn post at a set time
- Morning email digest
- Weekly activity summary

APScheduler runs inside the FastAPI process — no separate worker needed for MVP.
When you scale, move these to Celery or a separate cron service.
"""
import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from agent.graph import run_agent
from config import get_settings
from memory.store import MemoryStore
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class AgentScheduler:
    def __init__(self, send_telegram_message_fn):
        """
        Args:
            send_telegram_message_fn: Async function to send Telegram messages.
                Signature: async def send(user_id: int, text: str) -> None
        """
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.send = send_telegram_message_fn
        self.memory = MemoryStore()
        self._register_jobs()

    def _register_jobs(self) -> None:
        """Register all scheduled jobs."""

        # Daily LinkedIn post at 09:00 UTC
        self.scheduler.add_job(
            self.daily_linkedin_post,
            CronTrigger(hour=9, minute=0),
            id="daily_linkedin_post",
            replace_existing=True,
        )

        # Morning email digest at 08:00 UTC
        self.scheduler.add_job(
            self.morning_email_digest,
            CronTrigger(hour=8, minute=0),
            id="morning_email_digest",
            replace_existing=True,
        )

        # Weekly activity summary (Mondays 07:00 UTC)
        self.scheduler.add_job(
            self.weekly_summary,
            CronTrigger(day_of_week="mon", hour=7, minute=0),
            id="weekly_summary",
            replace_existing=True,
        )

        logger.info("scheduler_jobs_registered", job_count=3)

    async def daily_linkedin_post(self) -> None:
        """
        Generate and post daily LinkedIn content.
        Customize the prompt below to match your niche/voice.
        """
        if not settings.telegram_allowed_users:
            return

        user_id = settings.telegram_allowed_users[0]  # Post on behalf of primary user

        await self.send(user_id, "📅 Running your daily LinkedIn post automation...")

        prompt = (
            "Generate and post a LinkedIn post for today. "
            "Topic: Share an insight about AI, productivity, or entrepreneurship. "
            "Make it thought-provoking and under 250 words. "
            "Ask me for confirmation before posting."
        )

        history = await self.memory.get_history(user_id)
        response = await run_agent(user_id, prompt, history)
        await self.memory.add_message(user_id, "user", prompt)
        await self.memory.add_message(user_id, "assistant", response)
        await self.send(user_id, response)

    async def morning_email_digest(self) -> None:
        """Send a morning summary of unread emails."""
        if not settings.telegram_allowed_users:
            return

        user_id = settings.telegram_allowed_users[0]

        prompt = (
            "Check my Gmail inbox and give me a morning digest: "
            "how many unread emails, who they're from, and which ones need my attention. "
            "Keep it brief — under 200 words."
        )

        history = await self.memory.get_history(user_id, limit=5)
        response = await run_agent(user_id, prompt, history)
        await self.memory.add_message(user_id, "assistant", f"☀️ Morning digest:\n{response}")
        await self.send(user_id, f"☀️ Morning digest:\n{response}")

    async def weekly_summary(self) -> None:
        """Send a weekly summary of all agent activities."""
        if not settings.telegram_allowed_users:
            return

        user_id = settings.telegram_allowed_users[0]

        activities = await self.memory.get_recent_activities(user_id, limit=50)
        if not activities:
            await self.send(user_id, "📊 No activities recorded this week.")
            return

        # Group by tool
        from collections import Counter
        tool_counts = Counter(a["tool"] for a in activities)
        summary_lines = ["📊 Weekly summary:"]
        for tool, count in tool_counts.most_common():
            summary_lines.append(f"  • {tool}: {count} action(s)")

        success_rate = sum(1 for a in activities if a["status"] == "success") / len(activities)
        summary_lines.append(f"\nSuccess rate: {success_rate:.0%}")

        await self.send(user_id, "\n".join(summary_lines))

    def start(self) -> None:
        self.scheduler.start()
        logger.info("scheduler_started")

    def stop(self) -> None:
        self.scheduler.shutdown()
        logger.info("scheduler_stopped")
