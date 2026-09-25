from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
from contextlib import contextmanager
from typing import Any, Callable, Coroutine, Generator, TypeVar

T = TypeVar("T")


class ExecutionInterruptedError(Exception):
    """任务执行被中断异常（用户主动取消或信号终止）"""


class ExecutionTimeoutError(ExecutionInterruptedError):
    """任务执行超时中断异常（防止配置错误或异常挂起导致一直执行）"""


class InterruptController:
    """跨平台执行中断与超时控制器。

    负责协调异步协程取消、超时监控、多线程安全中断标记以及系统信号（SIGINT/SIGTERM）的捕获与响应。
    """

    def __init__(self) -> None:
        self._interrupted = threading.Event()
        self._interrupt_reason: str = ""

    def request_interrupt(self, reason: str = "任务被用户或系统信号中断") -> None:
        """标记中断请求。"""
        self._interrupt_reason = reason
        self._interrupted.set()

    def is_interrupted(self) -> bool:
        """是否已被请求中断。"""
        return self._interrupted.is_set()

    def check_interrupted(self) -> None:
        """检查中断标记，若已中断则主动抛出 ExecutionInterruptedError。"""
        if self._interrupted.is_set():
            raise ExecutionInterruptedError(self._interrupt_reason or "任务执行被中断")

    def reset(self) -> None:
        """重置控制器状态。"""
        self._interrupted.clear()
        self._interrupt_reason = ""


# 全局默认单例控制器
GLOBAL_INTERRUPT_CONTROLLER = InterruptController()


def check_interrupted() -> None:
    """全局检查中断快捷方法。"""
    GLOBAL_INTERRUPT_CONTROLLER.check_interrupted()


def reset_interrupted() -> None:
    """全局重置中断标记快捷方法。"""
    GLOBAL_INTERRUPT_CONTROLLER.reset()
@contextmanager
def signal_interrupt_handler(controller: InterruptController | None = None) -> Generator[InterruptController, None, None]:
    """上下文管理器：安全挂载和恢复 SIGINT/SIGTERM 信号监听。"""
    ctrl = controller or GLOBAL_INTERRUPT_CONTROLLER
    previous_handlers: dict[int, Any] = {}

    def _on_signal(signum: int, frame: Any) -> None:
        sig_name = "SIGINT" if signum == getattr(signal, "SIGINT", 2) else "SIGTERM"
        ctrl.request_interrupt(f"接收到中断信号 {sig_name}")
        # 如果是主线程且有先前的默认 handler，抛出 KeyboardInterrupt 以便外部快速响应
        raise KeyboardInterrupt(f"接收到中断信号 {sig_name}")

    signals_to_catch = [signal.SIGINT]
    if hasattr(signal, "SIGTERM"):
        signals_to_catch.append(signal.SIGTERM)

    # 仅在主线程安装信号处理器
    if threading.current_thread() is threading.main_thread():
        for sig in signals_to_catch:
            try:
                previous_handlers[sig] = signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass

    try:
        yield ctrl
    finally:
        if threading.current_thread() is threading.main_thread():
            for sig, handler in previous_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass


async def run_with_timeout_and_interrupt(
    coro: Coroutine[Any, Any, T],
    timeout_seconds: float | None = None,
    controller: InterruptController | None = None,
) -> T:
    """在超时监控与中断保护下执行异步协程。

    Args:
        coro: 待执行的协程（如 run() 任务）
        timeout_seconds: 超时秒数，<=0 或 None 表示不设全局超时
        controller: 中断控制器，默认为全局单例

    Raises:
        ExecutionTimeoutError: 执行超过指定时长
        ExecutionInterruptedError: 被中断标记唤醒或主动取消
        KeyboardInterrupt: 捕获到用户 Ctrl+C 信号
    """
    ctrl = controller or GLOBAL_INTERRUPT_CONTROLLER

    # 检查初始是否已被标记中断
    ctrl.check_interrupted()

    task = asyncio.create_task(coro)

    # 启动后台轮询任务，以便在 controller 被异步触发中断时迅速 cancel 任务
    async def _watch_interrupt() -> None:
        while not task.done():
            if ctrl.is_interrupted():
                task.cancel()
                break
            await asyncio.sleep(0.2)

    watcher = asyncio.create_task(_watch_interrupt())

    try:
        if timeout_seconds is not None and timeout_seconds > 0:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                raise ExecutionTimeoutError(f"任务执行超时中断（已超过设定限制 {timeout_seconds:.1f} 秒，防止配置错误一直执行）") from exc
        else:
            return await task
    except asyncio.CancelledError as exc:
        if ctrl.is_interrupted():
            raise ExecutionInterruptedError(ctrl._interrupt_reason or "任务被中断取消") from exc
        raise
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
