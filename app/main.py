from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import hashlib
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.browser import AuthenticationError, RiskControlError, SearchBoxNotReadyError, open_douyin, open_private_messages, save_trace, verify_login
from app.config import ConfigError, load_settings, load_task
from app.douyin import DouyinChat, PageOperationError
from app.errors import classify_error, get_retry_strategy, should_stop_all_tasks
from app.history import AlreadyRunningError, History, run_lock
from app.interrupt import (
    ExecutionInterruptedError,
    ExecutionTimeoutError,
    check_interrupted,
    reset_interrupted,
    run_with_timeout_and_interrupt,
    signal_interrupt_handler,
)
from app.metrics import Metrics, HistoricalMetrics, format_metrics_summary
from app.models import Settings, TargetResult
from app.notifier import send_dingtalk_notification, send_webhook_notification
from app.privacy import RedactingFormatter, build_target_aliases, redact_text, target_alias
from app.progress import create_single_run_progress
from app.sender import send_message

LOGGER = logging.getLogger("douyin_sender")


async def run(
    dry_run: bool = False,
    env_file: str | None = None,
    timeout: float | None = None,
    fail_fast: bool = False,
) -> int:
    reset_interrupted()
    settings = load_settings(env_file)
    task = load_task(settings)
    effective_timeout = timeout if timeout is not None else task.timeout_seconds
    async def _run_impl() -> int:
        return await _run_core(settings, task, dry_run=dry_run, fail_fast=fail_fast)

    if effective_timeout is not None and effective_timeout > 0:
        LOGGER.info("已启用执行超时保护: 最大运行时间 %.1f 秒", effective_timeout)
        return await run_with_timeout_and_interrupt(_run_impl(), timeout_seconds=effective_timeout)
    return await _run_impl()


