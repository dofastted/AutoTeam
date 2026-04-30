"""AutoTeam HTTP API - 将 CLI 功能暴露为 HTTP 接口"""

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from autoteam import outbound_proxy
from autoteam.config import API_KEY
from autoteam.textio import parse_env_line, read_text, write_text

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AutoTeam API",
    description="ChatGPT Team 账号自动轮转管理 API",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# API Key 鉴权中间件
# ---------------------------------------------------------------------------

_AUTH_SKIP_PATHS = {"/api/auth/check", "/api/setup/status", "/api/setup/save"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    try:
        _maybe_reload_runtime_config_from_env_file()
    except Exception as exc:
        logger.warning("[配置] 自动热加载失败: %s", exc)

    path = request.url.path
    # 不鉴权的路径：非 /api 路径、auth/check 端点
    if not path.startswith("/api/") or path in _AUTH_SKIP_PATHS:
        return await call_next(request)
    # 未配置 API_KEY 则跳过鉴权
    if not API_KEY:
        return await call_next(request)
    # 从 header 或 query param 获取 key
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.query_params.get("key", "")
    if token != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "未授权，请提供有效的 API Key"})
    return await call_next(request)


@app.get("/api/auth/check")
def check_auth(request: Request):
    """验证 API Key 是否有效。未配置 API_KEY 时始终返回成功。"""
    if not API_KEY:
        return {"authenticated": True, "auth_required": False}
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == API_KEY:
        return {"authenticated": True, "auth_required": True}
    return JSONResponse(status_code=401, content={"authenticated": False, "auth_required": True})


# ---------------------------------------------------------------------------
# 初始配置 API（无需鉴权）
# ---------------------------------------------------------------------------


class SetupConfig(BaseModel):
    MAIL_PROVIDER: str = "mo_email"
    MO_EMAIL_BASE_URL: str = "https://mo.gymbro.cloud"
    MO_EMAIL_API_KEY: str = ""
    MO_EMAIL_DOMAIN: str = "gymbro.cloud"
    MO_EMAIL_NAME_PREFIX: str = "abc"
    MO_EMAIL_START_INDEX: str = "1"
    MO_EMAIL_EXPIRY_TIME: str = "3600000"
    CLOUDMAIL_BASE_URL: str = ""
    CLOUDMAIL_EMAIL: str = ""
    CLOUDMAIL_PASSWORD: str = ""
    CLOUDMAIL_DOMAIN: str = ""
    CF_TEMP_EMAIL_BASE_URL: str = ""
    CF_TEMP_EMAIL_ADMIN_PASSWORD: str = ""
    CF_TEMP_EMAIL_DOMAIN: str = ""
    SYNC_TARGET_CPA: str = ""
    CPA_URL: str = "http://127.0.0.1:8317"
    CPA_KEY: str = ""
    SYNC_TARGET_SUB2API: str = ""
    SUB2API_URL: str = ""
    SUB2API_EMAIL: str = ""
    SUB2API_PASSWORD: str = ""
    SUB2API_GROUP: str = ""
    PLAYWRIGHT_BROWSER_MODE: str = "hidden"
    PLAYWRIGHT_HEADLESS: str = "true"
    PLAYWRIGHT_PROXY_URL: str = ""
    PLAYWRIGHT_PROXY_BYPASS: str = ""
    OUTBOUND_PROXY_ENABLED: str = "true"
    OUTBOUND_PROXY_POOL: str = outbound_proxy.DEFAULT_PROXY_URL
    OUTBOUND_PROXY_BYPASS: str = outbound_proxy.DEFAULT_BYPASS
    OUTBOUND_PROXY_STRATEGY: str = "task-sticky"
    OUTBOUND_PROXY_FAILOVER: str = "true"
    API_KEY: str = ""
    TEAM_TARGET_SEATS: str = "999"
    FILL_BATCH_SIZE: str = "10"
    BROWSER_PARALLEL_WORKERS: str = "1"


class SourceConfig(BaseModel):
    content: str = ""


_RUNTIME_CONFIG_CLEARABLE_FIELDS = {
    "PLAYWRIGHT_BROWSER_MODE",
    "PLAYWRIGHT_HEADLESS",
    "PLAYWRIGHT_PROXY_URL",
    "PLAYWRIGHT_PROXY_BYPASS",
    "OUTBOUND_PROXY_ENABLED",
    "OUTBOUND_PROXY_POOL",
    "OUTBOUND_PROXY_BYPASS",
    "OUTBOUND_PROXY_FAILOVER",
}

_CLOUDMAIL_REQUIRED_KEYS = ("CLOUDMAIL_BASE_URL", "CLOUDMAIL_EMAIL", "CLOUDMAIL_PASSWORD", "CLOUDMAIL_DOMAIN")
_CF_TEMP_EMAIL_REQUIRED_KEYS = (
    "CF_TEMP_EMAIL_BASE_URL",
    "CF_TEMP_EMAIL_ADMIN_PASSWORD",
    "CF_TEMP_EMAIL_DOMAIN",
)
_MO_EMAIL_REQUIRED_KEYS = (
    "MO_EMAIL_BASE_URL",
    "MO_EMAIL_API_KEY",
    "MO_EMAIL_DOMAIN",
    "MO_EMAIL_NAME_PREFIX",
    "MO_EMAIL_START_INDEX",
    "MO_EMAIL_EXPIRY_TIME",
)
_CPA_REQUIRED_KEYS = ("CPA_URL", "CPA_KEY")
_SUB2API_REQUIRED_KEYS = ("SUB2API_URL", "SUB2API_EMAIL", "SUB2API_PASSWORD")
_SYNC_TARGET_TOGGLE_KEYS = ("SYNC_TARGET_CPA", "SYNC_TARGET_SUB2API")
_CPA_VERIFY_KEYS = ("SYNC_TARGET_CPA", *_CPA_REQUIRED_KEYS)
_SUB2API_VERIFY_KEYS = ("SYNC_TARGET_SUB2API", "SUB2API_GROUP", *_SUB2API_REQUIRED_KEYS)

_ALL_RUNTIME_ENV_KEYS = [
    "MAIL_PROVIDER",
    "MO_EMAIL_BASE_URL",
    "MO_EMAIL_API_KEY",
    "MO_EMAIL_DOMAIN",
    "MO_EMAIL_NAME_PREFIX",
    "MO_EMAIL_START_INDEX",
    "MO_EMAIL_EXPIRY_TIME",
    "CLOUDMAIL_BASE_URL",
    "CLOUDMAIL_EMAIL",
    "CLOUDMAIL_PASSWORD",
    "CLOUDMAIL_DOMAIN",
    "CF_TEMP_EMAIL_BASE_URL",
    "CF_TEMP_EMAIL_ADMIN_PASSWORD",
    "CF_TEMP_EMAIL_DOMAIN",
    "CHATGPT_ACCOUNT_ID",
    "SYNC_TARGET_CPA",
    "CPA_URL",
    "CPA_KEY",
    "SYNC_TARGET_SUB2API",
    "SUB2API_URL",
    "SUB2API_EMAIL",
    "SUB2API_PASSWORD",
    "SUB2API_GROUP",
    "EMAIL_POLL_INTERVAL",
    "EMAIL_POLL_TIMEOUT",
    "API_KEY",
    "AUTO_CHECK_INTERVAL",
    "AUTO_CHECK_THRESHOLD",
    "AUTO_CHECK_MIN_LOW",
    "TEAM_TARGET_SEATS",
    "FILL_BATCH_SIZE",
    "BROWSER_PARALLEL_WORKERS",
    "PLAYWRIGHT_BROWSER_MODE",
    "PLAYWRIGHT_HEADLESS",
    "PLAYWRIGHT_PROXY_URL",
    "PLAYWRIGHT_PROXY_SERVER",
    "PLAYWRIGHT_PROXY_USERNAME",
    "PLAYWRIGHT_PROXY_PASSWORD",
    "PLAYWRIGHT_PROXY_BYPASS",
    "OUTBOUND_PROXY_ENABLED",
    "OUTBOUND_PROXY_POOL",
    "OUTBOUND_PROXY_BYPASS",
    "OUTBOUND_PROXY_STRATEGY",
    "OUTBOUND_PROXY_FAILOVER",
]
_RUNTIME_ENV_BASE = {key: os.environ.get(key) for key in _ALL_RUNTIME_ENV_KEYS}
_runtime_env_reload_lock = threading.Lock()
_runtime_env_reload_state = {"signature": None}


def _runtime_config_prompt_map():
    from autoteam.setup_wizard import REQUIRED_CONFIGS

    return {key: prompt for key, prompt, _default, _optional in REQUIRED_CONFIGS}


def _current_runtime_env():
    from autoteam.setup_wizard import _read_env

    env = _read_env()
    merged = {key: value for key, value in os.environ.items()}
    merged.update({key: value for key, value in env.items() if value is not None})
    return merged


def _missing_runtime_configs(keys: tuple[str, ...] | list[str], *, env: dict[str, str] | None = None):
    env_values = env or _current_runtime_env()
    prompt_map = _runtime_config_prompt_map()
    missing = []
    for key in keys:
        value = (env_values.get(key, "") or "").strip()
        if not value:
            missing.append((key, prompt_map.get(key, key)))
    return missing


def _format_missing_runtime_configs(missing: list[tuple[str, str]]) -> str:
    return "、".join(f"{key}（{prompt}）" for key, prompt in missing)


def _effective_sync_target_states(env: dict[str, str] | None = None):
    from autoteam.sync_targets import get_sync_target_states

    return get_sync_target_states(env or _current_runtime_env())


def _runtime_required_keys(env: dict[str, str] | None = None) -> set[str]:
    from autoteam.mail_provider import get_mail_provider_name, get_mail_provider_required_keys

    states = _effective_sync_target_states(env)
    provider = get_mail_provider_name(env)
    required = set(get_mail_provider_required_keys(provider))
    required.add("API_KEY")
    if states.get("cpa"):
        required.update(_CPA_REQUIRED_KEYS)
    if states.get("sub2api"):
        required.update(_SUB2API_REQUIRED_KEYS)
    return required


def _require_runtime_configs(
    keys: tuple[str, ...] | list[str], action_label: str, *, env: dict[str, str] | None = None
):
    missing = _missing_runtime_configs(keys, env=env)
    if not missing:
        return

    detail = _format_missing_runtime_configs(missing)
    raise HTTPException(status_code=400, detail=f"{action_label} 前请先在配置面板填写：{detail}")


def _require_pool_operation_configs(action_label: str):
    from autoteam.mail_provider import get_mail_provider_name, get_mail_provider_required_keys
    from autoteam.sync_targets import get_enabled_sync_targets

    env = _current_runtime_env()
    provider = get_mail_provider_name(env)
    _require_runtime_configs(get_mail_provider_required_keys(provider), action_label, env=env)

    enabled_targets = get_enabled_sync_targets(env)
    if not enabled_targets:
        raise HTTPException(
            status_code=400, detail=f"{action_label} 前请先在配置面板启用至少一个远端同步目标（CPA 或 Sub2API）"
        )

    missing = _missing_runtime_configs(
        [
            key
            for target in enabled_targets
            for key in (
                _CPA_REQUIRED_KEYS if target == "cpa" else _SUB2API_REQUIRED_KEYS if target == "sub2api" else ()
            )
        ],
        env=env,
    )
    if missing:
        detail = _format_missing_runtime_configs(missing)
        raise HTTPException(status_code=400, detail=f"{action_label} 前请先在配置面板填写：{detail}")


def _require_account_mail_configs(account: dict, action_label: str):
    from autoteam.mail_provider import get_account_mail_provider, get_mail_provider_required_keys

    provider = get_account_mail_provider(account)
    _require_runtime_configs(get_mail_provider_required_keys(provider), action_label, env=_current_runtime_env())


def _require_cpa_configs(action_label: str):
    _require_runtime_configs(_CPA_REQUIRED_KEYS, action_label)


def _require_sub2api_configs(action_label: str):
    _require_runtime_configs(_SUB2API_REQUIRED_KEYS, action_label)


def _require_sync_target_configs(action_label: str):
    from autoteam.sync_targets import get_enabled_sync_targets

    env = _current_runtime_env()
    enabled_targets = get_enabled_sync_targets(env)
    if not enabled_targets:
        raise HTTPException(
            status_code=400, detail=f"{action_label} 前请先在配置面板启用至少一个远端同步目标（CPA 或 Sub2API）"
        )

    missing = _missing_runtime_configs(
        [
            key
            for target in enabled_targets
            for key in (
                _CPA_REQUIRED_KEYS if target == "cpa" else _SUB2API_REQUIRED_KEYS if target == "sub2api" else ()
            )
        ],
        env=env,
    )
    if missing:
        detail = _format_missing_runtime_configs(missing)
        raise HTTPException(status_code=400, detail=f"{action_label} 前请先在配置面板填写：{detail}")


def _collect_config_fields(*, include_values: bool = False, configs=None):
    from autoteam.mail_provider import get_mail_provider_name
    from autoteam.setup_wizard import REQUIRED_CONFIGS, _read_env

    env = _read_env()
    merged_env = dict(os.environ)
    merged_env.update(env)
    target_states = _effective_sync_target_states(merged_env)
    runtime_required_keys = _runtime_required_keys(merged_env)
    mail_provider = get_mail_provider_name(merged_env)
    config_items = configs or REQUIRED_CONFIGS
    fields = []
    all_ok = True
    for key, prompt, default, optional in config_items:
        raw_value = env.get(key, "") or os.environ.get(key, "")
        if key == "SYNC_TARGET_CPA":
            raw_value = "true" if target_states.get("cpa") else "false"
            configured = True
        elif key == "SYNC_TARGET_SUB2API":
            raw_value = "true" if target_states.get("sub2api") else "false"
            configured = True
        elif key == "PLAYWRIGHT_BROWSER_MODE":
            raw_value = _normalize_playwright_browser_mode(raw_value, merged_env.get("PLAYWRIGHT_HEADLESS", ""))
            configured = True
        elif key == "PLAYWRIGHT_HEADLESS":
            raw_value = (
                "false"
                if _normalize_playwright_browser_mode(merged_env.get("PLAYWRIGHT_BROWSER_MODE", ""), raw_value)
                == "visible"
                else "true"
            )
            configured = True
        elif key == "MAIL_PROVIDER":
            raw_value = mail_provider
            configured = True
        else:
            configured = bool(raw_value)
        if not configured and (key in runtime_required_keys or not optional):
            all_ok = False

        field = {
            "key": key,
            "prompt": prompt,
            "default": default,
            "optional": optional,
            "configured": configured,
        }
        if include_values:
            field["value"] = raw_value if raw_value != "" else default
            field["runtime_required"] = key in runtime_required_keys
        fields.append(field)
    return {"configured": all_ok, "fields": fields}


