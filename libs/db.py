"""SQLite schema and queries.

Single table `entries`: one row per repository. The owner login lives in
the `profile` column; following status is mirrored across all rows of the
same profile to keep follow state consistent.

New table `inbound_followers`: tracks external profiles that followed the
user to facilitate follow-back actions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
    followed_back INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging immediately after opening
    conn.execute("PRAGMA journal_mode=WAL;")
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
    with conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO entries
                (repo, profile, clone_url, html_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (repo, profile, clone_url, html_url, now, now),
        )
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
    with conn:
        conn.execute(
            """
            UPDATE entries
               SET idea = ?, skill = ?, description = ?, updated_at = ?
             WHERE repo = ?
            """,
            (idea, skill, description, now_iso(), repo),
        )


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
    with conn:
        conn.execute("UPDATE entries SET followed = 1 WHERE profile = ?", (profile,))


def mark_starred(conn: sqlite3.Connection, repo: str) -> None:
    with conn:
        conn.execute("UPDATE entries SET starred = 1 WHERE repo = ?", (repo,))


def is_inbound_followed(conn: sqlite3.Connection, profile: str) -> bool:
    """Check if profile is followed in entries OR followed_back in inbound_followers.

    Uses UNION and LIMIT 1 to optimize query execution and avoid multiple disk operations.
    """
    row = conn.execute(
        """
        SELECT 1 FROM entries WHERE profile = ? AND followed = 1
        UNION
        SELECT 1 FROM inbound_followers WHERE profile = ? AND followed_back = 1
        LIMIT 1
        """,
        (profile, profile),
    ).fetchone()
    return row is not None


def insert_inbound_follower(
    conn: sqlite3.Connection,
    profile: str,
    followed_back: int = 0,
) -> bool:
    """Insert an inbound follower. Returns True if inserted, False if existed."""
    now = now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO inbound_followers (profile, followed_back, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (profile, followed_back, now, now),
        )
        return cur.rowcount > 0


def mark_inbound_followed_back(conn: sqlite3.Connection, profile: str) -> None:
    """Mark inbound follower as followed back."""
    now = now_iso()
    with conn:
        conn.execute(
            """
            UPDATE inbound_followers
               SET followed_back = 1, updated_at = ?
             WHERE profile = ?
            """,
            (now, profile),
        )


def mark_inbound_ignored(conn: sqlite3.Connection, profile: str) -> None:
    """Mark inbound follower as ignored (does not meet criteria)."""
    now = now_iso()
    with conn:
        conn.execute(
            """
            UPDATE inbound_followers
               SET followed_back = -1, updated_at = ?
             WHERE profile = ?
            """,
            (now, profile),
        )


def is_processed_inbound_follower(conn: sqlite3.Connection, profile: str) -> bool:
    """Check if the profile is already followed in entries or exists in inbound_followers."""
    row = conn.execute(
        """
        SELECT 1 FROM entries WHERE profile = ? AND followed = 1
        UNION
        SELECT 1 FROM inbound_followers WHERE profile = ?
        LIMIT 1
        """,
        (profile, profile),
    ).fetchone()
    return row is not None



def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) AS c FROM entries").fetchone()["c"]
    evaluated = conn.execute(
        "SELECT COUNT(*) AS c FROM entries WHERE idea IS NOT NULL"
    ).fetchone()["c"]
    followed = conn.execute("SELECT COUNT(DISTINCT profile) AS c FROM entries WHERE followed = 1").fetchone()["c"]
    starred = conn.execute("SELECT COUNT(*) AS c FROM entries WHERE starred = 1").fetchone()["c"]
    inbound = conn.execute("SELECT COUNT(*) AS c FROM inbound_followers").fetchone()["c"]
    inbound_followed = conn.execute("SELECT COUNT(*) AS c FROM inbound_followers WHERE followed_back = 1").fetchone()["c"]
    return {
        "total": total,
        "evaluated": evaluated,
        "followed": followed,
        "starred": starred,
        "inbound_followers": inbound,
        "inbound_followed_back": inbound_followed,
    }
