#!/usr/bin/env python3
"""Run the full pipeline sequentially: fetch, evaluate, subscribe, star, unfollow.

Default cycle:
  1. fetch 5 new repos
  2. evaluate everything not yet scored
  3. follow profiles updated in last 24h with idea+skill > SUBSCRIBE_THRESHOLD
  4. star repos    updated in last 24h with idea+skill > STAR_THRESHOLD
  5. async purge (unfollow) cycle every 7 days (or forced)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
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
    parser.add_argument("--force-unfollow", action="store_true",
                        help="Force the unfollow cycle to run immediately")
    parser.add_argument("-i", "--infinite", action="store_true",
                        help="Loop forever; sleep --sleep seconds between cycles")
    parser.add_argument("--sleep", type=float, default=600.0,
                        help="Seconds to sleep between cycles in --infinite mode (default 600)")
    return parser.parse_args()


def step(label: str) -> None:
    logger.info(f"=== {label} ===")


async def run_cycle(args: argparse.Namespace, settings: dict, session: aiohttp.ClientSession) -> None:
    from scripts.fetch import main as fetch_main
    from scripts.evaluate import main as evaluate_main
    from scripts.subscribe import main as subscribe_main
    from scripts.star import main as star_main
    from scripts.unfollow import run as unfollow_run

    count = args.count if args.count is not None else settings["fetch_count"]
    subscribe_threshold = args.subscribe_threshold if args.subscribe_threshold is not None else settings["subscribe_threshold"]
    star_threshold = args.star_threshold if args.star_threshold is not None else settings["star_threshold"]
    window = args.window_hours if args.window_hours is not None else settings["window_hours"]

    step(f"fetch -n {count}")
    sys.argv = ["scripts/fetch.py", "-n", str(count)]
    await fetch_main(session)

    step(f"evaluate{'' if args.evaluate_limit is None else f' -l {args.evaluate_limit}'}")
    sys.argv = ["scripts/evaluate.py"] + (["-l", str(args.evaluate_limit)] if args.evaluate_limit is not None else [])
    evaluate_main()

    step(f"subscribe -s {subscribe_threshold} -w {window}")
    sub_argv = ["scripts/subscribe.py", "-s", str(subscribe_threshold), "-w", str(window)]
    if args.dry_run:
        sub_argv.append("--dry-run")
    sys.argv = sub_argv
    await subscribe_main(session)

    step(f"star -s {star_threshold} -w {window}")
    star_argv = ["scripts/star.py", "-s", str(star_threshold), "-w", str(window)]
    if args.dry_run:
        star_argv.append("--dry-run")
    sys.argv = star_argv
    await star_main(session)

    # Database-backed rate limit check for unfollow purge
    conn = db.connect(settings["db_path"])
    should_unfollow = False

    if args.force_unfollow:
        should_unfollow = True
    else:
        last_unfollow_str = db.get_metadata(conn, "last_unfollow_time")
        if last_unfollow_str is None:
            should_unfollow = True
        else:
            try:
                last_unfollow = datetime.fromisoformat(last_unfollow_str)
                delta = datetime.now(timezone.utc) - last_unfollow
                if delta.days >= 7:
                    should_unfollow = True
            except Exception as e:
                logger.warning(f"Error parsing last_unfollow_time: {e}. Defaulting to running unfollow.")
                should_unfollow = True

    if should_unfollow:
        step("unfollow (purge)")
        unfollowed = await unfollow_run(settings, session, dry_run=args.dry_run)
        logger.info(f"Unfollow cycle finished. Unfollowed {unfollowed} users.")
        if not args.dry_run:
            db.set_metadata(conn, "last_unfollow_time", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    else:
        logger.info("Unfollow cycle skipped (runs every 7 days). Use --force-unfollow to override.")

    s = db.stats(conn)
    logger.info(
        f"DB stats: total={s['total']} evaluated={s['evaluated']} "
        f"followed_profiles={s['followed']} starred={s['starred']}"
    )


async def main() -> int:
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
            except KeyboardInterrupt:
                logger.info("Interrupted")
                return 130
            except Exception as exc:
                logger.warning(f"Cycle {cycle} failed: {exc}")
            logger.info(f"sleeping {args.sleep}s before next cycle")
            await asyncio.sleep(max(0.0, args.sleep))


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
