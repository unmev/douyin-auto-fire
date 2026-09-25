import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.interrupt import (
    ExecutionInterruptedError,
    ExecutionTimeoutError,
    InterruptController,
    check_interrupted,
    run_with_timeout_and_interrupt,
    signal_interrupt_handler,
)
from app.models import Message, Settings, Target, TaskConfig
import app.main as main_module
import app.account_runner as account_runner_module
import run as run_module


@pytest.mark.asyncio
async def test_run_with_timeout_success():
    async def fast_work():
        await asyncio.sleep(0.01)
        return "ok"

    res = await run_with_timeout_and_interrupt(fast_work(), timeout_seconds=1.0)
    assert res == "ok"


@pytest.mark.asyncio
async def test_run_with_timeout_triggers_timeout_error():
    async def hung_work():
        # 模拟因为配置错误导致一直执行的死等任务
        await asyncio.sleep(2.0)
        return "done"

    with pytest.raises(ExecutionTimeoutError, match="任务执行超时中断"):
        await run_with_timeout_and_interrupt(hung_work(), timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_run_with_controller_interrupt():
    ctrl = InterruptController()

    async def long_work():
        await asyncio.sleep(1.0)
        return "done"

    async def trigger():
        await asyncio.sleep(0.05)
        ctrl.request_interrupt("测试中断信号")

    asyncio.create_task(trigger())
    with pytest.raises(ExecutionInterruptedError, match="测试中断信号"):
        await run_with_timeout_and_interrupt(long_work(), timeout_seconds=5.0, controller=ctrl)


@pytest.mark.asyncio
async def test_main_run_timeout_in_dry_run(monkeypatch, tmp_path: Path):
    # 测试在 dry_run（测试执行）模式下，如果执行超时能够立即中断
    settings = Settings(
        task_config_path=tmp_path / "config.json",
        storage_state="storage-state.json",
        cookie=None,
        headless=True,
        browser_path=None,
        artifacts_dir=tmp_path / "artifacts",
        trace=False,
    )
    task = TaskConfig(
        task_id="test",
        timezone="Asia/Shanghai",
        targets=(Target(name="好友1", messages=()),),
        stickers={},
        interval_min=0.1,
        interval_max=0.2,
        continue_on_error=True,
        prevent_duplicates=False,
        timeout_seconds=0.1,  # 设定任务超时
    )
    monkeypatch.setattr(main_module, "load_settings", lambda _env=None: settings)
    monkeypatch.setattr(main_module, "load_task", lambda _s: task)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open_douyin(*args, **kwargs):
        await asyncio.sleep(1.0)
        session = MagicMock()
        session.page = MagicMock()
        yield session

    monkeypatch.setattr(main_module, "open_douyin", fake_open_douyin)
    with pytest.raises(ExecutionTimeoutError, match="任务执行超时中断"):
        await main_module.run(dry_run=True, timeout=0.1)

@pytest.mark.asyncio
async def test_fail_fast_stops_immediately_on_first_error(monkeypatch, tmp_path: Path):
    # 测试 --fail-fast 模式在首个错误时立即中断后续好友处理
    settings = Settings(
        task_config_path=tmp_path / "config.json",
        storage_state="storage-state.json",
        cookie=None,
        headless=True,
        browser_path=None,
        artifacts_dir=tmp_path / "artifacts",
        trace=False,
    )
    task = TaskConfig(
        task_id="test",
        timezone="Asia/Shanghai",
        targets=(
            Target(name="好友1", messages=()),
            Target(name="好友2", messages=()),
        ),
        stickers={},
        interval_min=0.1,
        interval_max=0.2,
        continue_on_error=True,
        prevent_duplicates=False,
    )

    monkeypatch.setattr(main_module, "load_settings", lambda _env=None: settings)
    monkeypatch.setattr(main_module, "load_task", lambda _s: task)

    chat = MagicMock()
    # 好友1 打开失败
    chat.open_target = AsyncMock(side_effect=RuntimeError("好友1配置不存在"))

    opened_targets = []

    async def fake_open_target_with_retry(c, name, retries):
        opened_targets.append(name)
        raise RuntimeError(f"打开好友 {name} 失败")

    monkeypatch.setattr(main_module, "_open_target_with_retry", fake_open_target_with_retry)
    monkeypatch.setattr(main_module, "open_private_messages", AsyncMock())
    monkeypatch.setattr(main_module, "DouyinChat", MagicMock(return_value=chat))
    monkeypatch.setattr(main_module, "_screenshot", AsyncMock(return_value=None))
    monkeypatch.setattr(main_module, "_write_results", MagicMock())
    monkeypatch.setattr(main_module, "_notify_dingtalk", AsyncMock())
    monkeypatch.setattr(main_module, "_notify_webhook", AsyncMock())

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open_douyin(_s):
        session = MagicMock()
        session.page = MagicMock()
        yield session

    monkeypatch.setattr(main_module, "open_douyin", fake_open_douyin)

    # 启用 fail_fast=True，由于出现 fatal_error，最终退出或抛出
    with pytest.raises(RuntimeError, match="打开好友 好友1 失败"):
        await main_module.run(dry_run=True, fail_fast=True)

    # 好友2 不应该被处理
    assert opened_targets == ["好友1"]


    from app.accounts import Account

    accounts = [
        Account(id="acc1", enabled=True, env_file=Path("a.env")),
        Account(id="acc2", enabled=True, env_file=Path("b.env")),
    ]
    monkeypatch.setattr(account_runner_module, "load_accounts", lambda: accounts)

    call_count = 0

    def fake_run(**kwargs):
        nonlocal call_count
        call_count += 1
        raise KeyboardInterrupt("用户按 Ctrl+C 中断")

    monkeypatch.setattr(account_runner_module, "run", fake_run)
    monkeypatch.setattr(account_runner_module, "account_env", MagicMock())
    monkeypatch.setattr(account_runner_module, "load_settings", MagicMock())
    monkeypatch.setattr(account_runner_module, "_configure_logging", MagicMock())
    monkeypatch.setattr(account_runner_module, "run_lock", MagicMock())

    # 调用 run_all_accounts
    ret = account_runner_module.run_all_accounts()
    assert ret == 130
    # 只执行了第 1 个账号，第 2 个账号被立即阻止，没有继续执行
    assert call_count == 1
