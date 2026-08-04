from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import mimetypes
import os
import secrets
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import aiohttp
import folder_paths
from aiohttp import web
from server import PromptServer

try:
    import win32crypt
except ImportError:  # pragma: no cover - only used outside the Windows bundle
    win32crypt = None


_AUTHORIZATION_URL = "https://x.com/i/oauth2/authorize"
_TOKEN_URL = "https://api.x.com/2/oauth2/token"
_ME_URL = "https://api.x.com/2/users/me"
_MEDIA_URL = "https://api.x.com/2/media/upload"
_POST_URL = "https://api.x.com/2/tweets"
_SCOPES = "tweet.read tweet.write users.read media.write offline.access"
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_CONFIG_FILENAME = "x.json"
_DPAPI_DESCRIPTION = "ComfyUI AutoPublish X"
_DEFAULT_LOOPBACK_REDIRECT_URI = "http://127.0.0.1:17863/x/callback"

_jobs: OrderedDict[str, dict] = OrderedDict()
_pending_oauth: dict[str, dict] = {}
_config_lock = asyncio.Lock()
_loopback_lock = asyncio.Lock()
_loopback_runner: web.AppRunner | None = None
_loopback_redirect_uri = ""
_loopback_stop_task: asyncio.Task | None = None


def _config_path() -> Path:
    return Path(folder_paths.get_system_user_directory("autopublish")) / _CONFIG_FILENAME


def _load_config() -> dict:
    path = _config_path()
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    return value if isinstance(value, dict) else {}


def _save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _protect_token(value: str) -> str:
    if not value:
        return ""
    if win32crypt is None:
        raise RuntimeError("当前 Python 缺少 Windows DPAPI 支持（pywin32），无法安全保存 X 授权")
    protected = win32crypt.CryptProtectData(
        value.encode("utf-8"), _DPAPI_DESCRIPTION, None, None, None, 0
    )
    if isinstance(protected, tuple):
        protected = protected[-1]
    return base64.b64encode(protected).decode("ascii")


def _unprotect_token(value: str) -> str:
    if not value:
        return ""
    if win32crypt is None:
        raise RuntimeError("当前 Python 缺少 Windows DPAPI 支持（pywin32），无法读取 X 授权")
    protected = base64.b64decode(value.encode("ascii"), validate=True)
    unprotected = win32crypt.CryptUnprotectData(protected, None, None, None, 0)
    if isinstance(unprotected, tuple):
        unprotected = unprotected[-1]
    return unprotected.decode("utf-8")


def _configured(config: dict) -> bool:
    return bool(config.get("client_id") and config.get("redirect_uri"))


def _connected(config: dict) -> bool:
    return bool(config.get("access_token_protected") or config.get("refresh_token_protected"))


def _public_config(config: dict) -> dict:
    return {
        "client_id": config.get("client_id", ""),
        "redirect_uri": config.get("redirect_uri", ""),
        "proxy_url": config.get("proxy_url", ""),
        "default_text": config.get("default_text", ""),
        "configured": _configured(config),
        "connected": _connected(config),
        "user_id": config.get("user_id", ""),
        "username": config.get("username", ""),
    }


def _normalize_config(payload: dict, current: dict) -> dict:
    client_id = str(payload.get("client_id", "")).strip()
    redirect_uri = str(payload.get("redirect_uri", "")).strip()
    if redirect_uri and not redirect_uri.startswith(("http://", "https://")):
        raise ValueError("X 回调地址必须以 http:// 或 https:// 开头")
    if len(str(payload.get("default_text", ""))) > 10000:
        raise ValueError("默认正文过长")
    proxy_url = str(payload.get("proxy_url", "")).strip()
    if proxy_url:
        parsed_proxy = urlsplit(proxy_url)
        if parsed_proxy.scheme not in {"http", "https"} or not parsed_proxy.hostname:
            raise ValueError("X HTTP 代理地址格式无效，例如 http://127.0.0.1:7890")
        if parsed_proxy.username or parsed_proxy.password:
            raise ValueError("当前版本不支持带用户名或密码的 X HTTP 代理")

    identity_changed = (
        client_id != current.get("client_id", "")
        or redirect_uri != current.get("redirect_uri", "")
    )
    config = dict(current)
    config.update(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "proxy_url": proxy_url,
            "default_text": str(payload.get("default_text", "")),
        }
    )
    if identity_changed:
        _clear_authorization(config)
    return config


