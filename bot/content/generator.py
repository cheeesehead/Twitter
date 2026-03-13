import logging
import anthropic

from bot.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from bot.sports.base import SportEvent
from bot.content.prompts import SYSTEM_PROMPT, build_prompt, build_system_prompt

log = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


async def generate_quote_tweets(source_text: str, context: str = "") -> list[str]:
    prompt = build_prompt("quote_tweet", {
        "source_text": source_text,
        "context": context or "No additional context provided.",
    })
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for quote tweet")
        return []

    text = response.content[0].text
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t) <= 280]
    if not valid:
        return await _retry_shorter(prompt)
    return valid


async def generate_tweets_from_idea(idea: str) -> list[str]:
    prompt = build_prompt("suggestion", {"idea": idea})
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for suggestion")
        return []

    text = response.content[0].text
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t) <= 280]
    if not valid:
        return await _retry_shorter(prompt)
    return valid


async def generate_tweets_from_news(article_data: dict) -> list[str]:
    """Generate tweet options from a news article/headline."""
    prompt = build_prompt("news_reaction", article_data)
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for news reaction")
        return []

    text = response.content[0].text
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t) <= 280]
    if not valid:
        return await _retry_shorter(prompt)
    return valid


async def revise_tweet(original_tweet: str, feedback: str) -> list[str]:
    """Regenerate a tweet incorporating user feedback."""
    prompt = build_prompt("revision", {
        "original_tweet": original_tweet,
        "feedback": feedback,
    })
    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for tweet revision")
        return []

    text = response.content[0].text
    tweets = _parse_tweets(text)
    valid = [t for t in tweets if len(t) <= 280]
    if not valid:
        return await _retry_shorter(prompt)
    return valid


async def generate_tweets(event: SportEvent) -> list[str]:
    prompt = build_prompt(event.event_type, event.data)

    try:
        system = await build_system_prompt()
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Claude API error for event %s", event.event_type)
        return []

    text = response.content[0].text
    tweets = _parse_tweets(text)

    # Validate length
    valid = [t for t in tweets if len(t) <= 280]
    if not valid:
        log.warning("All generated tweets exceeded 280 chars, retrying with emphasis")
        return await _retry_shorter(prompt)

    return valid


async def _retry_shorter(original_prompt: str) -> list[str]:
    retry_prompt = (
        original_prompt
        + "\n\nIMPORTANT: Your previous tweets were too long. Each tweet MUST be under 280 characters. "
        "Be more concise. Count characters carefully."
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

    text = response.content[0].text
    tweets = _parse_tweets(text)
    return [t for t in tweets if len(t) <= 280]


def _parse_tweets(text: str) -> list[str]:
    tweets = []
    lines = text.strip().split("\n")
    current = []

    for line in lines:
        stripped = line.strip()
        # Detect tweet boundaries: numbered options or blank lines between content
        if stripped and (
            stripped.startswith(("1.", "1)", "2.", "2)", "Option 1", "Option 2",
                "Tweet 1", "Tweet 2", "**Option", "**Tweet"))
        ):
            if current:
                tweets.append("\n".join(current).strip())
                current = []
            # Remove the prefix
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

    # Clean up quotes and preamble
    cleaned = []
    preamble_phrases = ("here are", "here's", "sure,", "sure!", "certainly")
    for t in tweets:
        t = t.strip('"').strip("'").strip("`").strip()
        if t and len(t) > 10:  # skip garbage fragments
            # Skip preamble lines Claude sometimes adds
            if t.lower().startswith(preamble_phrases):
                continue
            cleaned.append(t)

    return cleaned[:2]