async def _run_core(
    settings: Settings,
    task: Any,
    dry_run: bool = False,
    fail_fast: bool = False,
) -> int:
    aliases = build_target_aliases(task.targets)
    _configure_logging(settings.artifacts_dir, aliases)

    if not settings.storage_state and not settings.cookie:
        raise ConfigError("必须配置 DOUYIN_STORAGE_STATE 或 DOUYIN_COOKIE")

    # 初始化监控指标
    metrics = Metrics()
    metrics.started_at = datetime.now().astimezone().isoformat()
    start_time = time.time()

    # 初始化进度显示
    multi_stage, target_progress = create_single_run_progress(len(task.targets))

    history = History(settings.artifacts_dir / "history.json")
    run_date = history.run_date(task.timezone)
    results: list[TargetResult] = []
    screenshots: list[Path] = []
    fatal_error: Exception | None = None

    try:
        # 阶段1: 打开浏览器
        multi_stage.start_stage(0)
        async with open_douyin(settings) as session:
            page = session.page
            trace_saved = False
            multi_stage.finish_stage()

            # 阶段2: 验证登录
            multi_stage.start_stage(1)
            try:
                await open_private_messages(page)
                multi_stage.finish_stage()
            except Exception as exc:
                multi_stage.finish_stage()
                LOGGER.exception("打开抖音私信页面失败")
                screenshot = await _screenshot(page, settings.artifacts_dir, "login")
                if screenshot:
                    screenshots.append(screenshot)
                if settings.trace and not trace_saved:
                    try:
                        await save_trace(session, _trace_path(settings.artifacts_dir))
                        trace_saved = True
                    except Exception:
                        LOGGER.exception("保存 trace 失败")
                label = "登录检查" if isinstance(exc, (AuthenticationError, RiskControlError)) else "运行检查"
                results.append(TargetResult(target=label, status="failed", error=str(exc)))
                metrics.record_target_failure(type(exc).__name__)
                fatal_error = exc

            # 阶段3: 发送消息
            if fatal_error is None:
                multi_stage.start_stage(2, total_items=len(task.targets))
                chat = DouyinChat(page, timeout_ms=int(task.target_open_timeout_seconds * 1000))

                for index, target in enumerate(task.targets):
                    check_interrupted()
                    sent = 0
                    alias = target_alias(index)
                    target_progress.start_target(alias)
                    message_start_time = time.time()

                    try:
                        LOGGER.info("处理好友: %s", alias)

                        # 使用智能重试策略打开目标
                        await _open_target_with_retry(chat, target.name, task.target_open_retries)

                        if not dry_run:
                            for message_index, message in enumerate(target.messages):
                                message_id = _message_id(message_index, message)
                                key = history.key(task.task_id, run_date, target.name, message_id)

                                if task.prevent_duplicates and history.contains(key):
                                    LOGGER.info(
                                        "跳过当天已处理或结果不确定的消息: %s #%d",
                                        alias,
                                        message_index + 1,
                                    )
                                    metrics.record_skipped_message()
                                    continue

                                if task.prevent_duplicates:
                                    history.reserve(key)

                                # 发送单条消息并计时
                                check_interrupted()
                                msg_start = time.time()
                                await verify_login(page, timeout_ms=3_000)
                                await send_message(page, chat, message, task.stickers)
                                msg_duration = time.time() - msg_start
                                metrics.record_message_time(msg_duration)

                                if task.prevent_duplicates:
                                    history.mark_success(key)
                                sent += 1

                                if message_index < len(target.messages) - 1:
                                    await asyncio.sleep(random.uniform(task.interval_min, task.interval_max))

                        # 记录目标成功
                        results.append(TargetResult(target=target.name, status="success", sent=sent, target_alias=alias))
                        metrics.record_target_success(sent)
                        target_progress.finish_target("success")

                    except (AuthenticationError, RiskControlError) as exc:
                        # 认证失效或风控，立即停止
                        LOGGER.exception("处理好友时登录状态失效: %s", alias)
                        screenshot = await _screenshot(page, settings.artifacts_dir, alias)
                        if screenshot:
                            screenshots.append(screenshot)
                        if settings.trace and not trace_saved:
                            try:
                                await save_trace(session, _trace_path(settings.artifacts_dir))
                                trace_saved = True
                            except Exception:
                                LOGGER.exception("保存 trace 失败")

                        results.append(TargetResult(target=target.name, status="failed", sent=sent, error=str(exc), target_alias=alias))
                        metrics.record_target_failure(type(exc).__name__, sent)
                        target_progress.finish_target("failed")
                        fatal_error = exc
                        break

                    except Exception as exc:
                        # 其他错误，根据错误类型决定是否继续
                        error_category = classify_error(exc)
                        LOGGER.exception("好友处理失败: %s (错误类型: %s)", alias, error_category.value)

                        screenshot = await _screenshot(page, settings.artifacts_dir, alias)
                        if screenshot:
                            screenshots.append(screenshot)
                        if settings.trace and not trace_saved:
                            try:
                                await save_trace(session, _trace_path(settings.artifacts_dir))
                                trace_saved = True
                            except Exception:
                                LOGGER.exception("保存 trace 失败")

                        results.append(TargetResult(target=target.name, status="failed", sent=sent, error=str(exc), target_alias=alias))
                        metrics.record_target_failure(type(exc).__name__, sent)
                        target_progress.finish_target("failed")

                        # 检查是否应该停止所有任务
                        if fail_fast:
                            LOGGER.warning("--fail-fast 模式已生效，遇到错误立即中断后续任务")
                            fatal_error = exc
                            break

                        if should_stop_all_tasks(exc):
                            LOGGER.warning("检测到严重错误，停止处理剩余好友")
                            fatal_error = exc
                            break

                        if not task.continue_on_error:
                            break
                    multi_stage.update_progress(1)

                    if index < len(task.targets) - 1 and not dry_run:
                        await asyncio.sleep(random.uniform(task.interval_min, task.interval_max))

                multi_stage.finish_stage()

            if settings.trace and not trace_saved:
                try:
                    await session.context.tracing.stop()
                except Exception as exc:
                    LOGGER.exception("停止 trace 失败")
                    if fatal_error is None:
                        fatal_error = exc
                        results.append(TargetResult(target="运行收尾", status="failed", error=str(exc)))
                        metrics.record_target_failure(type(exc).__name__)
    except Exception as exc:
        if fatal_error is None:
            fatal_error = exc
            results.append(TargetResult(target="运行检查", status="failed", error=str(exc)))
            metrics.record_target_failure(type(exc).__name__)

    # 完成指标统计
    metrics.total_duration_seconds = time.time() - start_time
    metrics.finalize()

    # 保存指标
    metrics.save(settings.artifacts_dir / "metrics.json")

    # 更新历史指标
    historical = HistoricalMetrics.load(settings.artifacts_dir / "metrics_history.json")
    historical.update(metrics)
    historical.save(settings.artifacts_dir / "metrics_history.json")

    # 输出指标摘要
    LOGGER.info("\n%s", format_metrics_summary(metrics))

    _write_results(settings.artifacts_dir, task.task_id, dry_run, results, aliases)
    await _notify_dingtalk(settings, task.task_id, dry_run, results, screenshots)
    await _notify_webhook(settings, task.task_id, dry_run, results, screenshots)
    succeeded = sum(result.status == "success" for result in results)
    failed = sum(result.status == "failed" for result in results)
    LOGGER.info("执行结束: 成功 %d，失败 %d", succeeded, failed)

    if fatal_error is not None:
        raise fatal_error
    return 1 if failed else 0


