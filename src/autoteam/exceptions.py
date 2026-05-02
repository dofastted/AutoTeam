"""Shared AutoTeam exception types."""

from __future__ import annotations


class PhoneVerificationRequiredError(RuntimeError):
    """Raised when OpenAI requires phone verification for an account."""

    def __init__(self, message: str = "OpenAI 风控要求手机号验证", *, email: str = ""):
        super().__init__(message)
        self.email = (email or "").strip().lower()


class OpenAiCreateAccountBlockedError(RuntimeError):
    """Raised when OpenAI blocks account creation or a known registration gate."""

    def __init__(
        self,
        message: str = "OpenAI 创建账号命中 IP 风控",
        *,
        email: str = "",
        reason: str = "",
    ):
        super().__init__(message)
        self.email = (email or "").strip().lower()
        self.reason = (reason or "").strip().lower()


def is_openai_add_phone_url(value: object) -> bool:
    return "auth.openai.com/add-phone" in str(value or "").strip().lower()
