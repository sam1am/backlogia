# services/jobs.py
# Job management service for tracking background sync operations

import sqlite3
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from ..config import DATABASE_PATH


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    STORE_SYNC = "store_sync"
    IGDB_SYNC = "igdb_sync"
    METACRITIC_SYNC = "metacritic_sync"
    PROTONDB_SYNC = "protondb_sync"
    STEAM_SYNC = "steam_sync"


def ensure_jobs_table():
    """Create jobs table if it doesn't exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            progress INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            message TEXT,
            result TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def create_job(job_type: JobType, message: str = "") -> str:
    """Create a new job and return its ID."""
    ensure_jobs_table()

    job_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO jobs (id, type, status, message, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (job_id, job_type.value, JobStatus.PENDING.value, message,
          datetime.now().isoformat(), datetime.now().isoformat()))

    conn.commit()
    conn.close()

    return job_id


def update_job_progress(job_id: str, progress: int, total: int, message: str = ""):
    """Update job progress."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE jobs
        SET progress = ?, total = ?, message = ?, status = ?, updated_at = ?
        WHERE id = ?
    """, (progress, total, message, JobStatus.RUNNING.value,
          datetime.now().isoformat(), job_id))

    conn.commit()
    conn.close()


def complete_job(job_id: str, result: str, message: str = ""):
    """Mark job as completed."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE jobs
        SET status = ?, result = ?, message = ?, progress = total,
            updated_at = ?, completed_at = ?
        WHERE id = ?
    """, (JobStatus.COMPLETED.value, result, message,
          datetime.now().isoformat(), datetime.now().isoformat(), job_id))

    conn.commit()
    conn.close()


def fail_job(job_id: str, error: str):
    """Mark job as failed."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE jobs
        SET status = ?, error = ?, updated_at = ?, completed_at = ?
        WHERE id = ?
    """, (JobStatus.FAILED.value, error,
          datetime.now().isoformat(), datetime.now().isoformat(), job_id))

    conn.commit()
    conn.close()


def get_job(job_id: str) -> Optional[dict]:
    """Get job by ID."""
    ensure_jobs_table()

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def get_active_jobs() -> list:
    """Get all pending or running jobs."""
    ensure_jobs_table()

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM jobs
        WHERE status IN (?, ?)
        ORDER BY created_at DESC
    """, (JobStatus.PENDING.value, JobStatus.RUNNING.value))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_recent_jobs(limit: int = 10) -> list:
    """Get recent jobs including completed ones."""
    ensure_jobs_table()

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM jobs
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def cleanup_old_jobs(hours: int = 24):
    """Remove completed/failed jobs older than specified hours."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM jobs
        WHERE status IN (?, ?)
        AND completed_at < datetime('now', ?)
    """, (JobStatus.COMPLETED.value, JobStatus.FAILED.value, f'-{hours} hours'))

    conn.commit()
    conn.close()


def cleanup_orphaned_jobs():
    """Mark any running/pending jobs as failed (called on server startup)."""
    ensure_jobs_table()

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE jobs
        SET status = ?, error = ?, completed_at = ?
        WHERE status IN (?, ?)
    """, (
        JobStatus.FAILED.value,
        "Server restarted - job interrupted",
        datetime.now().isoformat(),
        JobStatus.PENDING.value,
        JobStatus.RUNNING.value
    ))

    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected > 0:
        print(f"Cleaned up {affected} orphaned job(s) from previous session")


# Thread-safe job runner
_job_threads: dict[str, threading.Thread] = {}


def run_job_async(job_id: str, job_func: Callable[[str], None]):
    """Run a job function in a background thread."""
    def wrapper():
        try:
            job_func(job_id)
        except Exception as e:
            fail_job(job_id, str(e))
        finally:
            # Cleanup thread reference
            if job_id in _job_threads:
                del _job_threads[job_id]

    thread = threading.Thread(target=wrapper, daemon=True)
    _job_threads[job_id] = thread
    thread.start()

    return job_id
