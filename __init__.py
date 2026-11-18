from __future__ import annotations

import asyncio
import json
import os
import posixpath
import sqlite3
import time
import uuid
from collections import OrderedDict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import folder_paths
import oss2
from aiohttp import web
from server import PromptServer

from .publish_protocol import (
    PublishConflict, content_suffix, publish_store, request_identity,
    stream_hash, trim_jobs, verified_snapshot, verify_file,
)


WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_jobs: OrderedDict[str, dict] = OrderedDict()
_max_jobs = 100
_config_filename = "oss.json"


def _config_path() -> Path:
    return Path(folder_paths.get_system_user_directory("autopublish")) / _config_filename


def _load_config() -> dict:
    path = _config_path()
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    return value if isinstance(value, dict) else {}


def _public_config(config: dict) -> dict:
    return {
        "endpoint": config.get("endpoint", ""),
        "bucket": config.get("bucket", ""),
        "prefix": config.get("prefix", "comfyui/%Y/%m/%d"),
        "public_base_url": config.get("public_base_url", ""),
        "access_key_id": config.get("access_key_id", ""),
        "access_key_secret_set": bool(config.get("access_key_secret")),
        "configured": _config_is_complete(config),
        "moss_publish_version": 1,
    }


def _config_is_complete(config: dict) -> bool:
    return all(config.get(name) for name in ("endpoint", "bucket", "access_key_id", "access_key_secret"))


def _normalize_config(payload: dict, current: dict) -> dict:
    endpoint = str(payload.get("endpoint", "")).strip().rstrip("/")
    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = f"https://{endpoint}"

    secret = str(payload.get("access_key_secret", "")).strip() or current.get("access_key_secret", "")
    config = {
        "endpoint": endpoint,
        "bucket": str(payload.get("bucket", "")).strip(),
        "prefix": str(payload.get("prefix", "comfyui/%Y/%m/%d")).strip().replace("\\", "/").strip("/"),
        "public_base_url": str(payload.get("public_base_url", "")).strip().rstrip("/"),
        "access_key_id": str(payload.get("access_key_id", "")).strip(),
        "access_key_secret": secret,
    }
    if any(part == ".." for part in config["prefix"].split("/")):
        raise ValueError("OSS 路径前缀不能包含 ..")
    return config


