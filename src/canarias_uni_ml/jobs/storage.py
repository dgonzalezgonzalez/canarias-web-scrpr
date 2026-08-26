from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..io import ensure_parent, write_csv_rows
from .models import JobRecord
from .utils import clean_text

JOB_FIELDS = tuple(field.name for field in fields(JobRecord))
VOLATILE_HASH_FIELDS = {"scraped_at", "is_active"}


@dataclass(slots=True)
class UpsertStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass(slots=True)
class CompactionStats:
    before: int = 0
    after: int = 0
    removed: int = 0
    ambiguous_ties: int = 0


def canonical_job_key(record: JobRecord) -> str:
    source = clean_text(record.source) or "unknown"
    source_url = (clean_text(record.source_url) or "").lower()
    if source_url:
        return f"url::{source_url}"

    external_id = clean_text(record.external_id)
    if external_id:
        return f"id::{source.lower()}::{external_id}"

    title = clean_text(record.title)
    company = clean_text(record.company)
    publication_date = clean_text(record.publication_date)
    location = clean_text(record.raw_location or record.municipality or record.island or record.province)
    if not any((title, company, publication_date, location)):
        raise ValueError("Job record has no stable identity fields")
    return "row::{source}::{title}::{company}::{date}::{location}".format(
        source=source.lower(),
        title=title or "",
        company=company or "",
        date=publication_date or "",
        location=location or "",
    )


def canonical_secondary_merge_key(record: JobRecord) -> str | None:
    source = (clean_text(record.source) or "").lower()
    title = (clean_text(record.title) or "").lower()
    company = (clean_text(record.company) or "").lower()
    publication_date = (clean_text(record.publication_date) or "").lower()
    location = (
        clean_text(record.raw_location or record.municipality or record.island or record.province) or ""
    ).lower()
    if not (source and title and company and publication_date):
        return None
    return f"sec::{source}::{title}::{company}::{publication_date}::{location}"


