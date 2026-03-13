import json
import os
import logging

log = logging.getLogger(__name__)

_MEME_DIR = os.path.dirname(__file__)
_MEMES_JSON = os.path.join(_MEME_DIR, "memes.json")
_IMAGES_DIR = os.path.join(_MEME_DIR, "images")

_memes: list[dict] = []


def _load_memes():
    global _memes
    try:
        with open(_MEMES_JSON, "r") as f:
            _memes = json.load(f)
    except Exception:
        log.exception("Failed to load memes.json")
        _memes = []


_load_memes()


def get_meme_menu() -> str:
    """Return a formatted list of available memes for Claude's prompt."""
    if not _memes:
        return ""
    lines = []
    for m in _memes:
        # Only include memes that have an actual image file
        path = os.path.join(_IMAGES_DIR, m["file"])
        if os.path.exists(path):
            lines.append(f'- {m["id"]}: {m["description"]} (mood: {", ".join(m["mood"])})')
    if not lines:
        return ""
    return "\n".join(lines)


def get_meme_path(meme_id: str) -> str | None:
    """Return the file path for a meme ID, or None if not found."""
    for m in _memes:
        if m["id"] == meme_id:
            path = os.path.join(_IMAGES_DIR, m["file"])
            if os.path.exists(path):
                return path
    return None
