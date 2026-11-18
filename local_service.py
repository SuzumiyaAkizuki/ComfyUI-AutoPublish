from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import folder_paths
from aiohttp import web
from server import PromptServer

from . import _resolve_image_path
from .publish_protocol import (
    PublishConflict, content_suffix, publish_store, request_identity,
    trim_jobs, verified_snapshot, verify_file,
)


_jobs: OrderedDict[str, dict] = OrderedDict()
_max_jobs = 100
_config_filename = "local.json"
_copy_lock = threading.Lock()


def _config_path() -> Path:
    return Path(folder_paths.get_system_user_directory("autopublish")) / _config_filename


def _load_config() -> dict:
    path = _config_path()
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    return value if isinstance(value, dict) else {}


def _normalize_destination(value: object) -> Path:
    raw = str(value or "").strip().strip('"')
    if not raw:
        raise ValueError("请填写精选结果文件夹")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("精选结果文件夹必须使用绝对路径")
    return path.resolve()


def _destination_directory(config: dict, create: bool = False) -> Path:
    path = _normalize_destination(config.get("output_directory", ""))
    if path.exists() and not path.is_dir():
        raise ValueError("精选结果路径不是文件夹")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("精选结果文件夹不存在，请重新保存配置")
    return path


def _public_config(config: dict) -> dict:
    output_directory = str(config.get("output_directory", ""))
    try:
        configured = _destination_directory(config).is_dir()
    except (OSError, ValueError):
        configured = False
    return {
        "output_directory": output_directory,
        "configured": configured,
        "moss_publish_version": 1,
    }


def _save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _copy_to_destination(source: Path, destination_directory: Path) -> Path:
    source = source.resolve()
    destination_directory = destination_directory.resolve()
    with _copy_lock:
        destination = destination_directory / source.name
        if destination.exists():
            try:
                if source.samefile(destination):
                    return destination
            except OSError:
                pass

            index = 1
            while destination.exists():
                destination = destination_directory / f"{source.stem}_{index}{source.suffix}"
                index += 1

        shutil.copy2(source, destination)
        return destination


def _copy_verified_file(image: dict, destination_directory: Path, destination_name: str, asset_hash: str) -> Path:
    source = _resolve_image_path(image)
    destination = destination_directory / destination_name
    with verified_snapshot(source, asset_hash) as snapshot:
        if destination.exists():
            verify_file(destination, asset_hash)
            return destination
        # Stage the complete file on the target volume, then create the final
        # name atomically without replacing any existing file (including links).
        descriptor, temporary_name = tempfile.mkstemp(prefix=".moss-", suffix=".tmp", dir=destination_directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                shutil.copyfileobj(snapshot, output)
                output.flush()
                os.fsync(output.fileno())
            shutil.copystat(source, temporary)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                verify_file(destination, asset_hash)
        finally:
            temporary.unlink()
    return destination


def _job_response(job: dict) -> dict:
    return {
        "id": job["id"],
        "request_id": job.get("request_id", ""),
        "asset_hash": job.get("asset_hash", ""),
        "image": job["image"],
        "result_path": job.get("result_path", ""),
        "result_url": "",
        "status": job["status"],
        "message": job["message"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


async def _update_job(job_id: str, status: str, message: str, result_path: str = "") -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    job["status"] = status
    job["message"] = message
    job["updated_at"] = time.time()
    if result_path:
        job["result_path"] = result_path
    if job.get("request_id"):
        await asyncio.to_thread(publish_store().update, job.copy())


async def _run_copy_job(job_id: str, source: Path, destination_directory: Path) -> None:
    if job_id not in _jobs:
        return
    try:
        await _update_job(job_id, "working", "正在复制到精选结果文件夹…")
        job = _jobs[job_id]
        if job.get("request_id"):
            result_path = await asyncio.to_thread(_copy_verified_file, job["image"], destination_directory,
                                                  job["destination_name"], job["asset_hash"])
        else:
            result_path = await asyncio.to_thread(_copy_to_destination, source, destination_directory)
    except Exception as error:
        message = str(error).strip() or error.__class__.__name__
        await _update_job(job_id, "failed", f"复制失败：{message[:240]}")
        return
    await _update_job(job_id, "done", f"已输出：{result_path.name}", str(result_path))


@PromptServer.instance.routes.get("/autopublish/local/config")
async def get_local_config(_request: web.Request) -> web.Response:
    try:
        config = _load_config()
    except (OSError, json.JSONDecodeError) as error:
        return web.json_response({"error": f"读取本地输出配置失败：{error}"}, status=500)
    return web.json_response({"config": _public_config(config)})


@PromptServer.instance.routes.post("/autopublish/local/config")
async def save_local_config(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象")
        destination = _normalize_destination(payload.get("output_directory", ""))
        if destination.exists() and not destination.is_dir():
            raise ValueError("精选结果路径不是文件夹")
        destination.mkdir(parents=True, exist_ok=True)
        config = {"output_directory": str(destination)}
        _save_config(config)
    except (json.JSONDecodeError, TypeError, ValueError, OSError) as error:
        return web.json_response({"error": str(error)}, status=400)
    return web.json_response({"config": _public_config(config)})


@PromptServer.instance.routes.post("/autopublish/local/publish")
async def create_local_publish_job(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象")
        request_id, asset_hash = request_identity(payload)
        config = _load_config()
        destination_directory = _destination_directory(config, create=True)
        image = payload.get("image")
        if not isinstance(image, dict):
            raise ValueError("缺少图片信息")
        image_path = _resolve_image_path(image)
        if asset_hash:
            await asyncio.to_thread(verify_file, image_path, asset_hash)
    except (json.JSONDecodeError, TypeError, ValueError, OSError) as error:
        return web.json_response({"error": str(error)}, status=400)

    now = time.time()
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "request_id": request_id,
        "asset_hash": asset_hash,
        "image": {
            "filename": image["filename"],
            "subfolder": str(image.get("subfolder", "")),
            "type": str(image.get("type", "output")),
        },
        "result_path": "",
        "destination_name": f"MOSS_{asset_hash}{content_suffix(image_path)}" if asset_hash else "",
        "status": "waiting",
        "message": "已交给本地复制队列",
        "created_at": now,
        "updated_at": now,
    }
    if request_id:
        target = {"output_directory": str(destination_directory)}
        try:
            job, created = await asyncio.to_thread(publish_store().claim, "local", target, job)
        except PublishConflict as error:
            return web.json_response({"error": str(error)}, status=409)
        except (OSError, sqlite3.Error) as error:
            return web.json_response({"error": f"保存发布记录失败：{error}"}, status=500)
        if not created:
            return web.json_response({"job": _job_response(job)}, status=202)
    _jobs[job["id"]] = job
    trim_jobs(_jobs, _max_jobs)

    asyncio.create_task(_run_copy_job(job["id"], image_path, destination_directory))
    return web.json_response({"job": _job_response(job)}, status=202)


@PromptServer.instance.routes.get("/autopublish/local/jobs")
async def list_local_publish_jobs(_request: web.Request) -> web.Response:
    try:
        stored = await asyncio.to_thread(publish_store().recent, "local", _max_jobs)
    except (OSError, sqlite3.Error) as error:
        return web.json_response({"error": f"读取发布记录失败：{error}"}, status=500)
    combined = {job["id"]: job for job in [*stored, *_jobs.values()]}
    jobs = [_job_response(job) for job in sorted(combined.values(), key=lambda job: job["updated_at"], reverse=True)[:_max_jobs]]
    return web.json_response({"jobs": jobs})
