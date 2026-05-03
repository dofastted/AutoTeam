#!/usr/bin/env python3
"""Scan Codex auth files, refresh expired tokens, and report invalidated ones.

This script ports key parts from CLIProxyAPI's Codex implementation and
extends the original 401 scanner with a built-in **detect + extract** pass:

  1. Probe each auth file against ``/backend-api/codex/responses``.
  2. Classify response as one of:
        - auth_ok   : HTTP 200, or HTTP 400 "<model> not supported"
                      (auth headers accepted; only model rejected)
        - quota_lim : HTTP 429 / explicit ``usage_limit_reached``
        - 401       : token invalidated
        - other     : 5xx, network errors, parse errors
  3. For 401 results, run a refresh_token round-trip via
     ``https://auth.openai.com/oauth/token``. If the refresh succeeds,
     persist the new access_token / refresh_token back into the auth JSON
     atomically, then re-probe. The result is upgraded to *refreshed*.
  4. Emit a final classification (auth_ok / refreshed / invalidated /
     quota_lim / other) and optional JSON report.

Failure mode "refresh also fails" is reported as *invalidated*, since the
account is no longer recoverable without a full browser re-login. Browser
re-login is intentionally **not** attempted by this script.

Usage examples:

  python scripts/codex_quota_401_scanner.py --auth-dir ./auths
  python scripts/codex_quota_401_scanner.py --auth-dir ./auths --output-json
  python scripts/codex_quota_401_scanner.py --auth-dir ./auths --no-refresh
  python scripts/codex_quota_401_scanner.py --auth-dir ./auths \
      --invalidated-dir ./auths/invalidated
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib import error, parse, request


DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_REFRESH_URL = "https://auth.openai.com/oauth/token"
DEFAULT_AUTH_DIR = "./auths"
DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_VERSION = "0.98.0"
DEFAULT_USER_AGENT = "codex_cli_rs/0.98.0 (python-port)"
DEFAULT_WORKERS = min(16, max(2, (os.cpu_count() or 1) * 2))
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF = 0.6
DEFAULT_INVALIDATED_DIR_NAME = "invalidated"
DEFAULT_EXCEEDED_DIR_NAME = "exceeded"

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_CYAN = "\033[36m"
ANSI_MAGENTA = "\033[35m"
ANSI_BLUE = "\033[34m"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    file: str
    provider: str
    email: str
    account_id: str
    status_code: int | None
    classification: str  # auth_ok / refreshed / 401 / quota_lim / other
    auth_ok: bool
    unauthorized_401: bool
    quota_exceeded: bool
    refresh_attempted: bool
    refresh_succeeded: bool
    refresh_error: str
    quota_resets_at: int | None
    error: str
    response_preview: str
    final_status_code: int | None  # status after optional refresh+re-probe


@dataclass
class DeleteError:
    file: str
    error: str


# ---------------------------------------------------------------------------
# Color / output helpers
# ---------------------------------------------------------------------------


def _is_tty_stdout() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _supports_color(disabled: bool) -> bool:
    return (not disabled) and _is_tty_stdout() and ("NO_COLOR" not in os.environ)


def _paint(text: str, *codes: str, enabled: bool) -> str:
    if not enabled or not codes:
        return text
    return "".join(codes) + text + ANSI_RESET


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return "." * limit
    return text[: limit - 3] + "..."


class _ProgressDisplay:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._last_len = 0
        self._finished = False

    def update(self, current: int, total: int, label: str) -> None:
        if not self.enabled or total <= 0:
            return
        width = shutil.get_terminal_size(fallback=(100, 20)).columns
        bar_width = max(12, min(30, width - 56))
        percent = int((current * 100) / total)
        filled = int((current * bar_width) / total)
        bar = "#" * filled + "-" * (bar_width - filled)
        message = f"[{bar}] {current}/{total} {percent:>3}% {_truncate(label, 32)}"
        message = _truncate(message, max(10, width - 1))
        padding = " " * max(0, self._last_len - len(message))
        sys.stdout.write(f"\r{message}{padding}")
        sys.stdout.flush()
        self._last_len = len(message)

    def finish(self) -> None:
        if not self.enabled or self._finished:
            return
        self._finished = True
        sys.stdout.write("\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _first_non_empty_str(values: Iterable[Any]) -> str:
    for value in values:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return ""


def _dot_get(data: Any, dotted_key: str) -> Any:
    current = data
    for key in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _pick(data: dict[str, Any], candidates: list[str]) -> str:
    values = [_dot_get(data, key) for key in candidates]
    return _first_non_empty_str(values)


def _looks_like_codex(path: Path, payload: dict[str, Any]) -> bool:
    provider = _pick(payload, ["type", "provider", "metadata.type"])
    if provider:
        return provider.lower() == "codex"

    name = path.name.lower()
    if name.startswith("codex-"):
        return True

    access_token = _pick(
        payload,
        [
            "access_token",
            "accessToken",
            "token.access_token",
            "token.accessToken",
            "metadata.access_token",
            "metadata.accessToken",
        ],
    )
    refresh_token = _pick(
        payload,
        [
            "refresh_token",
            "refreshToken",
            "token.refresh_token",
            "token.refreshToken",
        ],
    )
    account_id = _pick(
        payload,
        ["account_id", "accountId", "metadata.account_id", "metadata.accountId"],
    )
    return bool(access_token and (refresh_token or account_id))


def _extract_auth_fields(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "provider": _pick(payload, ["type", "provider", "metadata.type"]) or "codex",
        "email": _pick(payload, ["email", "metadata.email", "attributes.email"]),
        "access_token": _pick(
            payload,
            [
                "access_token",
                "accessToken",
                "token.access_token",
                "token.accessToken",
                "metadata.access_token",
                "metadata.accessToken",
            ],
        ),
        "refresh_token": _pick(
            payload,
            [
                "refresh_token",
                "refreshToken",
                "token.refresh_token",
                "token.refreshToken",
            ],
        ),
        "account_id": _pick(
            payload,
            ["account_id", "accountId", "metadata.account_id", "metadata.accountId"],
        ),
        "base_url": _pick(
            payload,
            [
                "base_url",
                "baseUrl",
                "metadata.base_url",
                "metadata.baseUrl",
            ],
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8-sig")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("root JSON value is not an object")
    return obj


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to *path* atomically (temp file + rename in same dir)."""
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _update_token_fields(payload: dict[str, Any], new_access: str, new_refresh: str) -> None:
    """Best-effort update of the same nested location used by _extract_auth_fields."""

    def _set_if_path(prefix: str | None, key: str, value: str) -> bool:
        if not value:
            return False
        node: dict[str, Any] | None
        if prefix is None:
            node = payload
        else:
            node = payload.get(prefix) if isinstance(payload.get(prefix), dict) else None
        if node is None:
            return False
        if key in node:
            node[key] = value
            return True
        return False

    # access_token: try every known path; if none found, set top-level
    access_paths = [
        (None, "access_token"),
        (None, "accessToken"),
        ("token", "access_token"),
        ("token", "accessToken"),
        ("metadata", "access_token"),
        ("metadata", "accessToken"),
    ]
    if not any(_set_if_path(prefix, key, new_access) for prefix, key in access_paths):
        payload["access_token"] = new_access

    if new_refresh:
        refresh_paths = [
            (None, "refresh_token"),
            (None, "refreshToken"),
            ("token", "refresh_token"),
            ("token", "refreshToken"),
            ("metadata", "refresh_token"),
            ("metadata", "refreshToken"),
        ]
        if not any(_set_if_path(prefix, key, new_refresh) for prefix, key in refresh_paths):
            payload["refresh_token"] = new_refresh

    payload["last_refresh"] = int(time.time())


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_request(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, bytes]:
    req = request.Request(url=url, data=body, method=method.upper())
    for key, value in headers.items():
        req.add_header(key, value)

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except error.HTTPError as exc:
        return int(exc.code), exc.read()


