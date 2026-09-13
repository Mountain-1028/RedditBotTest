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
import time
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


def _normalize_images(body: dict) -> list:
    """The gateway's actual completed-job shape is {"images": [{"url": "/user_content/...jpg", ...}]}
    -- a relative path, resolved against the gateway's root domain, not the
    OpenAI-style {"data": [{"url"|"b64_json": ...}]} this originally assumed.
    That mismatch was silent: a job reaching status="completed" with real
    image data sitting under "images" looked identical to "still working" to
    the old check (`if body.get("data")`), so every call spun until the
    timeout even on a successful generation. Understands both shapes."""
    if body.get("data"):
        return body["data"]
    images = body.get("images")
    if not images:
        return []
    root = config.IMAGE_GATEWAY_BASE_URL.split("/proxy", 1)[0]
    out = []
    for item in images:
        url = item.get("url", "")
        if url.startswith("/"):
            url = root + url
        out.append({**item, "url": url})
    return out


def _await_job(job: dict, timeout: int = 300, interval: float = 5.0) -> list:
    """Poll a queued generation job until it produces images."""
    job_id = job.get("id")
    if not job_id:
        raise RuntimeError(f"Gateway accepted the job but returned no id: {job}")

    url = f"{config.IMAGE_GATEWAY_BASE_URL}/generations/{job_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(interval)
        r = requests.get(url, headers=_headers(), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Polling job {job_id} failed ({r.status_code}): {r.text[:400]}")
        body = r.json()
        status = (body.get("status") or "").lower()
        images = _normalize_images(body)
        if images:
            return images
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Image job {job_id} ended as {status}: {str(body)[:400]}")
        if status == "completed":
            # Reached a terminal success state with no recognizable image
            # data -- a genuinely new/unhandled response shape, not "still
            # working". Fail fast with the raw body rather than spinning to
            # the timeout on every future call of this kind.
            raise RuntimeError(f"Job {job_id} completed but no image data was found in a "
                              f"recognized shape: {str(body)[:400]}")
    raise TimeoutError(f"Image job {job_id} did not finish within {timeout}s")


def generate_image(prompt: str, out_path: Path, model: str = None,
                   aspect_ratio: str = "9:16", image_size: str = "1K") -> Path:
    """This gateway rejects OpenAI-style "size" and expects aspect_ratio
    (e.g. "9:16", "1:1") plus image_size (0.5K, 1K, 2K, 4K). Not every backend
    model honours the ratio exactly -- assembly crops/pads if needed."""
    model = model or config.IMAGE_GATEWAY_MODEL
    api_model = MODEL_ID_OVERRIDES.get(model, model)

    resp = requests.post(
        f"{config.IMAGE_GATEWAY_BASE_URL}/generations",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"model": api_model, "prompt": prompt, "aspect_ratio": aspect_ratio,
              "image_size": image_size, "n": 1},
        timeout=120,
    )
    if resp.status_code == 202:
        # Submit-then-poll: the gateway queues the job and returns an id.
        data = _await_job(resp.json())
    elif resp.status_code == 200:
        data = _normalize_images(resp.json())
    else:
        raise RuntimeError(f"Image gateway request failed ({resp.status_code}): {resp.text[:500]}")
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