def _reload_runtime_config_modules():
    import importlib

    import autoteam.config

    modules = [autoteam.config]
    for module_name in (
        "autoteam.cloudmail",
        "autoteam.cloudflare_temp_email",
        "autoteam.mo_email",
        "autoteam.mail_provider",
        "autoteam.cpa_sync",
        "autoteam.sub2api_sync",
        "autoteam.outbound_proxy",
    ):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        modules.append(module)

    for module in modules:
        importlib.reload(module)


def _restore_runtime_env(previous_env: dict[str, str | None]):
    for key, previous in previous_env.items():
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _runtime_env_file_signature():
    from autoteam.setup_wizard import ENV_FILE

    if not ENV_FILE.exists():
        return None
    stat = ENV_FILE.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _read_runtime_env_file_text():
    from autoteam.setup_wizard import ENV_FILE

    if not ENV_FILE.exists():
        return ""
    return read_text(ENV_FILE)


def _read_runtime_source_text():
    from autoteam.setup_wizard import ENV_EXAMPLE, ENV_FILE

    if ENV_FILE.exists():
        return read_text(ENV_FILE), str(ENV_FILE)
    if ENV_EXAMPLE.exists():
        return read_text(ENV_EXAMPLE), str(ENV_FILE)
    return "", str(ENV_FILE)


def _write_runtime_source_text(content: str):
    from autoteam.setup_wizard import ENV_FILE

    write_text(ENV_FILE, content)


def _restore_runtime_source_text(previous_exists: bool, previous_content: str):
    from autoteam.setup_wizard import ENV_FILE

    if previous_exists:
        write_text(ENV_FILE, previous_content)
        return
    if ENV_FILE.exists():
        ENV_FILE.unlink()


def _load_env_values_from_source(content: str, env_keys: list[str]):
    values = {key: "" for key in env_keys}
    for line in content.splitlines():
        parsed = parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        if key in values:
            values[key] = value
    return values


def _load_present_env_values_from_source(content: str, env_keys: list[str]):
    allowed = set(env_keys)
    values = {}
    for line in content.splitlines():
        parsed = parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        if key in allowed:
            values[key] = value
    return values


def _validate_runtime_required_values(values: dict[str, str]):
    from autoteam.setup_wizard import STARTUP_REQUIRED_CONFIGS

    return [
        f"{key} ({prompt})"
        for key, prompt, _default, optional in STARTUP_REQUIRED_CONFIGS
        if not optional and not values.get(key)
    ]


def _sync_runtime_globals():
    global API_KEY

    API_KEY = os.environ.get("API_KEY", "")

    auto_check_config = globals().get("_auto_check_config")
    auto_check_restart = globals().get("_auto_check_restart")
    if auto_check_config is None:
        return

    try:
        from autoteam.config import AUTO_CHECK_INTERVAL, AUTO_CHECK_MIN_LOW, AUTO_CHECK_THRESHOLD, TEAM_TARGET_SEATS

        auto_check_config["interval"] = AUTO_CHECK_INTERVAL
        auto_check_config["threshold"] = AUTO_CHECK_THRESHOLD
        auto_check_config["min_low"] = AUTO_CHECK_MIN_LOW
        auto_check_config["target_seats"] = TEAM_TARGET_SEATS
        if auto_check_restart is not None:
            auto_check_restart.set()
    except Exception:
        pass


def _normalize_playwright_browser_mode(value: str | None, headless: str | None = None) -> str:
    mode = (value or "").strip().lower()
    if mode in {"hidden", "visible", "embedded"}:
        return mode
    if (headless or "").strip().lower() in {"0", "false", "no", "n", "off"}:
        return "visible"
    return "hidden"


def _apply_playwright_browser_mode(values: dict[str, str]):
    mode = _normalize_playwright_browser_mode(values.get("PLAYWRIGHT_BROWSER_MODE"), values.get("PLAYWRIGHT_HEADLESS"))
    values["PLAYWRIGHT_BROWSER_MODE"] = mode
    values["PLAYWRIGHT_HEADLESS"] = "false" if mode == "visible" else "true"


def _apply_runtime_env_file_values(values: dict[str, str]):
    _apply_playwright_browser_mode(values)
    for key in _ALL_RUNTIME_ENV_KEYS:
        if key in values:
            value = values[key]
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
            continue

        base_value = _RUNTIME_ENV_BASE.get(key)
        if base_value:
            os.environ[key] = base_value
        else:
            os.environ.pop(key, None)


def _sync_runtime_env_reload_state():
    with _runtime_env_reload_lock:
        _runtime_env_reload_state["signature"] = _runtime_env_file_signature()


def _maybe_reload_runtime_config_from_env_file(*, force: bool = False):
    signature = _runtime_env_file_signature()

    with _runtime_env_reload_lock:
        previous_signature = _runtime_env_reload_state.get("signature")
        if not force and signature == previous_signature:
            return False

        previous_env = {key: os.environ.get(key) for key in _ALL_RUNTIME_ENV_KEYS}
        try:
            content = _read_runtime_env_file_text()
            values = _load_present_env_values_from_source(content, _ALL_RUNTIME_ENV_KEYS)
            _apply_runtime_env_file_values(values)
            _reload_runtime_config_modules()
            _sync_runtime_globals()
            _runtime_env_reload_state["signature"] = signature
        except Exception:
            _restore_runtime_env(previous_env)
            _reload_runtime_config_modules()
            _sync_runtime_globals()
            raise

    if previous_signature is not None and signature != previous_signature:
        logger.info("[配置] 检测到 .env 变更，已自动热加载")
    return True


def _changed_runtime_keys(previous_env: dict[str, str | None], current_values: dict[str, str]) -> set[str]:
    changed = set()
    for key, value in current_values.items():
        if (previous_env.get(key) or "") != (value or ""):
            changed.add(key)
    return changed


def _should_verify_runtime_keys(changed_keys: set[str] | None, keys: tuple[str, ...] | set[str]) -> bool:
    return changed_keys is None or bool(changed_keys.intersection(keys))


def _verify_runtime_integrations(
    previous_env: dict[str, str | None] | None = None,
    changed_keys: set[str] | None = None,
):
    from autoteam.mail_provider import get_mail_provider_name, get_mail_provider_prompt, get_mail_provider_required_keys
    from autoteam.setup_wizard import _verify_cpa, _verify_mail_provider, _verify_sub2api

    errors = []
    mail_provider = get_mail_provider_name()
    mail_keys = tuple(get_mail_provider_required_keys(mail_provider))
    mail_verify_keys = {"MAIL_PROVIDER", *mail_keys}

    mail_values = [os.environ.get(key, "") for key in mail_keys]
    cpa_values = [os.environ.get(key, "") for key in _CPA_REQUIRED_KEYS]
    sub2api_values = [os.environ.get(key, "") for key in _SUB2API_REQUIRED_KEYS]
    sync_states = _effective_sync_target_states()

    if (
        _should_verify_runtime_keys(changed_keys, mail_verify_keys)
        and mail_keys
        and all(mail_values)
        and not _verify_mail_provider(mail_provider)
    ):
        errors.append(f"{get_mail_provider_prompt(mail_provider)} 连接失败")
    if (
        _should_verify_runtime_keys(changed_keys, _CPA_VERIFY_KEYS)
        and sync_states.get("cpa")
        and all(cpa_values)
        and not _verify_cpa()
    ):
        errors.append("CPA 连接失败")
    if (
        _should_verify_runtime_keys(changed_keys, _SUB2API_VERIFY_KEYS)
        and sync_states.get("sub2api")
        and all(sub2api_values)
        and not _verify_sub2api()
    ):
        errors.append("Sub2API 连接失败")
    if errors:
        api_key = ""
        if previous_env:
            api_key = previous_env.get("API_KEY", "") or ""
        return JSONResponse(status_code=400, content={"message": "、".join(errors), "api_key": api_key})
    return None


def _save_runtime_config(data: dict[str, str]):
    """保存运行时配置到 .env，并在当前进程立即生效。"""
    import secrets as _secrets

    from autoteam.mail_provider import normalize_mail_provider
    from autoteam.setup_wizard import REQUIRED_CONFIGS, _write_env

    env_keys = [key for key, _prompt, _default, _optional in REQUIRED_CONFIGS]
    existing = {key: os.environ.get(key, "") for key in env_keys}
    merged = {key: data.get(key, existing.get(key, "")) for key in env_keys}
    merged["MAIL_PROVIDER"] = normalize_mail_provider(merged.get("MAIL_PROVIDER") or existing.get("MAIL_PROVIDER"))
    _apply_playwright_browser_mode(merged)

    if not merged.get("API_KEY"):
        merged["API_KEY"] = _secrets.token_urlsafe(24)

    missing = _validate_runtime_required_values(merged)
    if missing:
        return JSONResponse(
            status_code=400,
            content={"message": "缺少必填项: " + "、".join(missing)},
        )

    previous_env = {key: os.environ.get(key) for key in env_keys}
    changed_keys = _changed_runtime_keys(previous_env, merged)
    try:
        for key, value in merged.items():
            os.environ[key] = value
        _reload_runtime_config_modules()

        verify_result = _verify_runtime_integrations(previous_env, changed_keys)
        if verify_result:
            _restore_runtime_env(previous_env)
            _reload_runtime_config_modules()
            return verify_result

        for key, value in merged.items():
            if value or key in _RUNTIME_CONFIG_CLEARABLE_FIELDS:
                _write_env(key, value)

        _sync_runtime_env_reload_state()
        _sync_runtime_globals()
        return {"message": "配置保存成功", "api_key": API_KEY, "configured": True}
    except Exception:
        _restore_runtime_env(previous_env)
        _reload_runtime_config_modules()
        raise


@app.get("/api/setup/status")
def get_setup_status():
    """检查配置是否完整"""
    from autoteam.setup_wizard import STARTUP_REQUIRED_CONFIGS

    return _collect_config_fields(configs=STARTUP_REQUIRED_CONFIGS)


@app.post("/api/setup/save")
def post_setup_save(config: SetupConfig):
    """保存配置到 .env 并验证连通性"""
    return _save_runtime_config(config.model_dump())


@app.get("/api/config/runtime")
def get_runtime_config():
    """获取当前运行时配置，供登录后的设置面板编辑。"""
    return _collect_config_fields(include_values=True)


@app.get("/api/config/source")
def get_runtime_config_source():
    """获取 .env 源文件内容。"""
    content, path = _read_runtime_source_text()
    return {"path": path, "content": content}


@app.get("/api/mail/mo-email/domains")
def get_mo_email_domains():
    """读取 Mo Email 当前可用邮箱域名。"""
    from autoteam.mo_email import MoEmailClient

    client = MoEmailClient()
    domains, payload = client._available_domains()
    return {"domains": domains, "config": payload}


@app.put("/api/config/runtime")
def put_runtime_config(config: SetupConfig):
    """登录后修改 CloudMail / CPA / Sub2API / 代理等运行时配置。"""
    return _save_runtime_config(config.model_dump())


@app.put("/api/config/source")
def put_runtime_config_source(config: SourceConfig):
    """保存 .env 源文件内容，并立即应用到运行时。"""
    env_keys = list(_ALL_RUNTIME_ENV_KEYS)
    previous_env = {key: os.environ.get(key) for key in env_keys}
    source_path = None
    previous_exists = False
    previous_content = ""

    try:
        current_content, source_path = _read_runtime_source_text()
        previous_content = current_content
        from autoteam.setup_wizard import ENV_FILE

        previous_exists = ENV_FILE.exists()

        _write_runtime_source_text(config.content)

        loaded_values = _load_env_values_from_source(config.content, env_keys)
        _apply_playwright_browser_mode(loaded_values)
        missing = _validate_runtime_required_values(loaded_values)
        if missing:
            _restore_runtime_source_text(previous_exists, previous_content)
            _restore_runtime_env(previous_env)
            _reload_runtime_config_modules()
            return JSONResponse(status_code=400, content={"message": "缺少必填项: " + "、".join(missing)})

        for key in env_keys:
            if loaded_values.get(key):
                os.environ[key] = loaded_values[key]
            else:
                os.environ.pop(key, None)

        _reload_runtime_config_modules()
        current_values = {key: os.environ.get(key, "") for key in env_keys}
        changed_keys = _changed_runtime_keys(previous_env, current_values)
        verify_result = _verify_runtime_integrations(previous_env, changed_keys)
        if verify_result:
            _restore_runtime_source_text(previous_exists, previous_content)
            _restore_runtime_env(previous_env)
            _reload_runtime_config_modules()
            return verify_result

        _sync_runtime_env_reload_state()
        _sync_runtime_globals()
        return {
            "message": "源文件保存成功",
            "api_key": API_KEY,
            "configured": True,
            "path": source_path,
        }
    except Exception:
        _restore_runtime_source_text(previous_exists, previous_content)
        _restore_runtime_env(previous_env)
        _reload_runtime_config_modules()
        raise


# ---------------------------------------------------------------------------
# 后台任务管理
# ---------------------------------------------------------------------------

_tasks: dict[str, dict] = {}
_task_threads: dict[str, threading.Thread] = {}
_playwright_lock = threading.Lock()
_current_task_id: str | None = None
_admin_login_api = None
_admin_login_step: str | None = None
_main_codex_flow = None
_main_codex_step: str | None = None
_main_codex_action: str | None = None
_manual_account_flow = None
MAX_TASK_HISTORY = 50


# ---------------------------------------------------------------------------
# Playwright 专用线程执行器（解决跨线程调用问题）
# ---------------------------------------------------------------------------

import queue as _queue


