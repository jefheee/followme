#!/usr/bin/env python3
"""Follow GitHub profiles whose repositories scored highly in the recent window."""

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
logger = logging.getLogger("subscribe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Follow authors of high-scoring repos.")
    parser.add_argument("-s", "--min-score", type=float, default=None,
                        help="Minimum idea+skill sum to follow (default: SUBSCRIBE_THRESHOLD)")
    parser.add_argument("-w", "--window-hours", type=int, default=None,
                        help="Only consider repos updated in the last N hours (default: WINDOW_HOURS)")
    parser.add_argument("--dry-run", action="store_true", help="Log candidates without following")
    return parser.parse_args()


async def subscribe_single(
    row: sqlite3.Row,
    settings: dict[str, Any],
    session: aiohttp.ClientSession,
    conn: sqlite3.Connection,
    semaphore: asyncio.Semaphore,
    dry_run: bool,
    index: int,
) -> None:
    """Follow a single profile asynchronously, with concurrency control and jitter."""
    score = row["idea"] + row["skill"]
    async with semaphore:
        if dry_run:
            logger.info(f"would follow {row['profile']} (via {row['repo']}, sum={score:.2f})")
            return

        if await github.follow(settings, row["profile"], session=session, task_index=index):
            db.mark_followed(conn, row["profile"])
            logger.info(f"followed {row['profile']} (via {row['repo']}, sum={score:.2f})")
        else:
            db.mark_followed(conn, row["profile"])
            logger.info(f"already followed {row['profile']} — synced flag")


async def run(
    settings: dict[str, Any],
    session: aiohttp.ClientSession,
    min_score: float | None = None,
    window_hours: int | None = None,
    dry_run: bool | None = None,
) -> int:
    """Orchestrate profile subscriptions concurrently using a Semaphore."""
    target_score = min_score if min_score is not None else settings["subscribe_threshold"]
    target_window = window_hours if window_hours is not None else settings["window_hours"]
    is_dry = dry_run if dry_run is not None else settings["dry_run"]

    conn = db.connect(settings["db_path"])
    candidates = db.unfollowed_above(conn, target_score, target_window)
    logger.info(
        f"Candidates: {len(candidates)} (min_score={target_score}, window={target_window}h, dry_run={is_dry})"
    )

    max_concurrent = settings.get("max_concurrent_github_mutations", 3)
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [
        subscribe_single(
            row=row,
            settings=settings,
            session=session,
            conn=conn,
            semaphore=semaphore,
            dry_run=is_dry,
            index=index,
        )
        for index, row in enumerate(candidates, start=1)
    ]

    await asyncio.gather(*tasks)
    return 0


def main() -> int:
    args = parse_args()
    settings = load_settings(PROJECT_ROOT)

    async def _run():
        async with aiohttp.ClientSession() as session:
            return await run(
                settings,
                session,
                min_score=args.min_score,
                window_hours=args.window_hours,
                dry_run=args.dry_run,
            )

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
