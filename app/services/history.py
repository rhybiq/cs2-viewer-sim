"""Local, append-only history of analyses (Layer 3 groundwork -- see the
project backlog: real before/after comparison and retention calibration
both need several past (fingerprint, real-outcome) pairs to exist before
they're buildable at all, so this is deliberately just the storage + save
action, not those consumer features. real_retention_json/real_outcome_note
exist now so attaching a real outcome later won't need a schema migration,
but nothing populates them yet.

Append-only, not upserted by clip: a future "pick which past analysis to
compare against" feature needs multiple distinct snapshots of the same clip
over time (e.g. re-edited versions) to diff against -- overwriting the
previous row on every re-analysis would destroy exactly the history that
feature needs.
"""

import json
import os
import sqlite3
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone

DB_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "CS2ViewerSim", "history.db"
)


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            video_path TEXT NOT NULL,
            video_filename TEXT NOT NULL,
            pass_type TEXT NOT NULL,
            overall_score REAL,
            duration_s REAL,
            is_vertical INTEGER,
            report_json TEXT NOT NULL,
            real_retention_json TEXT,
            real_outcome_note TEXT
        )
    """)
    return conn


def save(report, video_path, pass_type):
    """pass_type: "metrics" | "ai_viewer" (matches SaveControls' existing
    export suffix) -- recorded per row so it's visible which pass triggered
    a given snapshot, not used to partition data (report is always the full,
    progressively-merged Report; see main_window.py's _ensure_report()).
    """
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT INTO analyses (created_at, video_path, video_filename, pass_type, "
            "overall_score, duration_s, is_vertical, report_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                video_path,
                report.file,
                pass_type,
                report.overall_score,
                report.duration_s,
                int(report.is_vertical),
                json.dumps(asdict(report)),
            ),
        )
    conn.close()
