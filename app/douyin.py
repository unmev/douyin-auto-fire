from __future__ import annotations

import asyncio

from playwright.async_api import Locator, Page

from app.selectors import CHAT_PANEL_MARKERS, MESSAGE_INPUTS, SEARCH_INPUTS


class PageOperationError(RuntimeError):
    pass


RETRY_DELAY_MS = 3_000


class DouyinChat:
    def __init__(
        self,
        page: Page,
        timeout_ms: int = 15_000,
        confirm_timeout_ms: int = 15_000,
    ) -> None:
        self.page = page
        self.timeout_ms = timeout_ms
        self.confirm_timeout_ms = confirm_timeout_ms

    async def open_target(self, name: str, retries: int = 1) -> None:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                await self._open_target_once(name)
                return
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    await self.page.wait_for_timeout(RETRY_DELAY_MS)
        if last_error is not None:
            raise last_error
        raise PageOperationError("打开聊天失败")

    async def _open_target_once(self, name: str) -> None:
        search = await first_visible(self.page, SEARCH_INPUTS, self.timeout_ms)
        await search.click()
        await search.fill("")
        await search.fill(name)
        await self.page.wait_for_timeout(1_500)

        result = await self._search_result(name)
        if result is None:
            raise PageOperationError("搜索不到目标好友")
        await result.click(force=True)
        await self._confirm_opened(name)

    async def _search_result(self, name: str) -> Locator | None:
        # Search mode renders a separate SearchPanel. Its "发消息" action is the
        # correct control; clicking the hidden conversation cache does not mount
        # the composer.
        search_items = self.page.locator('[class*="SearchPanelitem"]').filter(has_text=name)
        for index in range(await search_items.count()):
            item = search_items.nth(index)
            button = item.locator('[class*="SearchPanelitemchat_btn"]').first
            if await button.count():
                return button

        # The nickname node can be hidden while its conversation row is visible.
        # Locate and click the complete row instead of relying on text visibility.
        row_selectors = (
            '[data-e2e="conversation-item"]',
            '[class*="conversationConversationItem"]',
            '[class*="conversation-item"]',
            '[class*="ConversationItem"]',
        )
        for selector in row_selectors:
            rows = self.page.locator(selector).filter(has_text=name)
            for index in range(await rows.count()):
                row = rows.nth(index)
                try:
                    class_name = await row.get_attribute("class") or ""
                    if "wrapper" in class_name or await row.get_attribute("data-e2e") == "conversation-item":
                        return row
                except Exception:
                    continue

        candidates = [self.page.get_by_text(name, exact=True), self.page.get_by_text(name, exact=False)]
        for candidate_group in candidates:
            count = await candidate_group.count()
            visible: list[Locator] = []
            for index in range(count):
                candidate = candidate_group.nth(index)
                try:
                    if await candidate.is_visible():
                        visible.append(candidate)
                except Exception:
                    continue
            if len(visible) == 1:
                return visible[0]
            if len(visible) > 1:
                return visible[0]

        # Some Douyin builds render the title itself as hidden, but keep a visible
        # ancestor as the actionable result. Find that ancestor from the hidden title.
        hidden_titles = self.page.locator('[class*="conversationConversationItemtitle"]').filter(has_text=name)
        for index in range(await hidden_titles.count()):
            row = hidden_titles.nth(index).locator(
                "xpath=ancestor::*[contains(@class, 'conversationConversationItem')][1]"
            )
            if await row.count() and await row.is_visible():
                return row

        for selector in (f'[title="{_css_escape(name)}"]', f'[aria-label="{_css_escape(name)}"]'):
            candidate = self.page.locator(selector).first
            if await candidate.count() and await candidate.is_visible():
                return candidate
        return None

    async def message_input(self) -> Locator:
        return await first_visible(self.page, MESSAGE_INPUTS, self.timeout_ms)

    async def _confirm_opened(self, name: str, timeout_ms: int | None = None) -> None:
        timeout = timeout_ms if timeout_ms is not None else self.confirm_timeout_ms
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while True:
            last_error = await self._chat_open_error(name)
            if last_error is None:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise last_error
            await self.page.wait_for_timeout(500)

    async def _chat_open_error(self, name: str) -> PageOperationError | None:
        for selector in CHAT_PANEL_MARKERS:
            locator = self.page.locator(selector).filter(has_text=name).first
            if await locator.count():
                return None

        composer_visible = await self._composer_visible()
        if composer_visible:
            body_text = ""
            try:
                body_text = (await self.page.locator("body").inner_text())[:1000].replace("\n", " ")
            except Exception:
                body_text = ""
            if name in body_text:
                return None
            text = self.page.get_by_text(name, exact=True)
            for index in range(await text.count()):
                candidate = text.nth(index)
                try:
                    if not await candidate.is_visible():
                        continue
                    class_name = await candidate.get_attribute("class") or ""
                    if "conversationConversationItemtitle" not in class_name:
                        return None
                except Exception:
                    continue
        return PageOperationError(
            f"点击搜索结果后无法确认聊天已打开（输入框: {'有' if composer_visible else '无'}）"
        )

    async def _composer_visible(self) -> bool:
        for selector in MESSAGE_INPUTS:
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    return True
            except Exception:
                continue
        return False


async def first_visible(page: Page, selectors: tuple[str, ...], timeout_ms: int = 15_000) -> Locator:
    per_selector = max(500, timeout_ms // max(1, len(selectors)))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=per_selector)
            return locator
        except Exception:
            continue
    raise PageOperationError(f"找不到页面元素，已尝试: {', '.join(selectors)}")


def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