def _http_request_with_retry(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
    retry_attempts: int,
    retry_backoff: float,
) -> tuple[int, bytes]:
    last_exc: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            return _http_request(
                url=url,
                method=method,
                headers=headers,
                body=body,
                timeout=timeout,
            )
        except error.URLError as exc:
            last_exc = exc
            if attempt >= retry_attempts:
                break
            if retry_backoff > 0:
                time.sleep(retry_backoff * (2 ** (attempt - 1)))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("request failed without a captured exception")


# ---------------------------------------------------------------------------
# Quota / auth detection
# ---------------------------------------------------------------------------


_QUOTA_EXCEEDED_TEXT_MARKERS = (
    "usage_limit_reached",
    "usage limit has been reached",
    "quota exceeded",
    "limit exceeded",
    "超出配额",
    "额度已用完",
)

_MODEL_NOT_SUPPORTED_MARKERS = (
    "is not supported when using codex",
    "model is not supported",
    "model not supported",
    "is not supported with",
    "is not available",
)


def _detect_quota_exceeded(response_text: str) -> tuple[bool, int | None]:
    if not response_text:
        return False, None
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict) and err.get("type") == "usage_limit_reached":
            resets_at = err.get("resets_at")
            if isinstance(resets_at, (int, float)):
                return True, int(resets_at)
            return True, None
    lowered = response_text.lower()
    if any(marker in lowered for marker in _QUOTA_EXCEEDED_TEXT_MARKERS):
        return True, None
    return False, None