class _PlaywrightExecutor:
    """将 Playwright 操作派发到专用线程执行，避免跨线程错误"""

    def __init__(self):
        self._queue: _queue.Queue = _queue.Queue()
        self._thread: threading.Thread | None = None

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            func, args, kwargs, result_event, result_holder = item
            try:
                result_holder["result"] = func(*args, **kwargs)
            except Exception as e:
                result_holder["error"] = e
            finally:
                result_event.set()

    def ensure_started(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def run(self, func, *args, **kwargs):
        """在专用线程中执行函数，阻塞等待结果"""
        self.ensure_started()
        result_event = threading.Event()
        result_holder: dict = {}
        self._queue.put((func, args, kwargs, result_event, result_holder))
        result_event.wait(timeout=300)  # 最长等 5 分钟
        if "error" in result_holder:
            raise result_holder["error"]
        return result_holder.get("result")

    def stop(self):
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=5)
            self._thread = None


_pw_executor = _PlaywrightExecutor()


def _stop_playwright_resource(resource):
    if not resource:
        return

    stop = getattr(resource, "stop", None)
    if not callable(stop):
        return

    try:
        stop()
    except Exception:
        pass


def _run_playwright_start(factory, starter, *args, **kwargs):
    resource = factory()
    try:
        result = starter(resource, *args, **kwargs)
        return resource, result
    except Exception:
        _stop_playwright_resource(resource)
        raise


def _run_with_chatgpt_session(callback):
    from autoteam.chatgpt_api import ChatGPTTeamAPI

    chatgpt = ChatGPTTeamAPI()
    try:
        chatgpt.start()
        return callback(chatgpt)
    finally:
        chatgpt.stop()


def _team_remover_factory(remove_from_team):
    def _team_remover(email: str, _acc: dict | None = None):
        return _run_with_chatgpt_session(lambda chatgpt: remove_from_team(chatgpt, email, return_status=True))

    return _team_remover


def _current_busy_detail(default_message: str):
    if _admin_login_api:
        return {
            "message": default_message,
            "running_task": {
                "task_id": "admin-login",
                "command": "admin-login",
                "started_at": None,
            },
        }

    if _main_codex_flow:
        return {
            "message": default_message,
            "running_task": {
                "task_id": "main-codex-sync",
                "command": "main-codex-sync",
                "started_at": None,
            },
        }

    running = _tasks.get(_current_task_id, {})
    return {
        "message": default_message,
        "running_task": {
            "task_id": _current_task_id,
            "command": running.get("command", "unknown"),
            "started_at": running.get("started_at"),
        },
    }


def _prune_tasks():
    """保留最近 MAX_TASK_HISTORY 个任务"""
    if len(_tasks) <= MAX_TASK_HISTORY:
        return
    sorted_ids = sorted(_tasks, key=lambda k: _tasks[k]["created_at"])
    for tid in sorted_ids[: len(_tasks) - MAX_TASK_HISTORY]:
        if _tasks[tid]["status"] in ("completed", "failed", "stopped"):
            del _tasks[tid]
            _task_threads.pop(tid, None)


def _mark_task_stopped(task: dict, reason: str):
    task["stop_requested"] = True
    task["status"] = "stopped"
    task["error"] = reason
    task["finished_at"] = time.time()


def _raise_thread_exit(thread: threading.Thread) -> str:
    """Best-effort stop for a worker thread used only by the force-stop API."""
    if not thread.is_alive():
        return "not_running"
    if thread.ident is None:
        return "missing_ident"

    import ctypes

    result = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread.ident),
        ctypes.py_object(SystemExit),
    )
    if result == 0:
        return "not_found"
    if result > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident), None)
        return "failed"
    return "requested"


def _stop_resource_direct(resource, timeout: float = 2.0) -> str:
    stop = getattr(resource, "stop", None)
    if not callable(stop):
        return "not_supported"

    done = threading.Event()
    result = {"status": "stopped"}

    def _worker():
        try:
            stop()
        except Exception as exc:
            result["status"] = f"error: {exc}"
        finally:
            done.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    if not done.wait(timeout):
        return "timeout"
    return result["status"]


def _stop_pending_flows(reason: str):
    global _admin_login_api, _admin_login_step, _main_codex_flow, _main_codex_step, _main_codex_action
    global _manual_account_flow

    stopped = []
    if _admin_login_api:
        stopped.append({"name": "admin-login", "stop": _stop_resource_direct(_admin_login_api)})
        _admin_login_api = None
        _admin_login_step = None

    if _main_codex_flow:
        stopped.append({"name": "main-codex", "stop": _stop_resource_direct(_main_codex_flow)})
        _main_codex_flow = None
        _main_codex_step = None
        _main_codex_action = None

    if _manual_account_flow:
        stopped.append({"name": "manual-account", "stop": _stop_resource_direct(_manual_account_flow)})
        _manual_account_flow = None

    if stopped and _playwright_lock.locked() and _current_task_id is None:
        try:
            _playwright_lock.release()
        except RuntimeError:
            pass

    if stopped:
        logger.warning("[API] 已强制停止等待中的流程: %s", reason)
    return stopped


def _request_stop_all_tasks(reason: str):
    stopped = []
    for task_id, task in list(_tasks.items()):
        if task.get("status") not in ("pending", "running"):
            continue

        _mark_task_stopped(task, reason)
        thread = _task_threads.get(task_id)
        thread_stop = "not_started"
        if thread:
            thread_stop = _raise_thread_exit(thread)
            thread.join(timeout=1)
        stopped.append(
            {
                "task_id": task_id,
                "command": task.get("command"),
                "thread_stop": thread_stop,
                "thread_alive": bool(thread and thread.is_alive()),
            }
        )

    return stopped


def _run_task(task_id: str, func, *args, **kwargs):
    """在后台线程中执行任务"""
    global _current_task_id
    task = _tasks[task_id]

    _playwright_lock.acquire()
    _current_task_id = task_id
    if task.get("stop_requested"):
        task["finished_at"] = time.time()
        _current_task_id = None
        _task_threads.pop(task_id, None)
        _playwright_lock.release()
        return
    task["status"] = "running"
    task["started_at"] = time.time()

    try:
        with outbound_proxy.task_proxy_context() as proxy_url:
            task["proxy_url"] = proxy_url or "direct"
            logger.info("[API] 任务 %s 使用出口代理: %s", task_id[:8], proxy_url or "direct")
            result = func(*args, **kwargs)
        if task.get("stop_requested"):
            _mark_task_stopped(task, task.get("error") or "任务已停止")
        else:
            task["status"] = "completed"
            task["result"] = result
    except Exception as e:
        if task.get("stop_requested"):
            _mark_task_stopped(task, task.get("error") or "任务已停止")
        else:
            task["status"] = "failed"
            task["error"] = str(e)
            logger.error("[API] 任务 %s 失败: %s", task_id[:8], e)
    except BaseException as e:
        if task.get("stop_requested"):
            _mark_task_stopped(task, task.get("error") or "任务已停止")
        else:
            task["status"] = "failed"
            task["error"] = str(e) or e.__class__.__name__
            logger.error("[API] 任务 %s 异常退出: %s", task_id[:8], task["error"])
    finally:
        if task.get("status") in ("stopped", "failed", "completed") and not task.get("finished_at"):
            task["finished_at"] = time.time()
        if _current_task_id == task_id:
            _current_task_id = None
        _task_threads.pop(task_id, None)
        if _playwright_lock.locked():
            _playwright_lock.release()


def _start_task(command: str, func, params: dict, *args, **kwargs) -> dict:
    """创建并启动后台任务，返回任务信息"""
    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再试"))
    _playwright_lock.release()

    task_id = uuid.uuid4().hex[:12]
    task = {
        "task_id": task_id,
        "command": command,
        "params": params,
        "status": "pending",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    _tasks[task_id] = task
    _prune_tasks()

    thread = threading.Thread(target=_run_task, args=(task_id, func, *args), kwargs=kwargs, daemon=True)
    _task_threads[task_id] = thread
    thread.start()

    return task


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class TaskParams(BaseModel):
    target: int | None = None
    parallel_workers: int | None = None


class CpaBatchParams(BaseModel):
    join_mode: str = "direct"
    target: int | None = None
    batch_size: int | None = None
    parallel_workers: int | None = None


class CleanupParams(BaseModel):
    max_seats: int | None = None


def _resolve_parallel_workers_param(value: int | None) -> int:
    from autoteam.config import BROWSER_PARALLEL_WORKERS

    resolved = BROWSER_PARALLEL_WORKERS if value is None else value
    try:
        resolved = int(resolved)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="parallel_workers 必须是 1 到 3") from exc
    if resolved < 1 or resolved > 3:
        raise HTTPException(status_code=400, detail="parallel_workers 必须是 1 到 3")
    return resolved


class AdminEmailParams(BaseModel):
    email: str


class AdminSessionParams(BaseModel):
    email: str
    session_token: str


class AdminPasswordParams(BaseModel):
    password: str


class AdminCodeParams(BaseModel):
    code: str


class AdminWorkspaceParams(BaseModel):
    option_id: str


class ManualAccountCallbackParams(BaseModel):
    redirect_url: str


class TeamMemberRemoveParams(BaseModel):
    email: str
    user_id: str
    type: str


class SellAccountParams(BaseModel):
    note: str | None = None


class UsageStatusParams(BaseModel):
    usage_status: str


class UnusableDirParams(BaseModel):
    directory: str = "auths/unusable/account_deactivated"


class DeactivatedMailCheckParams(BaseModel):
    keyword: str = "deactivated"
    size: int = 30
    directory: str | None = None
    apply: bool = False
    release_team: bool = True
    dispose_mailbox: bool = True


class AuthMetadataMigrationParams(BaseModel):
    apply: bool = False


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _is_main_account_email(email: str | None) -> bool:
    from autoteam.admin_state import get_admin_email

    return bool(_normalized_email(email)) and _normalized_email(email) == _normalized_email(get_admin_email())


def _quota_snapshot_status(quota_info: dict | None) -> str:
    if not isinstance(quota_info, dict):
        return ""

    values = []
    for key in ("primary_pct", "weekly_pct"):
        value = quota_info.get(key)
        if isinstance(value, (int, float)):
            values.append(value)

    if not values:
        return ""
    return "exhausted" if any(value >= 100 for value in values) else "active"


def _resolve_status_auth_file(acc: dict) -> str:
    for key in ("rt_auth_file", "auth_file", "session_auth_file"):
        auth_file = (acc.get(key) or "").strip()
        if auth_file and Path(auth_file).exists():
            return auth_file

    if _is_main_account_email(acc.get("email")):
        from autoteam.codex_auth import get_saved_main_auth_file

        saved_auth_file = get_saved_main_auth_file()
        if saved_auth_file and Path(saved_auth_file).exists():
            return saved_auth_file

    return ""


def _display_account_status(acc: dict, quota_snapshot: dict | None = None) -> str:
    status = acc.get("status", "")
    if not _is_main_account_email(acc.get("email")):
        return status

    quota_status = _quota_snapshot_status(quota_snapshot) or _quota_snapshot_status(acc.get("last_quota"))
    if quota_status:
        return quota_status

    return "active" if _resolve_status_auth_file(acc) else status


def _sanitize_account(acc: dict, quota_snapshot: dict | None = None) -> dict:
    """脱敏账号信息（去掉 password 等敏感字段）"""
    sanitized = {k: v for k, v in acc.items() if k not in ("password", "cloudmail_account_id", "mail_account_id")}
    sanitized["is_main_account"] = _is_main_account_email(acc.get("email"))
    sanitized["status"] = _display_account_status(acc, quota_snapshot)
    return sanitized


def _existing_auth_names_for_account(acc: dict) -> list[str]:
    names = []
    for key in ("auth_file", "rt_auth_file", "session_auth_file"):
        value = acc.get(key) or ""
        if not value:
            continue
        name = Path(value).name
        if name and name not in names:
            names.append(name)
    return names


def _admin_status():
    from autoteam.admin_state import get_admin_state_summary

    status = get_admin_state_summary()
    status["login_step"] = _admin_login_step
    status["login_in_progress"] = _admin_login_api is not None
    if _admin_login_api and _admin_login_step == "workspace_required":
        status["workspace_options"] = getattr(_admin_login_api, "workspace_options_cache", []) or []
    else:
        status["workspace_options"] = []
    return status


def _main_codex_status():
    return {
        "in_progress": _main_codex_flow is not None,
        "step": _main_codex_step,
        "action": _main_codex_action,
    }


def _manual_account_status():
    status = {
        "in_progress": False,
        "status": "idle",
        "state": "",
        "auth_url": "",
        "started_at": None,
        "message": "",
        "error": "",
        "account": None,
        "callback_received": False,
        "callback_source": "",
        "auto_callback_available": False,
        "auto_callback_error": "",
    }
    if _manual_account_flow:
        status.update(_manual_account_flow.status())
    return status


def _finish_admin_login(completed: dict):
    global _admin_login_api, _admin_login_step
    api = _admin_login_api
    info = None
    try:
        info = _pw_executor.run(api.complete_admin_login)
    finally:
        if api:
            try:
                _pw_executor.run(api.stop)
            except Exception:
                pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
    return {"status": "completed", "admin": _admin_status(), "codex": _main_codex_status(), "info": info}


def _set_pending_admin_login(api, step):
    global _admin_login_api, _admin_login_step
    _admin_login_api = api
    _admin_login_step = step
    return {"status": step, "admin": _admin_status()}


def _finish_main_codex_flow():
    global _main_codex_flow, _main_codex_step, _main_codex_action
    flow = _main_codex_flow
    action = _main_codex_action or "sync"
    try:
        info = _pw_executor.run(flow.complete)
    finally:
        if flow:
            try:
                _pw_executor.run(flow.stop)
            except Exception:
                pass
        _main_codex_flow = None
        _main_codex_step = None
        _main_codex_action = None
        if _playwright_lock.locked():
            _playwright_lock.release()

    message = "主号 Codex 已同步到已启用远端" if action == "sync" else "主号 Codex 已登录"
    return {
        "status": "completed",
        "message": message,
        "codex": _main_codex_status(),
        "info": info,
    }


def _set_pending_main_codex_flow(flow, step, action):
    global _main_codex_flow, _main_codex_step, _main_codex_action
    _main_codex_flow = flow
    _main_codex_step = step
    _main_codex_action = action
    return {"status": step, "codex": _main_codex_status()}


