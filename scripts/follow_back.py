#!/usr/bin/env python3
"""Follow back new followers who meet the minimum criteria (e.g. public repos)."""

from __future__ import annotations

import argparse
import logging
import sys
import asyncio
from pathlib import Path
from typing import Any
import sqlite3
import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from libs import db, github
from libs.settings import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("follow_back")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Follow back eligible inbound followers.")
    parser.add_argument("--dry-run", action="store_true", help="Log eligible candidates without following")
    return parser.parse_args()


async def process_single_follower(
    username: str,
    settings: dict[str, Any],
    session: aiohttp.ClientSession,
    conn: sqlite3.Connection,
    semaphore: asyncio.Semaphore,
    dry_run: bool,
    index: int,
) -> None:
    """Evaluate eligibility and perform follow-back asynchronously with Semaphore control."""
    async with semaphore:
        logger.info(f"Checking eligibility of follower: {username}")
        user_info = await github.get_user_info(settings, username, session=session)
        if not user_info:
            logger.warning(f"Could not fetch info for follower {username}, skipping.")
            return

        # Eligibility criteria: must have at least one public repository
        public_repos = user_info.get("public_repos", 0)
        if public_repos <= 0:
            logger.info(f"Follower {username} does not meet requirements (repos={public_repos}). Marking as ignored.")
            if not dry_run:
                db.insert_inbound_follower(conn, username, followed_back=-1)
                db.mark_inbound_ignored(conn, username)
            return

        if dry_run:
            logger.info(f"would follow back {username} (repos={public_repos})")
            return

        # Perform follow back with anti-bot jitter
        if await github.follow(settings, username, session=session, task_index=index):
            db.insert_inbound_follower(conn, username, followed_back=1)
            db.mark_inbound_followed_back(conn, username)
            logger.info(f"Followed back {username} (repos={public_repos})")
        else:
            db.insert_inbound_follower(conn, username, followed_back=1)
            db.mark_inbound_followed_back(conn, username)
            logger.info(f"already followed back {username} (synced flag)")


async def run(
    settings: dict[str, Any],
    session: aiohttp.ClientSession,
    dry_run: bool | None = None,
) -> int:
    """Query inbound followers and follow back eligible candidates concurrently."""
    is_dry = dry_run if dry_run is not None else settings["dry_run"]
    conn = db.connect(settings["db_path"])

    logger.info("Fetching inbound followers from GitHub API...")
    followers = await github.get_followers(settings, page=1, session=session)
    if not followers:
        logger.info("No followers found or failed to fetch.")
        return 0

    new_followers = []
    for follower in followers:
        username = follower.get("login")
        if not username:
            continue
        if db.is_processed_inbound_follower(conn, username):
            continue
        new_followers.append(username)

    if not new_followers:
        logger.info("No new inbound followers to process.")
        return 0

    logger.info(f"Found {len(new_followers)} new inbound followers. Processing eligibility and follow-back...")

    max_concurrent = settings.get("max_concurrent_github_mutations", 3)
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [
        process_single_follower(
            username=username,
            settings=settings,
            session=session,
            conn=conn,
            semaphore=semaphore,
            dry_run=is_dry,
            index=index,
        )
        for index, username in enumerate(new_followers, start=1)
    ]

    await asyncio.gather(*tasks)
    return 0


def main() -> int:
    args = parse_args()
    settings = load_settings(PROJECT_ROOT)

    async def _run():
        async with aiohttp.ClientSession() as session:
            return await run(settings, session, dry_run=args.dry_run)

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