def _is_auth_ok(status_code: int | None, response_text: str) -> bool:
    """Return True when the credentials are accepted by Codex API.

    Treats:
      - 2xx as auth_ok.
      - HTTP 400 ``<model> is not supported when using codex...`` as auth_ok
        (the auth header passed; only the model selection failed).
    """
    if status_code is None:
        return False
    if 200 <= status_code < 300:
        return True
    if status_code == 400 and response_text:
        lowered = response_text.lower()
        if any(marker in lowered for marker in _MODEL_NOT_SUPPORTED_MARKERS):
            return True
    return False


def _classify(
    status_code: int | None,
    response_text: str,
    quota_exceeded: bool,
) -> str:
    if status_code is None:
        return "other"
    if status_code == 401:
        return "401"
    if quota_exceeded or status_code == 429:
        return "quota_lim"
    if _is_auth_ok(status_code, response_text):
        return "auth_ok"
    return "other"


# ---------------------------------------------------------------------------
# Refresh + probe
# ---------------------------------------------------------------------------


def _refresh_access_token(
    refresh_url: str, refresh_token: str, timeout: float
) -> tuple[str, str]:
    body = parse.urlencode(
        {
            "client_id": DEFAULT_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "openid profile email",
        }
    ).encode("utf-8")
    status, resp_body = _http_request(
        url=refresh_url,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        body=body,
        timeout=timeout,
    )
    if status != 200:
        msg = resp_body.decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"refresh failed with {status}: {msg}")
    try:
        parsed = json.loads(resp_body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"refresh response is not valid JSON: {exc}") from exc
    new_token = _first_non_empty_str([parsed.get("access_token")])
    new_refresh = _first_non_empty_str([parsed.get("refresh_token")])
    if not new_token:
        raise RuntimeError("refresh succeeded but access_token missing")
    return new_token, new_refresh


def _build_probe_headers(access_token: str, account_id: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Version": DEFAULT_VERSION,
        "Openai-Beta": "responses=experimental",
        "User-Agent": DEFAULT_USER_AGENT,
        "Originator": "codex_cli_rs",
    }
    if account_id:
        headers["Chatgpt-Account-Id"] = account_id
    return headers


