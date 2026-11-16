from unittest.mock import AsyncMock, MagicMock

import pytest

from app.douyin import DouyinChat, PageOperationError
from app.selectors import CHAT_PANEL_MARKERS, MESSAGE_INPUTS


@pytest.mark.asyncio
async def test_search_failure_raises_without_page_text_or_real_name(monkeypatch) -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    search = MagicMock()
    search.click = AsyncMock()
    search.fill = AsyncMock()
    monkeypatch.setattr("app.douyin.first_visible", AsyncMock(return_value=search))
    chat = DouyinChat(page)
    chat._search_result = AsyncMock(return_value=None)

    with pytest.raises(PageOperationError, match="搜索不到目标好友") as exc_info:
        await chat._open_target_once("张三")

    message = str(exc_info.value)
    assert "当前页面文字" not in message
    assert "张三" not in message


def _locator_group(items: list[MagicMock]) -> MagicMock:
    group = MagicMock()
    group.count = AsyncMock(return_value=len(items))
    group.nth.side_effect = lambda index: items[index]
    if items:
        group.first = items[0]
    else:
        empty = MagicMock()
        empty.count = AsyncMock(return_value=0)
        empty.is_visible = AsyncMock(return_value=False)
        group.first = empty
    return group


def _search_page(names: list[str]) -> tuple[MagicMock, list[MagicMock]]:
    page = MagicMock()
    empty = _locator_group([])
    items: list[MagicMock] = []
    buttons: list[MagicMock] = []

    for displayed_name in names:
        name_node = MagicMock()
        name_node.inner_text = AsyncMock(return_value=f" {displayed_name} ")
        name_node.is_visible = AsyncMock(return_value=True)
        exact_names = _locator_group([name_node])
        button = MagicMock(name=f"message-{displayed_name}")
        button.count = AsyncMock(return_value=1)
        button.is_visible = AsyncMock(return_value=True)
        button_group = _locator_group([button])
        item = MagicMock()
        item.is_visible = AsyncMock(return_value=True)

        def item_locator(
            selector: str,
            *,
            button_group=button_group,
            exact_names=exact_names,
        ):
            if selector == '[class*="SearchPanelitemchat_btn"]':
                return button_group
            if selector == '[class*="SearchPanelitemname"]':
                return exact_names
            return empty

        item.locator.side_effect = item_locator
        items.append(item)
        buttons.append(button)

    search_items = _locator_group(items)

    def page_locator(selector: str):
        if selector == '[class*="SearchPanelitembox"], [class*="SearchPanelitem-box"], [class*="SearchPanelitem_box"]':
            return search_items
        return empty

    page.locator.side_effect = page_locator
    page.get_by_text.return_value = empty
    return page, buttons


@pytest.mark.asyncio
async def test_search_result_selects_exact_name_when_one_name_contains_another() -> None:
    page, buttons = _search_page(["test1", "test"])

    result = await DouyinChat(page)._search_result("test")

    assert result is buttons[1]


@pytest.mark.asyncio
async def test_search_result_selects_longer_exact_name() -> None:
    page, buttons = _search_page(["test1", "test"])

    result = await DouyinChat(page)._search_result("test1")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_keeps_normal_exact_match_working() -> None:
    page, buttons = _search_page(["好友A"])

    result = await DouyinChat(page)._search_result("好友A")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_accepts_group_count_suffix() -> None:
    # Group chats render as "<name>(<member count>)" in the search panel, e.g.
    # target "4161" is displayed as "4161(7)". The strict exact match alone would
    # reject this and break group sending.
    page, buttons = _search_page(["4161(7)"])

    result = await DouyinChat(page)._search_result("4161")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_accepts_fullwidth_group_count_suffix() -> None:
    page, buttons = _search_page(["4161（7）"])

    result = await DouyinChat(page)._search_result("4161")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_prefers_exact_name_over_group_suffix() -> None:
    # When both an exact "test" and a group-suffixed "test(7)" exist, the exact
    # friend must win even though "test(7)" sorts first. A naive single-pass
    # suffix check would wrongly return the group row.
    page, buttons = _search_page(["test(7)", "test"])

    result = await DouyinChat(page)._search_result("test")

    assert result is buttons[1]


@pytest.mark.asyncio
async def test_search_result_rejects_non_digit_group_suffix() -> None:
    # "(abc)" is not a member count; must not match target "test".
    page, _buttons = _search_page(["test(abc)"])

    result = await DouyinChat(page)._search_result("test")

    assert result is None


@pytest.mark.asyncio
async def test_search_result_rejects_containing_name_for_group_rule() -> None:
    # The group-suffix rule must not reintroduce the test/test1 mis-routing:
    # "test1" has no trailing member-count brackets, so it must be rejected.
    page, _buttons = _search_page(["test1"])

    result = await DouyinChat(page)._search_result("test")

    assert result is None


