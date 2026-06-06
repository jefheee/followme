"""Minimal Ollama JSON-generation client (aiohttp powered)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior code reviewer. Given a repository digest, return a STRICT JSON object "
    "with exactly three fields:\n"
    '  "idea":  float in [1.0, 10.0] grading the novelty and usefulness of the project idea,\n'
    '  "skill": float in [1.0, 10.0] grading the engineering skill shown in the code,\n'
    '  "description": one short English sentence summarizing what the repository does.\n'
    "Grade anchors: 1=trivial/junior, 5=ordinary/middle, 9=strong/senior. "
    "Return ONLY the JSON object, no prose."
)


async def ensure_available(
    settings: dict[str, Any],
    session: aiohttp.ClientSession | None = None,
) -> None:
    url = f"{settings['ollama_url']}/api/tags"
    timeout_cfg = aiohttp.ClientTimeout(total=settings.get("request_timeout_seconds", 30))

    try:
        if session is not None:
            async with session.get(url, timeout=timeout_cfg) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Cannot reach Ollama: status {resp.status}")
                payload = await resp.json()
        else:
            async with aiohttp.ClientSession() as new_session:
                async with new_session.get(url, timeout=timeout_cfg) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Cannot reach Ollama: status {resp.status}")
                    payload = await resp.json()
    except Exception as exc:
        raise RuntimeError(f"Cannot reach Ollama at {settings['ollama_url']}: {exc}") from exc

    models = {str(m.get("name", "")).strip() for m in payload.get("models", []) if isinstance(m, dict)}
    if settings["ollama_model"] not in models:
        raise RuntimeError(
            f"Model '{settings['ollama_model']}' not installed in Ollama. Installed: {sorted(models)}"
        )


async def evaluate(
    settings: dict[str, Any],
    full_name: str,
    digest: str,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """Ask Ollama for {idea, skill, description}; clamp scores into [1, 10]."""
    user_prompt = f"Repository: {full_name}\nLanguage: {settings['language']}\n\nDigest:\n{digest}\n\nReturn JSON only."
    payload = {
        "model": settings["ollama_model"],
        "system": SYSTEM_PROMPT,
        "prompt": user_prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }

    url = f"{settings['ollama_url']}/api/generate"
    timeout = max(180, settings.get("request_timeout_seconds", 30))
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)

    try:
        if session is not None:
            async with session.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout_cfg) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise RuntimeError(f"Ollama HTTP {resp.status}: {err_text}")
                parsed = await resp.json()
        else:
            async with aiohttp.ClientSession() as new_session:
                async with new_session.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout_cfg) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(f"Ollama HTTP {resp.status}: {err_text}")
                    parsed = await resp.json()
    except Exception as exc:
        raise RuntimeError(f"Cannot reach Ollama: {exc}") from exc

    text = str(parsed.get("response", "")).strip()
    return parse_json_blob(text)


JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_blob(text: str) -> dict[str, Any]:
    match = JSON_OBJECT_RE.search(text)
    if not match:
        raise RuntimeError(f"Ollama did not return JSON: {text[:200]!r}")
    data = json.loads(match.group(0))
    idea = clamp(safe_float(data.get("idea"), 0.0), 1.0, 10.0)
    skill = clamp(safe_float(data.get("skill"), 0.0), 1.0, 10.0)
    description = str(data.get("description", "")).strip()
    return {"idea": idea, "skill": skill, "description": description}


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