def main() -> int:
    args = _parse_cli_args()
    try:
        settings = load_settings(args.env_file)
        with run_lock(settings.artifacts_dir / "run.lock"):
            with signal_interrupt_handler():
                return asyncio.run(
                    run(
                        dry_run=args.dry_run,
                        env_file=args.env_file,
                        timeout=args.timeout,
                        fail_fast=args.fail_fast,
                    )
                )
    except (ConfigError, AuthenticationError, RiskControlError, SearchBoxNotReadyError, AlreadyRunningError) as exc:
        print(f"错误: {exc}")
        return 2
    except ExecutionTimeoutError as exc:
        print(f"执行超时中断: {exc}", file=sys.stderr)
        return 124
    except (KeyboardInterrupt, ExecutionInterruptedError):
        print("\n任务已由用户或系统中断取消")
        return 130


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="向多个抖音好友发送配置的消息")
    parser.add_argument("--dry-run", action="store_true", help="只验证登录和好友，不发送消息（测试模式）")
    parser.add_argument("--env-file", help="指定 .env 文件路径")
    parser.add_argument("--auth-file", help="指定 auth.json 凭证文件路径")
    parser.add_argument("--timeout", type=float, default=None, help="最大执行超时秒数，超时后自动中断并退出")
    parser.add_argument("--fail-fast", action="store_true", help="遇到首个目标失败或配置错误时立即中断退出")
    args, _ = parser.parse_known_args()
    return args

