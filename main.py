"""
main.py — FastAPI app + Telegram bot.

Two modes:
  1. Webhook mode (production): Telegram pushes updates to your HTTPS server
  2. Polling mode (development): Bot polls Telegram every few seconds

Run locally:
  python main.py
  → Starts polling mode automatically

Run in production:
  Set TELEGRAM_WEBHOOK_URL in .env
  → Starts webhook mode
"""
import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from agent.graph import run_agent
from config import get_settings
from memory.store import MemoryStore, init_db
from scheduler.jobs import AgentScheduler
from utils.error_handler import format_error_for_user, log_error_to_db
from utils.logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)
settings = get_settings()

# ── State (module-level singletons) ───────────────────────────────────────────
memory = MemoryStore()
telegram_app: Application | None = None
scheduler: AgentScheduler | None = None


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def _is_allowed(user_id: int) -> bool:
    """Check if the user is in the allowlist."""
    if not settings.telegram_allowed_users:
        return True  # If no allowlist, allow everyone (dev mode)
    return user_id in settings.allowed_user_ids


async def handle_start(update: Update, context) -> None:
    """Handle /start command."""
    user_id = update.effective_user.id
    if not await _is_allowed(user_id):
        await update.message.reply_text("⛔ You're not authorized to use this bot.")
        return

    welcome = (
        "👋 Hello! I'm your personal AI agent.\n\n"
        "I can:\n"
        "• Post on LinkedIn\n"
        "• Read and send emails\n"
        "• Research any topic\n"
        "• Take screenshots\n"
        "• Automate multi-step tasks\n\n"
        "Just tell me what to do!"
    )
    await update.message.reply_text(welcome)


async def handle_clear(update: Update, context) -> None:
    """Handle /clear command — reset conversation memory."""
    user_id = update.effective_user.id
    if not await _is_allowed(user_id):
        return
    await memory.clear_history(user_id)
    await update.message.reply_text("🧹 Memory cleared. Fresh start!")


async def handle_history(update: Update, context) -> None:
    """Handle /history command — show recent activities."""
    user_id = update.effective_user.id
    if not await _is_allowed(user_id):
        return
    activities = await memory.get_recent_activities(user_id, limit=10)
    if not activities:
        await update.message.reply_text("No recent activities found.")
        return
    lines = ["📋 Recent activities:"]
    for a in activities:
        icon = "✅" if a["status"] == "success" else "❌"
        lines.append(f"{icon} [{a['tool']}] {a['action']} — {a['at'][:16]}")
    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context) -> None:
    """
    Main message handler — called for every non-command text message.
    This is where user messages enter the agent pipeline.
    """
    user_id = update.effective_user.id

    if not await _is_allowed(user_id):
        await update.message.reply_text("⛔ You're not authorized to use this bot.")
        return

    user_message = update.message.text.strip()
    if not user_message:
        return

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    logger.info("message_received", user_id=user_id, message_preview=user_message[:50])

    try:
        # Load conversation history from memory
        history = await memory.get_history(user_id, limit=20)

        # Run the agent
        response = await run_agent(user_id, user_message, history)

        # Save both messages to memory
        await memory.add_message(user_id, "user", user_message)
        await memory.add_message(user_id, "assistant", response)

        # Log to activity store
        await memory.log_activity(
            user_id=user_id,
            tool="agent",
            action=user_message[:100],
            result=response[:200],
            status="success",
        )

        # Send response (Telegram has a 4096 char limit per message)
        if len(response) <= 4096:
            await update.message.reply_text(response)
        else:
            # Split long responses
            chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk)
                await asyncio.sleep(0.5)

    except Exception as e:
        user_friendly_error = format_error_for_user(e)
        await log_error_to_db(user_id=user_id, task=user_message, error=e)
        await memory.log_activity(
            user_id=user_id,
            tool="agent",
            action=user_message[:100],
            result=str(e)[:200],
            status="error",
        )
        await update.message.reply_text(f"❌ {user_friendly_error}")


# ── Helper to send Telegram messages (used by scheduler) ─────────────────────

async def send_telegram_message(user_id: int, text: str) -> None:
    """Send a proactive message to a user (used by scheduler)."""
    if telegram_app:
        await telegram_app.bot.send_message(chat_id=user_id, text=text)


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app, scheduler

    # Init DB
    await init_db()
    logger.info("database_initialized")

    # Build Telegram app
    telegram_app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Register handlers
    telegram_app.add_handler(CommandHandler("start", handle_start))
    telegram_app.add_handler(CommandHandler("clear", handle_clear))
    telegram_app.add_handler(CommandHandler("history", handle_history))
    telegram_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Start scheduler
    scheduler = AgentScheduler(send_telegram_message_fn=send_telegram_message)
    scheduler.start()

    if settings.telegram_webhook_url and settings.is_production:
        # Webhook mode: register with Telegram
        webhook_url = f"{settings.telegram_webhook_url}/telegram/webhook"
        await telegram_app.bot.set_webhook(webhook_url)
        await telegram_app.initialize()
        await telegram_app.start()
        logger.info("webhook_mode_started", url=webhook_url)
    else:
        # Polling mode for local dev
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        logger.info("polling_mode_started")

    yield  # ← App is running

    # Cleanup
    scheduler.stop()
    if telegram_app.updater.running:
        await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("app_shutdown_complete")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Personal AI Agent",
    description="Your personal automation agent",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive webhook updates from Telegram (production only)."""
    if not telegram_app:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "mode": "production" if settings.is_production else "development",
        "bot_running": telegram_app is not None,
    }


@app.get("/")
async def root():
    return {"message": "Personal AI Agent is running", "docs": "/docs"}


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
    )