def _start_main_codex_flow(action="sync"):
    from autoteam.codex_auth import MainCodexLoginFlow, MainCodexSyncFlow

    flow_cls = MainCodexSyncFlow if action == "sync" else MainCodexLoginFlow

    def _do_start():
        return _run_playwright_start(flow_cls, lambda flow: flow.start())

    flow, result = _pw_executor.run(_do_start)
    step = result["step"]
    if step == "completed":
        _set_pending_main_codex_flow(flow, step, action)
        return step, _finish_main_codex_flow()
    if step in ("password_required", "code_required"):
        return step, _set_pending_main_codex_flow(flow, step, action)

    _pw_executor.run(flow.stop)
    raise RuntimeError(result.get("detail") or "无法识别主号 Codex 登录步骤")


def _finish_manual_account_flow(result: dict):
    return {**result, "manual_account": _manual_account_status()}


def _set_pending_manual_account_flow(flow, result):
    global _manual_account_flow
    _manual_account_flow = flow
    return {**result, "manual_account": _manual_account_status()}


# ---------------------------------------------------------------------------
# 同步端点
# ---------------------------------------------------------------------------


@app.get("/api/admin/status")
def get_admin_status():
    """获取管理员登录状态。"""
    return _admin_status()


@app.get("/api/main-codex/status")
def get_main_codex_status():
    """获取主号 Codex 同步状态。"""
    return _main_codex_status()


@app.get("/api/manual-account/status")
def get_manual_account_status():
    """获取手动添加账号状态。"""
    return _manual_account_status()


@app.post("/api/admin/login/start")
def post_admin_login_start(params: AdminEmailParams):
    """开始管理员登录流程。"""
    global _admin_login_api, _admin_login_step

    if _admin_login_api:
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再进行管理员登录")
        )

    try:
        from autoteam.chatgpt_api import ChatGPTTeamAPI

        logger.info("[API] 开始管理员登录: %s", params.email.strip())

        def _do_start(email):
            return _run_playwright_start(
                ChatGPTTeamAPI, lambda api, login_email: api.begin_admin_login(login_email), email
            )

        api, result = _pw_executor.run(_do_start, params.email.strip())
        step = result["step"]
        logger.info("[API] 管理员登录 start 返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            _admin_login_api = api
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            return _set_pending_admin_login(api, step)
        _pw_executor.run(api.stop)
        _playwright_lock.release()
        raise HTTPException(status_code=400, detail=result.get("detail") or "无法识别管理员登录步骤")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员登录 start 失败")
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/session")
def post_admin_login_session(params: AdminSessionParams):
    """手动导入管理员 session_token。"""
    global _admin_login_api, _admin_login_step

    if _admin_login_api:
        post_admin_login_cancel()

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail=_current_busy_detail("有任务正在执行，请等待完成后再导入管理员 session_token"),
        )

    try:
        from autoteam.chatgpt_api import ChatGPTTeamAPI

        logger.info("[API] 导入管理员 session_token: %s", params.email.strip())

        def _do_import(email, session_token):
            api = ChatGPTTeamAPI()
            try:
                return api.import_admin_session(email, session_token)
            finally:
                api.stop()

        info = _pw_executor.run(_do_import, params.email.strip(), params.session_token.strip())
        _admin_login_api = None
        _admin_login_step = None
        return {"status": "completed", "admin": _admin_status(), "codex": _main_codex_status(), "info": info}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 导入管理员 session_token 失败")
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if _playwright_lock.locked():
            _playwright_lock.release()


@app.post("/api/admin/login/password")
def post_admin_login_password(params: AdminPasswordParams):
    """提交管理员密码。"""
    global _admin_login_api, _admin_login_step
    if not _admin_login_api or _admin_login_step != "password_required":
        raise HTTPException(status_code=409, detail="当前没有等待密码的管理员登录流程")

    try:
        logger.info("[API] 提交管理员密码 | current_step=%s", _admin_login_step)
        result = _pw_executor.run(_admin_login_api.submit_admin_password, params.password)
        step = result["step"]
        logger.info("[API] 管理员密码提交返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            _admin_login_step = step
            return {"status": step, "admin": _admin_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "管理员密码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员密码提交失败")
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/code")
def post_admin_login_code(params: AdminCodeParams):
    """提交管理员验证码。"""
    global _admin_login_api, _admin_login_step
    if not _admin_login_api or _admin_login_step != "code_required":
        raise HTTPException(status_code=409, detail="当前没有等待验证码的管理员登录流程")

    try:
        logger.info("[API] 提交管理员验证码 | current_step=%s code_len=%d", _admin_login_step, len(params.code.strip()))
        result = _pw_executor.run(_admin_login_api.submit_admin_code, params.code.strip())
        step = result["step"]
        logger.info("[API] 管理员验证码提交返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            _admin_login_step = step
            return {"status": step, "admin": _admin_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "管理员验证码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员验证码提交失败")
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/workspace")
def post_admin_login_workspace(params: AdminWorkspaceParams):
    """提交管理员 workspace 选择。"""
    global _admin_login_api, _admin_login_step
    if not _admin_login_api or _admin_login_step != "workspace_required":
        raise HTTPException(status_code=409, detail="当前没有等待组织选择的管理员登录流程")

    try:
        logger.info("[API] 提交管理员 workspace 选择 | option_id=%s", params.option_id)
        result = _pw_executor.run(_admin_login_api.select_workspace_option, params.option_id)
        step = result["step"]
        logger.info("[API] 管理员 workspace 选择返回: step=%s detail=%s", step, result.get("detail"))
        if step == "completed":
            return _finish_admin_login(result)
        if step in ("password_required", "code_required", "workspace_required"):
            _admin_login_step = step
            return {"status": step, "admin": _admin_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "管理员组织选择失败")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[API] 管理员 workspace 选择失败")
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/login/cancel")
def post_admin_login_cancel():
    """取消管理员登录流程。"""
    global _admin_login_api, _admin_login_step
    if _admin_login_api:
        try:
            _pw_executor.run(_admin_login_api.stop)
        except Exception:
            pass
        _admin_login_api = None
        _admin_login_step = None
        if _playwright_lock.locked():
            _playwright_lock.release()
    return {"message": "管理员登录已取消", "admin": _admin_status()}


@app.post("/api/admin/logout")
def post_admin_logout():
    """清除已保存的管理员登录态。"""
    from autoteam.admin_state import clear_admin_state

    if _admin_login_api:
        post_admin_login_cancel()
    clear_admin_state()
    return {"message": "管理员登录态已清除", "admin": _admin_status()}


@app.post("/api/main-codex/start")
def post_main_codex_start():
    """开始主号 Codex 登录并同步到已启用远端。"""
    global _main_codex_flow, _main_codex_step, _main_codex_action

    if _main_codex_flow:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        _main_codex_action = None
        if _playwright_lock.locked():
            _playwright_lock.release()

    _require_sync_target_configs("同步主号 Codex")

    from autoteam.codex_auth import get_saved_main_auth_file
    from autoteam.sync_targets import sync_main_codex_to_configured_targets

    saved_auth_file = get_saved_main_auth_file()
    if saved_auth_file:
        sync_main_codex_to_configured_targets(saved_auth_file)
        return {
            "status": "completed",
            "message": "主号 Codex 已同步到已启用远端",
            "codex": _main_codex_status(),
            "info": {"auth_file": saved_auth_file},
        }

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再同步主号 Codex")
        )

    try:
        _step, result = _start_main_codex_flow(action="sync")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/main-codex/login")
def post_main_codex_login():
    """开始主号 Codex 登录，仅保存本地认证文件。"""
    global _main_codex_flow, _main_codex_step, _main_codex_action

    if _main_codex_flow:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        _main_codex_action = None
        if _playwright_lock.locked():
            _playwright_lock.release()

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再登录主号 Codex")
        )

    try:
        _step, result = _start_main_codex_flow(action="login")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/main-codex/password")
def post_main_codex_password(params: AdminPasswordParams):
    """提交主号 Codex 登录密码。"""
    global _main_codex_flow, _main_codex_step, _main_codex_action
    if not _main_codex_flow or _main_codex_step != "password_required":
        raise HTTPException(status_code=409, detail="当前没有等待密码的主号 Codex 登录流程")

    try:
        result = _pw_executor.run(_main_codex_flow.submit_password, params.password)
        step = result["step"]
        if step == "completed":
            return _finish_main_codex_flow()
        if step in ("password_required", "code_required"):
            _main_codex_step = step
            return {"status": step, "codex": _main_codex_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "主号 Codex 密码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        _main_codex_action = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/main-codex/code")
def post_main_codex_code(params: AdminCodeParams):
    """提交主号 Codex 登录验证码。"""
    global _main_codex_flow, _main_codex_step, _main_codex_action
    if not _main_codex_flow or _main_codex_step != "code_required":
        raise HTTPException(status_code=409, detail="当前没有等待验证码的主号 Codex 登录流程")

    try:
        result = _pw_executor.run(_main_codex_flow.submit_code, params.code.strip())
        step = result["step"]
        if step == "completed":
            return _finish_main_codex_flow()
        if step in ("password_required", "code_required"):
            _main_codex_step = step
            return {"status": step, "codex": _main_codex_status()}
        raise HTTPException(status_code=400, detail=result.get("detail") or "主号 Codex 验证码登录失败")
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        _main_codex_action = None
        if _playwright_lock.locked():
            _playwright_lock.release()
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/main-codex/cancel")
def post_main_codex_cancel():
    """取消主号 Codex 登录流程。"""
    global _main_codex_flow, _main_codex_step, _main_codex_action
    if _main_codex_flow:
        try:
            _pw_executor.run(_main_codex_flow.stop)
        except Exception:
            pass
        _main_codex_flow = None
        _main_codex_step = None
        _main_codex_action = None
        if _playwright_lock.locked():
            _playwright_lock.release()
    return {"message": "主号 Codex 登录已取消", "codex": _main_codex_status()}


@app.post("/api/main-codex/delete-cpa")
def post_main_codex_delete_cpa():
    """删除 CPA 中已上传的主号 Codex 认证文件。"""
    from autoteam.cpa_sync import delete_main_codex_from_cpa

    result = delete_main_codex_from_cpa()
    return {
        "message": f"已从 CPA 删除 {result['count']} 个主号认证文件",
        "deleted": result["deleted"],
    }


@app.post("/api/manual-account/start")
def post_manual_account_start():
    """开始手动添加账号流程，返回 OAuth 链接。"""
    global _manual_account_flow

    if _manual_account_flow:
        try:
            _manual_account_flow.stop()
        except Exception:
            pass
        _manual_account_flow = None

    try:
        from autoteam.manual_account import ManualAccountFlow

        flow = ManualAccountFlow()
        result = flow.start()
        return _set_pending_manual_account_flow(flow, result)
    except HTTPException:
        raise
    except Exception as exc:
        if _manual_account_flow:
            try:
                _manual_account_flow.stop()
            except Exception:
                pass
            _manual_account_flow = None
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/manual-account/callback")
def post_manual_account_callback(params: ManualAccountCallbackParams):
    """提交 OAuth 回调 URL，完成手动添加账号。"""
    global _manual_account_flow
    if not _manual_account_flow:
        raise HTTPException(status_code=409, detail="当前没有等待回调的手动添加账号流程")

    try:
        result = _manual_account_flow.submit_callback(params.redirect_url)
        return _finish_manual_account_flow(result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/manual-account/cancel")
def post_manual_account_cancel():
    """取消手动添加账号流程。"""
    global _manual_account_flow
    if _manual_account_flow:
        try:
            _manual_account_flow.stop()
        except Exception:
            pass
        _manual_account_flow = None
    return {"message": "手动添加账号流程已取消", "manual_account": _manual_account_status()}


@app.get("/api/accounts")
def get_accounts():
    """获取所有账号列表"""
    from autoteam.accounts import load_accounts

    accounts = load_accounts()
    return [_sanitize_account(a) for a in accounts]


@app.get("/api/accounts/{email}/codex-auth")
def get_codex_auth(email: str):
    """导出账号的 Codex CLI 格式认证文件（~/.codex/auth.json）"""
    from autoteam.accounts import find_account, load_accounts
    from autoteam.codex_auth import get_saved_main_auth_file

    email = email.strip().lower()
    auth_file = ""

    if _is_main_account_email(email):
        auth_file = get_saved_main_auth_file()
        if not auth_file or not Path(auth_file).exists():
            raise HTTPException(status_code=404, detail="主号没有可导出的认证文件")
    else:
        acc = find_account(load_accounts(), email)
        if not acc:
            raise HTTPException(status_code=404, detail="账号不存在")
        auth_file = _resolve_status_auth_file(acc)
        if not auth_file or not Path(auth_file).exists():
            raise HTTPException(status_code=404, detail="该账号没有认证文件")

    auth_data = json.loads(Path(auth_file).read_text())

    # 转换为 Codex CLI 的 auth.json 格式
    codex_auth = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": auth_data.get("id_token", ""),
            "access_token": auth_data.get("access_token", ""),
            "refresh_token": auth_data.get("refresh_token", ""),
            "account_id": auth_data.get("account_id", ""),
        },
        "last_refresh": auth_data.get("last_refresh", ""),
    }

    return {
        "email": email,
        "codex_auth": codex_auth,
        "hint": "将内容保存到 ~/.codex/auth.json（Linux/macOS）或 %APPDATA%\\codex\\auth.json（Windows）",
    }


@app.get("/api/accounts/active")
def get_active():
    """获取活跃账号"""
    from autoteam.accounts import get_active_accounts

    return [_sanitize_account(a) for a in get_active_accounts()]


@app.get("/api/accounts/standby")
def get_standby():
    """获取待命账号"""
    from autoteam.accounts import get_standby_accounts

    accounts = get_standby_accounts()
    return [_sanitize_account(a) for a in accounts]


