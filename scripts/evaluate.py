#!/usr/bin/env python3
"""Evaluate unrated repositories with Ollama and store idea/skill/description."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
import asyncio
import tempfile
from pathlib import Path
from typing import Any
import sqlite3
import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from libs import db, digest, ollama
from libs.settings import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("evaluate")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade unrated repositories using Ollama.")
    parser.add_argument("-l", "--limit", type=int, default=None, help="Max repos to evaluate this run")
    return parser.parse_args()


async def evaluate_single_repo(
    row: sqlite3.Row,
    settings: dict[str, Any],
    session: aiohttp.ClientSession,
    conn: sqlite3.Connection,
    semaphore: asyncio.Semaphore,
    index: int,
    total: int,
) -> None:
    """Evaluate a single repository asynchronously within a concurrency semaphore."""
    full_name = row["repo"]
    async with semaphore:
        logger.info(f"[{index}/{total}] Starting evaluation for {full_name}")
        try:
            # Exclusive volatile temporary directory per coroutine task
            with tempfile.TemporaryDirectory() as temp_dir:
                repo_dir = Path(temp_dir)
                ok, err = await digest.clone(
                    row["clone_url"],
                    repo_dir,
                    settings["clone_depth"],
                    settings["github_token"],
                )
                if not ok:
                    logger.warning(f"Clone failed for {full_name}: {err}")
                    return

                blob = digest.build(repo_dir, settings)
                if not blob:
                    logger.warning(f"No usable files in {full_name}")
                    return

                result = await ollama.evaluate(settings, full_name, blob, session=session)
                
                db.save_evaluation(
                    conn,
                    full_name,
                    result["idea"],
                    result["skill"],
                    result["description"],
                )
                logger.info(
                    f"  {full_name} -> idea={result['idea']:.2f} skill={result['skill']:.2f} "
                    f"sum={result['idea'] + result['skill']:.2f} | {result['description']}"
                )
        except Exception as exc:
            logger.warning(f"Evaluation failed for {full_name}: {exc}\n{traceback.format_exc()}")


async def run(
    settings: dict[str, Any],
    session: aiohttp.ClientSession,
    limit: int | None = None,
) -> int:
    """Run parallel evaluations using a Semaphore limit."""
    conn = db.connect(settings["db_path"])

    pending = db.unevaluated(conn, limit=limit)
    if not pending:
        logger.info("Nothing to evaluate")
        return 0

    await ollama.ensure_available(settings, session=session)

    # Use max_concurrent_evaluations setting, default to 2
    max_concurrent = settings.get("max_concurrent_evaluations", 2)
    semaphore = asyncio.Semaphore(max_concurrent)
    logger.info(f"Evaluating {len(pending)} repos with model {settings['ollama_model']} (concurrency limit: {max_concurrent})")

    tasks = [
        evaluate_single_repo(
            row=row,
            settings=settings,
            session=session,
            conn=conn,
            semaphore=semaphore,
            index=index,
            total=len(pending),
        )
        for index, row in enumerate(pending, start=1)
    ]

    await asyncio.gather(*tasks)
    return 0


def main() -> int:
    args = parse_args()
    settings = load_settings(PROJECT_ROOT)

    async def _run():
        async with aiohttp.ClientSession() as session:
            return await run(settings, session, limit=args.limit)

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
