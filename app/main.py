from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import hashlib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.browser import AuthenticationError, RiskControlError, open_douyin, open_private_messages, save_trace, verify_login
from app.config import ConfigError, load_settings, load_task
from app.douyin import DouyinChat
from app.history import AlreadyRunningError, History, run_lock
from app.models import Settings, TargetResult
from app.notifier import send_dingtalk_notification
from app.sender import send_message


LOGGER = logging.getLogger("douyin_sender")


async def run(dry_run: bool = False, env_file: str | None = None) -> int:
    settings = load_settings(env_file)
    task = load_task(settings)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(settings.artifacts_dir)

    if not settings.storage_state and not settings.cookie:
        raise ConfigError("必须配置 DOUYIN_STORAGE_STATE 或 DOUYIN_COOKIE")

    history = History(settings.artifacts_dir / "history.json")
    run_date = history.run_date(task.timezone)
    results: list[TargetResult] = []
    screenshots: list[Path] = []
    fatal_error: Exception | None = None
    try:
        async with open_douyin(settings) as session:
            page = session.page
            trace_saved = False
            try:
                await open_private_messages(page)
            except Exception as exc:
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
                fatal_error = exc

            if fatal_error is None:
                chat = DouyinChat(page, timeout_ms=int(task.target_open_timeout_seconds * 1000))
                for index, target in enumerate(task.targets):
                    sent = 0
                    try:
                        LOGGER.info("处理好友: %s", target.name)
                        await chat.open_target(target.name, retries=task.target_open_retries)
                        if not dry_run:
                            for message_index, message in enumerate(target.messages):
                                message_id = _message_id(message_index, message)
                                key = history.key(task.task_id, run_date, target.name, message_id)
                                if task.prevent_duplicates and history.contains(key):
                                    LOGGER.info(
                                        "跳过当天已处理或结果不确定的消息: %s #%d",
                                        target.name,
                                        message_index + 1,
                                    )
                                    continue
                                if task.prevent_duplicates:
                                    history.reserve(key)
                                await verify_login(page, timeout_ms=3_000)
                                await send_message(page, chat, message, task.stickers)
                                if task.prevent_duplicates:
                                    history.mark_success(key)
                                sent += 1
                                if message_index < len(target.messages) - 1:
                                    await asyncio.sleep(random.uniform(task.interval_min, task.interval_max))
                        results.append(TargetResult(target=target.name, status="success", sent=sent))
                    except (AuthenticationError, RiskControlError) as exc:
                        LOGGER.exception("处理好友时登录状态失效: %s", target.name)
                        screenshot = await _screenshot(page, settings.artifacts_dir, f"{index + 1}-{target.name}")
                        if screenshot:
                            screenshots.append(screenshot)
                        if settings.trace and not trace_saved:
                            try:
                                await save_trace(session, _trace_path(settings.artifacts_dir))
                                trace_saved = True
                            except Exception:
                                LOGGER.exception("保存 trace 失败")
                        results.append(TargetResult(target=target.name, status="failed", sent=sent, error=str(exc)))
                        fatal_error = exc
                        break
                    except Exception as exc:
                        LOGGER.exception("好友处理失败: %s", target.name)
                        screenshot = await _screenshot(page, settings.artifacts_dir, f"{index + 1}-{target.name}")
                        if screenshot:
                            screenshots.append(screenshot)
                        if settings.trace and not trace_saved:
                            try:
                                await save_trace(session, _trace_path(settings.artifacts_dir))
                                trace_saved = True
                            except Exception:
                                LOGGER.exception("保存 trace 失败")
                        results.append(TargetResult(target=target.name, status="failed", sent=sent, error=str(exc)))
                        if not task.continue_on_error:
                            break
                    if index < len(task.targets) - 1 and not dry_run:
                        await asyncio.sleep(random.uniform(task.interval_min, task.interval_max))

            if settings.trace and not trace_saved:
                try:
                    await session.context.tracing.stop()
                except Exception as exc:
                    LOGGER.exception("停止 trace 失败")
                    if fatal_error is None:
                        fatal_error = exc
                        results.append(TargetResult(target="运行收尾", status="failed", error=str(exc)))
    except Exception as exc:
        if fatal_error is None:
            fatal_error = exc
            results.append(TargetResult(target="运行检查", status="failed", error=str(exc)))

    _write_results(settings.artifacts_dir, task.task_id, dry_run, results)
    await _notify_dingtalk(settings, task.task_id, dry_run, results, screenshots)
    succeeded = sum(result.status == "success" for result in results)
    failed = sum(result.status == "failed" for result in results)
    LOGGER.info("执行结束: 成功 %d，失败 %d", succeeded, failed)
    if fatal_error is not None:
        raise fatal_error
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="向多个抖音好友发送配置的消息")
    parser.add_argument("--dry-run", action="store_true", help="只验证登录和好友，不发送消息")
    parser.add_argument("--env-file", help="指定 .env 文件路径")
    args = parser.parse_args()
    try:
        settings = load_settings(args.env_file)
        with run_lock(settings.artifacts_dir / "run.lock"):
            return asyncio.run(run(dry_run=args.dry_run, env_file=args.env_file))
    except (ConfigError, AuthenticationError, RiskControlError, AlreadyRunningError) as exc:
        print(f"错误: {exc}")
        return 2
    except KeyboardInterrupt:
        print("任务已取消")
        return 130


def _configure_logging(artifacts_dir: Path) -> None:
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(artifacts_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


async def _screenshot(page, artifacts_dir: Path, label: str) -> Path | None:
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
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


def _write_results(artifacts_dir: Path, task_id: str, dry_run: bool, results: list[TargetResult]) -> None:
    payload = {
        "task_id": task_id,
        "dry_run": dry_run,
        "finished_at": datetime.now().astimezone().isoformat(),
        "results": [asdict(result) for result in results],
    }
    (artifacts_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _trace_path(artifacts_dir: Path) -> Path:
    return artifacts_dir / "traces" / f"{datetime.now():%Y%m%d-%H%M%S}.zip"


def _message_id(index, message) -> str:
    payload = json.dumps(asdict(message), ensure_ascii=False, sort_keys=True, default=str)
    return f"{index}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"
