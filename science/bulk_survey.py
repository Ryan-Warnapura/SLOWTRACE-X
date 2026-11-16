"""Persistent image queue, attempt ledger and quality-masked sky-area union."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid

from .archive import now
from .survey import canonical

SCHEMA_VERSION = 1
GOAL = 500_000
NSIDE = 1024
CELL_AREA = 4 * math.pi * (180 / math.pi) ** 2 / (12 * NSIDE ** 2)
BLOCK_BITS = 256
ATTEMPT_LIMIT = 3
LEASE_SECONDS = 1200
SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    url TEXT PRIMARY KEY, id TEXT NOT NULL, detector INTEGER NOT NULL,
    rank INTEGER NOT NULL, size INTEGER, etag TEXT, discovered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS inventory_id ON inventory(id, rank);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, url TEXT NOT NULL REFERENCES inventory(url), detector INTEGER NOT NULL,
    rank INTEGER NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'queued', tries INTEGER NOT NULL DEFAULT 0,
    eligible REAL NOT NULL DEFAULT 0, lease_until REAL, active_attempt INTEGER,
    first_success INTEGER, last_success INTEGER
);
CREATE INDEX IF NOT EXISTS jobs_claim_ready ON jobs(priority DESC, tries DESC) WHERE state='queued';
CREATE INDEX IF NOT EXISTS jobs_leases ON jobs(state, lease_until);
CREATE INDEX IF NOT EXISTS jobs_processed ON jobs(first_success) WHERE first_success IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_updated ON jobs(last_success) WHERE last_success IS NOT NULL;
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
    wall_seconds REAL, workers INTEGER NOT NULL, budget INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS image_attempts (
    seq INTEGER PRIMARY KEY, batch TEXT NOT NULL REFERENCES batches(id),
    id TEXT NOT NULL REFERENCES jobs(id), url TEXT NOT NULL REFERENCES inventory(url),
    number INTEGER NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running', reason TEXT, result TEXT, elapsed REAL
);
CREATE INDEX IF NOT EXISTS attempts_batch ON image_attempts(batch, status);
CREATE INDEX IF NOT EXISTS attempts_image ON image_attempts(id,seq);
CREATE TABLE IF NOT EXISTS image_completions (
    seq INTEGER PRIMARY KEY, attempt INTEGER NOT NULL UNIQUE REFERENCES image_attempts(seq)
);
CREATE TABLE IF NOT EXISTS catalog_scopes (
    prefix TEXT PRIMARY KEY, kind TEXT NOT NULL, position INTEGER NOT NULL,
    cursor TEXT, pages INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS catalog_events (
    seq INTEGER PRIMARY KEY, prefix TEXT NOT NULL, at TEXT NOT NULL,
    cursor TEXT, listed INTEGER, done INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS coverage_blocks (
    block INTEGER PRIMARY KEY, bits BLOB NOT NULL, occupied INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS survey_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def message(error):
    return f"{type(error).__name__}: {str(error).splitlines()[0][:320]}" if str(error) else type(error).__name__


def atomic_write(destination, write):
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as temp:
        stage = Path(temp.name)
    try:
        write(stage)
        # Windows readers can hold the published path open briefly.
        for attempt in range(6):
            try:
                stage.replace(path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * 2 ** attempt)
    finally:
        stage.unlink(missing_ok=True)


class BulkSurvey:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=40, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO survey_settings VALUES('version', ?)", (str(SCHEMA_VERSION),))
        if int(self.setting("version")) != SCHEMA_VERSION:
            self.close()
            raise ValueError("The survey database uses a different schema version.")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self, write=True):
        self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def setting(self, name):
        row = self.db.execute("SELECT value FROM survey_settings WHERE key=?", (name,)).fetchone()
        return row["value"] if row else None

    def save_setting(self, name, value):
        self.db.execute("INSERT INTO survey_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (name, str(value)))

    def _inventory(self, products, priority=0):
        stamp = now()
        for item in products:
            self.db.execute("INSERT OR IGNORE INTO inventory VALUES(?,?,?,?,?,?,?)",
                            (item.url, item.id, item.detector, item.rank, item.size, item.etag, stamp))
            self.db.execute("""INSERT INTO jobs (id,url,detector,rank,priority) VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET url=excluded.url,rank=excluded.rank,priority=max(priority,excluded.priority)
                WHERE jobs.state='queued' AND jobs.first_success IS NULL AND excluded.rank>=jobs.rank""",
                            (item.id, item.url, item.detector, item.rank, priority))

    def seed(self, products):
        with self.transaction():
            self._inventory(products, priority=1)

    def add_scopes(self, prefixes):
        self.db.executemany("""INSERT OR IGNORE INTO catalog_scopes (prefix,kind,position)
                            VALUES (?,'period',?)""", ((prefix, index) for index, prefix in enumerate(prefixes)))

    def reset_scopes(self):
        self.db.execute("UPDATE catalog_scopes SET cursor=NULL,done=0,pages=0,error=NULL")

    def next_scope(self, exclude, releases, periods):
        where = "done=0 AND (" + " OR ".join("prefix LIKE ?" for _ in releases) + ")"
        args = [release + "/%" for release in releases]
        if periods:
            where += " AND (" + " OR ".join("prefix LIKE ?" for _ in periods) + ")"
            args.extend("%/level2/" + period + "/%" for period in periods)
        rows = self.db.execute(f"SELECT * FROM catalog_scopes WHERE {where} ORDER BY pages,position,rowid", args)
        return next((row for row in rows if row["prefix"] not in exclude), None)

    def record_page(self, scope, cursor, done, *, children=(), products=()):
        with self.transaction():
            # Competing inventory writers may have fetched the same page. Only one advances it.
            updated = self.db.execute("""UPDATE catalog_scopes SET cursor=?,done=?,pages=pages+1,error=NULL
                WHERE prefix=? AND pages=? AND cursor IS ? AND done=0""",
                                      (cursor, done, scope["prefix"], scope["pages"], scope["cursor"]))
            if not updated.rowcount:
                return False
            self.db.executemany("""INSERT OR IGNORE INTO catalog_scopes (prefix,kind,position)
                VALUES (?,'images',?)""", ((child, scope["position"]) for child in children))
            self._inventory(products)
            self.db.execute("INSERT INTO catalog_events (prefix,at,cursor,listed,done) VALUES (?,?,?,?,?)",
                            (scope["prefix"], now(), cursor, len(products), done))
        return True

    def catalog_failure(self, scope, error):
        with self.transaction():
            detail = message(error)
            self.db.execute("UPDATE catalog_scopes SET error=? WHERE prefix=?", (detail, scope["prefix"]))
            self.db.execute("INSERT INTO catalog_events (prefix,at,cursor,error) VALUES (?,?,?,?)",
                            (scope["prefix"], now(), scope["cursor"], detail))

    def begin_batch(self, workers, budget):
        batch = "bulk-" + uuid.uuid4().hex[:16]
        self.db.execute("INSERT INTO batches (id,started_at,workers,budget) VALUES(?,?,?,?)",
                        (batch, now(), workers, budget))
        return batch

    def close_batch(self, batch, seconds):
        self.db.execute("UPDATE batches SET finished_at=?,wall_seconds=? WHERE id=?",
                        (now(), seconds, batch))

    def _recover(self, clock, stamp):
        expired = list(self.db.execute("""SELECT id,active_attempt,tries FROM jobs
            WHERE state='running' AND lease_until<=?""", (clock,)))
        for row in expired:
            self.db.execute("""UPDATE image_attempts SET status='interrupted',finished_at=?,
                reason='Lease expired before processing completed' WHERE seq=? AND status='running'""",
                            (stamp, row["active_attempt"]))
            self.db.execute("""UPDATE jobs SET state=?,lease_until=NULL,active_attempt=NULL,eligible=0 WHERE id=?""",
                            ("failed" if row["tries"] >= ATTEMPT_LIMIT else "queued", row["id"]))

    def claim(self, batch, *, clock=None, lease_seconds=LEASE_SECONDS):
        clock = time.time() if clock is None else clock
        with self.transaction():
            stamp = now()
            self._recover(clock, stamp)
            row = self.db.execute("""SELECT * FROM jobs INDEXED BY jobs_claim_ready WHERE state='queued' AND eligible<=?
                ORDER BY priority DESC, tries DESC, rowid LIMIT 1""", (clock,)).fetchone()
            if row is None:
                return None
            attempt = self.db.execute("""INSERT INTO image_attempts (batch,id,url,number,started_at)
                VALUES (?,?,?,?,?)""", (batch, row["id"], row["url"], row["tries"] + 1, stamp)).lastrowid
            self.db.execute("""UPDATE jobs SET state='running',tries=tries+1,lease_until=?,active_attempt=?
                WHERE id=?""", (clock + lease_seconds, attempt, row["id"]))
            return {**dict(row), "attempt": attempt, "tries": row["tries"] + 1}

    def requeue(self, *, failed=False, image_ids=()):
        with self.transaction():
            retry_count = 0
            if failed:
                cursor = self.db.execute("""UPDATE jobs SET state='queued',tries=0,eligible=0
                    WHERE state='failed' OR (state='queued' AND tries>0 AND eligible>0)""")
                retry_count += cursor.rowcount
            for image_id in image_ids:
                latest = self.db.execute("SELECT * FROM inventory WHERE id=? ORDER BY rank DESC,url LIMIT 1",
                                         (image_id,)).fetchone()
                if not latest:
                    raise ValueError(f"Unknown observation identity: {image_id}")
                cursor = self.db.execute("""UPDATE jobs SET state='queued',tries=0,eligible=0,url=?,rank=?
                    WHERE id=? AND state!='running'""", (latest["url"], latest["rank"], image_id))
                retry_count += cursor.rowcount
        return retry_count

    def _add_coverage(self, ranges):
        bits_by_block = {}
        previous = 0
        for start, end in ranges:
            if not (isinstance(start, int) and isinstance(end, int)
                    and previous <= start < end <= 12 * NSIDE * NSIDE):
                raise ValueError("Invalid NESTED HEALPix cell ranges.")
            previous = end
            while start < end:
                block, offset = divmod(start, BLOCK_BITS)
                count = min(BLOCK_BITS - offset, end - start)
                bits_by_block[block] = bits_by_block.get(block, 0) | (((1 << count) - 1) << offset)
                start += count
        for block, bits in bits_by_block.items():
            old = self.db.execute("SELECT bits FROM coverage_blocks WHERE block=?", (block,)).fetchone()
            union = bits | (int.from_bytes(old["bits"], "little") if old else 0)
            self.db.execute("""INSERT INTO coverage_blocks VALUES(?,?,?) ON CONFLICT(block) DO UPDATE
                SET bits=excluded.bits,occupied=excluded.occupied""",
                            (block, union.to_bytes(BLOCK_BITS // 8, "little"), union.bit_count()))

    def finish(self, claim, status, elapsed, *, result=None, reason=None):
        if status == "success":
            if (result is None or result["id"] != claim["id"] or result["detector"] != claim["detector"]
                    or result["cloudUrl"] != claim["url"] or not 0 < result["validPixels"] <= result["totalPixels"]
                    or not re.fullmatch(r"[a-f0-9]{64}", result["sha256"]) or result["downloadedBytes"] <= 0
                    or result["coverageNside"] != NSIDE):
                raise ValueError("The result does not substantiate successful full-image processing.")
        elif status not in {"error", "skipped", "interrupted"}:
            raise ValueError("Unknown image result status.")
        with self.transaction():
            current = self.db.execute("SELECT active_attempt FROM jobs WHERE id=?", (claim["id"],)).fetchone()
            if current["active_attempt"] != claim["attempt"]:
                return False
            if status == "success":
                self._add_coverage(result["coverageRanges"])
                self.db.execute("""UPDATE jobs SET state='complete',first_success=coalesce(first_success,?),
                    last_success=?,active_attempt=NULL,lease_until=NULL WHERE id=?""",
                                (claim["attempt"], claim["attempt"], claim["id"]))
                self.db.execute("INSERT INTO image_completions (attempt) VALUES (?)", (claim["attempt"],))
            else:
                retry = status != "skipped" and claim["tries"] < ATTEMPT_LIMIT
                state = "queued" if retry else ("skipped" if status == "skipped" else "failed")
                eligible = time.time() + 15 * 2 ** (claim["tries"] - 1) if retry else 0
                self.db.execute("""UPDATE jobs SET state=?,eligible=?,active_attempt=NULL,lease_until=NULL
                    WHERE id=?""", (state, eligible, claim["id"]))
            self.db.execute("""UPDATE image_attempts SET status=?,finished_at=?,reason=?,result=?,elapsed=?
                WHERE seq=?""", (status, now(), reason, canonical(result) if result is not None else None,
                                 elapsed, claim["attempt"]))
        return True

    def completed_since(self, checkpoint):
        """Append successes in commit order, including jobs finishing out of order."""
        # rowid of the queue claim is not a completion cursor. A slow earlier claim can finish later.
        after = int(checkpoint or 0)
        rows = self.db.execute("""SELECT c.seq,a.result FROM image_completions c
            JOIN image_attempts a ON a.seq=c.attempt WHERE c.seq>? ORDER BY c.seq""", (after,))
        for row in rows:
            yield row["seq"], json.loads(row["result"])

    def write_ledger(self, output):
        def write(path):
            with self.transaction(write=False), gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as out:
                out.write(canonical({"schema": SCHEMA_VERSION, "goal": GOAL, "coverageNside": NSIDE,
                                     "generatedAt": now(), "kind": "full-frame-image-attempt-ledger"}) + "\n")
                for row in self.db.execute("""SELECT a.*, CASE WHEN j.first_success=a.seq THEN 1 ELSE 0 END AS first_success
                    FROM image_attempts a JOIN jobs j ON j.id=a.id ORDER BY a.seq"""):
                    event = dict(row)
                    if event["result"]:
                        event["result"] = json.loads(event["result"])
                    out.write(canonical(event) + "\n")
        atomic_write(output, write)

    def snapshot(self, motion=None, *, footprint_limit=160, ledger_url=None):
        motion = motion or {}
        with self.transaction(write=False):
            states = dict(self.db.execute("SELECT state,count(*) FROM jobs GROUP BY state").fetchall())
            counts = dict(self.db.execute("SELECT status,count(*) FROM image_attempts GROUP BY status").fetchall())
            unique = self.db.execute("SELECT count(*) FROM jobs WHERE first_success IS NOT NULL").fetchone()[0]
            retries = self.db.execute("SELECT count(*) FROM image_attempts WHERE number>1").fetchone()[0]
            cells = self.db.execute("SELECT coalesce(sum(occupied),0) FROM coverage_blocks").fetchone()[0]
            motion_summary = motion.get("summary", {})
            summary = dict(discovered=sum(states.values()), uniqueProcessed=unique,
                           successfulOperations=counts.get("success", 0), pending=states.get("queued", 0),
                           running=states.get("running", 0), failed=states.get("failed", 0),
                           skipped=states.get("skipped", 0), retries=retries,
                           errorAttempts=counts.get("error", 0), interrupted=counts.get("interrupted", 0),
                           regionsAnalyzed=motion_summary.get("skyRegionsAnalyzed", motion_summary.get("fieldsAnalyzed", 0)),
                           fieldsPending=motion_summary.get("queued", 0) + motion_summary.get("running", 0),
                           fieldsFailed=motion_summary.get("errors", 0),
                           fieldsIncomplete=motion_summary.get("incomplete", 0),
                           fieldsEmpty=motion_summary.get("zeroPeakFields", 0),
                           fieldsUnsearched=motion_summary.get("unsearched", 0),
                           fieldsWaitingEpochs=motion_summary.get("waitingEpochs", 0),
                           motionInputs=motion_summary.get("exposuresAnalyzed"),
                           candidates=motion_summary.get("candidates", 0), investigated=motion_summary.get("investigated", 0),
                           catalogAttempts=motion_summary.get("catalogAttempts", 0),
                           catalogCompleted=motion_summary.get("catalogCompleted", 0),
                           knownMatches=motion_summary.get("knownMatches", 0), unresolved=motion_summary.get("unresolved", 0))
            fields = []
            for row in self.db.execute("""SELECT a.result FROM jobs j JOIN image_attempts a ON j.last_success=a.seq
                ORDER BY j.last_success DESC LIMIT ?""", (footprint_limit,)):
                image = json.loads(row["result"])
                if image.get("boundary"):
                    fields.append(dict(id=image["id"], **image["center"], boundary=image["boundary"]))
            batches = []
            for row in self.db.execute("""SELECT b.*, count(a.seq) AS attempts,
                sum(a.status='success') AS successful,sum(a.status='error') AS failed,
                sum(a.status='skipped') AS skipped,sum(a.status='interrupted') AS interrupted,
                sum(j.first_success=a.seq) AS first_success,
                sum(a.number>1) AS retries
                FROM batches b LEFT JOIN image_attempts a ON a.batch=b.id LEFT JOIN jobs j ON j.id=a.id
                WHERE b.id IN (SELECT id FROM batches ORDER BY started_at DESC LIMIT 180)
                GROUP BY b.id ORDER BY b.started_at DESC LIMIT 180"""):
                if row["attempts"]:
                    batches.append(dict(id=row["id"], startedAt=row["started_at"], finishedAt=row["finished_at"],
                                        wallSeconds=row["wall_seconds"], workers=row["workers"],
                                        successful=row["successful"] or 0, uniqueProcessed=row["first_success"] or 0,
                                        failed=row["failed"] or 0, skipped=row["skipped"] or 0,
                                        interrupted=row["interrupted"] or 0, retries=row["retries"] or 0))
            completed_scopes, total_scopes = self.db.execute(
                "SELECT coalesce(sum(done),0),count(*) FROM catalog_scopes").fetchone()
            inventory_errors = self.db.execute("SELECT count(*) FROM catalog_events WHERE error IS NOT NULL").fetchone()[0]
        limitations = [
            "A unique image is a SPHEREx observation ID and detector with completed measurements from a full native Level 2 image.",
            "Image area is the union of quality-valid sampled sky cells. A cell counts when its center falls on an accepted native pixel. Boundaries and gaps below the grid scale are approximate.",
            "Full-frame image measurements and automatic multi-epoch DeepTrace fields are reported independently. Candidate trial positions are not independent centroids.",
            "Catalog checks can be incomplete. Unresolved includes retained trial peaks that still require additional evidence.",
            "Motion sensitivity varies with wavelength, epoch spacing and velocity. The published injection experiment does not establish sensitivity across this survey.",
        ]
        if motion:
            limitations.extend(item for item in motion.get("limitations", []) if item not in limitations)
        coverage = dict(areaSquareDegrees=round(cells * CELL_AREA, 8), cells=cells, cellAreaSquareDegrees=CELL_AREA,
                        nside=NSIDE, footprintsTruncated=unique > len(fields),
                        method="Union of NESTED HEALPix cell centers accepted by the native image WCS and quality mask.")
        if "coverageSquareDegrees" in motion_summary:
            coverage["motionAreaSquareDegrees"] = motion_summary["coverageSquareDegrees"]
            coverage["motionNside"] = motion_summary["coverageNside"]
        return dict(schema=SCHEMA_VERSION, generatedAt=now(), goal=GOAL, summary=summary, coverage=coverage,
                    inventory=dict(listedScopes=total_scopes, completedScopes=completed_scopes, errors=inventory_errors),
                    batches=batches[::-1], footprints=fields, limitations=limitations, ledgerUrl=ledger_url)
