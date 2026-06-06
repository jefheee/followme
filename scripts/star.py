#!/usr/bin/env python3
"""Star repositories whose idea+skill score exceeds a threshold within the recent window."""

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
logger = logging.getLogger("star")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Star high-scoring repos.")
    parser.add_argument("-s", "--min-score", type=float, default=None,
                        help="Minimum idea+skill sum to star (default: STAR_THRESHOLD)")
    parser.add_argument("-w", "--window-hours", type=int, default=None,
                        help="Only consider repos updated in the last N hours (default: WINDOW_HOURS)")
    parser.add_argument("--dry-run", action="store_true", help="Log candidates without starring")
    return parser.parse_args()


async def main(session: aiohttp.ClientSession | None = None) -> int:
    args = parse_args()
    settings = load_settings(PROJECT_ROOT)
    min_score = args.min_score if args.min_score is not None else settings["star_threshold"]
    window_hours = args.window_hours if args.window_hours is not None else settings["window_hours"]
    dry_run = args.dry_run or settings["dry_run"]

    if session is None:
        async with aiohttp.ClientSession() as local_session:
            return await run_star(settings, min_score, window_hours, dry_run, local_session)
    else:
        return await run_star(settings, min_score, window_hours, dry_run, session)


async def run_star(
    settings: dict[str, Any],
    min_score: float,
    window_hours: int,
    dry_run: bool,
    session: aiohttp.ClientSession,
) -> int:
    conn = db.connect(settings["db_path"])
    candidates = db.unstarred_above(conn, min_score, window_hours)
    logger.info(
        f"Candidates: {len(candidates)} (min_score={min_score}, window={window_hours}h, dry_run={dry_run})"
    )

    for row in candidates:
        score = row["idea"] + row["skill"]
        if dry_run:
            logger.info(f"would star {row['repo']} (sum={score:.2f})")
            continue
        if await github.star(settings, row["repo"], session):
            db.mark_starred(conn, row["repo"])
            logger.info(f"starred {row['repo']} (sum={score:.2f})")
        else:
            db.mark_starred(conn, row["repo"])
            logger.info(f"already starred {row['repo']} — synced flag")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

