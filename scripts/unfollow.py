#!/usr/bin/env python3
"""Asynchronously purge non-reciprocal followed accounts."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
import aiohttp

from libs import db, github

logger = logging.getLogger("unfollow")


def read_whitelist(project_root_str: str) -> set[str]:
    """Read whitelist.txt synchronously (to be run in executor/thread)."""
    whitelist_path = Path(project_root_str) / "whitelist.txt"
    if not whitelist_path.exists():
        logger.info(f"No whitelist.txt found at {whitelist_path.resolve()}")
        return set()

    try:
        with open(whitelist_path, "r", encoding="utf-8") as f:
            profiles = {
                line.strip().lower()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            }
            logger.info(f"Loaded {len(profiles)} whitelisted profiles from {whitelist_path}")
            return profiles
    except Exception as exc:
        logger.error(f"Failed to read whitelist.txt: {exc}")
        return set()


async def run(settings: dict[str, Any], session: aiohttp.ClientSession, dry_run: bool = False) -> int:
    """Run the async unfollow cycle.
    
    1. Fetch whitelist of protected users.
    2. Retrieve the complete following and followers lists with pagination.
    3. Identify targets (following but not in followers, and not whitelisted).
    4. Unfollow targets and record them in the SQLite DB.
    
    Returns the number of users successfully unfollowed (or would be unfollowed in dry-run).
    """
    logger.info("Starting async unfollow (purge) cycle...")
    
    # 1. Load Whitelist
    project_root = settings.get("project_root", ".")
    whitelist = await asyncio.to_thread(read_whitelist, project_root)
    
    # 2. Paginated User Retrieval helper
    async def fetch_all_users(endpoint: str) -> set[str]:
        users: set[str] = set()
        next_url: str | None = endpoint
        while next_url:
            # We fetch 100 users per page
            params = {"per_page": 100} if not next_url.startswith("http") else None
            status, body, headers = await github.async_request(
                "GET", next_url, settings, session, params=params
            )
            if status != 200:
                logger.error(f"Failed to fetch users from {next_url} (status={status}): {body}")
                break
                
            if isinstance(body, list):
                for item in body:
                    if isinstance(item, dict) and "login" in item:
                        users.add(str(item["login"]).strip())
            
            # Read next page link header
            link_header = headers.get("Link") or headers.get("link")
            next_url = github.parse_next_link(link_header)
        return users

    logger.info("Fetching profiles followed by this account...")
    following = await fetch_all_users("/user/following")
    
    logger.info("Fetching profiles following this account...")
    followers = await fetch_all_users("/user/followers")
    
    logger.info(f"Summary: Following {len(following)} users | Followers: {len(followers)} users")
    
    # 3. Identify targets
    following_lower = {u.lower(): u for u in following}
    followers_lower = {u.lower() for u in followers}
    
    targets: list[str] = []
    for u_lower, original_name in following_lower.items():
        if u_lower not in followers_lower and u_lower not in whitelist:
            targets.append(original_name)
            
    logger.info(f"Identified {len(targets)} profiles to unfollow (non-reciprocal and not whitelisted).")
    
    # 4. Perform unfollow operations
    conn = db.connect(settings["db_path"])
    unfollowed_count = 0
    
    for target in targets:
        if dry_run:
            logger.info(f"[Dry Run] Would unfollow: {target}")
            unfollowed_count += 1
            continue
            
        success = await github.async_unfollow(settings, session, target)
        if success:
            db.mark_unfollowed(conn, target)
            logger.info(f"Successfully unfollowed: {target}")
            unfollowed_count += 1
        else:
            logger.error(f"Failed to unfollow: {target}")
            
    return unfollowed_count
