"""
agent/tools/linkedin.py — LinkedIn via linkedin-api (no browser needed).
Uses ~5MB RAM vs ~700MB for Playwright. Much more reliable.
"""
from langchain_core.tools import tool
from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

def _get_linkedin():
    from linkedin_api import Linkedin
    return Linkedin(
        settings.linkedin_email,
        settings.linkedin_password,
        authenticate=True,
    )

@tool
async def post_on_linkedin(content: str) -> str:
    """
    Post content on LinkedIn as the authenticated user.

    Use this when user says 'post on LinkedIn', 'share this on LinkedIn'.

    Args:
        content: The text content to post. Include hashtags in the content itself.
    """
    try:
        api = _get_linkedin()
        api.post(content)
        logger.info("linkedin_posted", length=len(content))
        return f"Successfully posted on LinkedIn ({len(content)} chars)."
    except Exception as e:
        logger.error("linkedin_post_failed", error=str(e))
        raise

@tool
async def generate_linkedin_post(topic: str, tone: str = "professional") -> str:
    """
    Generate a LinkedIn post draft without posting it.
    Returns the draft for user review.

    Args:
        topic: What the post should be about.
        tone: professional | casual | thought_leadership | story
    """
    tone_guides = {
        "professional": "Clear, concise, authoritative. Facts-first.",
        "casual": "Conversational and warm. Simple language.",
        "thought_leadership": "Bold take first. Challenge assumptions.",
        "story": "Start with a personal anecdote. Build to a lesson.",
    }
    return (
        f"Generate a LinkedIn post about: {topic}\n"
        f"Tone: {tone_guides.get(tone, tone_guides['professional'])}\n"
        "Format: Short paragraphs, 150-300 words, 3-5 hashtags at end."
    )
