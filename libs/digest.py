"""Clone a repo (shallow) and build a compact text digest for the LLM."""

from __future__ import annotations

import logging
import shutil
import asyncio
from pathlib import Path
from typing import Any

from libs.github import git_basic_auth_header

logger = logging.getLogger(__name__)

IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__", ".idea", ".vscode"}


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


async def clone(clone_url: str, target: Path, depth: int, token: str) -> tuple[bool, str]:
    """Clone a repository asynchronously using shallow cloning."""
    reset_dir(target)
    cmd = ["git"]
    auth_header = git_basic_auth_header(token)
    if auth_header:
        cmd += ["-c", f"http.extraheader={auth_header}"]
    cmd += ["clone", "--depth", str(depth), "--quiet", clone_url, str(target)]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except OSError:
                pass
            return False, "clone timeout"

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            return False, err_msg or "clone failed"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def iter_files(root: Path, extensions: list[str], max_bytes: int):
    ext_set = {e.lower() for e in extensions}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in ext_set:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            continue
        yield path


def build(repo_dir: Path, settings: dict[str, Any]) -> str:
    """Return a single string digest: file tree slice + snippets."""
    files = list(iter_files(repo_dir, settings["extensions"], settings["max_file_bytes"]))[: settings["max_files"]]
    if not files:
        return ""

    lines: list[str] = ["FILES:"]
    for path in files:
        lines.append(f"  {path.relative_to(repo_dir).as_posix()}")
    lines.append("")

    total_chars = sum(len(l) + 1 for l in lines)
    for path in files:
        rel = path.relative_to(repo_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippet_lines = text.splitlines()[: settings["max_lines_per_file"]]
        snippet = "\n".join(snippet_lines)[: settings["max_chars_per_file"]]
        block = f"\n----- {rel} -----\n{snippet}\n"
        if total_chars + len(block) > settings["max_total_chars"]:
            break
        lines.append(block)
        total_chars += len(block)

    return "\n".join(lines)
