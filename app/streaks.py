from __future__ import annotations

from playwright.async_api import Page


CONVERSATION_LIST = '[class*="conversationConversationListwrapper"]'
STREAK_CONVERSATIONS = (
    '[data-e2e="conversation-item"]:has([class*="commonStreakstreakContainer"])'
)
UNLIT_STREAK_CONVERSATIONS = (
    '[data-e2e="conversation-item"]:has('
    '[class*="commonStreakstreakContainer"] [class*="commonStreakicon"][src*="/gray_"]'
    ')'
)
CONVERSATION_TITLE = '[class~="conversationConversationItemtitle"]'


async def discover_streak_friends(page: Page, *, needs_renewal_only: bool = False) -> list[str]:
    """Return friends carrying a streak badge, optionally limited to gray/unlit streaks."""
    conversation_list = page.locator(CONVERSATION_LIST).first
    await conversation_list.wait_for(state="visible", timeout=15_000)
    await conversation_list.evaluate("element => { element.scrollTop = 0; }")
    await page.wait_for_timeout(500)

    names: list[str] = []
    seen: set[str] = set()
    unchanged_at_bottom = 0
    previous_bottom_count: int | None = None

    for _ in range(200):
        selector = UNLIT_STREAK_CONVERSATIONS if needs_renewal_only else STREAK_CONVERSATIONS
        rows = page.locator(selector)
        for index in range(await rows.count()):
            title = rows.nth(index).locator(CONVERSATION_TITLE).first
            if not await title.count():
                continue
            name = (await title.inner_text()).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)

        before = await conversation_list.evaluate(
            """element => ({
                top: element.scrollTop,
                height: element.scrollHeight,
                client: element.clientHeight,
            })"""
        )
        at_bottom = before["top"] + before["client"] >= before["height"] - 2
        if at_bottom:
            await page.wait_for_timeout(750)
            after = await conversation_list.evaluate(
                """element => ({
                    top: element.scrollTop,
                    height: element.scrollHeight,
                    client: element.clientHeight,
                })"""
            )
            if after["height"] == before["height"] and previous_bottom_count == len(names):
                unchanged_at_bottom += 1
            else:
                unchanged_at_bottom = 0
            previous_bottom_count = len(names)
            if unchanged_at_bottom >= 2:
                break
        else:
            unchanged_at_bottom = 0
            previous_bottom_count = None

        await conversation_list.evaluate(
            """element => {
                const step = Math.max(300, Math.floor(element.clientHeight * 0.8));
                element.scrollTop = Math.min(element.scrollTop + step, element.scrollHeight);
            }"""
        )
        await page.wait_for_timeout(500)

    return names
