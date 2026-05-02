from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AboutYouProfile:
    first_name: str
    last_name: str
    birth_year: int
    birth_month: int
    birth_day: int

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def age(self, *, as_of: date | None = None) -> int:
        today = as_of or date.today()
        years = today.year - self.birth_year
        before_birthday = (today.month, today.day) < (self.birth_month, self.birth_day)
        return years - int(before_birthday)

    def age_text(self, *, as_of: date | None = None) -> str:
        return str(self.age(as_of=as_of))

    def birthdate_values(self) -> dict[str, str]:
        return {
            "year": f"{self.birth_year:04d}",
            "month": f"{self.birth_month:02d}",
            "day": f"{self.birth_day:02d}",
        }


ABOUT_YOU_PROFILES: tuple[AboutYouProfile, ...] = (
    AboutYouProfile("Olivia", "Bennett", 2004, 3, 18),
    AboutYouProfile("Noah", "Carter", 1998, 11, 7),
    AboutYouProfile("Emma", "Brooks", 1993, 6, 24),
    AboutYouProfile("Liam", "Foster", 2001, 9, 12),
    AboutYouProfile("Ava", "Collins", 1988, 2, 9),
    AboutYouProfile("Mason", "Reed", 1996, 8, 30),
    AboutYouProfile("Sophia", "Turner", 2002, 12, 5),
    AboutYouProfile("Ethan", "Hayes", 1991, 4, 14),
    AboutYouProfile("Isabella", "Price", 2008, 1, 27),
    AboutYouProfile("James", "Cooper", 1985, 10, 2),
    AboutYouProfile("Mia", "Morgan", 1999, 7, 21),
    AboutYouProfile("Benjamin", "Ward", 1994, 5, 11),
    AboutYouProfile("Charlotte", "Hughes", 1989, 9, 16),
    AboutYouProfile("Lucas", "Rivera", 2003, 11, 3),
    AboutYouProfile("Amelia", "Sanders", 1997, 1, 8),
    AboutYouProfile("Henry", "Mitchell", 1990, 3, 26),
    AboutYouProfile("Harper", "Jenkins", 2005, 6, 19),
    AboutYouProfile("Alexander", "Perry", 1992, 12, 28),
    AboutYouProfile("Ella", "Richardson", 1987, 7, 4),
    AboutYouProfile("Daniel", "Ross", 2006, 2, 15),
)


def select_about_you_profile(email: str | None = None) -> AboutYouProfile:
    normalized = (email or "").strip().lower()
    if not normalized:
        return ABOUT_YOU_PROFILES[0]
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(ABOUT_YOU_PROFILES)
    return ABOUT_YOU_PROFILES[index]


def _log(logger, level: str, message: str, *args) -> None:
    if logger is None:
        return
    log_fn = getattr(logger, level, None)
    if callable(log_fn):
        log_fn(message, *args)


def _collect_date_spinbutton_meta(page):
    try:
        return page.evaluate(
            """() => {
                const byIdsText = (rawIds) => {
                    return (rawIds || '')
                        .split(/\\s+/)
                        .filter(Boolean)
                        .map(id => {
                            const el = document.getElementById(id);
                            return el ? (el.textContent || '').trim() : '';
                        })
                        .filter(Boolean)
                        .join(' ');
                };

                return Array.from(document.querySelectorAll('[role="spinbutton"]')).map((el, index) => ({
                    index,
                    text: (el.textContent || '').trim(),
                    ariaLabel: el.getAttribute('aria-label') || '',
                    ariaValueText: el.getAttribute('aria-valuetext') || '',
                    ariaValueMin: el.getAttribute('aria-valuemin') || '',
                    ariaValueMax: el.getAttribute('aria-valuemax') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    dataType: el.getAttribute('data-type') || el.dataset?.type || '',
                    labelledText: byIdsText(el.getAttribute('aria-labelledby')),
                    describedText: byIdsText(el.getAttribute('aria-describedby')),
                }));
            }"""
        )
    except Exception:
        return []


def _infer_date_spinbutton_kind(meta):
    text_parts = [
        meta.get("text", ""),
        meta.get("ariaLabel", ""),
        meta.get("ariaValueText", ""),
        meta.get("placeholder", ""),
        meta.get("dataType", ""),
        meta.get("labelledText", ""),
        meta.get("describedText", ""),
    ]
    lowered = " ".join(part for part in text_parts if part).lower()

    def _to_int(value):
        try:
            return int(str(value).strip())
        except Exception:
            return None

    max_val = _to_int(meta.get("ariaValueMax"))

    if any(token in lowered for token in ("year", "yyyy", "yy", "年")):
        return "year"
    if any(token in lowered for token in ("month", "mm", "月")):
        return "month"
    if any(token in lowered for token in ("day", "dd", "日")):
        return "day"

    if max_val is not None:
        if max_val > 31:
            return "year"
        if max_val == 12:
            return "month"
        if max_val <= 31:
            return "day"

    return None


