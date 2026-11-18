from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import oss2
from aiohttp import web


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAYLOAD = object()
folders = ModuleType("folder_paths")
server = ModuleType("server")
server.PromptServer = SimpleNamespace(instance=SimpleNamespace(routes=web.RouteTableDef()))
spec = importlib.util.spec_from_file_location("autopublish_test", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
oss = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = oss
with patch.dict(sys.modules, {"folder_paths": folders, "server": server}):
    spec.loader.exec_module(oss)
    local = sys.modules[f"{spec.name}.local_service"]
    protocol = sys.modules[f"{spec.name}.publish_protocol"]


class Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def body(response):
    return json.loads(response.text)


class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.puts = 0
        self.versioning = None
        self.lock = threading.Lock()
        self.race_content = None

    def get_object(self, key):
        with self.lock:
            if key not in self.objects:
                raise oss2.exceptions.NoSuchKey(404, {}, "", {"Code": "NoSuchKey"})
            return io.BytesIO(self.objects[key])

    def get_bucket_versioning(self):
        return SimpleNamespace(status=self.versioning)

    def put_object(self, key, stream, headers):
        assert headers["x-oss-forbid-overwrite"] == "true"
        content = stream.read()
        with self.lock:
            if self.race_content is not None:
                self.objects[key] = self.race_content
            if key in self.objects:
                raise oss2.exceptions.ServerError(409, {}, "", {"Code": "FileAlreadyExists"})
            self.objects[key] = content
            self.puts += 1
        return SimpleNamespace(status=200)


class PublishTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="autopublish-test-")
        self.root = Path(self.temporary.name)
        self.source_dir = self.root / "output"
        self.source_dir.mkdir()
        self.destination = self.root / "selected"
        self.destination.mkdir()
        folders.get_directory_by_type = lambda kind: str(self.source_dir)
        folders.get_system_user_directory = lambda name: str(self.root / "config")
        self.content = b"test-image-bytes"
        self.source = self.source_dir / "image_00001_.png"
        self.source.write_bytes(self.content)
        self.asset_hash = hashlib.sha256(self.content).hexdigest()
        self.image = {"filename": self.source.name, "subfolder": "", "type": "output"}
        self.config = {
            "endpoint": "https://oss.example.test", "bucket": "test", "prefix": "images/%Y/%m/%d",
            "access_key_id": "fake-id", "access_key_secret": "fake-secret", "public_base_url": "https://img.example.test",
        }
        self.local_config = {"output_directory": str(self.destination)}
        self.bucket = FakeBucket()
        self.tasks = []
        self.real_create_task = asyncio.create_task

        def track_task(coro, **kwargs):
            task = self.real_create_task(coro, **kwargs)
            self.tasks.append(task)
            return task

        self.patches = [
            patch.object(oss, "_load_config", return_value=self.config),
            patch.object(local, "_load_config", return_value=self.local_config),
            patch.object(oss.oss2, "Bucket", return_value=self.bucket),
            patch.object(asyncio, "create_task", side_effect=track_task),
        ]
        for item in self.patches:
            item.start()
        oss._jobs.clear()
        local._jobs.clear()
        protocol._store = None

    async def asyncTearDown(self):
        await self.finish()
        for item in reversed(self.patches):
            item.stop()
        protocol._store = None
        self.temporary.cleanup()

    async def finish(self):
        if self.tasks:
            tasks, self.tasks = self.tasks, []
            await asyncio.gather(*tasks)

    def payload(self, request_id="a" * 64, **changes):
        payload = {"image": dict(self.image), "request_id": request_id, "asset_hash": self.asset_hash}
        payload.update(changes)
        return payload

    async def submit(self, target="local", payload=DEFAULT_PAYLOAD):
        handler = local.create_local_publish_job if target == "local" else oss.create_oss_publish_job
        return await handler(Request(self.payload() if payload is DEFAULT_PAYLOAD else payload))

    async def test_capability_configs_hide_secret_and_keep_blank_secret(self):
        for handler in (oss.get_oss_config, local.get_local_config):
            config = body(await handler(None))["config"]
            self.assertEqual(config["moss_publish_version"], 1)
            self.assertIs(config["configured"], True)
            self.assertNotIn("access_key_secret", config)
        normalized = oss._normalize_config({**self.config, "access_key_secret": ""}, self.config)
        self.assertEqual(normalized["access_key_secret"], "fake-secret")

    async def test_invalid_identity_hash_and_path_rejected(self):
        malformed = [[], None, self.payload(request_id="A" * 64), self.payload(asset_hash=""),
                     self.payload(asset_hash="b" * 64), self.payload(image={**self.image, "subfolder": ".."}),
                     self.payload(image={**self.image, "filename": "../image.png"}),
                     self.payload(image={**self.image, "type": "invalid"})]
        partial = self.payload()
        del partial["asset_hash"]
        malformed.append(partial)
        partial = self.payload()
        del partial["request_id"]
        malformed.append(partial)
        for target in ("local", "oss"):
            for payload in malformed:
                with self.subTest(target=target, payload=payload):
                    self.assertEqual((await self.submit(target, payload)).status, 400)
        self.assertEqual(self.tasks, [])

    async def test_local_concurrent_requests_create_one_task_and_file(self):
        responses = await asyncio.gather(*(self.submit() for _ in range(50)))
        self.assertTrue(all(response.status == 202 for response in responses))
        self.assertEqual(len({body(response)["job"]["id"] for response in responses}), 1)
        self.assertEqual(len(self.tasks), 1)
        await self.finish()
        job = body(await local.list_local_publish_jobs(None))["jobs"][0]
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["asset_hash"], self.asset_hash)
        self.assertEqual(job["request_id"], "a" * 64)
        self.assertEqual(Path(job["result_path"]).read_bytes(), self.content)
        self.assertEqual(Path(job["result_path"]).name, f"MOSS_{self.asset_hash}.png")
        self.assertEqual(self.source.read_bytes(), self.content)
        self.assertEqual(len(list(self.destination.iterdir())), 1)

    async def test_success_survives_restart_and_memory_eviction(self):
        first = body(await self.submit())["job"]
        await self.finish()
        local._jobs.clear()
        protocol._store = None
        second = body(await self.submit())["job"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "done")
        self.assertEqual(self.tasks, [])
        restored = body(await local.list_local_publish_jobs(None))["jobs"]
        self.assertEqual(restored[0]["id"], first["id"])
        database = self.root / "config" / "moss_publish.sqlite3"
        self.assertNotIn(b"fake-secret", database.read_bytes())

    async def test_request_cannot_change_content_target_or_operation(self):
        await self.submit()
        await self.finish()
        self.local_config["output_directory"] = str(self.root / "other-selected")
        self.assertEqual((await self.submit()).status, 409)
        self.local_config["output_directory"] = str(self.destination)
        self.source.write_bytes(b"other content")
        different = hashlib.sha256(b"other content").hexdigest()
        self.assertEqual((await self.submit(payload=self.payload(asset_hash=different))).status, 409)
        self.source.write_bytes(self.content)
        self.assertEqual((await self.submit("oss")).status, 409)

    async def test_local_existing_equal_content_reused_with_new_request(self):
        await self.submit()
        await self.finish()
        await self.submit(payload=self.payload(request_id="b" * 64))
        await self.finish()
        self.assertEqual(len(list(self.destination.iterdir())), 1)
        self.assertTrue(all(job["status"] == "done" for job in local._jobs.values()))

    async def test_local_conflicting_file_never_overwritten_and_retry_allowed(self):
        destination = self.destination / f"MOSS_{self.asset_hash}.png"
        destination.write_bytes(b"conflict")
        first = body(await self.submit())["job"]
        await self.finish()
        self.assertEqual(local._jobs[first["id"]]["status"], "failed")
        self.assertEqual(destination.read_bytes(), b"conflict")
        second = body(await self.submit())["job"]
        self.assertNotEqual(first["id"], second["id"])
        await self.finish()
        self.assertEqual(destination.read_bytes(), b"conflict")
        self.assertEqual(len(list(self.destination.iterdir())), 1)

    async def test_local_race_checks_existing_hash_and_cleans_stage(self):
        destination = self.destination / f"MOSS_{self.asset_hash}.png"
        real_link = local.os.link

        def racing_link(source, target):
            destination.write_bytes(b"racing content")
            return real_link(source, target)

        with patch.object(local.os, "link", side_effect=racing_link):
            await self.submit()
            await self.finish()
        self.assertEqual(next(iter(local._jobs.values()))["status"], "failed")
        self.assertEqual(destination.read_bytes(), b"racing content")
        self.assertEqual(len(list(self.destination.iterdir())), 1)

    async def test_source_change_after_submission_cancels_copy(self):
        # Block working-state persistence until the source is replaced.
        release = asyncio.Event()
        original = local._update_job

        async def blocked(*args, **kwargs):
            await release.wait()
            return await original(*args, **kwargs)

        with patch.object(local, "_update_job", side_effect=blocked):
            await self.submit()
            self.source.write_bytes(b"changed")
            release.set()
            await self.finish()
        self.assertEqual(next(iter(local._jobs.values()))["status"], "failed")
        self.assertEqual(list(self.destination.iterdir()), [])

    async def test_local_legacy_naming_and_copy_behavior_preserved(self):
        for _ in range(2):
            response = await self.submit(payload={"image": self.image})
            self.assertEqual(response.status, 202)
            await self.finish()
        self.assertEqual(sorted(path.name for path in self.destination.iterdir()),
                         ["image_00001_.png", "image_00001__1.png"])

    async def test_oss_hash_key_and_same_content_reuse(self):
        first = body(await self.submit("oss"))["job"]
        await self.finish()
        self.assertTrue(first["object_key"].endswith(f"/moss/{self.asset_hash}.png"))
        self.assertEqual(oss._jobs[first["id"]]["status"], "done")
        self.assertTrue(oss._jobs[first["id"]]["result_url"].startswith("https://img.example.test/"))
        # Remove in-memory history and recreate the store like a restart.
        oss._jobs.clear()
        protocol._store = None
        second = body(await self.submit("oss"))["job"]
        self.assertEqual(first["id"], second["id"])
        await self.submit("oss", self.payload(request_id="b" * 64))
        await self.finish()
        self.assertEqual(self.bucket.puts, 1)
        self.assertEqual(len(self.bucket.objects), 1)
        self.assertNotIn(b"fake-secret", (self.root / "config" / "moss_publish.sqlite3").read_bytes())

    async def test_oss_same_filename_different_content_gets_different_key(self):
        await self.submit("oss")
        await self.finish()
        other = self.source_dir / "another-run"
        other.mkdir()
        (other / self.source.name).write_bytes(b"another image")
        payload = self.payload(request_id="b" * 64, asset_hash=hashlib.sha256(b"another image").hexdigest(),
                               image={**self.image, "subfolder": "another-run"})
        await self.submit("oss", payload)
        await self.finish()
        self.assertEqual(self.bucket.puts, 2)
        self.assertEqual(set(self.bucket.objects.values()), {self.content, b"another image"})

    async def test_oss_existing_conflicting_object_is_not_overwritten(self):
        key = oss._object_key(self.config, self.source, self.asset_hash)
        self.bucket.objects[key] = b"conflict"
        first = body(await self.submit("oss"))["job"]
        await self.finish()
        self.assertEqual(oss._jobs[first["id"]]["status"], "failed")
        self.assertEqual(self.bucket.objects[key], b"conflict")
        self.assertEqual(self.bucket.puts, 0)

    async def test_oss_atomic_put_race_equal_succeeds_different_fails(self):
        for content, expected, request_id in [(self.content, "done", "a" * 64), (b"conflict", "failed", "b" * 64)]:
            with self.subTest(content=content):
                self.bucket.objects.clear()
                self.bucket.race_content = content
                job = body(await self.submit("oss", self.payload(request_id=request_id)))["job"]
                await self.finish()
                self.assertEqual(oss._jobs[job["id"]]["status"], expected)
                self.assertEqual(self.bucket.puts, 0)

    async def test_oss_versioned_buckets_rejected_before_write(self):
        for status in ("Enabled", "Suspended"):
            self.bucket.versioning = status
            await self.submit("oss", self.payload(request_id=hashlib.sha256(status.encode()).hexdigest()))
            await self.finish()
        self.assertTrue(all(job["status"] == "failed" for job in oss._jobs.values()))
        self.assertEqual(self.bucket.puts, 0)

    async def test_oss_legacy_calls_original_uploader(self):
        with patch.object(oss, "_upload_file", return_value={"result_url": "https://example.test/legacy.png"}) as upload:
            response = await self.submit("oss", {"image": self.image})
            await self.finish()
            self.assertEqual(body(response)["job"]["object_key"].split("/")[-1], self.source.name)
            upload.assert_called_once()

    async def test_target_config_frozen_while_waiting(self):
        with patch.object(oss, "_upload_verified_file", return_value={"result_url": "https://example.test/frozen"}) as upload:
            await self.submit("oss")
            oss._load_config.return_value = {**self.config, "bucket": "changed"}
            await self.finish()
            self.assertEqual(upload.call_args.args[0]["bucket"], "test")
        await self.submit(payload=self.payload(request_id="b" * 64))
        local._load_config.return_value = {"output_directory": str(self.root / "changed")}
        await self.finish()
        self.assertEqual(len(list(self.destination.iterdir())), 1)
        self.assertFalse((self.root / "changed").exists())

    async def test_date_prefix_preserved_after_restart_and_failed_retry(self):
        key = oss._object_key(self.config, self.source, self.asset_hash)
        self.bucket.objects[key] = b"conflict"
        first = body(await self.submit("oss"))["job"]
        await self.finish()
        oss._jobs.clear()
        protocol._store = None
        with patch.object(oss, "_object_key", return_value="tomorrow/should-not-be-used.png"):
            second = body(await self.submit("oss"))["job"]
        self.assertEqual(first["object_key"], second["object_key"])
        await self.finish()

    async def test_interrupted_job_requires_explicit_retry_and_keeps_binding(self):
        store = protocol.publish_store()
        job = {"id": "interrupted", "request_id": "a" * 64, "asset_hash": self.asset_hash,
               "image": self.image, "status": "working", "message": "", "created_at": 0, "updated_at": 0,
               "object_key": "first-date/moss/hash.png"}
        await asyncio.to_thread(store.claim, "oss", {name: self.config[name] for name in ("endpoint", "bucket", "prefix")}, job)
        protocol._store = None
        recovered = body(await oss.list_oss_publish_jobs(None))["jobs"][0]
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(self.tasks, [])
        retried = body(await self.submit("oss"))["job"]
        self.assertEqual(retried["object_key"], job["object_key"])
        await self.finish()

    async def test_active_jobs_are_not_evicted_when_queue_exceeds_limit(self):
        with patch.object(local, "_max_jobs", 2):
            responses = await asyncio.gather(*(self.submit(payload=self.payload(request_id=f"{i:064x}")) for i in range(6)))
            await self.finish()
        self.assertEqual(len(responses), 6)
        self.assertTrue(all(job["status"] == "done" for job in local._jobs.values()))
        self.assertEqual(len(list(self.destination.iterdir())), 1)


class StoreTests(unittest.TestCase):
    def test_atomic_claim_from_threads_and_separate_store_connections(self):
        with tempfile.TemporaryDirectory(prefix="autopublish-store-test-") as temporary:
            path = Path(temporary) / "requests.sqlite3"
            first = protocol.PublishStore(path)
            second = protocol.PublishStore(path)
            # Initialize both before submissions; one user directory belongs to
            # one running ComfyUI process, and recovery occurs at startup only.
            first.recent("local", 100)
            second.recent("local", 100)

            def claim(index):
                job = {"id": str(index), "request_id": "a" * 64, "asset_hash": "b" * 64,
                       "status": "waiting", "updated_at": 0}
                return (first if index % 2 else second).claim("local", {"output_directory": temporary}, job)

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(claim, range(50)))
            self.assertEqual(sum(created for job, created in results), 1)
            self.assertEqual(len({job["id"] for job, created in results}), 1)


if __name__ == "__main__":
    unittest.main()