@app.delete("/api/accounts/{email}")
def delete_account(email: str):
    """删除本地管理账号及其关联资源。"""
    if not _playwright_lock.acquire(blocking=False):
        running = _tasks.get(_current_task_id, {})
        raise HTTPException(
            status_code=409,
            detail={
                "message": "有任务正在执行，请等待完成后再删除账号",
                "running_task": {
                    "task_id": _current_task_id,
                    "command": running.get("command", "unknown"),
                    "started_at": running.get("started_at"),
                },
            },
        )

    try:
        from autoteam.account_ops import delete_managed_account
        from autoteam.accounts import load_accounts

        if _is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不允许删除")

        accounts = load_accounts()
        if not any(a["email"].lower() == email.lower() for a in accounts):
            raise HTTPException(status_code=404, detail="账号不存在")

        cleanup = _pw_executor.run(delete_managed_account, email)
        return {
            "message": "账号删除完成",
            "deleted_email": email,
            "cleanup": cleanup,
        }
    finally:
        _playwright_lock.release()


@app.post("/api/accounts/{email}/kick")
def post_kick_account(email: str):
    """将账号从 Team 中移出，状态变为 standby"""
    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再操作"))

    try:
        from autoteam.accounts import find_account, load_accounts, update_account
        from autoteam.manager import remove_from_team

        email = email.strip().lower()
        if _is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不允许移出 Team")
        accounts = load_accounts()
        acc = find_account(accounts, email)
        if not acc:
            raise HTTPException(status_code=404, detail="账号不存在")
        if acc["status"] != "active":
            raise HTTPException(status_code=400, detail=f"账号状态为 {acc['status']}，不是 active")

        def _do_kick():
            return _run_with_chatgpt_session(lambda chatgpt: remove_from_team(chatgpt, email))

        ok = _pw_executor.run(_do_kick)
        if ok:
            update_account(email, status="standby")
            return {"message": f"已将 {email} 移出 Team", "email": email, "status": "standby"}
        raise HTTPException(status_code=500, detail=f"移出 {email} 失败")
    finally:
        _playwright_lock.release()


@app.post("/api/accounts/{email}/sell")
def post_sell_account(email: str, params: SellAccountParams = SellAccountParams()):
    """标记账号已售出：保留 Team 席位，删除 CPA/Sub2API 远端记录，并停止后续同步。"""
    from autoteam.accounts import STATUS_ACTIVE, find_account, load_accounts, mark_account_sold, update_account
    from autoteam.auth_archive import archive_account_auth_file
    from autoteam.sync_targets import delete_account_from_configured_targets

    email = email.strip().lower()
    if _is_main_account_email(email):
        raise HTTPException(status_code=400, detail="主号不允许标记为已售")

    accounts = load_accounts()
    acc = find_account(accounts, email)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    if acc.get("status") != STATUS_ACTIVE:
        raise HTTPException(status_code=400, detail=f"账号状态为 {acc.get('status')}，不是 active")

    auth_file = acc.get("rt_auth_file") or acc.get("auth_file") or ""
    if not auth_file or not Path(auth_file).exists():
        raise HTTPException(status_code=400, detail="账号缺少本地 CPA 认证文件，不能标记为合格已售账号")

    auth_names = _existing_auth_names_for_account(acc)
    archive_path = acc.get("cpa_archive_file") or ""
    if not archive_path or not Path(archive_path).exists():
        archive_path = archive_account_auth_file(email, auth_file)
        update_account(email, cpa_archive_file=archive_path)

    try:
        remote_cleanup = delete_account_from_configured_targets(email, auth_names=auth_names)
    except Exception as exc:
        logger.exception("[API] 已售账号远端删除失败: %s", email)
        raise HTTPException(status_code=502, detail=f"远端删除失败: {exc}") from exc

    updates = mark_account_sold(email, remote_cleanup=remote_cleanup)
    if params.note:
        updates = update_account(email, sale_note=params.note)

    return {
        "message": f"已标记为已售并停止同步: {email}",
        "email": email,
        "status": "sold",
        "auth_file": auth_file,
        "cpa_archive_file": (updates or {}).get("cpa_archive_file") or archive_path,
        "remote_cleanup": remote_cleanup,
    }


@app.post("/api/accounts/{email}/self-use")
def post_self_use_account(email: str, params: SellAccountParams = SellAccountParams()):
    """标记账号为自用：远端下架，本地账号和 auth 保留。"""
    from autoteam.accounts import STATUS_ACTIVE, find_account, load_accounts, mark_account_self_use, update_account
    from autoteam.auth_archive import archive_account_auth_file
    from autoteam.sync_targets import delete_account_from_configured_targets

    email = email.strip().lower()
    if _is_main_account_email(email):
        raise HTTPException(status_code=400, detail="主号不允许标记为自用")

    accounts = load_accounts()
    acc = find_account(accounts, email)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    if acc.get("status") != STATUS_ACTIVE:
        raise HTTPException(status_code=400, detail=f"账号状态为 {acc.get('status')}，不是 active")

    auth_file = acc.get("rt_auth_file") or acc.get("auth_file") or ""
    archive_path = acc.get("cpa_archive_file") or ""
    if auth_file and Path(auth_file).exists() and (not archive_path or not Path(archive_path).exists()):
        archive_path = archive_account_auth_file(email, auth_file)
        update_account(email, cpa_archive_file=archive_path)

    auth_names = _existing_auth_names_for_account(acc)
    try:
        remote_cleanup = delete_account_from_configured_targets(email, auth_names=auth_names)
    except Exception as exc:
        logger.exception("[API] 自用账号远端删除失败: %s", email)
        raise HTTPException(status_code=502, detail=f"远端删除失败: {exc}") from exc

    updates = mark_account_self_use(email, remote_cleanup=remote_cleanup)
    if params.note:
        updates = update_account(email, self_use_note=params.note)

    return {
        "message": f"已标记为自用并停止同步: {email}",
        "email": email,
        "usage_status": "self_use",
        "auth_file": auth_file,
        "cpa_archive_file": (updates or {}).get("cpa_archive_file") or archive_path,
        "remote_cleanup": remote_cleanup,
    }


@app.post("/api/accounts/{email}/usage-status")
def post_account_usage_status(email: str, params: UsageStatusParams):
    """切换账号业务属性，仅允许 normal/inventory 这种不需要远端下架的状态。"""
    from autoteam.accounts import USAGE_INVENTORY, USAGE_NORMAL, find_account, load_accounts, mark_account_usage_status

    email = email.strip().lower()
    accounts = load_accounts()
    acc = find_account(accounts, email)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")

    usage_status = (params.usage_status or "").strip().lower()
    if usage_status not in {USAGE_NORMAL, USAGE_INVENTORY}:
        raise HTTPException(status_code=400, detail="usage_status 只允许 normal 或 inventory")
    updated = mark_account_usage_status(email, usage_status)
    return {"email": email, "usage_status": updated.get("usage_status")}


class LoginAccountParams(BaseModel):
    email: str
    force: bool = False


@app.post("/api/accounts/{email}/cpa-auth", status_code=202)
def post_account_cpa_auth(email: str):
    """为单个 Team 席位账号完成 Codex 认证并上传到 CPA。"""
    from autoteam.accounts import STATUS_ACTIVE, find_account, load_accounts
    from autoteam.cpa_sync import _account_auth_path_for_cpa

    email = email.strip().lower()
    if _is_main_account_email(email):
        raise HTTPException(status_code=400, detail="主号不属于账号池认证对象")

    accounts = load_accounts()
    acc = find_account(accounts, email)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    if acc.get("status") != STATUS_ACTIVE:
        raise HTTPException(status_code=400, detail=f"账号状态为 {acc.get('status')}，不是 active")

    _require_cpa_configs("CPA 认证")
    auth_file = _account_auth_path_for_cpa(acc)
    if not auth_file:
        _require_account_mail_configs(acc, "CPA 认证")

    def _run():
        from autoteam.accounts import STATUS_ACTIVE, STATUS_EXHAUSTED, STATUS_UNAVAILABLE, update_account
        from autoteam.auth_archive import archive_account_auth_file
        import autoteam.codex_auth as codex_auth
        from autoteam.codex_auth import (
            check_codex_quota,
            get_existing_session_auth_file,
            login_codex_via_browser,
            quota_result_quota_info,
            quota_result_resets_at,
            save_auth_file,
        )
        from autoteam.cpa_sync import upload_to_cpa
        from autoteam.mail_provider import get_account_mail_account_id, get_mail_client_for_account

        latest = find_account(load_accounts(), email)
        if not latest:
            raise RuntimeError(f"账号不存在: {email}")

        auth_path_obj = _account_auth_path_for_cpa(latest)
        auth_path = str(auth_path_obj) if auth_path_obj else ""
        plan_type = (latest.get("plan_type") or "unknown").strip().lower()
        if auth_path:
            logger.info("[CPA认证] 使用已有本地认证文件: %s", email)
        else:
            logger.info("[CPA认证] 本地缺少认证文件，开始 Codex 登录: %s", email)
            mail_client = get_mail_client_for_account(latest)
            mail_client.login()
            previous_session_auth_file = get_existing_session_auth_file(latest)
            bundle = login_codex_via_browser(
                email,
                latest.get("password", ""),
                mail_client=mail_client,
                mail_account_id=get_account_mail_account_id(latest),
            )
            if not bundle:
                if codex_auth.LAST_OAUTH_FAILURE_REASON == "account_deactivated":
                    update_account(
                        email,
                        status=STATUS_UNAVAILABLE,
                        sync_disabled=True,
                        unavailable_reason="account_deactivated",
                        unavailable_at=time.time(),
                    )
                    raise RuntimeError(f"{email} 已返回 account_deactivated，已标记不可用")
                raise RuntimeError(f"Codex 登录失败: {email}")

            plan_type = (bundle.get("plan_type") or "unknown").strip().lower()
            auth_path = save_auth_file(bundle, source="oauth")
            archive_path = archive_account_auth_file(email, auth_path)
            update_fields = {
                "auth_file": auth_path,
                "rt_auth_file": auth_path,
                "plan_type": plan_type,
                "cpa_archive_file": archive_path,
            }
            if previous_session_auth_file:
                update_fields["session_auth_file"] = previous_session_auth_file
            update_account(email, **update_fields)

            if plan_type == "team":
                update_account(email, status=STATUS_ACTIVE, last_active_at=time.time())
                token = bundle.get("access_token")
                if token:
                    st, info = check_codex_quota(token, account_id=bundle.get("account_id"))
                    if st == "ok" and isinstance(info, dict):
                        update_account(email, last_quota=info)
                    elif st == "exhausted":
                        quota_info = quota_result_quota_info(info)
                        if quota_info:
                            update_account(email, last_quota=quota_info)
                        update_account(
                            email,
                            status=STATUS_EXHAUSTED,
                            quota_exhausted_at=time.time(),
                            quota_resets_at=quota_result_resets_at(info) or int(time.time() + 18000),
                        )
                    elif st == "account_deactivated":
                        update_account(
                            email,
                            status=STATUS_UNAVAILABLE,
                            sync_disabled=True,
                            unavailable_reason="account_deactivated",
                            unavailable_at=time.time(),
                        )
                        raise RuntimeError(f"{email} 已返回 account_deactivated，已标记不可用")
            else:
                raise RuntimeError(f"{email} 登录后 plan={plan_type}，不是 team")

        if not upload_to_cpa(auth_path):
            raise RuntimeError(f"上传 CPA 失败: {Path(auth_path).name}")
        archive_path = archive_account_auth_file(email, auth_path)
        update_account(email, cpa_uploaded_at=time.time(), cpa_archive_file=archive_path, qualified_at=time.time())

        return {
            "email": email,
            "plan": plan_type,
            "auth_file": auth_path,
            "cpa_archive_file": archive_path,
            "cpa_uploaded": True,
        }

    task = _start_task(f"cpa-auth:{email}", _run, {"email": email})
    return task


@app.post("/api/accounts/login", status_code=202)
def post_account_login(params: LoginAccountParams):
    """触发单个账号的 Codex 登录（后台执行）"""
    from autoteam.accounts import find_account, load_accounts

    email = params.email.strip().lower()
    if _is_main_account_email(email):
        raise HTTPException(status_code=400, detail="主号不属于账号池登录对象")
    accounts = load_accounts()
    acc = find_account(accounts, email)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    if acc.get("status") == "sold":
        raise HTTPException(status_code=400, detail="账号已售出并停止同步，不能重新登录")
    if acc.get("sync_disabled") and not params.force:
        raise HTTPException(status_code=400, detail="账号已停止同步，不能重新登录；排查时可显式传 force=true")
    _require_account_mail_configs(acc, "登录账号")

    def _run():
        from autoteam.accounts import STATUS_ACTIVE, STATUS_STANDBY, STATUS_UNAVAILABLE, update_account
        from autoteam.auth_archive import archive_account_auth_file
        import autoteam.codex_auth as codex_auth
        from autoteam.codex_auth import (
            check_codex_quota,
            get_existing_session_auth_file,
            login_codex_via_browser,
            quota_result_quota_info,
            quota_result_resets_at,
            save_auth_file,
        )
        from autoteam.mail_provider import get_account_mail_account_id, get_mail_client_for_account

        mail_client = get_mail_client_for_account(acc)
        mail_client.login()
        previous_session_auth_file = get_existing_session_auth_file(acc)
        bundle = login_codex_via_browser(
            email,
            acc.get("password", ""),
            mail_client=mail_client,
            mail_account_id=get_account_mail_account_id(acc),
        )
        if bundle:
            auth_file = save_auth_file(bundle, source="oauth")
            archive_path = archive_account_auth_file(email, auth_file)
            update_fields = {
                "auth_file": auth_file,
                "rt_auth_file": auth_file,
                "cpa_archive_file": archive_path,
            }
            if previous_session_auth_file:
                update_fields["session_auth_file"] = previous_session_auth_file
            update_account(email, **update_fields)
            # 登录成功且是 team plan，自动标记为 active
            if bundle.get("plan_type") == "team":
                update_account(email, status=STATUS_ACTIVE, last_active_at=time.time())
                # 查一下额度并保存快照
                token = bundle.get("access_token")
                if token:
                    st, info = check_codex_quota(token)
                    if st == "ok" and isinstance(info, dict):
                        update_account(email, last_quota=info)
                    elif st == "exhausted":
                        quota_info = quota_result_quota_info(info)
                        if quota_info:
                            update_account(email, last_quota=quota_info)
                        update_account(
                            email,
                            status="exhausted",
                            quota_exhausted_at=time.time(),
                            quota_resets_at=quota_result_resets_at(info) or int(time.time() + 18000),
                        )
                    elif st == "account_deactivated":
                        update_account(
                            email,
                            status=STATUS_UNAVAILABLE,
                            sync_disabled=True,
                            unavailable_reason="account_deactivated",
                            unavailable_at=time.time(),
                        )
                        raise RuntimeError(f"{email} 已返回 account_deactivated，已标记不可用")
            elif bundle.get("plan_type") not in {"team", "unknown"}:
                update_account(email, status=STATUS_STANDBY)
            return {
                "email": email,
                "plan": bundle.get("plan_type"),
                "auth_file": auth_file,
                "rt_auth_file": auth_file,
                "cpa_archive_file": archive_path,
            }
        if codex_auth.LAST_OAUTH_FAILURE_REASON == "account_deactivated":
            update_account(
                email,
                status=STATUS_UNAVAILABLE,
                sync_disabled=True,
                unavailable_reason="account_deactivated",
                unavailable_at=time.time(),
            )
            raise RuntimeError(f"{email} 已返回 account_deactivated，已标记不可用")
        raise RuntimeError(f"Codex 登录失败: {email}")

    task = _start_task(f"login:{email}", _run, {"email": email})
    return task