def _fill_birthday_by_meta(page, values: dict[str, str], *, logger=None, log_prefix: str = "[about-you]") -> bool:
    metas = _collect_date_spinbutton_meta(page)
    if len(metas) < 3:
        return False

    kind_to_meta = {}
    for meta in metas:
        kind = _infer_date_spinbutton_kind(meta)
        if kind and kind not in kind_to_meta:
            kind_to_meta[kind] = meta

    if not all(kind in kind_to_meta for kind in values):
        _log(logger, "info", "%s 无法可靠识别生日字段顺序，降级为位置猜测", log_prefix)
        return False

    try:
        for kind in ("year", "month", "day"):
            meta = kind_to_meta[kind]
            spinbutton = page.locator('[role="spinbutton"]').nth(meta["index"])
            spinbutton.click(force=True, timeout=3000)
            time.sleep(0.2)
            try:
                page.keyboard.press("ControlOrMeta+A")
                time.sleep(0.1)
            except Exception:
                pass
            page.keyboard.type(values[kind], delay=80)
            time.sleep(0.3)
        _log(
            logger,
            "info",
            "%s 已按字段识别填入生日: year=%s month=%s day=%s | order=%s",
            log_prefix,
            values["year"],
            values["month"],
            values["day"],
            {kind: kind_to_meta[kind]["index"] for kind in ("year", "month", "day")},
        )
        return True
    except Exception as exc:
        _log(logger, "warning", "%s 按字段填写生日失败，降级为位置猜测: %s", log_prefix, exc)
        return False


def fill_about_you_page(
    page,
    *,
    email: str | None = None,
    logger=None,
    log_prefix: str = "[about-you]",
    submit_timeout: float = 12,
    deadline: float | None = None,
) -> bool:
    if "about-you" not in (page.url or "").lower():
        return True

    def _timed_out() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    profile = select_about_you_profile(email)
    values = profile.birthdate_values()
    birthday_orders = [
        (values["year"], values["month"], values["day"]),
        (values["month"], values["day"], values["year"]),
        (values["day"], values["month"], values["year"]),
    ]

    for attempt, fallback_values in enumerate(birthday_orders, 1):
        if _timed_out():
            _log(logger, "warning", "%s about-you 总耗时已超时，停止填写", log_prefix)
            return False
        if "about-you" not in (page.url or "").lower():
            return True

        try:
            name_input = page.locator(
                'input[name="name"], input[placeholder*="name" i], input[id="name"], input[placeholder*="全名" i]'
            ).first
            if name_input.is_visible(timeout=2000) and name_input.is_editable(timeout=500):
                name_input.fill(profile.full_name, timeout=3000)
                time.sleep(0.3)
        except Exception:
            pass

        try:
            spinbuttons = page.locator('[role="spinbutton"]').all()
        except Exception:
            spinbuttons = []

        if len(spinbuttons) >= 3:
            filled = _fill_birthday_by_meta(page, values, logger=logger, log_prefix=log_prefix)
            if not filled:
                for label_selector in ("text=生日日期", "text=Date of birth"):
                    try:
                        page.locator(label_selector).first.click(timeout=1000)
                        time.sleep(0.3)
                        break
                    except Exception:
                        continue

                try:
                    for spinbutton, fallback_value in zip(spinbuttons[:3], fallback_values):
                        if _timed_out():
                            return False
                        spinbutton.click(force=True, timeout=3000)
                        time.sleep(0.2)
                        try:
                            page.keyboard.press("ControlOrMeta+A")
                            time.sleep(0.1)
                        except Exception:
                            pass
                        page.keyboard.type(fallback_value, delay=80)
                        time.sleep(0.3)
                    _log(
                        logger,
                        "info",
                        "%s 尝试按位置填入生日（第 %d 次）: %s/%s/%s",
                        log_prefix,
                        attempt,
                        *fallback_values,
                    )
                except Exception as exc:
                    _log(logger, "warning", "%s 生日字段填写失败（第 %d 次）: %s", log_prefix, attempt, exc)
        else:
            try:
                age_input = page.locator(
                    'input[name="age"], input[id="age"], input[placeholder*="年龄"], input[placeholder*="Age"], input[type="number"]'
                ).first
                if age_input.is_visible(timeout=2000) and age_input.is_editable(timeout=500):
                    age_input.fill(profile.age_text(), timeout=3000)
                    _log(logger, "info", "%s 填入年龄: %s", log_prefix, profile.age_text())
            except Exception:
                pass

        submitted = False
        for button_selector in (
            'button:has-text("完成帐户创建")',
            'button:has-text("Create account")',
            'button:has-text("Complete")',
            'button:has-text("Continue")',
            'button:has-text("继续")',
            'button[type="submit"]',
        ):
            try:
                button = page.locator(button_selector).first
                if button.is_visible(timeout=1000):
                    button.click(timeout=3000)
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass

        submit_deadline = time.monotonic() + submit_timeout
        if deadline is not None:
            submit_deadline = min(submit_deadline, deadline)
        while time.monotonic() < submit_deadline:
            if "about-you" not in (page.url or "").lower():
                return True
            time.sleep(0.5)

    _log(logger, "warning", "%s about-you 页面仍未完成，当前 URL: %s", log_prefix, page.url)
    return False
