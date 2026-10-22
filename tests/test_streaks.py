from __future__ import annotations

from typing import Any

import pytest

from app.streaks import (
    CONVERSATION_LIST,
    CONVERSATION_TITLE,
    STREAK_CONVERSATIONS,
    UNLIT_STREAK_CONVERSATIONS,
    discover_streak_friends,
)


class FakeLocator:
    def __init__(self, names: list[str] | None = None) -> None:
        self.names = names or []
        self.first = self
        self.evaluate_calls = 0

    async def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "visible"
        assert timeout == 15_000

    async def evaluate(self, script: str) -> Any:
        if "scrollTop = 0" in script:
            return None
        self.evaluate_calls += 1
        if "top: element.scrollTop" in script:
            return {"top": 0, "height": 100, "client": 100}
        return None

    async def count(self) -> int:
        return len(self.names)

    def nth(self, index: int) -> "FakeRow":
        return FakeRow(self.names[index])


class FakeRow:
    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def first(self) -> "FakeRow":
        return self

    def locator(self, selector: str) -> "FakeRow":
        assert selector == CONVERSATION_TITLE
        return self

    async def count(self) -> int:
        return 1

    async def inner_text(self) -> str:
        return self.name


class FakePage:
    def __init__(self, names: list[str]) -> None:
        self.conversation_list = FakeLocator()
        self.rows = FakeLocator(names)
        self.selectors: list[str] = []

    def locator(self, selector: str) -> FakeLocator:
        self.selectors.append(selector)
        if selector == CONVERSATION_LIST:
            return self.conversation_list
        return self.rows

    async def wait_for_timeout(self, _: int) -> None:
        return None


@pytest.mark.asyncio
async def test_discovers_unique_streak_friend_names() -> None:
    page = FakePage(["好友甲", "好友甲", "好友乙"])

    names = await discover_streak_friends(page)

    assert names == ["好友甲", "好友乙"]
    assert STREAK_CONVERSATIONS in page.selectors


@pytest.mark.asyncio
async def test_limits_discovery_to_unlit_streaks_when_requested() -> None:
    page = FakePage(["好友甲"])

    await discover_streak_friends(page, needs_renewal_only=True)

    assert UNLIT_STREAK_CONVERSATIONS in page.selectors
