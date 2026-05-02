"""配置文件 - 从 .env 文件或环境变量加载"""

import importlib
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from autoteam import outbound_proxy
from autoteam.textio import parse_env_line, parse_env_value, read_text

# 项目根目录（pyproject.toml 所在位置）
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 加载 .env 文件（从项目根目录）
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in read_text(_env_file).splitlines():
        parsed = parse_env_line(line)
        if parsed:
            key, value = parsed
            os.environ.setdefault(key, value)

outbound_proxy = importlib.reload(outbound_proxy)


def _get_int_env(name: str, default: int) -> int:
    return int(parse_env_value(os.environ.get(name, str(default))))


def _get_bool_env(name: str, default: bool) -> bool:
    raw = parse_env_value(os.environ.get(name, "true" if default else "false")).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


# CloudMail 配置
CLOUDMAIL_BASE_URL = os.environ.get("CLOUDMAIL_BASE_URL", "")
CLOUDMAIL_EMAIL = os.environ.get("CLOUDMAIL_EMAIL", "")
CLOUDMAIL_PASSWORD = os.environ.get("CLOUDMAIL_PASSWORD", "")
CLOUDMAIL_DOMAIN = os.environ.get("CLOUDMAIL_DOMAIN", "")

# 邮箱提供者配置
MAIL_PROVIDER = os.environ.get("MAIL_PROVIDER", "mo_email").strip().lower() or "mo_email"

# Cloudflare Temp Email 配置
CF_TEMP_EMAIL_BASE_URL = os.environ.get("CF_TEMP_EMAIL_BASE_URL", "")
CF_TEMP_EMAIL_ADMIN_PASSWORD = os.environ.get("CF_TEMP_EMAIL_ADMIN_PASSWORD", "")
CF_TEMP_EMAIL_DOMAIN = os.environ.get("CF_TEMP_EMAIL_DOMAIN", "")

# mo.gymbro.cloud 邮箱配置
MO_EMAIL_BASE_URL = os.environ.get("MO_EMAIL_BASE_URL", "https://mo.gymbro.cloud")
MO_EMAIL_API_KEY = os.environ.get("MO_EMAIL_API_KEY", "")
MO_EMAIL_DOMAIN = os.environ.get("MO_EMAIL_DOMAIN", "gymbro.cloud")
MO_EMAIL_NAME_PREFIX = os.environ.get("MO_EMAIL_NAME_PREFIX", "abc")
MO_EMAIL_START_INDEX = _get_int_env("MO_EMAIL_START_INDEX", 1)
MO_EMAIL_EXPIRY_TIME = _get_int_env("MO_EMAIL_EXPIRY_TIME", 3600000)

# ChatGPT Team 配置
CHATGPT_ACCOUNT_ID = os.environ.get("CHATGPT_ACCOUNT_ID", "")

# CPA (CLIProxyAPI) 配置
CPA_URL = os.environ.get("CPA_URL", "")
CPA_KEY = os.environ.get("CPA_KEY", "")

# Sub2API 配置
SUB2API_URL = os.environ.get("SUB2API_URL", "")
SUB2API_EMAIL = os.environ.get("SUB2API_EMAIL", "")
SUB2API_PASSWORD = os.environ.get("SUB2API_PASSWORD", "")
SUB2API_GROUP = os.environ.get("SUB2API_GROUP", "")

# 轮询邮件间隔/超时（秒）
EMAIL_POLL_INTERVAL = _get_int_env("EMAIL_POLL_INTERVAL", 3)
EMAIL_POLL_TIMEOUT = _get_int_env("EMAIL_POLL_TIMEOUT", 300)

# API 鉴权（不设置则不启用）
API_KEY = os.environ.get("API_KEY", "")

# 自动巡检配置
AUTO_CHECK_INTERVAL = _get_int_env("AUTO_CHECK_INTERVAL", 300)  # 巡检间隔（秒），默认 5 分钟
AUTO_CHECK_THRESHOLD = _get_int_env("AUTO_CHECK_THRESHOLD", 10)  # 额度低于此百分比触发轮转，默认 10%
AUTO_CHECK_MIN_LOW = _get_int_env("AUTO_CHECK_MIN_LOW", 2)  # 至少几个账号低于阈值才触发，默认 2
MAX_TEAM_SEATS = 999
TEAM_TARGET_SEATS = min(MAX_TEAM_SEATS, max(1, _get_int_env("TEAM_TARGET_SEATS", MAX_TEAM_SEATS)))  # Team 总人数目标
FILL_BATCH_SIZE = min(MAX_TEAM_SEATS, max(1, _get_int_env("FILL_BATCH_SIZE", 10)))  # 补满成员单次最多新增账号数
BROWSER_PARALLEL_WORKERS = min(3, max(1, _get_int_env("BROWSER_PARALLEL_WORKERS", 1)))  # 浏览器并行窗口数

