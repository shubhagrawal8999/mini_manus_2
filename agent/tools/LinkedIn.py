"""
agent/tools/linkedin.py — LinkedIn automation via Playwright headless browser.

Why Playwright and not the LinkedIn API?
  LinkedIn's official API has extremely restricted posting access.
  Browser automation is the practical approach for a personal agent.
  Uses the li_at session cookie — the same one your browser has when logged in.

WARNING: LinkedIn's ToS prohibits some forms of automation.
  Use this for legitimate personal productivity (your own posts, your own data).
  Do not use for spam, scraping at scale, or anything that harms others.
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool

from config import get_settings
from utils.error_handler import with_retry
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

LINKEDIN_HOME = "https://www.linkedin.com"
LINKEDIN_FEED = "https://www.linkedin.com/feed/"


async def _get_browser_page():
    """
    Return an authenticated Playwright page using the li_at cookie.
    This is the simplest auth method — copy your li_at cookie from browser DevTools.
    """
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    )

    # Inject the li_at cookie — this authenticates us without logging in
    await context.add_cookies([
        {
            "name": "li_at",
            "value": settings.linkedin_li_at_cookie,
            "domain": ".linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        }
    ])

    page = await context.new_page()
    return playwright, browser, context, page


@tool
async def post_on_linkedin(content: str, hashtags: list[str] | None = None) -> str:
    """
    Post content on LinkedIn as the authenticated user.

    Use this when user says:
    - 'post on LinkedIn', 'share this on LinkedIn', 'publish a post about X'

    Args:
        content: The text content of the LinkedIn post.
        hashtags: Optional list of hashtags to append (without #). E.g. ['AI', 'Tech']
    """
    # Append hashtags if provided
    if hashtags:
        tag_string = " ".join(f"#{tag}" for tag in hashtags)
        full_content = f"{content}\n\n{tag_string}"
    else:
        full_content = content

    playwright, browser, context, page = await _get_browser_page()

    try:
        # Navigate to feed
        await page.goto(LINKEDIN_FEED, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)  # Let the page settle

        # Click "Start a post" button
        start_post_selectors = [
            '[aria-label="Start a post"]',
            'button:has-text("Start a post")',
            '.share-box-feed-entry__trigger',
        ]
        clicked = False
        for selector in start_post_selectors:
            try:
                await page.click(selector, timeout=5_000)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            raise RuntimeError("Could not find the 'Start a post' button on LinkedIn.")

        await asyncio.sleep(1)

        # Type content into the post editor
        editor = page.locator('[role="textbox"]').first
        await editor.click()
        await editor.fill(full_content)
        await asyncio.sleep(1)

        # Click the Post button
        post_button_selectors = [
            'button[aria-label="Post"]',
            'button:has-text("Post"):not([aria-label="Start a post"])',
            '.share-actions__primary-action',
        ]
        posted = False
        for selector in post_button_selectors:
            try:
                await page.click(selector, timeout=5_000)
                posted = True
                break
            except Exception:
                continue

        if not posted:
            raise RuntimeError("Could not find the Post submit button.")

        await asyncio.sleep(3)  # Wait for post to go through

        logger.info("linkedin_posted", content_length=len(full_content))
        return f"Successfully posted on LinkedIn! Content ({len(full_content)} chars) published."

    except Exception as e:
        # Save a debug screenshot when something goes wrong
        debug_path = Path("./screenshots") / f"linkedin_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        debug_path.parent.mkdir(exist_ok=True)
        try:
            await page.screenshot(path=str(debug_path))
            logger.error("linkedin_post_failed", error=str(e), screenshot=str(debug_path))
        except Exception:
            logger.error("linkedin_post_failed", error=str(e))
        raise

    finally:
        await browser.close()
        await playwright.stop()


@tool
async def generate_linkedin_post(
    topic: str,
    tone: Literal["professional", "casual", "thought_leadership", "story"] = "professional",
    include_cta: bool = True,
) -> str:
    """
    Generate a LinkedIn post on a given topic WITHOUT actually posting it.
    Returns the draft for the user to review before posting.

    Use this when user says:
    - 'write a LinkedIn post about X', 'draft a post for LinkedIn on Y'
    - 'create content for LinkedIn'

    Args:
        topic: What the post should be about.
        tone: Writing style.
        include_cta: Whether to include a call-to-action at the end.
    """
    # This tool is intentionally thin — it hands off to the LLM.
    # The LLM's response IS the tool result. We just return the prompt structure.
    tone_guides = {
        "professional": "Clear, concise, authoritative. Use short paragraphs. Facts-first.",
        "casual": "Conversational, warm, like talking to a friend. Use simple language.",
        "thought_leadership": "Bold take first. Challenge assumptions. Share a unique insight.",
        "story": "Start with a personal anecdote. Build to a lesson. End with takeaway.",
    }
    cta_instruction = (
        "End with 1 question to drive comments, or a clear call-to-action."
        if include_cta else ""
    )

    return (
        f"Generate a LinkedIn post about: {topic}\n"
        f"Tone: {tone_guides.get(tone, tone_guides['professional'])}\n"
        f"{cta_instruction}\n"
        "Format: Use line breaks for readability. No bullet spam. 150-300 words. "
        "Include 3-5 relevant hashtags at the end."
    )
