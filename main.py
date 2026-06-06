#!/usr/bin/env python3
"""Run the full pipeline sequentially: fetch, evaluate, follow_back, subscribe, star.

Default cycle:
  1. fetch 5 new repos
  2. evaluate everything not yet scored
  3. follow back new eligible followers
  4. follow profiles updated in last 24h with idea+skill > SUBSCRIBE_THRESHOLD
  5. star repos    updated in last 24h with idea+skill > STAR_THRESHOLD
"""

from __future__ import annotations

import argparse
import logging
import sys
import asyncio
from pathlib import Path
import aiohttp

from libs import db
from libs.settings import load_settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full followme pipeline.")
    parser.add_argument("-n", "--count", type=int, default=None,
                        help="Repos to fetch this cycle (default: FETCH_COUNT, normally 5)")
    parser.add_argument("--subscribe-threshold", type=float, default=None,
                        help="idea+skill > X to follow (default: SUBSCRIBE_THRESHOLD)")
    parser.add_argument("--star-threshold", type=float, default=None,
                        help="idea+skill > Y to star (default: STAR_THRESHOLD)")
    parser.add_argument("-w", "--window-hours", type=int, default=None,
                        help="Recency window in hours (default: WINDOW_HOURS)")
    parser.add_argument("--evaluate-limit", type=int, default=None,
                        help="Cap repos evaluated this cycle (default: no cap)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip follow/star side effects; still fetches and evaluates")
    parser.add_argument("-i", "--infinite", action="store_true",
                        help="Loop forever; sleep --sleep seconds between cycles")
    parser.add_argument("--sleep", type=float, default=600.0,
                        help="Seconds to sleep between cycles in --infinite mode (default 600)")
    return parser.parse_args()


def step(label: str) -> None:
    logger.info(f"=== {label} ===")


async def run_cycle(args: argparse.Namespace, settings: dict, session: aiohttp.ClientSession) -> None:
    from scripts.fetch import run as fetch_run
    from scripts.evaluate import run as evaluate_run
    from scripts.follow_back import run as follow_back_run
    from scripts.subscribe import run as subscribe_run
    from scripts.star import run as star_run

    count = args.count if args.count is not None else settings["fetch_count"]
    subscribe_threshold = args.subscribe_threshold if args.subscribe_threshold is not None else settings["subscribe_threshold"]
    star_threshold = args.star_threshold if args.star_threshold is not None else settings["star_threshold"]
    window = args.window_hours if args.window_hours is not None else settings["window_hours"]
    dry_run = args.dry_run or settings["dry_run"]

    step(f"fetch -n {count}")
    await fetch_run(settings, session, count=count)

    step(f"evaluate{'' if args.evaluate_limit is None else f' -l {args.evaluate_limit}'}")
    await evaluate_run(settings, session, limit=args.evaluate_limit)

    step("follow_back")
    await follow_back_run(settings, session, dry_run=dry_run)

    step(f"subscribe -s {subscribe_threshold} -w {window}")
    await subscribe_run(
        settings,
        session,
        min_score=subscribe_threshold,
        window_hours=window,
        dry_run=dry_run,
    )

    step(f"star -s {star_threshold} -w {window}")
    await star_run(
        settings,
        session,
        min_score=star_threshold,
        window_hours=window,
        dry_run=dry_run,
    )

    conn = db.connect(settings["db_path"])
    s = db.stats(conn)
    logger.info(
        f"DB stats: total={s['total']} evaluated={s['evaluated']} "
        f"followed_profiles={s['followed']} starred={s['starred']} "
        f"inbound_followers={s['inbound_followers']} inbound_followed_back={s['inbound_followed_back']}"
    )


async def main_async() -> int:
    args = parse_args()
    settings = load_settings(Path(__file__).resolve().parent)

    async with aiohttp.ClientSession() as session:
        if not args.infinite:
            await run_cycle(args, settings, session)
            return 0

        cycle = 0
        while True:
            cycle += 1
            logger.info(f"# cycle {cycle}")
            try:
                await run_cycle(args, settings, session)
            except asyncio.CancelledError:
                logger.info("Infinite cycle execution cancelled.")
                break
            except KeyboardInterrupt:
                logger.info("Interrupted")
                return 130
            except Exception as exc:
                logger.warning(f"Cycle {cycle} failed: {exc}")
            
            logger.info(f"sleeping {args.sleep}s before next cycle")
            await asyncio.sleep(max(0.0, args.sleep))
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
