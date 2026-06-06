#!/usr/bin/env python3
"""Evaluate unrated repositories with Ollama and store idea/skill/description."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import traceback
from pathlib import Path


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


def main() -> int:
    args = parse_args()
    settings = load_settings(PROJECT_ROOT)
    conn = db.connect(settings["db_path"])

    pending = db.unevaluated(conn, limit=args.limit)
    if not pending:
        logger.info("Nothing to evaluate")
        return 0

    ollama.ensure_available(settings)
    repo_dir = Path(settings["repo_dir"])
    logger.info(f"Evaluating {len(pending)} repos with model {settings['ollama_model']}")

    for index, row in enumerate(pending, start=1):
        full_name = row["repo"]
        logger.info(f"[{index}/{len(pending)}] {full_name}")
        try:
            ok, err = digest.clone(row["clone_url"], repo_dir, settings["clone_depth"], settings["github_token"])
            if not ok:
                logger.warning(f"Clone failed for {full_name}: {err}")
                continue
            blob = digest.build(repo_dir, settings)
            if not blob:
                logger.warning(f"No usable files in {full_name}")
                continue
            result = ollama.evaluate(settings, full_name, blob)
            db.save_evaluation(conn, full_name, result["idea"], result["skill"], result["description"])
            logger.info(
                f"  idea={result['idea']:.2f} skill={result['skill']:.2f} "
                f"sum={result['idea'] + result['skill']:.2f} | {result['description']}"
            )
        except Exception as exc:
            logger.warning(f"Evaluation failed for {full_name}: {exc}\n{traceback.format_exc()}")
        finally:
            digest.remove_dir(repo_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