def _build_probe_body(model: str) -> bytes:
    payload = {
        "model": model,
        "stream": True,
        "store": False,
        "instructions": "",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "ping"}],
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _probe(
    access_token: str,
    account_id: str,
    *,
    base_url: str,
    quota_path: str,
    model: str,
    timeout: float,
    retry_attempts: int,
    retry_backoff: float,
) -> tuple[int | None, str, str]:
    """Run the Codex /responses probe. Returns (status, body_text, error_msg)."""
    probe_url = base_url.rstrip("/") + "/" + quota_path.lstrip("/")
    headers = _build_probe_headers(access_token, account_id)
    body = _build_probe_body(model)
    try:
        status, resp_body = _http_request_with_retry(
            url=probe_url,
            method="POST",
            headers=headers,
            body=body,
            timeout=timeout,
            retry_attempts=retry_attempts,
            retry_backoff=retry_backoff,
        )
        return status, resp_body.decode("utf-8", errors="replace"), ""
    except error.URLError as exc:
        return None, "", f"network error: {exc}"


def _scan_single_file(path: Path, args: argparse.Namespace) -> list[CheckResult]:
    try:
        payload = _load_json(path)
    except Exception as exc:  # noqa: BLE001
        return [
            CheckResult(
                file=str(path),
                provider="unknown",
                email="",
                account_id="",
                status_code=None,
                classification="other",
                auth_ok=False,
                unauthorized_401=False,
                quota_exceeded=False,
                refresh_attempted=False,
                refresh_succeeded=False,
                refresh_error="",
                quota_resets_at=None,
                error=f"parse error: {exc}",
                response_preview="",
                final_status_code=None,
            )
        ]

    if not _looks_like_codex(path, payload):
        return []

    fields = _extract_auth_fields(payload)
    access_token = fields["access_token"]
    refresh_token = fields["refresh_token"]
    base_url = fields["base_url"] or args.base_url

    if not access_token:
        return [
            CheckResult(
                file=str(path),
                provider=fields["provider"],
                email=fields["email"],
                account_id=fields["account_id"],
                status_code=None,
                classification="other",
                auth_ok=False,
                unauthorized_401=False,
                quota_exceeded=False,
                refresh_attempted=False,
                refresh_succeeded=False,
                refresh_error="",
                quota_resets_at=None,
                error="missing access token",
                response_preview="",
                final_status_code=None,
            )
        ]

    status, body_text, err_msg = _probe(
        access_token,
        fields["account_id"],
        base_url=base_url,
        quota_path=args.quota_path,
        model=args.model,
        timeout=args.timeout,
        retry_attempts=args.retry_attempts,
        retry_backoff=args.retry_backoff,
    )

    quota_exceeded, resets_at = _detect_quota_exceeded(body_text)
    classification = _classify(status, body_text, quota_exceeded)
    final_status = status

    refresh_attempted = False
    refresh_succeeded = False
    refresh_error = ""

    if (
        not args.no_refresh
        and classification == "401"
        and refresh_token
    ):
        refresh_attempted = True
        try:
            new_access, new_refresh = _refresh_access_token(
                args.refresh_url, refresh_token, args.timeout
            )
            payload2 = dict(payload)
            _update_token_fields(payload2, new_access, new_refresh or refresh_token)
            if not args.dry_run:
                _atomic_write_json(path, payload2)
            access_token = new_access
            # re-probe with the refreshed token
            status2, body_text2, err_msg2 = _probe(
                new_access,
                fields["account_id"],
                base_url=base_url,
                quota_path=args.quota_path,
                model=args.model,
                timeout=args.timeout,
                retry_attempts=args.retry_attempts,
                retry_backoff=args.retry_backoff,
            )
            quota_exceeded2, resets_at2 = _detect_quota_exceeded(body_text2)
            new_class = _classify(status2, body_text2, quota_exceeded2)
            final_status = status2
            if new_class == "auth_ok":
                classification = "refreshed"
                refresh_succeeded = True
                quota_exceeded = quota_exceeded2
                resets_at = resets_at2
                body_text = body_text2
                err_msg = err_msg2
            else:
                classification = new_class  # may still be 401 / quota_lim / other
                refresh_succeeded = (new_class != "401")
                quota_exceeded = quota_exceeded2
                resets_at = resets_at2
                body_text = body_text2
                err_msg = err_msg2
                if new_class == "401":
                    refresh_error = "re-probe still 401 after refresh"
        except Exception as exc:  # noqa: BLE001
            refresh_error = str(exc)

    auth_ok = _is_auth_ok(final_status, body_text) or classification == "refreshed"

    return [
        CheckResult(
            file=str(path),
            provider=fields["provider"],
            email=fields["email"],
            account_id=fields["account_id"],
            status_code=status,
            classification=classification,
            auth_ok=auth_ok,
            unauthorized_401=(classification == "401"),
            quota_exceeded=quota_exceeded,
            refresh_attempted=refresh_attempted,
            refresh_succeeded=refresh_succeeded,
            refresh_error=refresh_error,
            quota_resets_at=resets_at,
            error=err_msg,
            response_preview=body_text[:300],
            final_status_code=final_status,
        )
    ]


