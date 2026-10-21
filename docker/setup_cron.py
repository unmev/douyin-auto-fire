#!/usr/bin/env python3
"""生成容器内 cron 定时任务需要的 crontab 和环境变量文件。

为什么需要这个脚本
------------------
cron 启动的作业**不会继承容器自身的环境变量**。作业能拿到的变量只有
crontab 文件里显式写出来的部分，加上 cron 自己设置的
``HOME`` / ``LOGNAME`` / ``PWD`` / ``SHELL`` / ``PATH``。

原来的 ``docker/entrypoint.sh`` 只往 crontab 里写了 ``SHELL`` 和 ``PATH``，
于是通过 compose 的 ``environment:`` 传入的 ``DOUYIN_COOKIE``、``TASK_CONFIG``、
``ARTIFACTS_DIR``、``HEADLESS``，以及 Dockerfile 里定义的
``PLAYWRIGHT_BROWSERS_PATH``、``PYTHONUNBUFFERED`` 在定时任务里全部丢失，
任务每次都会以「必须配置 DOUYIN_STORAGE_STATE 或 DOUYIN_COOKIE」失败。

本脚本把容器环境写成一个可被 shell ``source`` 的文件，并让 crontab 在执行
任务前加载它，让定时任务和 ``RUN_ON_START`` / ``docker exec`` 的运行环境保持一致。

为什么不用 crontab 的环境变量区
------------------------------
crontab 的 ``NAME=value`` 只支持成对的单/双引号，值里**没有转义机制**：
值里出现单引号会导致整行解析失败，双引号又无法承载 Cookie / Webhook 模板
里的 JSON。因此环境变量统一放进单独的文件，用 shell 引用（``shlex.quote``）保存。
"""

from __future__ import annotations

import argparse
import os
import shlex
from collections.abc import Mapping
from pathlib import Path

DEFAULT_SCHEDULE = "30 0 * * *"
DEFAULT_CRON_FILE = Path("/etc/cron.d/douyin-auto-fire")
DEFAULT_ENV_FILE = Path("/run/douyin-auto-fire/env.sh")
FALLBACK_ENV_FILE = Path("/tmp/douyin-auto-fire/env.sh")
DEFAULT_APP_DIR = Path("/app")
DEFAULT_PYTHON_BIN = "/usr/local/bin/python"
CRON_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# 由 shell / cron 自身维护的变量，写进环境文件没有意义。
IGNORED_ENV_NAMES = frozenset({"PWD", "OLDPWD", "SHLVL", "_"})

ENV_FILE_HEADER = (
    "# 由 docker/setup_cron.py 生成，请勿手动修改。\n"
    "# 容器内 cron 定时任务在执行前 source 本文件，\n"
    "# 以获得与容器启动时一致的环境变量。\n"
)


def render_env_file(environ: Mapping[str, str]) -> str:
    """把环境变量渲染成可被 shell source 的脚本内容。

    空值按「未设置」处理：应用侧的 ``_optional_env`` / ``_parse_bool``
    都把空字符串当成没有配置，跳过可以避免 ``HEADLESS=""`` 之类的写法
    直接让任务报错退出。
    """
    lines = [ENV_FILE_HEADER.rstrip("\n")]
    for name in sorted(environ):
        if name in IGNORED_ENV_NAMES:
            continue
        value = environ[name]
        if not value:
            continue
        lines.append(f"export {name}={shlex.quote(value)}")
    return "\n".join(lines) + "\n"


def render_crontab(
    schedule: str,
    env_file: Path,
    app_dir: Path = DEFAULT_APP_DIR,
    python_bin: str = DEFAULT_PYTHON_BIN,
) -> str:
    """渲染 /etc/cron.d 下的 crontab 内容。

    任务命令里的 ``%`` 会被 cron 当成换行符，所以命令部分不能出现 ``%``；
    环境变量放在单独的文件里，正是为了避开这个限制。
    """
    command = (
        f"cd {app_dir} && . {env_file} && exec {python_bin} run.py "
        ">> /proc/1/fd/1 2>> /proc/1/fd/2"
    )
    assert "%" not in command, "cron 命令里不能出现 %"
    return (
        "SHELL=/bin/sh\n"
        f"PATH={CRON_PATH}\n"
        'MAILTO=""\n'
        "# cron 启动的作业不会继承容器环境变量，这里先加载环境变量文件。\n"
        f"{schedule} root {command}\n"
    )


def _write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _write_env_file(path: Path, content: str) -> Path:
    """写入环境变量文件，必要时回退到 /tmp。

    环境变量文件里有 Cookie 等敏感信息，权限设为 0600。
    """
    try:
        _write(path, content, 0o600)
        return path
    except OSError:
        _write(FALLBACK_ENV_FILE, content, 0o600)
        return FALLBACK_ENV_FILE


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成容器内 cron 定时任务的 crontab 和环境变量文件")
    parser.add_argument("--schedule", default=os.getenv("CRON_SCHEDULE", DEFAULT_SCHEDULE), help="cron 表达式")
    parser.add_argument("--cron-file", default=os.getenv("CRON_FILE", str(DEFAULT_CRON_FILE)), help="crontab 输出路径")
    parser.add_argument(
        "--env-file", default=os.getenv("CRON_ENV_FILE", str(DEFAULT_ENV_FILE)), help="环境变量文件输出路径"
    )
    parser.add_argument("--app-dir", default=os.getenv("APP_DIR", str(DEFAULT_APP_DIR)), help="任务工作目录")
    parser.add_argument("--python-bin", default=os.getenv("PYTHON_BIN", DEFAULT_PYTHON_BIN), help="python 解释器路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env_file = _write_env_file(Path(args.env_file), render_env_file(os.environ))
    # crontab 必须由 root 拥有，且不能对 group/other 可写，否则 cron 会忽略该文件。
    _write(Path(args.cron_file), render_crontab(args.schedule, env_file, Path(args.app_dir), args.python_bin), 0o644)
    print(f"[docker] cron env file: {env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
