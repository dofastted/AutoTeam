"""mo.gymbro.cloud 临时邮箱客户端。"""

from __future__ import annotations

import html
import logging
import re
import threading
import time
from urllib.parse import quote

import requests

from autoteam.config import (
    EMAIL_POLL_INTERVAL,
    EMAIL_POLL_TIMEOUT,
    MO_EMAIL_API_KEY,
    MO_EMAIL_BASE_URL,
    MO_EMAIL_DOMAIN,
    MO_EMAIL_EXPIRY_TIME,
    MO_EMAIL_NAME_PREFIX,
    MO_EMAIL_START_INDEX,
)
from autoteam.mail_provider import MAIL_PROVIDER_MO_EMAIL

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15
_PAGE_LIMIT = 100
_CREATE_EMAIL_LOCK = threading.Lock()
_RESERVED_EMAIL_NAMES: set[str] = set()

_VERIFICATION_CODE_PATTERNS = (
    r"(?:temporary\s+(?:openai|chatgpt)\s+login\s+code(?:\s+is)?|verification\s+code(?:\s+is)?|login\s+code(?:\s+is)?|code(?:\s+is)?|验证码(?:为|是)?)\D{0,24}(\d{6})",
    r"\b(\d{6})\b",
)


def normalize_mo_email_base_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    if value.endswith("/api"):
        value = value[: -len("/api")]
    return value.rstrip("/")


def _coerce_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


