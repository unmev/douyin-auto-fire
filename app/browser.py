from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.config import ConfigError, parse_auth_json
from app.models import Settings
from app.selectors import (
    DOUYIN_CHAT_URL,
    LOGIN_MARKERS,
    LOGIN_REQUIRED_MARKERS,
    RISK_MARKERS,
    SEARCH_INPUTS,
)


LOGGER = logging.getLogger("douyin_sender")


class AuthenticationError(RuntimeError):
    pass


class RiskControlError(RuntimeError):
    pass


# Collects only safe, whitelisted attributes. It deliberately reads no
# innerText / innerHTML / outerHTML / value, so page content, chat messages
# and friend nicknames can never enter the public diagnostic output.
_DOM_SNAPSHOT_JS = """() => {
  const attrs = el => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type'),
    placeholder: el.getAttribute('placeholder'),
    role: el.getAttribute('role'),
    aria_label: el.getAttribute('aria-label'),
  });
  return {
    inputs: Array.from(document.querySelectorAll('input')).map(attrs),
    textareas: Array.from(document.querySelectorAll('textarea')).map(attrs),
    contenteditable_count: document.querySelectorAll('[contenteditable="true"]').length,
    role_textbox_count: document.querySelectorAll('[role="textbox"]').length,
  };
}"""

_SAFE_ELEMENT_KEYS = ("tag", "type", "placeholder", "role", "aria_label")


@dataclass
class BrowserSession:
    page: Page
    context: BrowserContext


@asynccontextmanager
async def open_douyin(settings: Settings) -> AsyncIterator[BrowserSession]:
    playwright: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    try:
        playwright = await async_playwright().start()
        launch_args = {"headless": settings.headless}
        if settings.browser_path:
            launch_args["executable_path"] = settings.browser_path
        browser = await playwright.chromium.launch(**launch_args)

        context_args = {"viewport": {"width": 1440, "height": 1000}, "locale": "zh-CN"}
        if settings.storage_state:
            state = parse_auth_json(settings.storage_state, "DOUYIN_STORAGE_STATE")
            if not isinstance(state, dict):
                raise ConfigError("DOUYIN_STORAGE_STATE 必须是 JSON 对象")
            context_args["storage_state"] = state
        context = await browser.new_context(**context_args)
        if not settings.storage_state and settings.cookie:
            cookies = parse_auth_json(settings.cookie, "DOUYIN_COOKIE")
            if not isinstance(cookies, list):
                raise ConfigError("DOUYIN_COOKIE 必须是 Cookie 数组")
            await context.add_cookies(_normalize_cookies(cookies))

        page = await context.new_page()
        if settings.trace:
            await context.tracing.start(screenshots=True, snapshots=True, sources=False)
        yield BrowserSession(page=page, context=context)
    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


async def verify_login(page: Page, timeout_ms: int = 15_000) -> None:
    if await _any_visible(page, RISK_MARKERS, timeout_ms=2_000):
        raise RiskControlError("抖音要求进行安全验证，任务已停止")
    if await _any_visible(page, LOGIN_REQUIRED_MARKERS, timeout_ms=2_000):
        raise AuthenticationError("抖音登录状态已失效")
    if not await _any_visible(page, LOGIN_MARKERS, timeout_ms=timeout_ms):
        raise AuthenticationError("未检测到抖音私信页面，登录状态可能失效或页面结构已变化")


