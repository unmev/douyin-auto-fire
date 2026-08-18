from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import dotenv_values, load_dotenv

from app.accounts import load_accounts
from app.config import ConfigError, load_settings
from app.history import run_lock
from app.main import LOGGER, _configure_logging, _parse_cli_args, run


# 单账号模式的旧环境变量。多账号模式下由各账号的 env 文件提供，
# 启动时先清掉进程环境中的旧值，避免残留值被所有账号继承。
_LEGACY_ENV_KEYS = ("DOUYIN_COOKIE", "DOUYIN_STORAGE_STATE", "TASK_CONFIG", "ARTIFACTS_DIR")


def run_all_accounts() -> int:
    """串行执行 accounts.json 中所有启用账号。

    单账号失败（Cookie 失效、好友不存在、发送异常等）只记为该账号
    failed，不阻止其他账号运行。返回码与单账号语义一致：
    0=全部成功，1=存在失败，2=多账号配置整体错误。
    """
    args = _parse_cli_args()
    accounts = load_accounts()
    if not accounts:
        print("没有启用任何账号，本次任务跳过")
        return 0
    if args.env_file:
        load_dotenv(args.env_file)
    for key in _LEGACY_ENV_KEYS:
        os.environ.pop(key, None)

    _configure_logging(Path("artifacts"), label=None, reset=True)
    LOGGER.info("多账号模式：共 %d 个启用账号", len(accounts))

    summary: list[tuple[str, str, str | None]] = []
    for account in accounts:
        # 先按默认产物目录配置账号日志，保证账号内任何失败都带 [账号id] 前缀；
        # 若账号 env 显式指定了 ARTIFACTS_DIR，进入账号环境后会重定向。
        _configure_logging(Path("artifacts") / account.id, label=account.id, reset=True)
        LOGGER.info("开始执行任务")
        try:
            with account_env(account.env_file, defaults={"ARTIFACTS_DIR": f"artifacts/{account.id}"}):
                settings = load_settings(None)
                _configure_logging(settings.artifacts_dir, label=account.id, reset=True)
                with run_lock(settings.artifacts_dir / "run.lock"):
                    code = asyncio.run(run(dry_run=args.dry_run))
            status = "success" if code == 0 else "failed"
            summary.append((account.id, status, None))
            LOGGER.info("执行完成: %s", status)
        except Exception as exc:
            # 异常消息可能包含好友真名（如 Playwright 定位器超时），此处只记录
            # 异常类型；完整脱敏详情已由 run() 写入该账号的 run.log。
            summary.append((account.id, "failed", type(exc).__name__))
            LOGGER.exception("执行失败: %s", exc)

    _configure_logging(Path("artifacts"), label=None, reset=True)
    for account_id, status, error in summary:
        detail = f" - {error}" if error else ""
        LOGGER.info("[%s] 结果: %s%s", account_id, status, detail)
    failed = sum(1 for _, status, _ in summary if status == "failed")
    LOGGER.info("多账号执行结束: 成功 %d，失败 %d", len(summary) - failed, failed)
    return 1 if failed else 0


def _load_account_env(env_file: Path, defaults: dict[str, str] | None = None) -> dict[str, str]:
    env_file = Path(env_file)
    if not env_file.is_file():
        raise ConfigError(f"账号环境文件不存在: {env_file}")
    values = {key: value for key, value in (dotenv_values(env_file) or {}).items() if value is not None}
    for key, value in (defaults or {}).items():
        values.setdefault(key, value)
    return values


@contextmanager
def account_env(env_file: Path, defaults: dict[str, str] | None = None) -> Iterator[None]:
    """临时把账号 env 应用到进程环境，退出时完全恢复。

    - 账号 env 中的键覆盖进程环境已有值，退出时恢复原值；
    - 账号 env 新增的键，退出时删除，绝不泄漏给下一个账号；
    - 账号 env 未定义的键（如 CI 的 HEADLESS）保持继承进程环境。
    """
    values = _load_account_env(env_file, defaults)
    saved = {key: os.environ[key] for key in values if key in os.environ}
    fresh = set(values) - set(saved)
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.update(saved)
        for key in fresh:
            os.environ.pop(key, None)