@app.get("/api/status")
def get_status(realtime_quota: bool = True):
    """获取所有账号状态，可选查询 active 账号实时额度。"""
    from autoteam.accounts import (
        STATUS_ACTIVE,
        STATUS_EXHAUSTED,
        STATUS_PENDING,
        STATUS_SOLD,
        STATUS_STANDBY,
        STATUS_UNAVAILABLE,
        USAGE_INVENTORY,
        VALID_USAGE_STATUSES,
        load_accounts,
    )
    from autoteam.codex_auth import check_codex_quota, quota_result_quota_info

    accounts = load_accounts()
    quota_cache = {}

    if realtime_quota:
        for acc in accounts:
            if acc["status"] != STATUS_ACTIVE and not _is_main_account_email(acc.get("email")):
                continue

            auth_file = _resolve_status_auth_file(acc)
            if not auth_file:
                continue

            try:
                auth_data = json.loads(read_text(Path(auth_file)))
                access_token = auth_data.get("access_token")
                if access_token:
                    status, info = check_codex_quota(access_token)
                    if status == "ok" and isinstance(info, dict):
                        quota_cache[acc["email"]] = info
                    elif status == "exhausted":
                        quota_info = quota_result_quota_info(info)
                        if quota_info:
                            quota_cache[acc["email"]] = quota_info
            except Exception:
                pass

    sanitized_accounts = [_sanitize_account(a, quota_cache.get(a.get("email"))) for a in accounts]

    summary = {
        "active": sum(1 for a in sanitized_accounts if a["status"] == STATUS_ACTIVE),
        "standby": sum(1 for a in sanitized_accounts if a["status"] == STATUS_STANDBY),
        "exhausted": sum(1 for a in sanitized_accounts if a["status"] == STATUS_EXHAUSTED),
        "pending": sum(1 for a in sanitized_accounts if a["status"] == STATUS_PENDING),
        "unavailable": sum(1 for a in sanitized_accounts if a["status"] == STATUS_UNAVAILABLE),
        "sold": sum(1 for a in sanitized_accounts if a["status"] == STATUS_SOLD),
        "total": len(sanitized_accounts),
    }
    usage_summary = {status: 0 for status in sorted(VALID_USAGE_STATUSES)}
    for account in sanitized_accounts:
        usage_status = (account.get("usage_status") or "normal").strip().lower()
        usage_summary[usage_status] = usage_summary.get(usage_status, 0) + 1

    inventory_ready = [
        account
        for account in sanitized_accounts
        if (account.get("usage_status") or "").strip().lower() == USAGE_INVENTORY
        and account.get("cpa_status") == "success"
        and not account.get("sync_disabled")
        and bool(account.get("rt_auth_file") or account.get("auth_file"))
    ]
    cpa_summary = {
        "success": sum(1 for a in sanitized_accounts if a.get("cpa_status") == "success"),
        "failed": sum(1 for a in sanitized_accounts if a.get("cpa_status") == "failed"),
        "pending": sum(1 for a in sanitized_accounts if a.get("cpa_status") == "pending"),
        "cloud_stocked": sum(1 for a in sanitized_accounts if a.get("cloud_stocked_at")),
        "inventory_ready": len(inventory_ready),
        "inventory_missing_to_100": max(0, 100 - len(inventory_ready)),
    }

    return {
        "accounts": sanitized_accounts,
        "summary": summary,
        "usage_summary": usage_summary,
        "cpa_summary": cpa_summary,
        "quota_cache": quota_cache,
    }


@app.post("/api/sync")
def post_sync():
    """同步认证文件到已启用远端。"""
    from autoteam.sync_targets import describe_sync_targets, get_enabled_sync_targets, sync_to_configured_targets

    _require_sync_target_configs("同步远端")
    targets = get_enabled_sync_targets()
    result = sync_to_configured_targets()
    return {"message": f"已同步到 {describe_sync_targets(targets)}", "result": result}


@app.post("/api/sync/cpa")
def post_sync_cpa():
    """只同步账号池认证文件到 CPA。"""
    _require_cpa_configs("同步 CPA")

    from autoteam.cpa_sync import sync_to_cpa

    result = sync_to_cpa()
    return {"message": "已同步到 CPA", "result": result}


@app.post("/api/sync/cpa-stock")
def post_sync_cpa_stock():
    """维护 CPA 云端库存，至少保留 100 个库存 RT 文件。"""
    _require_cpa_configs("维护 CPA 库存")

    from autoteam.cpa_sync import maintain_cpa_inventory

    result = maintain_cpa_inventory(target=100)
    return {"message": "已维护 CPA 库存", "result": result}


@app.post("/api/sync/cpa/cleanup-401")
def post_cleanup_cpa_401():
    """删除 CPA 远端 401 文件，并按返回名单标记本地账号不可用。"""
    _require_cpa_configs("清理 CPA 401")

    from autoteam.cpa_sync import delete_http401_from_cpa

    result = delete_http401_from_cpa()
    return {"message": "已清理 CPA 401 文件", "result": result}


@app.post("/api/sync/cpa/cleanup-invalid-rt")
def post_cleanup_cpa_invalid_rt():
    """直接刷新 CPA OAuth RT 文件，删除明确失效的远端文件。"""
    _require_cpa_configs("清理 CPA 失效 RT")

    from autoteam.cpa_sync import cleanup_invalid_cpa_refresh_tokens

    result = cleanup_invalid_cpa_refresh_tokens()
    return {"message": "已清理 CPA 失效 RT 文件", "result": result}


@app.post("/api/accounts/mark-unusable/account-deactivated")
def post_mark_unusable_account_deactivated(params: UnusableDirParams = UnusableDirParams()):
    """按 auths/unusable/account_deactivated 目录标记本地账号不可用。"""
    from autoteam.cpa_sync import mark_unusable_account_deactivated_from_dir

    result = mark_unusable_account_deactivated_from_dir(params.directory)
    return {"message": "已按 account_deactivated 目录标记本地账号", "result": result}


@app.post("/api/accounts/check-deactivated-mail")
def post_check_deactivated_mail(params: DeactivatedMailCheckParams = DeactivatedMailCheckParams()):
    """检查邮箱是否收到 deactivated 邮件，并在命中时释放 Team 席位。"""
    from autoteam.account_deactivation import check_deactivated_mail

    if not params.apply:
        return {
            "message": "已完成 deactivated 邮件检查（dry-run）",
            "result": check_deactivated_mail(
                keyword=params.keyword,
                size=params.size,
                directory=params.directory,
                apply=False,
                release_team=params.release_team,
                dispose_mailbox=params.dispose_mailbox,
            ),
        }

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再操作"))

    try:
        from autoteam.account_deactivation import check_deactivated_mail
        from autoteam.manager import remove_from_team

        def _run_check():
            return check_deactivated_mail(
                keyword=params.keyword,
                size=params.size,
                directory=params.directory,
                apply=True,
                release_team=params.release_team,
                dispose_mailbox=params.dispose_mailbox,
                team_remover=_team_remover_factory(remove_from_team) if params.release_team else None,
            )

        result = _pw_executor.run(_run_check)
        return {
            "message": "已完成 deactivated 邮件检查并处理命中账号",
            "result": result,
        }
    finally:
        _playwright_lock.release()


@app.post("/api/accounts/migrate-auth-metadata")
def post_migrate_auth_metadata(params: AuthMetadataMigrationParams = AuthMetadataMigrationParams()):
    """将旧 auth_file 元数据迁移到 rt_auth_file；默认只报告不写入。"""
    from autoteam.accounts import migrate_legacy_auth_file_metadata

    result = migrate_legacy_auth_file_metadata(apply=params.apply)
    message = "已迁移旧认证文件元数据" if params.apply else "已生成旧认证文件元数据迁移报告"
    return {"message": message, "result": result}


@app.post("/api/sync/sub2api")
def post_sync_sub2api():
    """只同步账号池认证文件到 Sub2API。"""
    _require_sub2api_configs("同步 Sub2API")

    from autoteam.sub2api_sync import sync_to_sub2api

    result = sync_to_sub2api()
    return {"message": "已同步到 Sub2API", "result": result}


@app.post("/api/sync/from-cpa")
def post_sync_from_cpa():
    """从 CPA 反向同步认证文件到本地。"""
    _require_cpa_configs("拉取 CPA")

    from autoteam.cpa_sync import sync_from_cpa

    result = sync_from_cpa()
    return {"message": "已从 CPA 同步到本地", "result": result}


@app.post("/api/sync/accounts")
def post_sync_accounts():
    """从 auths 目录和 Team 成员同步账号到 accounts.json"""
    from autoteam.manager import sync_account_states

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再同步"))

    try:
        _pw_executor.run(sync_account_states)
    finally:
        _playwright_lock.release()

    from autoteam.accounts import load_accounts

    accounts = load_accounts()
    return {"message": f"同步完成，共 {len(accounts)} 个账号", "total": len(accounts)}


@app.get("/api/team/members")
def get_team_members(refresh: bool = False, allow_browser: bool = False):
    """获取 Team 全部成员。

    默认只返回本地缓存或本地账号快照，避免进入页面时被浏览器远端请求拖慢。
    refresh=true 时优先使用已缓存的 ChatGPT access token 直连远端；只有显式
    allow_browser=true 才会回退到 Playwright。
    """
    from autoteam.admin_state import (
        get_admin_session_token,
        get_chatgpt_access_token,
        get_chatgpt_account_id,
        get_chatgpt_oai_device_id,
    )
    from autoteam.team_cache import load_team_members_cache, save_team_members_cache

    account_id = get_chatgpt_account_id()
    if not get_admin_session_token() or not account_id:
        raise HTTPException(status_code=400, detail="请先完成管理员登录")

    def _local_account_summary(account: dict | None) -> dict:
        if not account:
            return {}
        auth_file = account.get("auth_file") or ""
        cpa_archive_file = account.get("cpa_archive_file") or ""
        return {
            "status": account.get("status", ""),
            "sync_disabled": bool(account.get("sync_disabled")),
            "is_main_account": _is_main_account_email(account.get("email")),
            "auth_file": auth_file,
            "has_auth_file": bool(auth_file),
            "cpa_archive_file": cpa_archive_file,
            "has_cpa_archive_file": bool(cpa_archive_file),
            "sold_at": account.get("sold_at"),
        }

    def _local_accounts_by_email() -> dict[str, dict]:
        from autoteam.accounts import load_accounts

        return {(a.get("email") or "").lower(): a for a in load_accounts() if a.get("email")}

    def _attach_local_account_fields(payload: dict) -> dict:
        local_accounts = _local_accounts_by_email()
        members = []
        for member in payload.get("members") or []:
            email = (member.get("email") or "").lower()
            local_account = local_accounts.get(email)
            enriched = dict(member)
            enriched["is_local"] = local_account is not None
            enriched.update(_local_account_summary(local_account))
            members.append(enriched)
        return {**payload, "members": members}

    cached = load_team_members_cache()
    if cached and not refresh:
        return {**_attach_local_account_fields(cached), "cached": True}

    def _local_snapshot(refresh_error: str = ""):
        members = []
        for account in _local_accounts_by_email().values():
            email = (account.get("email") or "").lower()
            if not email:
                continue
            members.append(
                {
                    "email": email,
                    "role": "member",
                    "user_id": "",
                    "is_local": True,
                    "type": "member",
                    **_local_account_summary(account),
                }
            )
        payload = {
            "members": members,
            "total": len(members),
            "invites": 0,
            "cached": True,
            "local_snapshot": True,
            "cache_updated_at": time.time(),
        }
        if refresh_error:
            payload["refresh_error"] = refresh_error
        return payload

    def _format_team_payload(members, invites):
        local_accounts = _local_accounts_by_email()
        result = []
        for m in members:
            email = (m.get("email") or "").lower()
            local_account = local_accounts.get(email)
            result.append(
                {
                    "email": m.get("email", ""),
                    "role": m.get("role", ""),
                    "user_id": m.get("user_id") or m.get("id", ""),
                    "is_local": local_account is not None,
                    "type": "member",
                    **_local_account_summary(local_account),
                }
            )
        for inv in invites:
            email = (inv.get("email_address") or inv.get("email") or "").lower()
            local_account = local_accounts.get(email)
            result.append(
                {
                    "email": email,
                    "role": inv.get("role", ""),
                    "user_id": inv.get("id", ""),
                    "is_local": local_account is not None,
                    "type": "invite",
                    **_local_account_summary(local_account),
                }
            )
        return {
            "members": result,
            "total": len(members),
            "invites": len(invites),
            "cached": False,
            "cache_updated_at": time.time(),
        }

    def _fetch_with_cached_token():
        access_token = get_chatgpt_access_token()
        if not access_token:
            return None


        headers = {
            "authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "oai-language": "en-US",
        }
        device_id = get_chatgpt_oai_device_id()
        if device_id:
            headers["oai-device-id"] = device_id

        users_resp = outbound_proxy.request(
            "GET",
            f"https://chatgpt.com/backend-api/accounts/{account_id}/users",
            headers=headers,
            timeout=20,
        )
        users_resp.raise_for_status()
        users_data = users_resp.json()
        members = users_data.get("items", users_data.get("users", users_data.get("members", [])))

        invites_resp = outbound_proxy.request(
            "GET",
            f"https://chatgpt.com/backend-api/accounts/{account_id}/invites",
            headers=headers,
            timeout=20,
        )
        invites_resp.raise_for_status()
        invites_data = invites_resp.json()
        invites = (
            invites_data
            if isinstance(invites_data, list)
            else invites_data.get("invites", invites_data.get("account_invites", []))
        )
        return _format_team_payload(members, invites)

    try:
        token_result = _fetch_with_cached_token()
        if token_result is not None:
            return save_team_members_cache(token_result)
    except Exception as exc:
        logger.warning("[API] 使用缓存 access token 获取 Team 成员失败: %s", exc)
        if cached:
            return {**cached, "cached": True, "refresh_error": str(exc)}
        if not allow_browser:
            return _local_snapshot(str(exc))

    if not allow_browser:
        message = "尚未缓存 ChatGPT access token，请重新完成管理员登录后再点击验证刷新"
        if cached:
            return {**cached, "cached": True, "refresh_error": message}
        return _local_snapshot(message if refresh else "")

    if not _playwright_lock.acquire(blocking=False):
        detail = _current_busy_detail("有任务正在执行，请等待完成后再查询")
        if cached:
            return {**cached, "cached": True, "refresh_error": detail}
        raise HTTPException(status_code=409, detail=detail)

    try:

        def _fetch_team_members():
            from autoteam.account_ops import fetch_team_state

            def _collect(chatgpt):
                members, invites = fetch_team_state(chatgpt)
                return _format_team_payload(members, invites)

            return _run_with_chatgpt_session(_collect)

        try:
            result = _pw_executor.run(_fetch_team_members)
            return save_team_members_cache(result)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[API] 获取 Team 成员失败")
            if cached:
                return {**cached, "cached": True, "refresh_error": str(exc)}
            raise HTTPException(status_code=502, detail=str(exc))
    finally:
        _playwright_lock.release()


