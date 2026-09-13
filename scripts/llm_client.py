#!/usr/bin/env python3
"""
Thin wrapper around the OpenAI-compatible client so every stage of the
pipeline talks to Danny's gateway the same way, regardless of which
underlying model (Gemini/Qwen/Claude/GLM/etc.) is selected per call.
"""
from openai import OpenAI

import config

_client = None

# The gateway reports upstream failures as a normal 200 completion whose body
# is a markdown error page, so nothing raises and callers happily use it as
# model output. That is not theoretical: a 503 page once reached the narration
# field and was synthesized into a finished video, read aloud. Any response
# carrying these markers is treated as a failed call.
_PROXY_ERROR_MARKERS = (
    "<!-- oai-proxy-error -->",
    "Proxy error (HTTP",
    "oai-proxy-error",
    '"proxy_note"',
)


class GatewayError(RuntimeError):
    """The gateway returned an error page in place of a completion."""


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.LLM_BASE_URL or not config.LLM_API_KEY:
            raise RuntimeError(
                "LLM_BASE_URL / LLM_API_KEY not set. Add them to .env in the project root."
            )
        _client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    return _client


def call_llm(model: str, system: str, user: str, max_tokens: int = 1200, temperature: float = 0.9,
             json_mode: bool = False) -> str:
    client = get_client()
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if config.LLM_EXTRA_BODY:
        kwargs["extra_body"] = config.LLM_EXTRA_BODY

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    )
    content = resp.choices[0].message.content
    if content and any(m in content for m in _PROXY_ERROR_MARKERS):
        snippet = " ".join(content.split())[:180]
        raise GatewayError(f"gateway returned an error page instead of a completion: {snippet}")
    return content


if __name__ == "__main__":
    import sys
    print(call_llm(config.LLM_MODEL_SCRIPT, "You are helpful.", sys.argv[1] if len(sys.argv) > 1 else "Say hi in 5 words."))
