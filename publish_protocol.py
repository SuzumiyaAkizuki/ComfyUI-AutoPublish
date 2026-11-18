from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path

import folder_paths


class PublishConflict(ValueError):
    pass


def request_identity(payload: dict) -> tuple[str, str]:
    if "request_id" not in payload and "asset_hash" not in payload:
        return "", ""
    for name in ("request_id", "asset_hash"):
        if not isinstance(payload.get(name), str) or not re.fullmatch(r"[0-9a-f]{64}", payload[name]):
            raise ValueError(f"{name} 必须是 64 位小写 SHA-256，且两个字段必须同时提供")
    return payload["request_id"], payload["asset_hash"]


def stream_hash(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, asset_hash: str) -> None:
    with path.open("rb") as source:
        if stream_hash(source) != asset_hash:
            raise ValueError("图片 SHA-256 与 asset_hash 不一致，请重新选择原图")


@contextmanager
def verified_snapshot(path: Path, asset_hash: str):
    # Publish exactly the verified bytes even if the source changes during the job.
    with tempfile.TemporaryFile() as snapshot:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                snapshot.write(chunk)
        if digest.hexdigest() != asset_hash:
            raise ValueError("原图内容已改变，取消发布")
        snapshot.seek(0)
        yield snapshot


def content_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,16}", suffix) else ""


def trim_jobs(jobs: dict, limit: int) -> None:
    for job_id in list(jobs):
        if len(jobs) <= limit:
            break
        if jobs[job_id]["status"] in {"done", "failed"}:
            del jobs[job_id]


class PublishStore:
    """Durable request bindings; credentials never enter this database.

    One ComfyUI process owns the user directory. Interrupted jobs are retried
    only by an explicit publish request after restart, with their original key.
    """

    def __init__(self, path: Path):
        self.path = path
        self._initialized = False
        self._lock = threading.Lock()

    @contextmanager
    def _connection(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=30)) as connection:
                with connection:
                    connection.execute("""CREATE TABLE IF NOT EXISTS requests (
                        request_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
                        target TEXT NOT NULL, asset_hash TEXT NOT NULL,
                        job TEXT NOT NULL, updated_at REAL NOT NULL)""")
                    connection.execute("CREATE INDEX IF NOT EXISTS requests_recent ON requests(operation, updated_at DESC)")
                    if not self._initialized:
                        rows = connection.execute("SELECT request_id, job FROM requests")
                        for request_id, raw in rows:
                            job = json.loads(raw)
                            if job["status"] in {"waiting", "working"}:
                                job.update(status="failed", message="服务重启中断了任务，请核对目标后手动重试", updated_at=time.time())
                                connection.execute("UPDATE requests SET job=?, updated_at=? WHERE request_id=?",
                                                   (json.dumps(job, ensure_ascii=False), job["updated_at"], request_id))
                self._initialized = True
                yield connection

    def claim(self, operation: str, target: dict, job: dict) -> tuple[dict, bool]:
        target_json = json.dumps(target, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT operation, target, asset_hash, job FROM requests WHERE request_id=?",
                                     (job["request_id"],)).fetchone()
            if row:
                if row[:3] != (operation, target_json, job["asset_hash"]):
                    raise PublishConflict("request_id 已绑定到其他内容或发布目标")
                previous = json.loads(row[3])
                if previous["status"] != "failed":
                    return previous, False
                # Date expansion and extension belong to the first submission.
                job["object_key"] = previous.get("object_key", "")
                job["destination_name"] = previous.get("destination_name", "")
            connection.execute("INSERT OR REPLACE INTO requests VALUES (?, ?, ?, ?, ?, ?)",
                               (job["request_id"], operation, target_json, job["asset_hash"],
                                json.dumps(job, ensure_ascii=False), job["updated_at"]))
        return job, True

    def update(self, job: dict) -> None:
        with self._connection() as connection, connection:
            connection.execute("UPDATE requests SET job=?, updated_at=? WHERE request_id=?",
                               (json.dumps(job, ensure_ascii=False), job["updated_at"], job["request_id"]))

    def recent(self, operation: str, limit: int) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT job FROM requests WHERE operation=? ORDER BY updated_at DESC LIMIT ?",
                                      (operation, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]


_store: PublishStore | None = None
_store_lock = threading.Lock()


def publish_store() -> PublishStore:
    global _store
    with _store_lock:
        if _store is None:
            path = Path(folder_paths.get_system_user_directory("autopublish")) / "moss_publish.sqlite3"
            _store = PublishStore(path)
        return _store
