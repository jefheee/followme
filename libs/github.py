"""Minimal GitHub REST helpers (stdlib and aiohttp)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
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


def request(
    method: str,
    path: str,
    settings: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    url = f"{GITHUB_API}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url=url, method=method, headers=auth_headers(settings["github_token"]))
    try:
        with urllib.request.urlopen(req, timeout=settings["request_timeout_seconds"]) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.getcode(), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = {"raw": raw}
        return exc.code, body


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    parts = link_header.split(",")
    for part in parts:
        if 'rel="next"' in part:
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1:
                return part[start+1:end]
    return None


async def async_request(
    method: str,
    path_or_url: str,
    settings: dict[str, Any],
    session: aiohttp.ClientSession,
    params: dict[str, Any] | None = None,
    json_data: Any | None = None,
) -> tuple[int, Any, dict[str, str]]:
    url = path_or_url if path_or_url.startswith("http") else f"{GITHUB_API}{path_or_url}"
    headers = auth_headers(settings["github_token"])
    
    while True:
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=settings.get("request_timeout_seconds", 30),
            ) as resp:
                status = resp.status
                resp_headers = dict(resp.headers)
                
                # Defensively read rate limit headers to avoid KeyErrors
                remaining_str = resp_headers.get("X-RateLimit-Remaining")
                reset_str = resp_headers.get("X-RateLimit-Reset")
                
                is_rate_limited = False
                sleep_time = 0.0
                
                if remaining_str is not None and str(remaining_str).strip() == "0":
                    is_rate_limited = True
                elif status in (403, 429):
                    is_rate_limited = True
                    
                if is_rate_limited and reset_str is not None:
                    try:
                        reset_ts = float(reset_str)
                        delta = reset_ts - time.time()
                        if delta > 0:
                            sleep_time = delta + 2
                    except (ValueError, TypeError):
                        pass
                
                if is_rate_limited:
                    if sleep_time <= 0:
                        sleep_time = 60.0
                    logger.warning(f"Rate limit reached on {url}. Sleeping for {sleep_time:.2f}s before retry.")
                    await asyncio.sleep(sleep_time)
                    continue
                    
                try:
                    text = await resp.text()
                    body = json.loads(text) if text else None
                except Exception:
                    body = None
                    
                return status, body, resp_headers
        except Exception as exc:
            logger.error(f"Async request error for {url}: {exc}")
            raise


async def search_recent_repositories(
    settings: dict[str, Any],
    wanted: int,
    skip: set[str],
    skip_profiles: set[str] | None = None,
    session: aiohttp.ClientSession | None = None,
) -> list[dict[str, Any]]:
    """Search GitHub for recent repos; return up to `wanted` items whose full_name is not in `skip`.

    If skip_profiles is provided, filters out repositories owned by those profiles.
    """
    if session is None:
        async with aiohttp.ClientSession() as local_session:
            return await search_recent_repositories(settings, wanted, skip, skip_profiles, local_session)

    out: list[dict[str, Any]] = []
    seen: set[str] = set(skip)
    query = f"language:{settings['language']} stars:<{settings['max_stars']}"
    page = 1
    while len(out) < wanted and page <= 10:
        code, body, headers = await async_request(
            "GET", "/search/repositories", settings, session,
            params={"q": query, "sort": "updated", "order": "desc", "per_page": 100, "page": page},
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
            if skip_profiles and login in skip_profiles:
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


async def is_starred(settings: dict[str, Any], repo: str, session: aiohttp.ClientSession) -> bool:
    code, body, headers = await async_request("GET", f"/user/starred/{repo}", settings, session)
    return code == 204


async def star(settings: dict[str, Any], repo: str, session: aiohttp.ClientSession) -> bool:
    if await is_starred(settings, repo, session):
        return False
    code, body, headers = await async_request("PUT", f"/user/starred/{repo}", settings, session)
    if code == 204:
        return True
    logger.warning(f"Star failed for {repo}: {code} {body}")
    return False


async def is_following(settings: dict[str, Any], login: str, session: aiohttp.ClientSession) -> bool:
    code, body, headers = await async_request("GET", f"/user/following/{login}", settings, session)
    return code == 204


async def follow(settings: dict[str, Any], login: str, session: aiohttp.ClientSession) -> bool:
    if await is_following(settings, login, session):
        return False
    code, body, headers = await async_request("PUT", f"/user/following/{login}", settings, session)
    if code == 204:
        return True
    logger.warning(f"Follow failed for {login}: {code} {body}")
    return False


async def async_unfollow(settings: dict[str, Any], session: aiohttp.ClientSession, username: str) -> bool:
    code, body, headers = await async_request("DELETE", f"/user/following/{username}", settings, session)
    if code == 204:
        return True
    logger.warning(f"Unfollow failed for {username}: {code} {body}")
    return False