def _clear_authorization(config: dict) -> None:
    for name in (
        "access_token_protected",
        "refresh_token_protected",
        "expires_at",
        "user_id",
        "username",
    ):
        config.pop(name, None)


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
        raise ValueError("只能发布 ComfyUI input、output 或 temp 目录内的图片") from error
    if not path.is_file():
        raise ValueError(f"找不到图片文件：{filename}")
    if path.stat().st_size > _MAX_IMAGE_BYTES:
        raise ValueError("X 单张图片上限为 5 MB，请先压缩后再发布")

    media_type = mimetypes.guess_type(path.name)[0] or ""
    if media_type not in _ALLOWED_MEDIA_TYPES:
        raise ValueError("X 发布仅支持 JPG、PNG、GIF 或 WEBP 图片")
    return path


def _oauth_error(payload: dict, status: int) -> str:
    if isinstance(payload.get("detail"), str):
        detail = payload["detail"]
    elif isinstance(payload.get("error_description"), str):
        detail = payload["error_description"]
    elif isinstance(payload.get("title"), str):
        detail = payload["title"]
    elif isinstance(payload.get("error"), str):
        detail = payload["error"]
    else:
        detail = f"HTTP {status}"
    return detail[:500]


async def _request_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> dict:
    try:
        async with session.request(method, url, **kwargs) as response:
            raw = await response.text()
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            if not 200 <= response.status < 300:
                raise RuntimeError(_oauth_error(payload, response.status))
            if not isinstance(payload, dict):
                raise RuntimeError("X API 返回了无法识别的数据")
            return payload
    except asyncio.TimeoutError as error:
        raise RuntimeError("连接 X API 超时，请检查网络或在 X 配置中填写 HTTP 代理") from error
    except aiohttp.ClientError as error:
        raise RuntimeError(f"无法连接 X API：{error}") from error


async def _stop_loopback_after(delay: float) -> None:
    global _loopback_runner, _loopback_redirect_uri
    await asyncio.sleep(delay)
    async with _loopback_lock:
        runner = _loopback_runner
        _loopback_runner = None
        _loopback_redirect_uri = ""
        if runner is not None:
            await runner.cleanup()


def _schedule_loopback_stop(delay: float) -> None:
    global _loopback_stop_task
    if _loopback_stop_task is not None and not _loopback_stop_task.done():
        _loopback_stop_task.cancel()
    _loopback_stop_task = asyncio.create_task(_stop_loopback_after(delay))


async def _ensure_loopback_server(redirect_uri: str) -> None:
    global _loopback_runner, _loopback_redirect_uri
    parsed = urlsplit(redirect_uri)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port is None
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"当前版本的 X 回调必须是本机 HTTP 地址，例如 {_DEFAULT_LOOPBACK_REDIRECT_URI}"
        )

    async with _loopback_lock:
        if _loopback_runner is not None and _loopback_redirect_uri == redirect_uri:
            _schedule_loopback_stop(620)
            return
        if _loopback_runner is not None:
            await _loopback_runner.cleanup()
            _loopback_runner = None
            _loopback_redirect_uri = ""

        callback_app = web.Application()
        callback_app.router.add_get(parsed.path, x_oauth_callback)
        runner = web.AppRunner(callback_app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, parsed.hostname, parsed.port)
            await site.start()
        except OSError as error:
            await runner.cleanup()
            raise RuntimeError(
                f"无法监听 X 回调端口 {parsed.port}，请确认该端口未被其他程序占用"
            ) from error
        _loopback_runner = runner
        _loopback_redirect_uri = redirect_uri
        _schedule_loopback_stop(620)


def _store_tokens(config: dict, token_payload: dict) -> None:
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("X 授权响应中没有 access_token")
    config["access_token_protected"] = _protect_token(access_token)
    refresh_token = token_payload.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        config["refresh_token_protected"] = _protect_token(refresh_token)
    expires_in = token_payload.get("expires_in", 7200)
    try:
        expires_in = max(60, int(expires_in))
    except (TypeError, ValueError):
        expires_in = 7200
    config["expires_at"] = time.time() + expires_in


async def _get_access_token(session: aiohttp.ClientSession) -> str:
    async with _config_lock:
        config = _load_config()
        if not _connected(config):
            raise RuntimeError("请先连接 X 账号")
        expires_at = float(config.get("expires_at") or 0)
        if config.get("access_token_protected") and expires_at > time.time() + 60:
            return _unprotect_token(config["access_token_protected"])

        refresh_token = _unprotect_token(config.get("refresh_token_protected", ""))
        if not refresh_token:
            raise RuntimeError("X 授权已过期，请重新连接 X 账号")
        payload = await _request_json(
            session,
            "POST",
            _TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "client_id": config.get("client_id", ""),
            },
            **({"proxy": config["proxy_url"]} if config.get("proxy_url") else {}),
        )
        _store_tokens(config, payload)
        _save_config(config)
        return _unprotect_token(config["access_token_protected"])


