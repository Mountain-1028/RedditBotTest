#!/usr/bin/env python3
"""
Client for the image-generation gateway (OpenAI-compatible
/v1/images/generations). Used for custom thumbnail generation -- the one
visual asset per video that stock footage can't really provide, since a
thumbnail needs to be a single deliberately composed, eye-catching frame.

Docs given:
  Base URL: {IMAGE_GATEWAY_BASE_URL}
  List:     GET  {base}/models
  Generate: POST {base}/generations
  Auth:     Authorization: Bearer <IMAGE_GATEWAY_API_KEY>

Some display names differ from the model id the API actually expects --
mapped below from what was shown in the model table. Everything else
(gpt-image-2, gpt-image-2.5-flare/sunburst, seedream-4.5, flux.2-pro,
veo-3.1) uses its display name as-is.
"""
import base64
import sys
from pathlib import Path

import requests

import config

# display name -> actual API model id, only where they differ
MODEL_ID_OVERRIDES = {
    "nano-banana-2": "gemini-3.1-flash-image",
    "nano-banana-lite": "gemini-3.1-flash-lite-image",
    "nano-banana-pro": "gemini-3-pro-image",
}


def _headers():
    if not config.IMAGE_GATEWAY_API_KEY:
        raise RuntimeError("IMAGE_GATEWAY_API_KEY not set in .env")
    return {"Authorization": f"Bearer {config.IMAGE_GATEWAY_API_KEY}"}


def list_models():
    r = requests.get(f"{config.IMAGE_GATEWAY_BASE_URL}/models", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def generate_image(prompt: str, out_path: Path, model: str = None, size: str = "1024x1792") -> Path:
    """size defaults to a portrait ratio close to 9:16; not all backend models
    are guaranteed to honor it exactly -- we crop/pad in assembly if needed."""
    model = model or config.IMAGE_GATEWAY_MODEL
    api_model = MODEL_ID_OVERRIDES.get(model, model)

    resp = requests.post(
        f"{config.IMAGE_GATEWAY_BASE_URL}/generations",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"model": api_model, "prompt": prompt, "size": size, "n": 1},
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Image gateway request failed ({resp.status_code}): {resp.text[:500]}")

    data = resp.json().get("data", [])
    if not data:
        raise RuntimeError(f"Image gateway returned no data: {resp.text[:500]}")

    item = data[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if "b64_json" in item:
        out_path.write_bytes(base64.b64decode(item["b64_json"]))
    elif "url" in item:
        img = requests.get(item["url"], timeout=60)
        img.raise_for_status()
        out_path.write_bytes(img.content)
    else:
        raise RuntimeError(f"Unrecognized image response shape: {item.keys()}")

    return out_path


if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Overhead shot of golden crispy parmesan chicken on a white plate, appetizing food photography, vibrant colors"
    out = generate_image(prompt, config.ASSETS_DIR / "thumbnail_test.png")
    print("Saved:", out)