def scan_auth_files(
    args: argparse.Namespace,
    progress_callback: Callable[[int, int, Path], None] | None = None,
) -> list[CheckResult]:
    auth_dir = Path(args.auth_dir).expanduser().resolve()
    if not auth_dir.exists() or not auth_dir.is_dir():
        raise FileNotFoundError(f"auth directory not found: {auth_dir}")

    if args.recursive:
        json_files = sorted(auth_dir.rglob("*.json"))
    else:
        json_files = sorted(auth_dir.glob("*.json"))
    total_json = len(json_files)
    if total_json == 0:
        return []

    indexed_results: list[tuple[int, list[CheckResult]]] = []
    workers = max(1, min(args.workers, total_json))
    if workers <= 1:
        for index, path in enumerate(json_files, start=1):
            if progress_callback is not None:
                progress_callback(index, total_json, path)
            file_results = _scan_single_file(path, args)
            if file_results:
                indexed_results.append((index, file_results))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_scan_single_file, path, args): (index, path)
                for index, path in enumerate(json_files, start=1)
            }
            completed = 0
            for future in as_completed(future_map):
                completed += 1
                index, path = future_map[future]
                if progress_callback is not None:
                    progress_callback(completed, total_json, path)
                try:
                    file_results = future.result()
                except Exception as exc:  # noqa: BLE001
                    file_results = [
                        CheckResult(
                            file=str(path),
                            provider="unknown",
                            email="",
                            account_id="",
                            status_code=None,
                            classification="other",
                            auth_ok=False,
                            unauthorized_401=False,
                            quota_exceeded=False,
                            refresh_attempted=False,
                            refresh_succeeded=False,
                            refresh_error="",
                            quota_resets_at=None,
                            error=f"internal error: {exc}",
                            response_preview="",
                            final_status_code=None,
                        )
                    ]
                if file_results:
                    indexed_results.append((index, file_results))

    indexed_results.sort(key=lambda item: item[0])
    return [row for _, group in indexed_results for row in group]


# ---------------------------------------------------------------------------
# Output / reporting
# ---------------------------------------------------------------------------


def _classification_label(classification: str, use_color: bool) -> str:
    mapping = {
        "auth_ok":   ("OK",  ANSI_GREEN, ANSI_BOLD),
        "refreshed": ("REF", ANSI_BLUE,  ANSI_BOLD),
        "401":       ("401", ANSI_RED,   ANSI_BOLD),
        "quota_lim": ("LIM", ANSI_MAGENTA, ANSI_BOLD),
        "other":     ("ERR", ANSI_YELLOW, ANSI_BOLD),
    }
    text, *codes = mapping.get(classification, (classification.upper(),))
    return _paint(text, *codes, enabled=use_color)