async def _upload_media(
    session: aiohttp.ClientSession, token: str, image_path: Path, proxy_url: str = ""
) -> str:
    media_type = mimetypes.guess_type(image_path.name)[0]
    media = await asyncio.to_thread(image_path.read_bytes)
    payload = await _request_json(
        session,
        "POST",
        _MEDIA_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "media": base64.b64encode(media).decode("ascii"),
            "media_category": "tweet_image",
            "media_type": media_type,
            "shared": False,
        },
        **({"proxy": proxy_url} if proxy_url else {}),
    )
    media_id = payload.get("data", {}).get("id") if isinstance(payload.get("data"), dict) else None
    if not media_id:
        raise RuntimeError("X 媒体上传成功，但响应中没有媒体 ID")
    return str(media_id)


async def _create_post(
    session: aiohttp.ClientSession,
    token: str,
    media_id: str,
    text: str,
    proxy_url: str = "",
) -> dict:
    body: dict = {"media": {"media_ids": [media_id]}}
    if text:
        body["text"] = text
    payload = await _request_json(
        session,
        "POST",
        _POST_URL,
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        **({"proxy": proxy_url} if proxy_url else {}),
    )
    data = payload.get("data")
    post_id = data.get("id") if isinstance(data, dict) else None
    if not post_id:
        raise RuntimeError("X 返回发帖成功，但响应中没有帖子 ID")
    return {"post_id": str(post_id), "post_url": f"https://x.com/i/web/status/{post_id}"}


