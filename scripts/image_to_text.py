#!/usr/bin/env python3
"""
Reads the text out of image posts (SMS screenshots, chat logs, notes) so they
can be narrated like any self-post.

Uses the vision model on the configured gateway rather than classical OCR --
these images are usually chat bubbles and UI chrome, which a vision model
handles far better than Tesseract, and it can lay the result out as readable
dialogue in the same pass.

Personal identifiers are deliberately stripped: these screenshots routinely
contain real names and phone numbers, and the output gets published.
"""
import base64
import sys
from pathlib import Path

import requests

import config

TRANSCRIBE_PROMPT = """This image is from a Reddit post that will be narrated aloud in a video.

Transcribe the text it contains as a clear, readable account:
- If it's a conversation (texts, chat, DMs), format each turn as "Name: message"
  using generic labels like "Mom", "Dad", "Me", "My boss" -- whatever role the
  context supports.
- Preserve wording and tone exactly; do not soften, editorialise, or add commentary.
- REDACT every personal identifier, including ones appearing inside the message
  text itself, not just in headers:
    * phone numbers, emails, street addresses, account handles -> [redacted]
    * any person referred to by first AND last name -> keep the first name only
      (e.g. "Margaret Whitfield says you missed dinner" -> "Margaret says you
      missed dinner")
  Plain first names and role labels ("Mom", "my boss") are fine to keep.
- Label every line with its speaker, including the first one.
- Skip interface furniture (timestamps, battery icons, "Delivered", reaction counts)
  unless it actually matters to the story.

If the image contains no meaningful text, reply with exactly: NO_TEXT"""


def _headers():
    return {"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"}


def _as_data_url(raw: bytes, content_type: str = "image/jpeg") -> str:
    return f"data:{content_type};base64,{base64.b64encode(raw).decode()}"


def fetch_image(url: str, timeout: int = 30) -> tuple:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "image/jpeg").split(";")[0]


def transcribe_image(source, timeout: int = 120) -> str:
    """source: a URL string or a local Path. Returns transcribed text, or ""."""
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
        p = Path(source)
        raw, ctype = p.read_bytes(), f"image/{p.suffix.lstrip('.').replace('jpg', 'jpeg')}"
    else:
        raw, ctype = fetch_image(str(source))

    payload = {
        "model": config.LLM_MODEL_SCRIPT,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": TRANSCRIBE_PROMPT},
            {"type": "image_url", "image_url": {"url": _as_data_url(raw, ctype)}},
        ]}],
        "max_tokens": 2000,
    }
    if config.LLM_EXTRA_BODY:
        payload.update(config.LLM_EXTRA_BODY)

    r = requests.post(f"{config.LLM_BASE_URL}/chat/completions",
                      headers=_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if "choices" not in data:
        raise RuntimeError(f"Unexpected vision response: {str(data)[:400]}")

    text = (data["choices"][0]["message"].get("content") or "").strip()
    if text.upper().startswith("NO_TEXT") or not text:
        return ""
    return text


def transcribe_images(sources, timeout: int = 120) -> str:
    """Transcribe several images (a multi-screenshot post) into one block,
    in the order given."""
    parts = []
    for i, src in enumerate(sources, start=1):
        try:
            text = transcribe_image(src, timeout=timeout)
        except Exception as e:
            print(f"  image {i}: failed ({e})", file=sys.stderr)
            continue
        if text:
            parts.append(text)
    return "\n\n".join(parts)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 image_to_text.py <image-url-or-path> [more...]")
        sys.exit(1)
    out = transcribe_images(sys.argv[1:])
    print(out or "(no text found)")