def _save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _resolve_image_path(image: dict) -> Path:
    filename = image.get("filename")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise ValueError("图片文件名无效")

    image_type = str(image.get("type", "output"))
    if image_type not in {"input", "output", "temp"}:
        raise ValueError("图片目录类型无效")
    base = Path(folder_paths.get_directory_by_type(image_type)).resolve()

    subfolder = Path(str(image.get("subfolder", "")))
    folder = subfolder if subfolder.is_absolute() else base / subfolder
    path = (folder / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError("只能上传 ComfyUI input、output 或 temp 目录内的图片") from error
    if not path.is_file():
        raise ValueError(f"找不到图片文件：{filename}")
    return path


def _object_key(config: dict, image_path: Path, asset_hash: str = "") -> str:
    prefix = datetime.now().strftime(config["prefix"])
    name = f"moss/{asset_hash}{content_suffix(image_path)}" if asset_hash else image_path.name
    return posixpath.join(prefix, name) if prefix else name


def _result_url(config: dict, object_key: str) -> str:
    encoded_key = quote(object_key, safe="/")
    public_base_url = config.get("public_base_url", "")
    if public_base_url:
        if public_base_url.startswith("http://"):
            public_base_url = f"https://{public_base_url.removeprefix('http://')}"
        elif not public_base_url.startswith("https://"):
            public_base_url = f"https://{public_base_url}"
        return f"{public_base_url}/{encoded_key}"

    endpoint = urlsplit(config["endpoint"])
    if not endpoint.scheme or not endpoint.netloc:
        return ""
    bucket_host = endpoint.netloc
    bucket_prefix = f"{config['bucket']}."
    if not bucket_host.startswith(bucket_prefix):
        bucket_host = f"{bucket_prefix}{bucket_host}"
    return f"https://{bucket_host}/{encoded_key}"


def _upload_file(config: dict, image_path: Path, object_key: str) -> dict:
    auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
    bucket = oss2.Bucket(auth, config["endpoint"], config["bucket"], connect_timeout=30)
    result = bucket.put_object_from_file(object_key, str(image_path))
    if not 200 <= result.status < 300:
        raise RuntimeError(f"OSS 返回 HTTP {result.status}")

    return {"request_id": result.request_id, "result_url": _result_url(config, object_key)}


def _existing_oss_content(bucket, object_key: str, asset_hash: str) -> bool:
    try:
        remote = bucket.get_object(object_key)
    except oss2.exceptions.NoSuchKey:
        return False
    with closing(remote):
        if stream_hash(remote) != asset_hash:
            raise PublishConflict("OSS 目标对象已存在且内容不同，未覆盖")
    return True


def _upload_verified_file(config: dict, image: dict, object_key: str, asset_hash: str) -> dict:
    with verified_snapshot(_resolve_image_path(image), asset_hash) as snapshot:
        auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
        bucket = oss2.Bucket(auth, config["endpoint"], config["bucket"], connect_timeout=30)
        if not _existing_oss_content(bucket, object_key, asset_hash):
            # OSS ignores forbid-overwrite on versioned/suspended buckets.
            if bucket.get_bucket_versioning().status:
                raise ValueError("MOSS 防覆盖上传需要从未启用版本控制的 Bucket，请选择其他 Bucket")
            try:
                result = bucket.put_object(object_key, snapshot, headers={"x-oss-forbid-overwrite": "true"})
                if not 200 <= result.status < 300:
                    raise RuntimeError(f"OSS 返回 HTTP {result.status}")
            except oss2.exceptions.ServerError as error:
                if error.code not in {"FileAlreadyExists", "ObjectAlreadyExists"}:
                    raise
                if not _existing_oss_content(bucket, object_key, asset_hash):
                    raise
    return {"result_url": _result_url(config, object_key)}


def _job_response(job: dict) -> dict:
    return {
        "id": job["id"],
        "request_id": job.get("request_id", ""),
        "asset_hash": job.get("asset_hash", ""),
        "image": job["image"],
        "object_key": job["object_key"],
        "result_url": job.get("result_url", ""),
        "result_path": "",
        "status": job["status"],
        "message": job["message"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


async def _update_job(job_id: str, status: str, message: str, result_url: str = "") -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    job["status"] = status
    job["message"] = message
    job["updated_at"] = time.time()
    if result_url:
        job["result_url"] = result_url
    if job.get("request_id"):
        await asyncio.to_thread(publish_store().update, job.copy())


async def _run_upload_job(job_id: str, config: dict, image_path: Path) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    try:
        await _update_job(job_id, "working", "正在上传到 OSS…")
        if job.get("request_id"):
            result = await asyncio.to_thread(_upload_verified_file, config, job["image"], job["object_key"], job["asset_hash"])
        else:
            result = await asyncio.to_thread(_upload_file, config, image_path, job["object_key"])
    except Exception as error:
        message = str(error).strip() or error.__class__.__name__
        await _update_job(job_id, "failed", f"上传失败：{message[:240]}")
        return
    await _update_job(job_id, "done", f"上传成功：{job['object_key']}", result["result_url"])


@PromptServer.instance.routes.get("/autopublish/oss/config")
async def get_oss_config(_request: web.Request) -> web.Response:
    try:
        config = _load_config()
    except (OSError, json.JSONDecodeError) as error:
        return web.json_response({"error": f"读取 OSS 配置失败：{error}"}, status=500)
    return web.json_response({"config": _public_config(config)})


@PromptServer.instance.routes.post("/autopublish/oss/config")
async def save_oss_config(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象")
        current = _load_config()
        config = _normalize_config(payload, current)
        if not _config_is_complete(config):
            raise ValueError("Endpoint、Bucket、AccessKey ID 和 AccessKey Secret 均为必填项")
        _save_config(config)
    except (json.JSONDecodeError, TypeError, ValueError, OSError) as error:
        return web.json_response({"error": str(error)}, status=400)
    return web.json_response({"config": _public_config(config)})


@PromptServer.instance.routes.post("/autopublish/oss/publish")
async def create_oss_publish_job(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象")
        request_id, asset_hash = request_identity(payload)
        config = _load_config()
        if not _config_is_complete(config):
            raise ValueError("请先完成 OSS 配置")
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
        "object_key": _object_key(config, image_path, asset_hash),
        "result_url": "",
        "status": "waiting",
        "message": "已交给后台上传队列",
        "created_at": now,
        "updated_at": now,
    }
    if request_id:
        target = {name: config[name] for name in ("endpoint", "bucket", "prefix")}
        try:
            job, created = await asyncio.to_thread(publish_store().claim, "oss", target, job)
        except PublishConflict as error:
            return web.json_response({"error": str(error)}, status=409)
        except (OSError, sqlite3.Error) as error:
            return web.json_response({"error": f"保存发布记录失败：{error}"}, status=500)
        if not created:
            return web.json_response({"job": _job_response(job)}, status=202)
    _jobs[job["id"]] = job
    trim_jobs(_jobs, _max_jobs)

    asyncio.create_task(_run_upload_job(job["id"], config, image_path))
    return web.json_response({"job": _job_response(job)}, status=202)


@PromptServer.instance.routes.get("/autopublish/oss/jobs")
async def list_oss_publish_jobs(_request: web.Request) -> web.Response:
    try:
        stored = await asyncio.to_thread(publish_store().recent, "oss", _max_jobs)
    except (OSError, sqlite3.Error) as error:
        return web.json_response({"error": f"读取发布记录失败：{error}"}, status=500)
    combined = {job["id"]: job for job in [*stored, *_jobs.values()]}
    jobs = [_job_response(job) for job in sorted(combined.values(), key=lambda job: job["updated_at"], reverse=True)[:_max_jobs]]
    return web.json_response({"jobs": jobs})


from . import x_service as _x_service  # noqa: E402,F401 - registers X routes
from . import local_service as _local_service  # noqa: E402,F401 - registers local copy routes


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