@pytest.mark.asyncio
async def test_search_result_matches_remark_rendered_on_second_line() -> None:
    # Douyin renders a friend remark on the line below the nickname. The
    # configured target can be that visible remark, so one complete line must
    # match without accepting the longer "张张1".
    page, buttons = _search_page(["ᅟᅟ ᅟ ᅟ\n张张"])

    result = await DouyinChat(page)._search_result("张张")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_rejects_longer_remark_line() -> None:
    page, _buttons = _search_page(["ᅟᅟ ᅟ ᅟ\n张张1"])

    result = await DouyinChat(page)._search_result("张张")

    assert result is None


@pytest.mark.asyncio
async def test_open_target_retries_after_failed_first_attempt() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page)
    calls = {"n": 0}

    async def flaky(name: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PageOperationError("首次失败")

    chat._open_target_once = flaky

    await chat.open_target("好友A", retries=1)

    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_open_target_raises_after_retries_exhausted() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page)

    async def fail(name: str) -> None:
        raise PageOperationError("始终失败")

    chat._open_target_once = fail

    with pytest.raises(PageOperationError, match="始终失败"):
        await chat.open_target("好友A", retries=1)

    assert page.wait_for_timeout.await_count == 1


@pytest.mark.asyncio
async def test_open_target_succeeds_without_retry() -> None:
    page = MagicMock()
    chat = DouyinChat(page)

    async def ok(name: str) -> None:
        return None

    chat._open_target_once = ok

    await chat.open_target("好友A", retries=1)

    page.wait_for_timeout.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_opened_polls_until_confirmed() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page, confirm_timeout_ms=5_000)
    results = iter([PageOperationError("未就绪"), None])

    async def checker(name: str):
        return next(results, None)

    chat._chat_open_error = checker

    await chat._confirm_opened("好友A")

    assert page.wait_for_timeout.await_count == 1


@pytest.mark.asyncio
async def test_confirm_opened_raises_on_timeout() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page, confirm_timeout_ms=100)

    async def checker(name: str):
        return PageOperationError("一直失败")

    chat._chat_open_error = checker

    with pytest.raises(PageOperationError, match="一直失败"):
        await chat._confirm_opened("好友A")


def _chat_page(
    header_name: str,
    *,
    input_count: int = 1,
    header_selector: str = CHAT_PANEL_MARKERS[0],
    header_visible: bool = True,
    name_visible: bool = True,
    stale_name: str | None = None,
) -> MagicMock:
    page = MagicMock()
    empty = _locator_group([])
    header_name_node = MagicMock()
    header_name_node.inner_text = AsyncMock(return_value=f" {header_name} ")
    header_name_node.is_visible = AsyncMock(return_value=name_visible)
    nodes = [header_name_node]
    if stale_name is not None:
        stale_node = MagicMock()
        stale_node.inner_text = AsyncMock(return_value=f" {stale_name} ")
        stale_node.is_visible = AsyncMock(return_value=False)
        nodes.append(stale_node)
    exact_names = _locator_group(nodes)
    header = MagicMock()
    header.count = AsyncMock(return_value=1)
    header.is_visible = AsyncMock(return_value=header_visible)
    header.locator.side_effect = lambda selector: exact_names if selector == '[class*="RightPanelHeadertitle"]' else empty

    def header_group() -> MagicMock:
        return _locator_group([header])

    composer_target = MagicMock()
    composer_target.count = AsyncMock(return_value=input_count)
    composer_target.is_visible = AsyncMock(return_value=bool(input_count))
    composer = MagicMock()
    composer.first = composer_target

    def locator_router(selector: str):
        if selector == header_selector:
            return header_group()
        if selector in MESSAGE_INPUTS:
            return composer
        return empty

    page.locator.side_effect = locator_router
    return page


@pytest.mark.asyncio
async def test_chat_open_error_accepts_exact_name_in_each_header_fallback() -> None:
    for header_selector in CHAT_PANEL_MARKERS[:3]:
        page = _chat_page("好友A", header_selector=header_selector)

        error = await DouyinChat(page)._chat_open_error("好友A")

        assert error is None


@pytest.mark.asyncio
async def test_chat_open_error_rejects_hidden_exact_header_name() -> None:
    page = _chat_page("test", header_visible=False)

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_containing_header_name() -> None:
    page = _chat_page("test1")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)
    assert "无法确认聊天已打开" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_hidden_stale_name_in_visible_header() -> None:
    # Visible current chat is `test1`, but the header retains a hidden stale name
    # node equal to the requested `test`. The hidden stale node must not confirm
    # the wrong recipient; only a visible exact title node may.
    page = _chat_page("test1", stale_name="test")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)
    assert "无法确认聊天已打开" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_accepts_group_count_suffix_in_header() -> None:
    # Right-side group chat header shows "4161(7)" while the configured target
    # is bare "4161". Confirmation must succeed so group chats can be sent.
    page = _chat_page("4161(7)")

    error = await DouyinChat(page)._chat_open_error("4161")

    assert error is None