@app.post("/api/team/members/remove")
def post_team_member_remove(params: TeamMemberRemoveParams):
    """移出 Team 成员或取消邀请。"""
    from autoteam.admin_state import get_admin_session_token, get_chatgpt_account_id

    if not get_admin_session_token() or not get_chatgpt_account_id():
        raise HTTPException(status_code=400, detail="请先完成管理员登录")

    if not _playwright_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_current_busy_detail("有任务正在执行，请等待完成后再操作"))

    try:
        from autoteam.accounts import find_account, load_accounts, update_account

        email = params.email.strip().lower()
        user_id = params.user_id.strip()
        member_type = params.type.strip().lower()

        if not email or not user_id:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        if _is_main_account_email(email):
            raise HTTPException(status_code=400, detail="主号不允许从 Team 成员页移出")
        if member_type not in ("member", "invite"):
            raise HTTPException(status_code=400, detail="无效的成员类型")

        account_id = get_chatgpt_account_id()

        def _do_remove_team_member():
            def _remove(chatgpt):
                if member_type == "invite":
                    path = f"/backend-api/accounts/{account_id}/invites/{user_id}"
                    action_text = "取消邀请"
                else:
                    path = f"/backend-api/accounts/{account_id}/users/{user_id}"
                    action_text = "移出 Team"

                result = chatgpt._api_fetch("DELETE", path)
                return result, action_text

            return _run_with_chatgpt_session(_remove)

        try:
            result, action_text = _pw_executor.run(_do_remove_team_member)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[API] Team 成员移除失败")
            raise HTTPException(status_code=502, detail=str(exc))
        if result["status"] not in (200, 204):
            raise HTTPException(status_code=500, detail=f"{action_text}失败: HTTP {result['status']}")

        accounts = load_accounts()
        acc = find_account(accounts, email)
        if acc:
            update_account(email, status="standby")

        return {
            "message": f"已{action_text}: {email}",
            "email": email,
            "type": member_type,
        }
    finally:
        _playwright_lock.release()


# ---------------------------------------------------------------------------
# 日志收集
# ---------------------------------------------------------------------------

_log_buffer: list[dict] = []
_LOG_BUFFER_MAX = 500


class _LogCollector(logging.Handler):
    """收集日志到内存 buffer，供前端查询"""

    def emit(self, record):
        entry = {
            "time": record.created,
            "level": record.levelname,
            "message": self.format(record),
        }
        _log_buffer.append(entry)
        if len(_log_buffer) > _LOG_BUFFER_MAX:
            del _log_buffer[: len(_log_buffer) - _LOG_BUFFER_MAX]


_log_collector = _LogCollector()
_log_collector.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_log_collector)


@app.get("/api/logs")
def get_logs(limit: int = 100, since: float = 0):
    """获取最近的日志"""
    if since > 0:
        entries = [e for e in _log_buffer if e["time"] > since]
    else:
        entries = _log_buffer[-limit:]
    return {"logs": entries, "total": len(_log_buffer)}


@app.post("/api/sync/main-codex")
def post_sync_main_codex():
    """兼容旧接口：开始主号 Codex 登录并同步到已启用远端。"""
    return post_main_codex_start()


@app.post("/api/sync/main-codex/saved")
def post_sync_saved_main_codex():
    """只推送本地已有的主号 Codex 凭证，不启动浏览器登录。"""
    _require_sync_target_configs("同步主号 Codex")

    from autoteam.codex_auth import get_saved_main_auth_file
    from autoteam.sync_targets import sync_main_codex_to_configured_targets

    saved_auth_file = get_saved_main_auth_file()
    if not saved_auth_file:
        raise HTTPException(status_code=400, detail="未找到主号 Codex 凭证，请先在配置面板完成主号 Codex 登录")

    result = sync_main_codex_to_configured_targets(saved_auth_file)
    return {
        "message": "主号 Codex 凭证已同步到已启用远端",
        "result": result,
        "info": {"auth_file": saved_auth_file},
    }


@app.get("/api/cpa/files")
def get_cpa_files():
    """获取 CPA 中的认证文件列表"""
    _require_cpa_configs("查看 CPA 文件")

    from autoteam.cpa_sync import list_cpa_files

    return list_cpa_files()


@app.get("/api/cpa-batch/runs")
def get_cpa_batch_runs():
    """获取批量 CPA JSON 任务记录。"""
    from autoteam.flow_runs import load_flow_runs

    return load_flow_runs()


@app.get("/api/cpa-batch/runs/{run_id}")
def get_cpa_batch_run(run_id: str):
    """获取单次批量 CPA JSON 任务记录。"""
    from autoteam.flow_runs import get_flow_run

    run = get_flow_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务记录不存在")
    return run


