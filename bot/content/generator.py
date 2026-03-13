import logging
import anthropic

from bot.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from bot.sports.base import SportEvent
from bot.content.prompts import (
    SYSTEM_PROMPT, build_prompt, build_system_prompt,
    MEME_INSTRUCTIONS, MEME_INSTRUCTIONS_EMPTY,
)
from bot.media.meme_picker import get_meme_menu

log = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
}


def _extract_text(response) -> str:
    """Extract the text content from a response that may include web search blocks."""
    for block in reversed(response.content):
        if block.type == "text":
            return block.text
    return ""


def _append_meme_instructions(prompt: str) -> str:
    """Append meme selection instructions to a prompt."""
    menu = get_meme_menu()
    if menu:
        return prompt + MEME_INSTRUCTIONS.format(meme_menu=menu)
    return prompt + MEME_INSTRUCTIONS_EMPTY


async def generate_quote_tweets(source_text: str, context: str = "") -> list[dict]:
    prompt = build_prompt("quote_tweet", {
        "source_text": source_text,
        "context": context or "No additional context provided.",
    })
    prompt = _append_meme_instructions(prompt)
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for quote tweet")
        return []

    text = _extract_text(response)
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t["text"]) <= 280]
    if not valid:
        return await _retry_shorter(prompt)
    return valid


async def generate_tweets_from_idea(idea: str) -> list[dict]:
    prompt = build_prompt("suggestion", {"idea": idea})
    prompt = _append_meme_instructions(prompt)
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for suggestion")
        return []

    text = _extract_text(response)
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t["text"]) <= 280]
    if not valid:
        return await _retry_shorter(prompt)
    return valid


async def generate_tweets_from_news(article_data: dict, event_type: str = "news_reaction") -> list[dict]:
    """Generate tweet options from a news article/headline."""
    article_url = article_data.get("url", "")
    prompt = build_prompt(event_type, article_data)
    prompt = _append_meme_instructions(prompt)
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for news reaction")
        return []

    text = _extract_text(response)
    # URLs count as 23 chars on Twitter + 1 space = 24 chars overhead
    max_len = 256 if article_url else 280
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t["text"]) <= max_len]
    if not valid:
        return await _retry_shorter(prompt, max_len=max_len)

    # Attach article URL to each tweet dict
    if article_url:
        for t in valid:
            t["article_url"] = article_url
    return valid


async def revise_tweet(original_tweet: str, feedback: str) -> list[dict]:
    """Regenerate a tweet incorporating user feedback."""
    prompt = build_prompt("revision", {
        "original_tweet": original_tweet,
        "feedback": feedback,
    })
    prompt = _append_meme_instructions(prompt)
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for tweet revision")
        return []

    text = _extract_text(response)
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t["text"]) <= 280]
    if not valid:
        return await _retry_shorter(prompt)
    return valid


async def generate_tweets(event: SportEvent) -> list[dict]:
    prompt = build_prompt(event.event_type, event.data)
    prompt = _append_meme_instructions(prompt)

    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for event %s", event.event_type)
        return []

    text = _extract_text(response)
    tweets = _parse_tweets(text)

    # Validate length
    valid = [t for t in tweets if len(t["text"]) <= 280]
    if not valid:
        log.warning("All generated tweets exceeded 280 chars, retrying with emphasis")
        return await _retry_shorter(prompt)

    return valid


async def _retry_shorter(original_prompt: str, max_len: int = 280) -> list[dict]:
    retry_prompt = (
        original_prompt
        + "\n\nIMPORTANT: Your previous tweets were too long. Each tweet MUST be under "
        f"{max_len} characters. Be more concise. Count characters carefully."
    )
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": retry_prompt}],
        )
    except Exception:
        log.exception("Claude API retry error")
        return []

    text = _extract_text(response)
    tweets = _parse_tweets(text)
    return [t for t in tweets if len(t["text"]) <= max_len]


def _parse_tweets(text: str) -> list[dict]:
    """Parse Claude's response into tweet dicts with text and optional meme_id."""
    tweets = []
    lines = text.strip().split("\n")

    current_text = None
    current_meme = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for TWEET: prefix (new format)
        if stripped.upper().startswith("TWEET:"):
            # Save previous tweet if exists
            if current_text is not None:
                tweets.append({"text": current_text, "meme_id": current_meme, "article_url": None})
            current_text = stripped[6:].strip().strip('"').strip("'").strip("`")
            current_meme = None
            continue

        # Check for MEME: prefix
        if stripped.upper().startswith("MEME:"):
            meme_val = stripped[5:].strip()
            if meme_val.upper() != "NONE" and meme_val:
                current_meme = meme_val.lower()
            continue

        # If we're collecting a TWEET: block, append continuation lines
        if current_text is not None:
            current_text += " " + stripped

    # Save last tweet
    if current_text is not None:
        tweets.append({"text": current_text, "meme_id": current_meme, "article_url": None})

    # If no TWEET: format found, fall back to old parsing
    if not tweets:
        tweets = _parse_tweets_legacy(text)

    # Clean up and filter
    cleaned = []
    preamble_phrases = ("here are", "here's", "sure,", "sure!", "certainly")
    for t in tweets:
        txt = t["text"].strip('"').strip("'").strip("`").strip()
        if txt and len(txt) > 10:
            if txt.lower().startswith(preamble_phrases):
                continue
            t["text"] = txt
            cleaned.append(t)

    return cleaned[:2]


def _parse_tweets_legacy(text: str) -> list[dict]:
    """Legacy parser for when Claude doesn't use TWEET:/MEME: format."""
    tweets = []
    lines = text.strip().split("\n")
    current = []

    for line in lines:
        stripped = line.strip()
        if stripped and (
            stripped.startswith(("1.", "1)", "2.", "2)", "Option 1", "Option 2",
                "Tweet 1", "Tweet 2", "**Option", "**Tweet"))
        ):
            if current:
                tweets.append("\n".join(current).strip())
                current = []
            for prefix in ("**Option 1:**", "**Option 2:**", "**Tweet 1:**", "**Tweet 2:**",
                           "Option 1:", "Option 2:", "Tweet 1:", "Tweet 2:",
                           "Option 1.", "Option 2.", "Tweet 1.", "Tweet 2.",
                           "1)", "2)", "1.", "2."):
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):].strip()
                    break
            if stripped:
                current.append(stripped)
        elif stripped:
            current.append(stripped)
        elif current:
            tweets.append("\n".join(current).strip())
            current = []

    if current:
        tweets.append("\n".join(current).strip())

    return [{"text": t, "meme_id": None, "article_url": None} for t in tweets]