# 出口代理池配置
OUTBOUND_PROXY_ENABLED = _get_bool_env("OUTBOUND_PROXY_ENABLED", True)
OUTBOUND_PROXY_POOL = os.environ.get("OUTBOUND_PROXY_POOL", outbound_proxy.DEFAULT_PROXY_URL).strip()
OUTBOUND_PROXY_BYPASS = os.environ.get("OUTBOUND_PROXY_BYPASS", outbound_proxy.DEFAULT_BYPASS).strip()
OUTBOUND_PROXY_STRATEGY = os.environ.get("OUTBOUND_PROXY_STRATEGY", "task-sticky").strip() or "task-sticky"
OUTBOUND_PROXY_FAILOVER = _get_bool_env("OUTBOUND_PROXY_FAILOVER", True)

# Playwright 代理配置
_PLAYWRIGHT_BROWSER_MODES = {"hidden", "visible", "embedded"}
_raw_browser_mode = os.environ.get("PLAYWRIGHT_BROWSER_MODE", "").strip().lower()
if _raw_browser_mode in _PLAYWRIGHT_BROWSER_MODES:
    PLAYWRIGHT_BROWSER_MODE = _raw_browser_mode
else:
    PLAYWRIGHT_BROWSER_MODE = "hidden" if _get_bool_env("PLAYWRIGHT_HEADLESS", True) else "visible"
PLAYWRIGHT_HEADLESS = PLAYWRIGHT_BROWSER_MODE == "hidden"


def _get_default_playwright_proxy_url() -> str:
    explicit = os.environ.get("PLAYWRIGHT_PROXY_URL", "").strip()
    if explicit:
        return explicit
    current_proxy = outbound_proxy.current_proxy_url()
    if current_proxy:
        return current_proxy
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


PLAYWRIGHT_PROXY_URL = os.environ.get("PLAYWRIGHT_PROXY_URL", "").strip()
PLAYWRIGHT_PROXY_SERVER = os.environ.get("PLAYWRIGHT_PROXY_SERVER", "").strip()
PLAYWRIGHT_PROXY_USERNAME = os.environ.get("PLAYWRIGHT_PROXY_USERNAME", "").strip()
PLAYWRIGHT_PROXY_PASSWORD = os.environ.get("PLAYWRIGHT_PROXY_PASSWORD", "").strip()
PLAYWRIGHT_PROXY_BYPASS = os.environ.get("PLAYWRIGHT_PROXY_BYPASS", "").strip() or "localhost,127.0.0.1"
PLAYWRIGHT_BROWSER_CHANNEL = os.environ.get("PLAYWRIGHT_BROWSER_CHANNEL", "").strip().lower()
PLAYWRIGHT_BROWSER_EXECUTABLE_PATH = os.environ.get("PLAYWRIGHT_BROWSER_EXECUTABLE_PATH", "").strip()
PLAYWRIGHT_BROWSER_CDP_URL = os.environ.get("PLAYWRIGHT_BROWSER_CDP_URL", "").strip()
PLAYWRIGHT_BROWSER_CDP_COMMAND = os.environ.get("PLAYWRIGHT_BROWSER_CDP_COMMAND", "").strip()
PLAYWRIGHT_USER_DATA_DIR = os.environ.get("PLAYWRIGHT_USER_DATA_DIR", "").strip()  # 固定 Chromium profile，空值时禁用


def _format_proxy_host(hostname: str) -> str:
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]"
    return hostname


def _parse_proxy_url(proxy_url: str):
    if "://" not in proxy_url:
        return {"server": proxy_url}

    parsed = urlsplit(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        return {"server": proxy_url}

    host = _format_proxy_host(parsed.hostname)
    server = f"{parsed.scheme}://{host}"
    if parsed.port:
        server = f"{server}:{parsed.port}"

    proxy = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def get_playwright_launch_options():
    """统一的 Playwright Chromium 启动参数。"""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--window-position=0,0",
        "--window-size=1280,800",
    ]
    options = {
        "headless": PLAYWRIGHT_HEADLESS,
        "args": args,
    }
    if PLAYWRIGHT_BROWSER_EXECUTABLE_PATH:
        options["executable_path"] = PLAYWRIGHT_BROWSER_EXECUTABLE_PATH
    elif PLAYWRIGHT_BROWSER_CHANNEL:
        options["channel"] = PLAYWRIGHT_BROWSER_CHANNEL

    proxy = None
    playwright_proxy_url = _get_default_playwright_proxy_url()
    if playwright_proxy_url:
        proxy = _parse_proxy_url(playwright_proxy_url)
    elif PLAYWRIGHT_PROXY_SERVER:
        proxy = {"server": PLAYWRIGHT_PROXY_SERVER}
        if PLAYWRIGHT_PROXY_USERNAME:
            proxy["username"] = PLAYWRIGHT_PROXY_USERNAME
        if PLAYWRIGHT_PROXY_PASSWORD:
            proxy["password"] = PLAYWRIGHT_PROXY_PASSWORD

    if proxy:
        if PLAYWRIGHT_PROXY_BYPASS:
            proxy["bypass"] = PLAYWRIGHT_PROXY_BYPASS
        options["proxy"] = proxy

    return options