def payload_hash(record: JobRecord) -> str:
    payload = {
        key: value
        for key, value in record.to_row().items()
        if key not in VOLATILE_HASH_FIELDS
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class JobsRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        ensure_parent(self.db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        column_defs = ", ".join(f'"{name}" TEXT' for name in JOB_FIELDS)
        with self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_key TEXT PRIMARY KEY,
                    {column_defs},
                    secondary_key TEXT,
                    payload_hash TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cols = [row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
            if "secondary_key" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN secondary_key TEXT")
            if "closing_date" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN closing_date TEXT")
            if "is_active" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN is_active TEXT NOT NULL DEFAULT '1'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_secondary_key ON jobs(secondary_key)")
            conn.commit()

    def upsert_records(self, records: Iterable[JobRecord]) -> UpsertStats:
        stats = UpsertStats()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for record in records:
                key = canonical_job_key(record)
                secondary_key = canonical_secondary_merge_key(record)
                record_hash = payload_hash(record)
                existing = conn.execute(
                    """
                    SELECT job_key, payload_hash
                    FROM jobs
                    WHERE job_key = ?
                       OR (? IS NOT NULL AND secondary_key = ?)
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (key, secondary_key, secondary_key),
                ).fetchone()
                row = record.to_row()
                if existing is None:
                    self._insert(
                        conn=conn,
                        job_key=key,
                        secondary_key=secondary_key,
                        row=row,
                        row_hash=record_hash,
                        now=now,
                    )
                    stats.inserted += 1
                    continue

                if existing["payload_hash"] == record_hash:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET last_seen_at = ?,
                            secondary_key = ?,
                            is_active = '1'
                        WHERE job_key = ?
                        """,
                        (now, secondary_key, existing["job_key"]),
                    )
                    stats.unchanged += 1
                    continue

                self._update(
                    conn=conn,
                    old_job_key=existing["job_key"],
                    new_job_key=key,
                    secondary_key=secondary_key,
                    row=row,
                    row_hash=record_hash,
                    now=now,
                )
                stats.updated += 1
            conn.commit()
        return stats

    def deactivate_missing_source(self, source: str, records: Iterable[JobRecord]) -> int:
        """Deactivate rows absent from a complete source snapshot.

        Callers must only invoke this after a source has proved its crawl was
        complete. Capped, blocked, and partial sources intentionally leave
        historical rows active so a transient outage cannot erase the snapshot.
        """
        source_clean = clean_text(source)
        if not source_clean:
            return 0
        active_keys = {canonical_job_key(record) for record in records}
        with self._connect() as conn:
            if active_keys:
                placeholders = ", ".join("?" for _ in active_keys)
                cursor = conn.execute(
                    f"UPDATE jobs SET is_active = '0' WHERE source = ? AND job_key NOT IN ({placeholders})",
                    (source_clean, *sorted(active_keys)),
                )
            else:
                cursor = conn.execute(
                    "UPDATE jobs SET is_active = '0' WHERE source = ?",
                    (source_clean,),
                )
            conn.commit()
            return int(cursor.rowcount)

    def compact_latest_records(self) -> CompactionStats:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT job_key, {", ".join(f'"{name}"' for name in JOB_FIELDS)}, payload_hash, first_seen_at, last_seen_at, updated_at
                FROM jobs
                """
            ).fetchall()
            before = len(rows)
            if before == 0:
                return CompactionStats(before=0, after=0, removed=0, ambiguous_ties=0)

            winners_primary: dict[str, sqlite3.Row] = {}
            ties = 0
            for row in rows:
                record = self._record_from_row(row)
                logical_key = canonical_job_key(record)
                current = winners_primary.get(logical_key)
                if current is None:
                    winners_primary[logical_key] = row
                    continue
                if self._row_sort_key(row) > self._row_sort_key(current):
                    winners_primary[logical_key] = row
                elif self._row_sort_key(row) == self._row_sort_key(current):
                    ties += 1

            winners: dict[str, sqlite3.Row] = {}
            for row in winners_primary.values():
                record = self._record_from_row(row)
                logical_key = canonical_secondary_merge_key(record) or canonical_job_key(record)
                current = winners.get(logical_key)
                if current is None:
                    winners[logical_key] = row
                    continue
                if self._row_sort_key(row) > self._row_sort_key(current):
                    winners[logical_key] = row
                elif self._row_sort_key(row) == self._row_sort_key(current):
                    ties += 1

            conn.execute("DELETE FROM jobs")
            for winner in winners.values():
                self._insert_row(conn=conn, row=winner)
            conn.commit()

        after = len(winners)
        return CompactionStats(before=before, after=after, removed=before - after, ambiguous_ties=ties)

    def export_csv(self, output_path: str | Path, *, active_only: bool = True) -> int:
        query = f"""
            SELECT {", ".join(f'"{name}"' for name in JOB_FIELDS)}
            FROM jobs
            {"WHERE is_active <> '0'" if active_only else ""}
            ORDER BY COALESCE(publication_date, '') DESC, source ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        records = [self._record_from_row(row) for row in rows]
        return write_csv_rows(records, output_path)

    def read_all(self, *, active_only: bool = False) -> list[JobRecord]:
        query = f"""
            SELECT {", ".join(f'"{name}"' for name in JOB_FIELDS)}
            FROM jobs
            {"WHERE is_active <> '0'" if active_only else ""}
            ORDER BY source ASC, title ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._record_from_row(row) for row in rows]

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> JobRecord:
        values = {name: row[name] for name in JOB_FIELDS}
        active = values.get("is_active")
        if isinstance(active, str):
            values["is_active"] = active.strip().casefold() not in {"", "0", "false", "no", "off"}
        else:
            values["is_active"] = bool(active) if active is not None else True
        return JobRecord(**values)

    def _insert(
        self,
        *,
        conn: sqlite3.Connection,
        job_key: str,
        secondary_key: str | None,
        row: dict[str, str | None],
        row_hash: str,
        now: str,
    ) -> None:
        columns = (
            "job_key",
            *JOB_FIELDS,
            "secondary_key",
            "payload_hash",
            "first_seen_at",
            "last_seen_at",
            "updated_at",
        )
        placeholders = ", ".join("?" for _ in columns)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        conn.execute(
            f"INSERT INTO jobs ({quoted_columns}) VALUES ({placeholders})",
            (job_key, *[row.get(name) for name in JOB_FIELDS], secondary_key, row_hash, now, now, now),
        )

    def _insert_row(self, *, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        secondary_key = row["secondary_key"] if "secondary_key" in row.keys() else None
        columns = (
            "job_key",
            *JOB_FIELDS,
            "secondary_key",
            "payload_hash",
            "first_seen_at",
            "last_seen_at",
            "updated_at",
        )
        placeholders = ", ".join("?" for _ in columns)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        conn.execute(
            f"INSERT INTO jobs ({quoted_columns}) VALUES ({placeholders})",
            tuple(
                secondary_key if column == "secondary_key" else row[column]
                for column in columns
            ),
        )

    def _update(
        self,
        *,
        conn: sqlite3.Connection,
        old_job_key: str,
        new_job_key: str,
        secondary_key: str | None,
        row: dict[str, str | None],
        row_hash: str,
        now: str,
    ) -> None:
        assignments = ", ".join(f'"{name}" = ?' for name in JOB_FIELDS)
        conn.execute(
            f"""
            UPDATE jobs
            SET job_key = ?,
                {assignments},
                secondary_key = ?,
                payload_hash = ?,
                last_seen_at = ?,
                updated_at = ?
            WHERE job_key = ?
            """,
            (new_job_key, *[row.get(name) for name in JOB_FIELDS], secondary_key, row_hash, now, now, old_job_key),
        )

    def _row_sort_key(self, row: sqlite3.Row) -> tuple[str, str, str, str]:
        update_date = _normalize_date(row["update_date"])
        publication_date = _normalize_date(row["publication_date"])
        updated_at = _normalize_date(row["updated_at"])
        # Deterministic final tie-breaker to keep compaction stable.
        payload_hash = row["payload_hash"] or ""
        return (update_date, publication_date, updated_at, payload_hash)


def _normalize_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value
