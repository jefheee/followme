"""Minimal GitHub REST helpers (aiohttp powered)."""

from __future__ import annotations

import base64
import json
import logging
import random
import asyncio
from typing import Any
import aiohttp

GITHUB_API = "https://api.github.com"

logger = logging.getLogger(__name__)


def auth_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "followme",
    }


def git_basic_auth_header(token: str) -> str:
    if not token:
        return ""
    raw = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    return f"Authorization: Basic {raw}"


async def apply_jitter(base_delay: float = 15.0, max_delay: float = 45.0, task_index: int = 0) -> None:
    """Apply an anti-bot jitter sleep before mutations.

    For parallel requests in a batch, adds a task_index-based stagger
    so write calls don't fire at the exact same millisecond.
    """
    stagger = task_index * 1.5
    delay = random.uniform(base_delay, max_delay) + stagger
    logger.info(f"Applying jitter delay: {delay:.2f}s (stagger={stagger:.1f}s) before write action...")
    await asyncio.sleep(delay)


async def request(
    method: str,
    path: str,
    settings: dict[str, Any],
    params: dict[str, Any] | None = None,
    session: aiohttp.ClientSession | None = None,
) -> tuple[int, Any]:
    url = f"{GITHUB_API}{path}"
    headers = auth_headers(settings["github_token"])
    timeout_cfg = aiohttp.ClientTimeout(total=settings.get("request_timeout_seconds", 30))

    if session is not None:
        return await _make_request(session, method, url, headers, params, timeout_cfg)

    async with aiohttp.ClientSession() as new_session:
        return await _make_request(new_session, method, url, headers, params, timeout_cfg)


async def _make_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout_cfg: aiohttp.ClientTimeout,
) -> tuple[int, Any]:
    try:
        async with session.request(
            method,
            url,
            headers=headers,
            params=params,
            timeout=timeout_cfg,
        ) as resp:
            # Check for empty body status codes (like 204 No Content)
            if resp.status == 204:
                return resp.status, None
            raw = await resp.text(encoding="utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError:
                body = {"raw": raw}
            return resp.status, body
    except aiohttp.ClientResponseError as exc:
        logger.error(f"HTTP client response error: {exc}")
        return exc.status, {"error": str(exc)}
    except Exception as exc:
        logger.error(f"HTTP request failed: {exc}")
        return 500, {"error": str(exc)}


async def search_recent_repositories(
    settings: dict[str, Any],
    wanted: int,
    skip: set[str],
    session: aiohttp.ClientSession | None = None,
) -> list[dict[str, Any]]:
    """Search GitHub for recent repos; return up to `wanted` items whose full_name is not in `skip`."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set(skip)
    query = f"language:{settings['language']} stars:<{settings['max_stars']}"
    page = 1
    while len(out) < wanted and page <= 10:
        code, body = await request(
            "GET", "/search/repositories", settings,
            params={"q": query, "sort": "updated", "order": "desc", "per_page": 100, "page": page},
            session=session,
        )
        if code != 200 or not isinstance(body, dict):
            logger.error(f"Search failed (code={code}): {body}")
            break
        items = body.get("items") or []
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            full_name = str(item.get("full_name", "")).strip()
            owner = item.get("owner") or {}
            login = str(owner.get("login", "")).strip() if isinstance(owner, dict) else ""
            clone_url = str(item.get("clone_url", "")).strip()
            if not full_name or not login or not clone_url or full_name in seen:
                continue
            seen.add(full_name)
            out.append({
                "full_name": full_name,
                "owner_login": login,
                "clone_url": clone_url,
                "html_url": str(item.get("html_url", "")),
            })
            if len(out) >= wanted:
                break
        page += 1
    return out


async def is_starred(
    settings: dict[str, Any],
    repo: str,
    session: aiohttp.ClientSession | None = None,
) -> bool:
    code, body = await request("GET", f"/user/starred/{repo}", settings, session=session)
    return code == 204


async def star(
    settings: dict[str, Any],
    repo: str,
    session: aiohttp.ClientSession | None = None,
    task_index: int = 0,
) -> bool:
    if await is_starred(settings, repo, session=session):
        return False
    # Anti-bot delay prior to mutating state
    await apply_jitter(task_index=task_index)
    code, body = await request("PUT", f"/user/starred/{repo}", settings, session=session)
    if code == 204:
        return True
    logger.warning(f"Star failed for {repo}: {code} {body}")
    return False


async def is_following(
    settings: dict[str, Any],
    login: str,
    session: aiohttp.ClientSession | None = None,
) -> bool:
    code, body = await request("GET", f"/user/following/{login}", settings, session=session)
    return code == 204


async def follow(
    settings: dict[str, Any],
    login: str,
    session: aiohttp.ClientSession | None = None,
    task_index: int = 0,
) -> bool:
    if await is_following(settings, login, session=session):
        return False
    # Anti-bot delay prior to mutating state
    await apply_jitter(task_index=task_index)
    code, body = await request("PUT", f"/user/following/{login}", settings, session=session)
    if code == 204:
        return True
    logger.warning(f"Follow failed for {login}: {code} {body}")
    return False


async def get_followers(
    settings: dict[str, Any],
    page: int = 1,
    session: aiohttp.ClientSession | None = None,
) -> list[dict[str, Any]]:
    """Fetch user's followers page by page."""
    code, body = await request(
        "GET",
        "/user/followers",
        settings,
        params={"per_page": 100, "page": page},
        session=session,
    )
    if code == 200 and isinstance(body, list):
        return body
    logger.error(f"Failed to fetch followers: {code} {body}")
    return []


async def get_user_info(
    settings: dict[str, Any],
    username: str,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any] | None:
    """Retrieve detailed user profile payload."""
    code, body = await request("GET", f"/users/{username}", settings, session=session)
    if code == 200 and isinstance(body, dict):
        return body
    logger.error(f"Failed to fetch user info for {username}: {code} {body}")
    return None