def _configure_logging(
    artifacts_dir: Path,
    aliases: dict[str, str] | None = None,
    *,
    label: str | None = None,
    reset: bool = False,
) -> None:
    if reset or not LOGGER.handlers:
        for handler in list(LOGGER.handlers):
            LOGGER.removeHandler(handler)
            if isinstance(handler, logging.FileHandler):
                handler.close()
        LOGGER.setLevel(logging.INFO)
        pattern = "%(asctime)s %(levelname)s %(message)s"
        if label:
            pattern = pattern.replace(" %(message)s", f" [{label}] %(message)s")
        formatter = RedactingFormatter(pattern, aliases=aliases)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(artifacts_dir / "run.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        LOGGER.addHandler(file_handler)
        LOGGER.addHandler(stream_handler)
        return
    # 已有 handler（多账号模式下 run() 内部会再次调用）：只更新脱敏别名。
    for handler in LOGGER.handlers:
        if isinstance(handler.formatter, RedactingFormatter):
            handler.formatter.aliases = dict(aliases or {})


async def _screenshot(page, artifacts_dir: Path, label: str) -> Path | None:
    safe_label = re.sub(r"[^A-Za-z0-9_.\-一-鿿]+", "_", label).strip("_")
    suffix = hashlib.sha1(label.encode("utf-8")).hexdigest()[:6]
    safe_label = f"{safe_label}-{suffix}" if safe_label else f"failure-{suffix}"
    directory = artifacts_dir / "screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.now():%Y%m%d-%H%M%S}-{safe_label}.png"
    try:
        await page.screenshot(path=path, full_page=True)
        return path
    except Exception:
        LOGGER.exception("保存截图失败")
        return None


def _write_results(
    artifacts_dir: Path,
    task_id: str,
    dry_run: bool,
    results: list[TargetResult],
    aliases: dict[str, str] | None = None,
) -> None:
    payload = {
        "task_id": task_id,
        "dry_run": dry_run,
        "finished_at": datetime.now().astimezone().isoformat(),
        "results": [_redacted_result(result, aliases) for result in results],
    }
    (artifacts_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _redacted_result(result: TargetResult, aliases: dict[str, str] | None = None) -> dict:
    aliases = dict(aliases or {})
    aliases[result.target] = result.target_alias or aliases.get(result.target, result.target)
    return {
        "target": aliases[result.target],
        "status": result.status,
        "sent": result.sent,
        "error": redact_text(result.error, aliases) if result.error else None,
    }


async def _notify_dingtalk(
    settings: Settings,
    task_id: str,
    dry_run: bool,
    results: list[TargetResult],
    screenshots: list[Path],
) -> None:
    if not settings.dingtalk_webhook or not settings.dingtalk_secret:
        return
    try:
        await send_dingtalk_notification(
            settings.dingtalk_webhook,
            settings.dingtalk_secret,
            task_id,
            dry_run,
            results,
            screenshots,
        )
        LOGGER.info("钉钉通知发送成功")
    except Exception:
        LOGGER.exception("钉钉通知发送失败，不影响本次任务结果")


async def _notify_webhook(
    settings: Settings,
    task_id: str,
    dry_run: bool,
    results: list[TargetResult],
    screenshots: list[Path],
) -> None:
    if not settings.webhook_url:
        return
    try:
        await send_webhook_notification(
            settings.webhook_url,
            task_id,
            dry_run,
            results,
            screenshots,
            settings.webhook_template,
            settings.webhook_headers,
        )
        LOGGER.info("Webhook 通知发送成功")
    except Exception:
        LOGGER.exception("Webhook 通知发送失败，不影响本次任务结果")


def _trace_path(artifacts_dir: Path) -> Path:
    return artifacts_dir / "traces" / f"{datetime.now():%Y%m%d-%H%M%S}.zip"


def _message_id(index, message) -> str:
    payload = json.dumps(asdict(message), ensure_ascii=False, sort_keys=True, default=str)
    return f"{index}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


async def _open_target_with_retry(chat: DouyinChat, target_name: str, max_retries: int) -> None:
    """使用智能重试策略打开目标聊天。

    Args:
        chat: DouyinChat 实例
        target_name: 目标好友名称
        max_retries: 最大重试次数（来自配置）

    Raises:
        Exception: 最后一次重试失败后抛出
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            await chat.open_target(target_name, retries=0)  # 单次尝试，重试逻辑在这里控制
            return
        except Exception as exc:
            last_exception = exc

            # 获取错误的重试策略
            strategy = get_retry_strategy(exc)
            category = classify_error(exc)

            if attempt >= max_retries:
                # 达到最大重试次数
                LOGGER.warning(
                    "打开目标失败，已达最大重试次数 %d (错误类型: %s)",
                    max_retries,
                    category.value,
                )
                break

            if not strategy.should_retry(attempt):
                # 策略判断不应重试（如永久性错误）
                LOGGER.warning(
                    "打开目标失败，错误类型 %s 不建议重试",
                    category.value,
                )
                break

            # 计算重试延迟
            delay = strategy.get_delay(attempt)
            LOGGER.info(
                "打开目标失败 (尝试 %d/%d)，%s 秒后重试 (错误类型: %s)",
                attempt + 1,
                max_retries + 1,
                delay,
                category.value,
            )
            await asyncio.sleep(delay)

    # 所有重试都失败，抛出最后一个异常
    if last_exception:
        raise last_exception
