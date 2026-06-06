"""SQLite schema and queries.

Single table `entries`: one row per repository. The owner login lives in
the `profile` column; following status is mirrored across all rows of the
same profile to keep follow state consistent.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    repo         TEXT PRIMARY KEY,
    profile      TEXT NOT NULL,
    clone_url    TEXT NOT NULL,
    html_url     TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    followed     INTEGER NOT NULL DEFAULT 0,
    starred      INTEGER NOT NULL DEFAULT 0,
    idea         REAL,
    skill        REAL,
    description  TEXT
);
CREATE INDEX IF NOT EXISTS entries_profile_idx  ON entries(profile);
CREATE INDEX IF NOT EXISTS entries_updated_idx  ON entries(updated_at);
CREATE INDEX IF NOT EXISTS entries_idea_skill_idx ON entries((COALESCE(idea,0) + COALESCE(skill,0)));

CREATE TABLE IF NOT EXISTS inbound_followers (
    profile      TEXT PRIMARY KEY,
    unfollowed   INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS inbound_followers_unfollowed_idx ON inbound_followers(unfollowed);

CREATE TABLE IF NOT EXISTS metadata (
    key          TEXT PRIMARY KEY,
    value        TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def known_repos(conn: sqlite3.Connection) -> set[str]:
    return {row["repo"] for row in conn.execute("SELECT repo FROM entries")}


def insert_repo(
    conn: sqlite3.Connection,
    repo: str,
    profile: str,
    clone_url: str,
    html_url: str,
) -> bool:
    """Insert a new repo entry. Returns True if inserted, False if it existed."""
    now = now_iso()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO entries
            (repo, profile, clone_url, html_url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (repo, profile, clone_url, html_url, now, now),
    )
    conn.commit()
    return cur.rowcount > 0


def unevaluated(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM entries WHERE idea IS NULL OR skill IS NULL ORDER BY created_at ASC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql))


def save_evaluation(
    conn: sqlite3.Connection,
    repo: str,
    idea: float,
    skill: float,
    description: str,
) -> None:
    conn.execute(
        """
        UPDATE entries
           SET idea = ?, skill = ?, description = ?, updated_at = ?
         WHERE repo = ?
        """,
        (idea, skill, description, now_iso(), repo),
    )
    conn.commit()


def window_cutoff_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def unfollowed_above(
    conn: sqlite3.Connection,
    min_score: float,
    window_hours: int,
) -> list[sqlite3.Row]:
    """Distinct profiles with at least one repo updated in the window where idea+skill > min_score
    and which we have not followed yet. Returns one representative row per profile."""
    cutoff = window_cutoff_iso(window_hours)
    return list(
        conn.execute(
            """
            SELECT * FROM entries
             WHERE followed = 0
               AND updated_at >= ?
               AND idea IS NOT NULL AND skill IS NOT NULL
               AND (idea + skill) > ?
             GROUP BY profile
             ORDER BY (idea + skill) DESC
            """,
            (cutoff, min_score),
        )
    )


def unstarred_above(
    conn: sqlite3.Connection,
    min_score: float,
    window_hours: int,
) -> list[sqlite3.Row]:
    cutoff = window_cutoff_iso(window_hours)
    return list(
        conn.execute(
            """
            SELECT * FROM entries
             WHERE starred = 0
               AND updated_at >= ?
               AND idea IS NOT NULL AND skill IS NOT NULL
               AND (idea + skill) > ?
             ORDER BY (idea + skill) DESC
            """,
            (cutoff, min_score),
        )
    )


def mark_followed(conn: sqlite3.Connection, profile: str) -> None:
    conn.execute("UPDATE entries SET followed = 1 WHERE profile = ?", (profile,))
    conn.commit()


def mark_starred(conn: sqlite3.Connection, repo: str) -> None:
    conn.execute("UPDATE entries SET starred = 1 WHERE repo = ?", (repo,))
    conn.commit()


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) AS c FROM entries").fetchone()["c"]
    evaluated = conn.execute(
        "SELECT COUNT(*) AS c FROM entries WHERE idea IS NOT NULL"
    ).fetchone()["c"]
    followed = conn.execute("SELECT COUNT(DISTINCT profile) AS c FROM entries WHERE followed = 1").fetchone()["c"]
    starred = conn.execute("SELECT COUNT(*) AS c FROM entries WHERE starred = 1").fetchone()["c"]
    return {"total": total, "evaluated": evaluated, "followed": followed, "starred": starred}


def mark_unfollowed(conn: sqlite3.Connection, profile: str) -> None:
    now = now_iso()
    conn.execute(
        """
        INSERT OR REPLACE INTO inbound_followers (profile, unfollowed, updated_at)
        VALUES (?, 1, ?)
        """,
        (profile, now),
    )
    conn.commit()


def get_processed_profiles(conn: sqlite3.Connection) -> set[str]:
    """Get all profiles that are followed or have been unfollowed."""
    query = """
    SELECT profile FROM entries WHERE followed = 1
    UNION
    SELECT profile FROM inbound_followers WHERE unfollowed = 1
    """
    return {row["profile"] for row in conn.execute(query)}


def is_profile_processed(conn: sqlite3.Connection, profile: str) -> bool:
    """Check if a profile is either currently followed or has been unfollowed.

    Uses a highly performant query with UNION and LIMIT 1 to minimize I/O.
    """
    query = """
    SELECT 1 FROM entries WHERE profile = ? AND followed = 1
    UNION
    SELECT 1 FROM inbound_followers WHERE profile = ? AND unfollowed = 1
    LIMIT 1
    """
    cur = conn.execute(query, (profile, profile))
    return cur.fetchone() is not None


def get_metadata(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()