@app.post("/api/cpa-batch/runs/{run_id}/pause")
def pause_cpa_batch_run(run_id: str):
    """请求批量 CPA JSON 任务暂停。"""
    from autoteam.flow_runs import request_flow_pause

    run = request_flow_pause(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务记录不存在")
    return {"message": "已请求暂停，当前账号阶段结束后停止继续新账号", "run": run}


@app.post("/api/cpa-batch/runs/{run_id}/resume", status_code=202)
def resume_cpa_batch_run(run_id: str):
    """从已有批量 CPA JSON 记录继续执行。"""
    from autoteam.cpa_batch import run_cpa_batch
    from autoteam.flow_runs import get_flow_run

    run = get_flow_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务记录不存在")
    if run.get("status") == "running":
        raise HTTPException(status_code=409, detail="任务已经在运行")
    if int(run.get("success_count") or 0) >= int(run.get("target") or 0):
        raise HTTPException(status_code=400, detail="任务已达到目标数量")

    task = _start_task(
        "cpa-batch",
        run_cpa_batch,
        {
            "run_id": run_id,
            "join_mode": run.get("join_mode") or "direct",
            "target": run.get("target") or 100,
            "batch_size": run.get("batch_size") or 20,
            "resume": True,
        },
        run_id,
        resume=True,
    )
    return task


# ---------------------------------------------------------------------------
# 后台任务端点
# ---------------------------------------------------------------------------


@app.post("/api/tasks/check", status_code=202)
def post_check():
    """检查所有 active 账号额度（后台执行）"""
    from autoteam.manager import cmd_check

    def _run():
        exhausted = cmd_check()
        return {"exhausted": [a["email"] for a in exhausted]}

    task = _start_task("check", _run, {})
    return task


@app.post("/api/tasks/rotate", status_code=202)
def post_rotate(params: TaskParams = TaskParams()):
    """智能轮转（后台执行）"""
    _require_pool_operation_configs("智能轮转")

    from autoteam.config import MAX_TEAM_SEATS, TEAM_TARGET_SEATS
    from autoteam.manager import cmd_rotate

    target = min(MAX_TEAM_SEATS, max(1, params.target or TEAM_TARGET_SEATS))
    parallel_workers = _resolve_parallel_workers_param(params.parallel_workers)
    task = _start_task(
        "rotate",
        cmd_rotate,
        {"target": target, "parallel_workers": parallel_workers},
        target,
        parallel_workers=parallel_workers,
    )
    return task


@app.post("/api/tasks/add", status_code=202)
def post_add():
    """添加新账号（后台执行）"""
    _require_pool_operation_configs("添加新账号")

    from autoteam.manager import cmd_add

    task = _start_task("add", cmd_add, {})
    return task


@app.post("/api/tasks/fill", status_code=202)
def post_fill(params: TaskParams = TaskParams()):
    """补满 Team 成员（后台执行）"""
    _require_pool_operation_configs("补满 Team 成员")

    from autoteam.config import FILL_BATCH_SIZE, MAX_TEAM_SEATS, TEAM_TARGET_SEATS
    from autoteam.manager import cmd_fill

    task_params = {"target": min(MAX_TEAM_SEATS, max(1, params.target or TEAM_TARGET_SEATS))}
    parallel_workers = _resolve_parallel_workers_param(params.parallel_workers)
    task_params["parallel_workers"] = parallel_workers
    if params.target is None:
        task_params["max_add"] = FILL_BATCH_SIZE
    task = _start_task("fill", cmd_fill, task_params, params.target, parallel_workers=parallel_workers)
    return task


@app.post("/api/tasks/cpa-batch", status_code=202)
def post_cpa_batch(params: CpaBatchParams = CpaBatchParams()):
    """新做 100 个 team 账号 CPA JSON。"""
    from autoteam.mail_provider import get_mail_provider_name, get_mail_provider_required_keys

    env = _current_runtime_env()
    provider = get_mail_provider_name(env)
    _require_runtime_configs(get_mail_provider_required_keys(provider), "批量 CPA JSON", env=env)
    _require_cpa_configs("批量 CPA JSON")
    if not _admin_status().get("configured"):
        raise HTTPException(status_code=400, detail="批量 CPA JSON 前请先完成管理员登录")

    import uuid

    from autoteam.cpa_batch import (
        DEFAULT_BATCH_SIZE,
        DEFAULT_TARGET,
        JOIN_MODE_DIRECT,
        JOIN_MODE_INVITE,
        VALID_JOIN_MODES,
        run_cpa_batch,
    )

    join_mode = (params.join_mode or JOIN_MODE_DIRECT).strip().lower()
    if join_mode not in VALID_JOIN_MODES:
        raise HTTPException(status_code=400, detail=f"未知入席方式: {join_mode}")

    target = min(DEFAULT_TARGET, max(1, params.target or DEFAULT_TARGET))
    batch_size = min(DEFAULT_BATCH_SIZE, max(1, params.batch_size or DEFAULT_BATCH_SIZE))
    parallel_workers = _resolve_parallel_workers_param(params.parallel_workers)
    if join_mode == JOIN_MODE_INVITE:
        parallel_workers = 1
    run_id = uuid.uuid4().hex[:12]
    task = _start_task(
        "cpa-batch",
        run_cpa_batch,
        {
            "run_id": run_id,
            "join_mode": join_mode,
            "target": target,
            "batch_size": batch_size,
            "parallel_workers": parallel_workers,
        },
        run_id,
        join_mode=join_mode,
        target=target,
        batch_size=batch_size,
        parallel_workers=parallel_workers,
    )
    return task


@app.post("/api/tasks/cleanup", status_code=202)
def post_cleanup(params: CleanupParams = CleanupParams()):
    """清理多余成员（后台执行）"""
    from autoteam.manager import cmd_cleanup

    task = _start_task("cleanup", cmd_cleanup, {"max_seats": params.max_seats}, params.max_seats)
    return task


@app.get("/api/tasks")
def get_tasks():
    """查看所有任务"""
    sorted_tasks = sorted(_tasks.values(), key=lambda t: t["created_at"], reverse=True)
    return sorted_tasks


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """查看任务状态"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/api/tasks/stop-all")
def post_stop_all_tasks():
    """强制停止面板当前已知的任务和等待中的登录/OAuth 流程。"""
    reason = "用户强制停止"
    stopped_tasks = _request_stop_all_tasks(reason)
    stopped_flows = _stop_pending_flows(reason)
    logger.warning(
        "[API] 用户请求强制停止全部工作: tasks=%d flows=%d",
        len(stopped_tasks),
        len(stopped_flows),
    )
    return {
        "message": "已请求停止全部工作",
        "stopped_tasks": stopped_tasks,
        "stopped_flows": stopped_flows,
    }


# ---------------------------------------------------------------------------
# 后台自动巡检
# ---------------------------------------------------------------------------

from autoteam.config import (
    AUTO_CHECK_INTERVAL as _DEFAULT_INTERVAL,
)
from autoteam.config import (
    AUTO_CHECK_MIN_LOW as _DEFAULT_MIN_LOW,
)
from autoteam.config import (
    AUTO_CHECK_THRESHOLD as _DEFAULT_THRESHOLD,
)
from autoteam.config import (
    TEAM_TARGET_SEATS as _DEFAULT_TEAM_TARGET_SEATS,
)

# 运行时可修改的巡检配置
_auto_check_config = {
    "interval": _DEFAULT_INTERVAL,
    "threshold": _DEFAULT_THRESHOLD,
    "min_low": _DEFAULT_MIN_LOW,
    "target_seats": _DEFAULT_TEAM_TARGET_SEATS,
}
_auto_check_stop = threading.Event()
_auto_check_restart = threading.Event()  # 配置变更时通知线程重启


def _auto_check_team_member_count(timeout_seconds=30, retries=3):
    """查询 Team 实际成员数，供自动巡检的人数兜底判断使用。"""
    for attempt in range(1, max(1, retries) + 1):
        result_holder: dict[str, object] = {}
        done = threading.Event()

        def _worker(result_holder=result_holder, done=done):
            chatgpt = None
            try:
                from autoteam.chatgpt_api import ChatGPTTeamAPI
                from autoteam.manager import get_team_member_count

                chatgpt = ChatGPTTeamAPI()
                chatgpt.start()
                result_holder["count"] = get_team_member_count(chatgpt)
            except Exception as exc:
                result_holder["error"] = exc
            finally:
                try:
                    if chatgpt and chatgpt.browser:
                        chatgpt.stop()
                except Exception:
                    pass
                done.set()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        if not done.wait(timeout=timeout_seconds):
            if attempt < retries:
                logger.warning(
                    "[巡检] 查询 Team 实际成员数超时（>%ss），准备重试第 %d/%d 次",
                    timeout_seconds,
                    attempt + 1,
                    retries,
                )
                continue
            logger.warning(
                "[巡检] 查询 Team 实际成员数超时（>%ss，已重试 %d 次），跳过本轮人数校验",
                timeout_seconds,
                retries,
            )
            return -1

        if "error" in result_holder:
            logger.warning("[巡检] 查询 Team 实际成员数失败: %s", result_holder["error"])
            return -1

        try:
            return int(result_holder.get("count", -1))
        except Exception:
            return -1

    return -1


def _auto_check_wait(interval_seconds, poll_seconds=0.2):
    """等待下一轮巡检，同时允许 stop / restart 尽快生效。"""
    interval = max(0.0, float(interval_seconds))
    poll = max(0.05, float(poll_seconds))
    deadline = time.monotonic() + interval

    while True:
        try:
            _maybe_reload_runtime_config_from_env_file()
        except Exception as exc:
            logger.warning("[配置] 自动热加载失败: %s", exc)

        if _auto_check_restart.is_set():
            _auto_check_restart.clear()
            return "restart"

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if _auto_check_stop.wait(0):
                return "stop"
            return "timeout"

        step = min(remaining, poll)
        if _auto_check_stop.wait(step):
            return "stop"


def _auto_check_loop():
    """后台巡检线程：定期检查额度，多个账号低于阈值时自动轮转"""
    from autoteam.accounts import STATUS_ACTIVE, STATUS_UNAVAILABLE, load_accounts, update_account
    from autoteam.codex_auth import check_codex_quota

    while not _auto_check_stop.is_set():
        try:
            _maybe_reload_runtime_config_from_env_file()
        except Exception as exc:
            logger.warning("[配置] 自动热加载失败: %s", exc)

        cfg = _auto_check_config
        target_seats = cfg.get("target_seats", _DEFAULT_TEAM_TARGET_SEATS)
        logger.info(
            "[巡检] 等待 %d 分钟后执行下一轮检查（目标: %d, 阈值: %d%%, 触发: >=%d 个）",
            cfg["interval"] // 60,
            target_seats,
            cfg["threshold"],
            cfg["min_low"],
        )

        # 等待 interval 秒，期间可被 restart 或 stop 唤醒
        wait_result = _auto_check_wait(cfg["interval"])
        if wait_result == "stop":
            break
        if wait_result == "restart":
            continue  # 配置变更，跳到下一轮重新读取配置

        try:
            cfg = _auto_check_config  # 重新读取
            target_seats = cfg.get("target_seats", _DEFAULT_TEAM_TARGET_SEATS)
            accounts = load_accounts()
            local_active_count = sum(
                1
                for a in accounts
                if a["status"] == STATUS_ACTIVE
                and not a.get("sync_disabled")
                and not _is_main_account_email(a.get("email"))
            )
            active = [
                a
                for a in accounts
                if a["status"] == STATUS_ACTIVE
                and not a.get("sync_disabled")
                and not _is_main_account_email(a.get("email"))
                and a.get("auth_file")
                and Path(a["auth_file"]).exists()
            ]

            low_accounts = []
            for acc in active:
                try:
                    auth_data = json.loads(read_text(Path(acc["auth_file"])))
                    access_token = auth_data.get("access_token")
                    if not access_token:
                        continue
                    status, info = check_codex_quota(access_token)
                    if status == "ok" and isinstance(info, dict):
                        remaining = 100 - info.get("primary_pct", 0)
                        if remaining < cfg["threshold"]:
                            low_accounts.append((acc["email"], remaining, status, info))
                    elif status == "exhausted":
                        low_accounts.append((acc["email"], 0, status, info))
                    elif status == "account_deactivated":
                        logger.warning("[%s] 巡检发现 account_deactivated，标记为不可用并跳过", acc["email"])
                        update_account(
                            acc["email"],
                            status=STATUS_UNAVAILABLE,
                            sync_disabled=True,
                            unavailable_reason="account_deactivated",
                            unavailable_at=time.time(),
                        )
                except Exception:
                    pass

            if low_accounts:
                logger.info(
                    "[巡检] %d 个账号额度不足: %s",
                    len(low_accounts),
                    ", ".join(f"{e}({r}%)" for e, r, _status, _info in low_accounts),
                )

            shortage = max(0, target_seats - local_active_count)
            actual_team_count = -1
            team_count_check_failed = False
            trigger_rotate = len(low_accounts) >= cfg["min_low"]
            trigger_cleanup = False

            if not trigger_rotate:
                actual_team_count = _auto_check_team_member_count()
                if actual_team_count < 0:
                    team_count_check_failed = True
                elif actual_team_count > target_seats:
                    trigger_cleanup = True
                    shortage = 0
                else:
                    shortage = max(0, target_seats - actual_team_count)
                    trigger_rotate = shortage > 0

            if trigger_rotate or trigger_cleanup:
                # 检查是否有任务在跑
                if not _playwright_lock.acquire(blocking=False):
                    logger.info("[巡检] 有任务正在执行，跳过本轮自动轮转/补位/清理")
                    continue
                _playwright_lock.release()

                if trigger_rotate:
                    try:
                        _require_pool_operation_configs("自动轮转/补位")
                    except HTTPException as exc:
                        logger.warning("[巡检] 跳过自动轮转/补位: %s", exc.detail)
                        continue

                    # 将低于阈值的账号标记为 exhausted，rotate 会自动移出并补充
                    from autoteam.accounts import STATUS_EXHAUSTED, update_account
                    from autoteam.codex_auth import quota_result_quota_info, quota_result_resets_at

                    for email, remaining, status, info in low_accounts:
                        logger.info("[巡检] %s 剩余 %d%%，标记为 exhausted", email, remaining)
                        status_kwargs = {
                            "status": STATUS_EXHAUSTED,
                            "quota_exhausted_at": time.time(),
                        }
                        if status == "ok":
                            status_kwargs["last_quota"] = info if isinstance(info, dict) else None
                            status_kwargs["quota_resets_at"] = (
                                info.get("primary_resets_at") if isinstance(info, dict) else None
                            ) or int(time.time() + 18000)
                        else:
                            status_kwargs["last_quota"] = quota_result_quota_info(info)
                            status_kwargs["quota_resets_at"] = quota_result_resets_at(info) or int(time.time() + 18000)
                        update_account(email, **status_kwargs)

                    if shortage > 0 and len(low_accounts) >= cfg["min_low"]:
                        logger.info(
                            "[巡检] 当前 active 数不足: %d/%d，且检测到低额度账号，触发自动轮转...",
                            local_active_count,
                            target_seats,
                        )
                    elif shortage > 0:
                        logger.info(
                            "[巡检] Team 实际成员数不足（%d/%d），触发自动补位...",
                            actual_team_count,
                            target_seats,
                        )
                    else:
                        logger.info("[巡检] 触发自动轮转...")
                    from autoteam.manager import cmd_rotate

                    try:
                        _start_task(
                            "auto-rotate",
                            cmd_rotate,
                            {
                                "target": target_seats,
                                "trigger": "auto-check",
                                "shortage": shortage,
                                "low_accounts": len(low_accounts),
                            },
                            target_seats,
                        )
                    except Exception as e:
                        logger.error("[巡检] 自动轮转失败: %s", e)
                else:
                    logger.info(
                        "[巡检] Team 实际成员数超出目标（%d/%d），触发自动清理...",
                        actual_team_count,
                        target_seats,
                    )
                    from autoteam.manager import cmd_cleanup

                    try:
                        _start_task(
                            "auto-cleanup",
                            cmd_cleanup,
                            {
                                "max_seats": target_seats,
                                "trigger": "auto-check",
                                "team_count": actual_team_count,
                            },
                            target_seats,
                        )
                    except Exception as e:
                        logger.error("[巡检] 自动清理失败: %s", e)
            else:
                if low_accounts and actual_team_count >= target_seats:
                    logger.info(
                        "[巡检] 低额度账号未达到触发阈值（%d/%d），且 Team 实际成员数已满足（%d/%d），无需轮转",
                        len(low_accounts),
                        cfg["min_low"],
                        actual_team_count,
                        target_seats,
                    )
                elif low_accounts:
                    logger.info(
                        "[巡检] 低额度账号未达到触发阈值（%d/%d），无需轮转",
                        len(low_accounts),
                        cfg["min_low"],
                    )
                elif team_count_check_failed:
                    logger.info("[巡检] Team 成员数校验失败，且未达到低额度触发阈值，跳过本轮自动动作")
                elif actual_team_count >= target_seats and local_active_count < target_seats:
                    logger.info(
                        "[巡检] Team 实际成员数已满足（%d/%d），当前本地 active=%d/%d，无需补位",
                        actual_team_count,
                        target_seats,
                        local_active_count,
                        target_seats,
                    )
                else:
                    logger.info("[巡检] 额度正常且 active 数充足（%d/%d），无需轮转", local_active_count, target_seats)

        except Exception as e:
            logger.error("[巡检] 巡检异常: %s", e)


class AutoCheckConfig(BaseModel):
    interval: int = 300  # 巡检间隔（秒）
    threshold: int = 10  # 额度阈值（%）
    min_low: int = 2  # 触发轮转的最少账号数


@app.get("/api/config/auto-check")
def get_auto_check_config():
    """获取巡检配置"""
    return _auto_check_config.copy()


@app.put("/api/config/auto-check")
def set_auto_check_config(cfg: AutoCheckConfig):
    """修改巡检配置（运行时生效）"""
    _auto_check_config["interval"] = max(60, cfg.interval)  # 最少 1 分钟
    _auto_check_config["threshold"] = max(1, min(100, cfg.threshold))
    _auto_check_config["min_low"] = max(1, cfg.min_low)
    _auto_check_restart.set()  # 唤醒巡检线程，立即应用新配置
    logger.info(
        "[巡检] 配置已更新: 间隔=%ds 阈值=%d%% 触发=%d个",
        _auto_check_config["interval"],
        _auto_check_config["threshold"],
        _auto_check_config["min_low"],
    )
    return _auto_check_config.copy()


@app.on_event("startup")
def _start_auto_check():
    try:
        from autoteam.auth_storage import ensure_auth_file_permissions

        fixed = ensure_auth_file_permissions()
        if fixed:
            logger.info("[启动] 已修复 %d 个 auths 认证文件权限", fixed)
    except Exception as exc:
        logger.warning("[启动] 修复 auths 认证文件权限失败: %s", exc)

    try:
        from autoteam.flow_runs import mark_interrupted_running_runs

        interrupted = mark_interrupted_running_runs()
        if interrupted:
            logger.warning("[启动] 已标记 %d 条未结束的批量流程为失败", interrupted)
    except Exception as exc:
        logger.warning("[启动] 标记未结束批量流程失败: %s", exc)

    _sync_runtime_env_reload_state()
    thread = threading.Thread(target=_auto_check_loop, daemon=True)
    thread.start()


@app.on_event("shutdown")
def _stop_auto_check():
    _auto_check_stop.set()


# ---------------------------------------------------------------------------
# 前端静态文件
# ---------------------------------------------------------------------------

DIST_DIR = Path(__file__).parent / "web" / "dist"

if DIST_DIR.exists():
    # Vite 构建的 assets 目录
    assets_dir = DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{path:path}")
    def serve_frontend(path: str):
        """兜底路由：serve 前端 SPA"""
        file = DIST_DIR / path
        if file.is_file() and ".." not in path:
            return FileResponse(str(file))
        return FileResponse(str(DIST_DIR / "index.html"))


class _QuietAccessLog(logging.Filter):
    """过滤前端轮询产生的高频访问日志"""

    _quiet_paths = (
        "/api/status",
        "/api/tasks",
        "/api/config/auto-check",
        "/api/config/runtime",
        "/api/admin/status",
        "/api/main-codex/status",
        "/api/manual-account/status",
        "/api/auth/check",
        "/api/setup/status",
    )

    def filter(self, record):
        msg = record.getMessage()
        return not any(p in msg for p in self._quiet_paths)


def start_server(host: str = "0.0.0.0", port: int = 8787):
    """启动 API 服务器"""
    import uvicorn

    # 过滤轮询日志，避免刷屏
    logging.getLogger("uvicorn.access").addFilter(_QuietAccessLog())
    # 首次启动检查配置
    from autoteam.setup_wizard import check_and_setup

    check_and_setup(interactive=True)

    # 重新读取 API_KEY（可能刚刚被向导写入）
    global API_KEY
    from autoteam.config import API_KEY as _fresh_key

    API_KEY = _fresh_key or os.environ.get("API_KEY", "")
    if API_KEY:
        logger.info("[API] API Key 鉴权已启用")
    else:
        logger.warning("[API] 未设置 API_KEY，所有接口无需认证")
    logger.info("[API] 启动 AutoTeam API 服务器 http://%s:%d", host, port)
    if DIST_DIR.exists():
        logger.info("[API] 前端面板 http://%s:%d", host, port)
    logger.info("[API] API 文档 http://%s:%d/docs", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