async def open_private_messages(page: Page, timeout_ms: int = 15_000) -> None:
    await page.goto(DOUYIN_CHAT_URL, wait_until="domcontentloaded", timeout=45_000)
    # 1. Explicit risk-control page takes priority, independently of login state.
    if await _any_visible(page, RISK_MARKERS, timeout_ms=2_000):
        raise RiskControlError("抖音私信页面要求进行安全验证，任务已停止")
    # 2. An explicit login page is the only signal that lets us attribute to
    #    expired credentials. Marker absence does not imply the credentials are
    #    valid, so search-box detection (steps 3/4) is kept separate.
    if await _any_visible(page, LOGIN_REQUIRED_MARKERS, timeout_ms=2_000):
        raise AuthenticationError("进入抖音私信页面后登录状态失效")
    # 3. Detect the friend search box.
    if await _any_visible(page, SEARCH_INPUTS, timeout_ms):
        await page.wait_for_timeout(3_000)
        return
    # 4. Search box is missing: emit a safe structural diagnostic before
    #    raising, without assuming the cause is expired cookies.
    diagnostic = await _collect_safe_diagnostic(page, LOGIN_REQUIRED_MARKERS, RISK_MARKERS)
    LOGGER.error("未检测到好友搜索框，页面安全诊断:\n%s", diagnostic)
    raise AuthenticationError("已进入抖音私信页面，但没有检测到好友搜索框")


async def save_trace(session: BrowserSession, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await session.context.tracing.stop(path=path)


async def _any_visible(page: Page, selectors: tuple[str, ...], timeout_ms: int) -> bool:
    per_selector = max(250, timeout_ms // max(1, len(selectors)))
    for selector in selectors:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=per_selector)
            return True
        except Exception:
            continue
    return False


async def _collect_safe_diagnostic(
    page: Page,
    login_markers: tuple[str, ...],
    risk_markers: tuple[str, ...],
) -> str:
    url = _safe_url(page.url)
    try:
        title = (await page.title()).strip()
    except Exception:
        title = ""

    try:
        snapshot = await page.evaluate(_DOM_SNAPSHOT_JS) or {}
    except Exception:
        snapshot = {}

    inputs = [_safe_element(item) for item in snapshot.get("inputs", [])]
    textareas = [_safe_element(item) for item in snapshot.get("textareas", [])]
    login_marker = await _any_visible(page, login_markers, timeout_ms=1_000)
    risk_marker = await _any_visible(page, risk_markers, timeout_ms=1_000)
    private_marker = await _any_visible(page, LOGIN_MARKERS, timeout_ms=1_000)

    parts = [
        f"url={url}",
        f"title={title}",
        f"inputs={json.dumps(inputs, ensure_ascii=False)}",
        f"textareas={json.dumps(textareas, ensure_ascii=False)}",
        f"role_textbox_count={snapshot.get('role_textbox_count', 0)}",
        f"contenteditable_count={snapshot.get('contenteditable_count', 0)}",
        f"login_marker={str(login_marker).lower()}",
        f"risk_marker={str(risk_marker).lower()}",
        f"private_marker={str(private_marker).lower()}",
    ]
    return "\n".join(parts)


def _safe_element(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {key: raw.get(key) for key in _SAFE_ELEMENT_KEYS}


def _safe_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _normalize_cookies(cookies: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for index, cookie in enumerate(cookies):
        if not isinstance(cookie, dict):
            raise ConfigError(f"DOUYIN_COOKIE[{index}] 必须是对象")

        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        if name == "":
            continue
        if not isinstance(name, str) or not isinstance(value, str):
            raise ConfigError(f"DOUYIN_COOKIE[{index}] 缺少有效的 name 或 value")
        if not isinstance(domain, str) or not domain:
            raise ConfigError(f"DOUYIN_COOKIE[{index}] 缺少有效的 domain")

        expires = cookie.get("expires", cookie.get("expirationDate", -1))
        if cookie.get("session") is True:
            expires = -1
        if isinstance(expires, bool) or not isinstance(expires, (int, float)):
            expires = -1

        normalized.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": cookie.get("path") if isinstance(cookie.get("path"), str) else "/",
                "expires": expires,
                "httpOnly": bool(cookie.get("httpOnly", False)),
                "secure": bool(cookie.get("secure", False)),
                "sameSite": _normalize_same_site(cookie.get("sameSite")),
            }
        )
    if not normalized:
        raise ConfigError("DOUYIN_COOKIE 没有有效 Cookie")
    return normalized


def _normalize_same_site(value: Any) -> str:
    mapping = {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
    }
    return mapping.get(str(value).lower(), "Lax")