def _job_response(job: dict) -> dict:
    return {
        "id": job["id"],
        "image": job["image"],
        "text": job["text"],
        "post_id": job.get("post_id", ""),
        "post_url": job.get("post_url", ""),
        "status": job["status"],
        "message": job["message"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def _update_job(job_id: str, status: str, message: str, result: dict | None = None) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    job["status"] = status
    job["message"] = message
    job["updated_at"] = time.time()
    if result:
        job.update(result)


async def _run_publish_job(job_id: str, image_path: Path) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    timeout = aiohttp.ClientTimeout(total=90, connect=20)
    try:
        config = _load_config()
        proxy_url = str(config.get("proxy_url", ""))
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            _update_job(job_id, "working", "正在确认 X 授权…")
            token = await _get_access_token(session)
            _update_job(job_id, "working", "正在上传图片到 X…")
            media_id = await _upload_media(session, token, image_path, proxy_url)
            _update_job(job_id, "working", "正在发布到 X…")
            result = await _create_post(session, token, media_id, job["text"], proxy_url)
    except Exception as error:
        message = str(error).strip() or error.__class__.__name__
        _update_job(job_id, "failed", f"X 发布失败：{message[:240]}")
        return
    _update_job(job_id, "done", "已发布到 X", result)


def _callback_page(title: str, message: str, success: bool) -> web.Response:
    color = "#7fd59a" if success else "#ff8f8f"
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    content = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{safe_title}</title>
<style>body{{margin:0;background:#171a20;color:#f2f5f8;font-family:Segoe UI,Microsoft YaHei UI,sans-serif;display:grid;place-items:center;min-height:100vh}}main{{width:min(440px,calc(100vw - 48px));padding:28px;background:#20242c;border:1px solid #343a45;border-radius:14px}}h1{{margin:0 0 12px;color:{color};font-size:21px}}p{{margin:0;color:#b6bfca;line-height:1.65}}</style>
</head><body><main><h1>{safe_title}</h1><p>{safe_message}</p></main></body></html>"""
    return web.Response(text=content, content_type="text/html")


@PromptServer.instance.routes.get("/autopublish/x/config")
async def get_x_config(_request: web.Request) -> web.Response:
    try:
        config = _load_config()
    except (OSError, json.JSONDecodeError) as error:
        return web.json_response({"error": f"读取 X 配置失败：{error}"}, status=500)
    return web.json_response({"config": _public_config(config)})


@PromptServer.instance.routes.post("/autopublish/x/config")
async def save_x_config(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("配置格式无效")
        async with _config_lock:
            current = _load_config()
            config = _normalize_config(payload, current)
            if not _configured(config):
                raise ValueError("Client ID 和回调地址均为必填项")
            _save_config(config)
    except (json.JSONDecodeError, TypeError, ValueError, OSError) as error:
        return web.json_response({"error": str(error)}, status=400)
    return web.json_response({"config": _public_config(config)})


@PromptServer.instance.routes.post("/autopublish/x/oauth/start")
async def start_x_oauth(_request: web.Request) -> web.Response:
    try:
        config = _load_config()
        if not _configured(config):
            raise ValueError("请先保存 X Client ID 和回调地址")
        await _ensure_loopback_server(config["redirect_uri"])
        now = time.time()
        for old_state in [key for key, value in _pending_oauth.items() if now - value["created_at"] > 600]:
            _pending_oauth.pop(old_state, None)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        _pending_oauth[state] = {
            "verifier": verifier,
            "redirect_uri": config["redirect_uri"],
            "created_at": now,
        }
        query = urlencode(
            {
                "response_type": "code",
                "client_id": config["client_id"],
                "redirect_uri": config["redirect_uri"],
                "scope": _SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=400)
    return web.json_response({"authorization_url": f"{_AUTHORIZATION_URL}?{query}"})


@PromptServer.instance.routes.get("/autopublish/x/oauth/callback")
async def x_oauth_callback(request: web.Request) -> web.Response:
    oauth_error = request.query.get("error")
    if oauth_error:
        state = request.query.get("state", "")
        if _pending_oauth.pop(state, None) is not None:
            _schedule_loopback_stop(2)
        detail = request.query.get("error_description") or oauth_error
        return _callback_page("X 授权未完成", detail, False)

    state = request.query.get("state", "")
    code = request.query.get("code", "")
    pending = _pending_oauth.pop(state, None)
    if not code or not pending or time.time() - pending["created_at"] > 600:
        return _callback_page("X 授权已失效", "请回到 ComfyUI 重新点击“连接 X”。", False)

    try:
        config = _load_config()
        if pending["redirect_uri"] != config.get("redirect_uri"):
            raise RuntimeError("回调地址在授权过程中发生了变化，请重新授权")
        timeout = aiohttp.ClientTimeout(total=45, connect=20)
        proxy_options = {"proxy": config["proxy_url"]} if config.get("proxy_url") else {}
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            token_payload = await _request_json(
                session,
                "POST",
                _TOKEN_URL,
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "client_id": config.get("client_id", ""),
                    "redirect_uri": config.get("redirect_uri", ""),
                    "code_verifier": pending["verifier"],
                },
                **proxy_options,
            )
            _store_tokens(config, token_payload)
            access_token = _unprotect_token(config["access_token_protected"])
            me_payload = await _request_json(
                session,
                "GET",
                _ME_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                **proxy_options,
            )
        user = me_payload.get("data") if isinstance(me_payload.get("data"), dict) else {}
        config["user_id"] = str(user.get("id", ""))
        config["username"] = str(user.get("username", ""))
        async with _config_lock:
            _save_config(config)
    except Exception as error:
        _schedule_loopback_stop(2)
        return _callback_page("X 授权失败", str(error)[:500], False)

    account = f"@{config['username']}" if config.get("username") else "你的 X 账号"
    _schedule_loopback_stop(2)
    return _callback_page("X 已连接", f"已连接 {account}，现在可以关闭此页面并返回 ComfyUI。", True)


@PromptServer.instance.routes.post("/autopublish/x/disconnect")
async def disconnect_x(_request: web.Request) -> web.Response:
    try:
        async with _config_lock:
            config = _load_config()
            _clear_authorization(config)
            _save_config(config)
    except (OSError, json.JSONDecodeError) as error:
        return web.json_response({"error": f"断开 X 失败：{error}"}, status=500)
    return web.json_response({"config": _public_config(config)})


@PromptServer.instance.routes.post("/autopublish/x/publish")
async def create_x_publish_job(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        config = _load_config()
        if not _connected(config):
            raise ValueError("请先连接 X 账号")
        image = payload.get("image")
        if not isinstance(image, dict):
            raise ValueError("缺少图片信息")
        image_path = _resolve_image_path(image)
        text = payload.get("text", "")
        if not isinstance(text, str):
            raise ValueError("帖子正文格式无效")
        if not text.strip():
            text = ""
        if len(text) > 10000:
            raise ValueError("帖子正文过长")
    except (json.JSONDecodeError, TypeError, ValueError, OSError) as error:
        return web.json_response({"error": str(error)}, status=400)

    now = time.time()
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "image": {
            "filename": image["filename"],
            "subfolder": str(image.get("subfolder", "")),
            "type": str(image.get("type", "output")),
        },
        "text": text,
        "post_id": "",
        "post_url": "",
        "status": "waiting",
        "message": "已交给 X 后台发布队列",
        "created_at": now,
        "updated_at": now,
    }
    _jobs[job_id] = job
    while len(_jobs) > 100:
        _jobs.popitem(last=False)
    asyncio.create_task(_run_publish_job(job_id, image_path))
    return web.json_response({"job": _job_response(job)}, status=202)


@PromptServer.instance.routes.get("/autopublish/x/jobs")
async def list_x_publish_jobs(_request: web.Request) -> web.Response:
    return web.json_response({"jobs": [_job_response(job) for job in reversed(_jobs.values())]})