def _print_table(results: list[CheckResult], use_color: bool) -> None:
    if not results:
        print(_paint("No codex auth files found.", ANSI_YELLOW, enabled=use_color))
        return

    counts: dict[str, int] = {}
    for r in results:
        counts[r.classification] = counts.get(r.classification, 0) + 1

    print(_paint("Scan Summary", ANSI_BOLD, ANSI_CYAN, enabled=use_color))
    print(f"  total checked       : {len(results)}")
    print(f"  auth_ok             : {counts.get('auth_ok', 0)}")
    print(f"  refreshed           : {counts.get('refreshed', 0)}")
    print(f"  invalidated (401)   : {counts.get('401', 0)}")
    print(f"  quota_lim           : {counts.get('quota_lim', 0)}")
    print(f"  other / errors      : {counts.get('other', 0)}")
    refresh_attempted = sum(1 for r in results if r.refresh_attempted)
    refresh_ok = sum(1 for r in results if r.refresh_attempted and r.refresh_succeeded)
    if refresh_attempted:
        print(
            f"  refresh attempts    : {refresh_attempted} (succeeded: {refresh_ok}, failed: {refresh_attempted - refresh_ok})"
        )
    print()

    sections = [
        ("Invalidated (401, refresh failed)", "401", ANSI_RED),
        ("Refreshed (recovered)", "refreshed", ANSI_BLUE),
        ("Quota Exceeded", "quota_lim", ANSI_MAGENTA),
        ("Other / Errors", "other", ANSI_YELLOW),
        ("Auth OK", "auth_ok", ANSI_GREEN),
    ]
    for header, cls, color in sections:
        rows = [r for r in results if r.classification == cls]
        if not rows:
            continue
        print(_paint(header, ANSI_BOLD, color, enabled=use_color))
        for r in rows:
            email = f" ({r.email})" if r.email else ""
            label = _classification_label(r.classification, use_color)
            extra = ""
            if r.refresh_error:
                extra = f" :: refresh_error={_truncate(r.refresh_error, 80)}"
            elif r.error:
                extra = f" :: {_truncate(r.error, 80)}"
            elif cls == "other" and r.response_preview:
                extra = f" :: {_truncate(r.response_preview.replace(chr(10), ' '), 80)}"
            print(f"  [{label}] {r.file}{email}{extra}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Detect Codex auth file 401 / quota issues, and extract fresh "
            "access_tokens via refresh_token round-trip when possible."
        )
    )
    parser.add_argument(
        "--auth-dir",
        default=DEFAULT_AUTH_DIR,
        help=f"Folder containing auth JSON files (default: {DEFAULT_AUTH_DIR}).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse into subfolders of --auth-dir (default: top-level only).",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_CODEX_BASE_URL,
        help=f"Codex base URL (default: {DEFAULT_CODEX_BASE_URL})",
    )
    parser.add_argument(
        "--quota-path",
        default="/responses",
        help="API path used for the auth probe (default: /responses)",
    )
    parser.add_argument(
        "--model",
        default="gpt-5",
        help="Model used in probe request body (default: gpt-5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20,
        help="HTTP timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent workers for file scan/probe (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=DEFAULT_RETRY_ATTEMPTS,
        help=f"Total HTTP attempts per probe (default: {DEFAULT_RETRY_ATTEMPTS})",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF,
        help=f"Base seconds for exponential retry backoff (default: {DEFAULT_RETRY_BACKOFF})",
    )
    parser.add_argument(
        "--refresh-url",
        default=DEFAULT_REFRESH_URL,
        help=f"Token refresh endpoint (default: {DEFAULT_REFRESH_URL})",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Do not attempt to refresh 401 access_tokens.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe and refresh in-memory but do not write back to disk.",
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Emit JSON report to stdout instead of the human-readable table.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable live scan progress in terminal output.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output.",
    )
    parser.add_argument(
        "--invalidated-dir",
        default=None,
        help=(
            "Directory to move auth files that remain 401 after refresh. "
            f"Defaults to '<auth-dir>/{DEFAULT_INVALIDATED_DIR_NAME}/'."
        ),
    )
    parser.add_argument(
        "--no-quarantine",
        action="store_true",
        help="Disable moving invalidated files into the invalidated/ folder.",
    )
    return parser


