"""
agent/tools/deep_search.py — web research tool using Tavily.

Tavily is purpose-built for LLM agents: it returns clean, summarised results,
not raw HTML. Way better than calling Google directly.

Optional: screenshot any URL using Playwright.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from tavily import TavilyClient

from config import get_settings
from utils.error_handler import with_retry
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_tavily_client: TavilyClient | None = None


def _get_tavily() -> TavilyClient:
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = TavilyClient(api_key=settings.tavily_api_key)
    return _tavily_client


@tool
async def deep_search(query: str, max_results: int = 5) -> str:
    """
    Search the web for up-to-date information on any topic.
    Returns a clean summary with sources.

    Use this when:
    - User asks 'research X', 'find out about Y', 'what is the latest on Z'
    - You need facts you don't already know
    - User asks for an article or post that needs real information

    Args:
        query: What to search for. Be specific.
        max_results: How many sources to pull (3-10).
    """
    logger.info("deep_search_start", query=query)

    try:
        client = _get_tavily()
        response = client.search(
            query=query,
            search_depth="advanced",    # 'basic' is faster, 'advanced' is more thorough
            max_results=max_results,
            include_answer=True,        # Tavily's own AI summary of results
            include_raw_content=False,  # Raw HTML — too noisy for agents
        )

        # Build a structured summary the agent can use
        answer = response.get("answer", "No summary available.")
        sources = response.get("results", [])

        result_lines = [f"Summary: {answer}", "\nSources:"]
        for i, src in enumerate(sources, 1):
            title = src.get("title", "Untitled")
            url = src.get("url", "")
            snippet = src.get("content", "")[:300]  # First 300 chars
            result_lines.append(f"\n[{i}] {title}\n    URL: {url}\n    {snippet}")

        result = "\n".join(result_lines)
        logger.info("deep_search_done", query=query, sources=len(sources))
        return result

    except Exception as e:
        logger.error("deep_search_failed", query=query, error=str(e))
        raise


@tool
async def take_screenshot(url: str) -> str:
    """
    Take a screenshot of a webpage and save it locally.
    Returns the file path of the saved screenshot.

    Use this when:
    - User asks to 'screenshot X website'
    - You want to capture visual reference material
    - User says 'take a snapshot of Y'

    Args:
        url: Full URL including https://
    """
    try:
        from playwright.async_api import async_playwright

        save_dir = Path(settings.screenshot_save_path)
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize URL for filename
        safe_name = url.replace("https://", "").replace("/", "_")[:40]
        filename = f"{timestamp}_{safe_name}.png"
        filepath = save_dir / filename

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await page.screenshot(path=str(filepath), full_page=False)
            await browser.close()

        logger.info("screenshot_saved", url=url, path=str(filepath))
        return f"Screenshot saved: {filepath}"

    except Exception as e:
        logger.error("screenshot_failed", url=url, error=str(e))
        raise