class MoEmailClient:
    provider_name = MAIL_PROVIDER_MO_EMAIL

    def __init__(self):
        self.base_url = normalize_mo_email_base_url(MO_EMAIL_BASE_URL)
        self.api_key = str(MO_EMAIL_API_KEY or "").strip()
        self.domain = str(MO_EMAIL_DOMAIN or "").strip().lstrip("@")
        self.name_prefix = str(MO_EMAIL_NAME_PREFIX or "abc").strip() or "abc"
        self.start_index = max(1, _coerce_int(MO_EMAIL_START_INDEX, 1))
        self.expiry_time = _coerce_int(MO_EMAIL_EXPIRY_TIME, 3600000)
        self.session = requests.Session()

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }

    def _request(self, method: str, path: str, *, label: str, **kwargs):
        url = f"{self.base_url}{path}"
        response = self.session.request(
            method,
            url,
            headers={**self._headers(), **(kwargs.pop("headers", {}) or {})},
            timeout=_REQUEST_TIMEOUT,
            **kwargs,
        )

        try:
            payload = response.json()
        except Exception as exc:
            excerpt = str(response.text or "").strip().replace("\n", " ")
            if len(excerpt) > 200:
                excerpt = excerpt[:200] + "..."
            raise RuntimeError(f"Mo Email {label}返回了非 JSON 内容: {excerpt}") from exc

        if response.status_code >= 400:
            detail = payload
            if isinstance(payload, dict):
                detail = payload.get("message") or payload.get("detail") or payload.get("error") or payload
            raise RuntimeError(f"Mo Email {label}失败: HTTP {response.status_code} {detail}")

        if (
            isinstance(payload, dict)
            and payload.get("error")
            and not payload.get("emails")
            and not payload.get("messages")
        ):
            raise RuntimeError(f"Mo Email {label}失败: {payload.get('error')}")

        return payload

    @staticmethod
    def _normalize_email(value):
        return str(value or "").strip().lower()

    @staticmethod
    def _html_to_visible_text(value):
        content = str(value or "")
        if not content:
            return ""

        content = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", content)
        content = re.sub(r"(?is)<!--.*?-->", " ", content)
        content = re.sub(r"(?i)<br\\s*/?>", "\n", content)
        content = re.sub(r"(?i)</(?:p|div|tr|table|h[1-6]|li|td|section|article)>", "\n", content)
        content = re.sub(r"(?s)<[^>]+>", " ", content)
        content = html.unescape(content)
        content = re.sub(r"[\t\r\f\v ]+", " ", content)
        content = re.sub(r"\n\s+", "\n", content)
        content = re.sub(r"\n{2,}", "\n", content)
        return content.strip()

    @staticmethod
    def _list_from_payload(payload, keys):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def _unwrap_item(payload, key: str):
        if isinstance(payload, dict) and isinstance(payload.get(key), dict):
            return payload[key]
        return {}

    def _available_domains(self):
        payload = self._request("GET", "/api/config", label="获取系统配置")
        raw = ""
        if isinstance(payload, dict):
            raw = str(payload.get("emailDomains") or payload.get("domains") or "")
        domains = [item.strip().lstrip("@") for item in raw.split(",") if item.strip()]
        return domains, payload

    def login(self):
        domains, _payload = self._available_domains()
        if self.domain and domains and self.domain not in domains:
            raise RuntimeError(f"Mo Email 域名不可用: {self.domain}")
        logger.info("[MoEmail] 连接成功")
        return self.api_key

    def _normalize_account_item(self, item):
        item = item or {}
        email = str(
            item.get("address") or item.get("email") or item.get("mailAddress") or item.get("name") or ""
        ).strip()
        account_id = (
            item.get("id") or item.get("emailId") or item.get("accountId") or item.get("address_id") or item.get("_id")
        )
        return {
            **item,
            "accountId": account_id,
            "id": account_id,
            "email": email,
            "address": email,
        }

    def list_accounts(self, size=200):
        results = []
        cursor = None
        remaining = max(1, int(size or _PAGE_LIMIT))

        while remaining > 0:
            params = {"cursor": cursor} if cursor else None
            payload = self._request("GET", "/api/emails", label="获取邮箱列表", params=params)
            page_items = self._list_from_payload(payload, ("emails", "items", "results", "list"))
            if not page_items:
                break

            for item in page_items:
                account = self._normalize_account_item(item)
                if account.get("email"):
                    results.append(account)
                if len(results) >= remaining:
                    break

            cursor = payload.get("nextCursor") if isinstance(payload, dict) else None
            if not cursor or len(results) >= remaining:
                break

        return results[:remaining]

    def _iter_existing_email_values(self):
        for account in self.list_accounts(size=1000):
            email = account.get("email")
            if email:
                yield email

        try:
            from autoteam.accounts import load_accounts

            for acc in load_accounts():
                email = acc.get("email")
                if email:
                    yield email
        except Exception:
            return

    def _next_prefix(self):
        base = self.name_prefix.strip()
        domain = self.domain.strip().lower()
        pattern = re.compile(rf"^{re.escape(base)}-(\d+)@{re.escape(domain)}$", re.IGNORECASE)
        max_index = self.start_index - 1

        for email in self._iter_existing_email_values():
            match = pattern.match(str(email or "").strip())
            if match:
                max_index = max(max_index, int(match.group(1)))
        for reserved in _RESERVED_EMAIL_NAMES:
            match = pattern.match(reserved)
            if match:
                max_index = max(max_index, int(match.group(1)))

        return f"{base}-{max_index + 1}"

    def create_temp_email(self, prefix=None):
        with _CREATE_EMAIL_LOCK:
            name = str(prefix or "").strip() or self._next_prefix()
            _RESERVED_EMAIL_NAMES.add(f"{name}@{self.domain}".lower())
            payload = self._request(
                "POST",
                "/api/emails/generate",
                label="创建邮箱",
                json={
                    "name": name,
                    "expiryTime": self.expiry_time,
                    "domain": self.domain,
                },
            )

        account_payload = self._unwrap_item(payload, "email")
        if not account_payload:
            account_payload = self._unwrap_item(payload, "data")
        if not account_payload and isinstance(payload, dict):
            account_payload = payload
        account = self._normalize_account_item(account_payload)
        email = account.get("email") or f"{name}@{self.domain}"
        account_id = account.get("accountId") or account.get("id")

        if account_id is None:
            account_id = self._resolve_account_id_for_email(email)

        logger.info("[MoEmail] 临时邮箱已创建: %s (emailId=%s)", email, account_id)
        return account_id, email

    def _resolve_account_id_for_email(self, to_email):
        target = self._normalize_email(to_email)
        if not target:
            return None

        try:
            from autoteam.accounts import load_accounts

            for acc in load_accounts():
                if self._normalize_email(acc.get("email")) == target:
                    account_id = acc.get("mail_account_id") or acc.get("cloudmail_account_id")
                    if account_id is not None:
                        return account_id
        except Exception:
            pass

        try:
            for account in self.list_accounts(size=1000):
                if self._normalize_email(account.get("email")) == target:
                    return account.get("accountId")
        except Exception:
            pass
        return None

    def _normalize_message_item(self, item, account_id=None, to_email=None):
        item = item or {}
        message_id = item.get("id") or item.get("messageId") or item.get("emailId")
        sender = (
            item.get("from_address")
            or item.get("from")
            or item.get("sender")
            or item.get("source")
            or item.get("sendEmail")
            or ""
        )
        recipient = item.get("to_address") or item.get("to") or item.get("recipient") or item.get("toEmail") or to_email
        text_value = item.get("text") or item.get("content") or ""
        html_value = item.get("html") or item.get("htmlContent") or item.get("body_html") or ""
        content = html_value or text_value or item.get("body") or item.get("raw") or ""

        return {
            **item,
            "emailId": message_id,
            "messageId": message_id,
            "accountId": item.get("emailId") or item.get("accountId") or item.get("address_id") or account_id,
            "accountEmail": recipient,
            "receiveEmail": recipient,
            "toEmail": recipient,
            "mailAddress": recipient,
            "email": recipient,
            "sendEmail": str(sender or ""),
            "subject": str(item.get("subject") or ""),
            "text": str(text_value or ""),
            "content": str(content or ""),
            "raw": item.get("raw") or "",
        }

    def _get_message_detail(self, account_id, message_id):
        payload = self._request(
            "GET",
            f"/api/emails/{quote(str(account_id), safe='')}/{quote(str(message_id), safe='')}",
            label="获取单封邮件",
        )
        message = self._unwrap_item(payload, "message")
        if not message:
            message = self._unwrap_item(payload, "data")
        if not message and isinstance(payload, dict):
            message = payload
        return message

    def search_emails_by_recipient(self, to_email, size=10, account_id=None):
        target_email = str(to_email or "").strip()
        if not target_email:
            return []

        resolved_account_id = account_id or self._resolve_account_id_for_email(target_email)
        if resolved_account_id is None:
            return []

        payload = self._request(
            "GET",
            f"/api/emails/{quote(str(resolved_account_id), safe='')}",
            label="获取邮件列表",
        )
        page_items = self._list_from_payload(payload, ("messages", "emails", "items", "results", "list"))
        emails = []
        for item in page_items[: max(1, int(size or 10))]:
            normalized = self._normalize_message_item(item, account_id=resolved_account_id, to_email=target_email)
            message_id = normalized.get("messageId")
            if message_id and not normalized.get("content"):
                try:
                    detail = self._get_message_detail(resolved_account_id, message_id)
                    normalized = self._normalize_message_item(
                        detail,
                        account_id=resolved_account_id,
                        to_email=target_email,
                    )
                except Exception:
                    pass
            emails.append(normalized)
        return emails

    def list_emails(self, account_id, size=10):
        for account in self.list_accounts(size=1000):
            if str(account.get("accountId")) == str(account_id):
                return self.search_emails_by_recipient(account.get("email"), size=size, account_id=account_id)
        return []

    def wait_for_email(self, to_email, timeout=None, sender_keyword=None):
        timeout = EMAIL_POLL_TIMEOUT if timeout is None else timeout
        logger.info("[MoEmail] 等待邮件到达 %s... (超时 %ss)", to_email, "不限" if timeout == 0 else timeout)
        start = time.time()

        while timeout == 0 or time.time() - start < timeout:
            emails = self.search_emails_by_recipient(to_email)
            for email_item in emails:
                sender = str(email_item.get("sendEmail") or "")
                if sender_keyword and sender_keyword.lower() not in sender.lower():
                    continue
                subject = email_item.get("subject", "")
                logger.info("[MoEmail] 收到邮件: %s (from: %s)", subject, sender)
                return email_item

            elapsed = int(time.time() - start)
            print(f"\r[MoEmail] 等待中... ({elapsed}s)", end="", flush=True)
            time.sleep(EMAIL_POLL_INTERVAL)

        print()
        raise TimeoutError("等待邮件超时")

    def extract_verification_code(self, email_data):
        sources = []

        plain_text = str(email_data.get("text") or "").strip()
        if plain_text:
            sources.append(plain_text)

        html_text = self._html_to_visible_text(email_data.get("content"))
        if html_text and html_text not in sources:
            sources.append(html_text)

        raw_text = self._html_to_visible_text(email_data.get("raw"))
        if raw_text and raw_text not in sources:
            sources.append(raw_text)

        for source in sources:
            for pattern in _VERIFICATION_CODE_PATTERNS:
                match = re.search(pattern, source, re.IGNORECASE)
                if match:
                    return match.group(1)

        return None

    def extract_invite_link(self, email_data):
        html_value = str(email_data.get("content") or "")
        text_value = str(email_data.get("text") or "")
        raw_value = str(email_data.get("raw") or "")

        links = re.findall(r'href="(https://chatgpt\.com/auth/login\?[^"]*)"', html_value)
        if links:
            link = links[0]
            logger.info("[MoEmail] 提取到邀请链接: %s...", link[:80])
            return link

        links = re.findall(r'(https://chatgpt\.com/auth/login\?[^\s<>"\']+)', text_value)
        if links:
            link = links[0]
            logger.info("[MoEmail] 提取到邀请链接: %s...", link[:80])
            return link

        match = re.search(
            r'https?://[^\s<>"\']+(?:invite|accept|join|workspace)[^\s<>"\']*',
            html_value or text_value or raw_value,
            re.IGNORECASE,
        )
        if match:
            link = match.group(0)
            logger.info("[MoEmail] 提取到链接: %s...", link[:80])
            return link

        return None

    def delete_emails_for(self, to_email):
        logger.info("[MoEmail] 当前接口未提供删除邮件能力，跳过: %s", to_email)
        return 0

    def delete_account(self, account_id):
        logger.info("[MoEmail] 当前接口未提供删除邮箱能力，跳过 (emailId=%s)", account_id)
        return {"code": 501, "success": False, "message": "Mo Email API does not provide delete endpoint"}