def _move_file_safely(src: Path, dst_dir: Path) -> tuple[str | None, str | None]:
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        counter = 1
        while dst.exists():
            dst = dst_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1
        shutil.move(str(src), str(dst))
        return str(dst), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.retry_attempts < 1:
        parser.error("--retry-attempts must be >= 1")
    if args.retry_backoff < 0:
        parser.error("--retry-backoff must be >= 0")

    use_color = _supports_color(args.no_color) and (not args.output_json)
    progress_enabled = (
        _is_tty_stdout() and (not args.no_progress) and (not args.output_json)
    )
    progress = _ProgressDisplay(progress_enabled)

    auth_dir = Path(args.auth_dir).expanduser().resolve()
    invalidated_dir = (
        Path(args.invalidated_dir).expanduser().resolve()
        if args.invalidated_dir
        else auth_dir / DEFAULT_INVALIDATED_DIR_NAME
    )

    if progress_enabled:
        print(_paint(f"Scanning auth JSON files in {auth_dir} ...", ANSI_DIM, enabled=use_color))

    try:
        results = scan_auth_files(
            args,
            progress_callback=(
                (lambda c, t, p: progress.update(c, t, p.name))
                if progress_enabled
                else None
            ),
        )
    except Exception as exc:  # noqa: BLE001
        progress.finish()
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    progress.finish()

    moved_invalidated: list[str] = []
    move_errors: list[DeleteError] = []
    if not args.no_quarantine and not args.dry_run:
        for r in results:
            if r.classification == "401":
                src = Path(r.file)
                if not src.exists():
                    continue
                dst, err = _move_file_safely(src, invalidated_dir)
                if err:
                    move_errors.append(DeleteError(file=r.file, error=err))
                elif dst:
                    moved_invalidated.append(dst)

    if args.output_json:
        print(
            json.dumps(
                {
                    "results": [asdict(r) for r in results],
                    "quarantine": {
                        "enabled": (not args.no_quarantine) and (not args.dry_run),
                        "invalidated_dir": str(invalidated_dir),
                        "moved_invalidated": moved_invalidated,
                        "move_errors": [asdict(e) for e in move_errors],
                    },
                    "summary": {
                        "total": len(results),
                        "auth_ok": sum(1 for r in results if r.classification == "auth_ok"),
                        "refreshed": sum(1 for r in results if r.classification == "refreshed"),
                        "invalidated_401": sum(1 for r in results if r.classification == "401"),
                        "quota_lim": sum(1 for r in results if r.classification == "quota_lim"),
                        "other": sum(1 for r in results if r.classification == "other"),
                        "refresh_attempted": sum(1 for r in results if r.refresh_attempted),
                        "refresh_succeeded": sum(
                            1 for r in results if r.refresh_attempted and r.refresh_succeeded
                        ),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_table(results, use_color=use_color)
        if moved_invalidated or move_errors:
            print()
            print(
                _paint(
                    f"Quarantine Moves (auth-dir → {invalidated_dir})",
                    ANSI_BOLD,
                    ANSI_RED,
                    enabled=use_color,
                )
            )
            for dst in moved_invalidated:
                print(f"  [{_paint('moved', ANSI_RED, enabled=use_color)}] → {dst}")
            for e in move_errors:
                print(
                    f"  [{_paint('move-failed', ANSI_RED, enabled=use_color)}] {e.file} :: {e.error}"
                )

    has_invalidated = any(r.classification == "401" for r in results)
    return 1 if has_invalidated else 0


if __name__ == "__main__":
    raise SystemExit(main())
