#!/usr/bin/env python3
"""Fetch N recent repositories from GitHub Search and insert them into the DB."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
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
logger = logging.getLogger("fetch")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch new repositories into the local DB.")
    parser.add_argument("-n", "--count", type=int, default=None, help="How many new repos to insert (default: FETCH_COUNT)")
    return parser.parse_args()


async def main(session: aiohttp.ClientSession | None = None) -> int:
    args = parse_args()
    settings = load_settings(PROJECT_ROOT)
    wanted = max(1, args.count if args.count is not None else settings["fetch_count"])

    conn = db.connect(settings["db_path"])
    skip = db.known_repos(conn)
    skip_profiles = db.get_processed_profiles(conn)
    logger.info(f"DB has {len(skip)} repos and {len(skip_profiles)} processed profiles; fetching up to {wanted} new ones")

    repos = await github.search_recent_repositories(settings, wanted, skip, skip_profiles, session)
    inserted = 0
    for repo in repos:
        if db.insert_repo(
            conn,
            repo=repo["full_name"],
            profile=repo["owner_login"],
            clone_url=repo["clone_url"],
            html_url=repo["html_url"],
        ):
            inserted += 1
            logger.info(f"+ {repo['full_name']} (owner: {repo['owner_login']})")
    logger.info(f"Inserted {inserted} new repositories")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