@pytest.mark.asyncio
async def test_chat_open_error_accepts_fullwidth_group_count_suffix_in_header() -> None:
    page = _chat_page("4161（7）")

    error = await DouyinChat(page)._chat_open_error("4161")

    assert error is None


@pytest.mark.asyncio
async def test_chat_open_error_still_rejects_containing_header_name() -> None:
    # The group rule must not weaken the test/test1 guard: a header "test1" must
    # not confirm target "test" (no trailing member-count brackets).
    page = _chat_page("test1")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_hidden_stale_group_name_in_visible_header() -> None:
    # Visible current chat is "test1" but the header retains a hidden stale
    # node "test(7)". The hidden stale node must not confirm target "test";
    # only a visible title node may confirm. This preserves the stale-header
    # safety check under the new group-suffix logic.
    page = _chat_page("test1", stale_name="test(7)")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)
    assert "无法确认聊天已打开" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_when_header_name_absent() -> None:
    page = _chat_page("其他好友", input_count=0)

    error = await DouyinChat(page)._chat_open_error("好友A")

    assert isinstance(error, PageOperationError)
    assert "无法确认聊天已打开" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_accepts_remark_appended_to_nickname() -> None:
    # The chat header concatenates the nickname and remark on one line and puts
    # the streak count on the next line.
    page = _chat_page("ᅟᅟ   ᅟ   ᅟ张张\n478")

    error = await DouyinChat(page)._chat_open_error("张张")

    assert error is None


@pytest.mark.asyncio
async def test_chat_open_error_rejects_longer_remark_in_header() -> None:
    page = _chat_page("ᅟᅟ   ᅟ   ᅟ张张1")

    error = await DouyinChat(page)._chat_open_error("张张")

    assert isinstance(error, PageOperationError)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_hidden_stale_remark_suffix() -> None:
    # A hidden stale node ending with the remark must not confirm a visible
    # header for another friend.
    page = _chat_page("其他好友", stale_name="ᅟᅟ   ᅟ   ᅟ张张")

    error = await DouyinChat(page)._chat_open_error("张张")

    assert isinstance(error, PageOperationError)
    assert "无法确认聊天已打开" in str(error)


# Direct unit tests for the standalone group-suffix matcher. The friend exact
# matcher (_text_equals) stays strict; only this independent helper accepts a
# trailing "(N)" / "（N）" member count, and nothing else.
import re  # noqa: E402

from app.douyin import _group_count_suffix_matches  # noqa: E402


def test_group_count_suffix_matches_accepts_bare_name() -> None:
    assert _group_count_suffix_matches("4161", "4161")


def test_group_count_suffix_matches_accepts_halfwidth_suffix() -> None:
    assert _group_count_suffix_matches("4161(7)", "4161")


def test_group_count_suffix_matches_accepts_fullwidth_suffix() -> None:
    assert _group_count_suffix_matches("4161（123）", "4161")


def test_group_count_suffix_matches_accepts_internal_spaces() -> None:
    assert _group_count_suffix_matches("4161 ( 7 )", "4161")


def test_group_count_suffix_matches_rejects_non_digit_suffix() -> None:
    assert not _group_count_suffix_matches("4161(abc)", "4161")


def test_group_count_suffix_matches_rejects_empty_suffix() -> None:
    assert not _group_count_suffix_matches("4161()", "4161")


def test_group_count_suffix_matches_rejects_trailing_chars() -> None:
    assert not _group_count_suffix_matches("4161(7)abc", "4161")


def test_group_count_suffix_matches_rejects_prefix() -> None:
    assert not _group_count_suffix_matches("abc4161(7)", "4161")


def test_group_count_suffix_matches_rejects_longer_name() -> None:
    # The core test/test1 safety property: expected "test" must not match the
    # longer bare name "test1" (no member-count brackets to legitimize it).
    assert not _group_count_suffix_matches("test1", "test")


def test_group_count_suffix_matches_remark_line_with_suffix() -> None:
    assert _group_count_suffix_matches("ᅟᅟ ᅟ ᅟ\n4161(7)", "4161")


def test_group_count_suffix_matches_rejects_longer_multiline_line() -> None:
    assert not _group_count_suffix_matches("ᅟᅟ ᅟ ᅟ\n4161(7)abc", "4161")


def test_group_count_suffix_matches_escapes_expected_regex_meta() -> None:
    # re.escape must be used so a name like "a.b" is literal, not "any char".
    assert _group_count_suffix_matches("a.b(7)", "a.b")
    assert not _group_count_suffix_matches("aXb(7)", "a.b")


# Suppress the unused `re` import warning the linter may raise for the
# pure-assertion block above; `re` is intentionally kept as a sanity anchor.
_ = re
