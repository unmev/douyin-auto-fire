"""docker/setup_cron.py 的回归测试。

重点覆盖：cron 作业拿不到容器环境变量这个 bug 的根因修复，
以及环境变量文件里的特殊字符（引号、空格、%、$、换行）不会被破坏。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "docker" / "setup_cron.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("setup_cron", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup_cron = _load_module()

requires_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="需要 POSIX shell")


# ---------- 环境变量文件 ----------


def test_env_file_exports_container_variables() -> None:
    content = setup_cron.render_env_file({"DOUYIN_COOKIE": "/data/cookie.json", "TASK_CONFIG": "/app/config.json"})

    assert "export DOUYIN_COOKIE=/data/cookie.json" in content
    assert "export TASK_CONFIG=/app/config.json" in content


def test_env_file_ignores_shell_bookkeeping_variables() -> None:
    content = setup_cron.render_env_file({"PWD": "/app", "OLDPWD": "/", "SHLVL": "1", "_": "/usr/bin/python"})

    assert "export PWD" not in content
    assert "export OLDPWD" not in content
    assert "export SHLVL" not in content
    assert "export _=" not in content


def test_env_file_skips_empty_values() -> None:
    content = setup_cron.render_env_file({"DINGTALK_WEBHOOK": "", "HEADLESS": "true"})

    assert "export DINGTALK_WEBHOOK" not in content
    assert "export HEADLESS=true" in content


def test_env_file_skips_invalid_shell_variable_names() -> None:
    content = setup_cron.render_env_file({"BASH_FUNC_x%%": "() { :; }", "BAD-NAME": "x", "GOOD_NAME": "y"})

    assert "export GOOD_NAME=y" in content
    assert "BASH_FUNC" not in content
    assert "BAD-NAME" not in content


def test_env_file_quotes_json_values() -> None:
    cookie = '[{"name":"sessionid","value":"abc"}]'

    content = setup_cron.render_env_file({"DOUYIN_COOKIE": cookie})

    assert content.count("export DOUYIN_COOKIE=") == 1
    assert "\n" not in content.split("export DOUYIN_COOKIE=")[1].rstrip("\n")


# ---------- crontab ----------


def test_crontab_contains_schedule_and_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "env.sh"

    content = setup_cron.render_crontab("30 0 * * *", env_file)

    assert "30 0 * * * root " in content
    assert f". {env_file}" in content
    assert "python run.py" in content


def test_crontab_disables_mail() -> None:
    content = setup_cron.render_crontab("30 0 * * *", Path("/run/douyin-auto-fire/env.sh"))

    assert 'MAILTO=""' in content


def test_crontab_command_has_no_percent_sign(tmp_path: Path) -> None:
    """cron 会把命令里的 % 当成换行符，命令部分不能出现 %。"""
    content = setup_cron.render_crontab("30 0 * * *", tmp_path / "env.sh")

    command = content.strip().splitlines()[-1]
    assert "%" not in command


def test_crontab_sets_shell_and_path() -> None:
    content = setup_cron.render_crontab("30 0 * * *", Path("/run/douyin-auto-fire/env.sh"))

    assert "SHELL=/bin/sh" in content
    assert "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" in content


# ---------- 落盘行为 ----------


def test_written_files_have_safe_permissions(tmp_path: Path) -> None:
    cron_file = tmp_path / "cron.d" / "douyin-auto-fire"
    env_file = tmp_path / "run" / "env.sh"

    exit_code = setup_cron.main(
        [
            "--schedule",
            "30 0 * * *",
            "--cron-file",
            str(cron_file),
            "--env-file",
            str(env_file),
        ]
    )

    assert exit_code == 0
    assert cron_file.exists()
    assert env_file.exists()
    # crontab 不能对 group/other 可写，否则 cron 会直接忽略这个文件。
    assert cron_file.stat().st_mode & 0o022 == 0
    # 环境变量文件里有 Cookie，必须只有 root 可读。
    assert env_file.stat().st_mode & 0o077 == 0


def test_cli_writes_crontab_and_env_file(tmp_path: Path) -> None:
    cron_file = tmp_path / "cron.d" / "douyin-auto-fire"
    env_file = tmp_path / "run" / "env.sh"
    env = {**os.environ, "DOUYIN_COOKIE": "/data/cookie.json", "CRON_SCHEDULE": "0 8 * * *"}

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--cron-file",
            str(cron_file),
            "--env-file",
            str(env_file),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "0 8 * * * root" in cron_file.read_text(encoding="utf-8")
    assert "export DOUYIN_COOKIE=/data/cookie.json" in env_file.read_text(encoding="utf-8")
    assert "cron env file" in result.stdout


# ---------- 端到端：source 之后环境变量必须原样还原 ----------


@requires_sh
@pytest.mark.parametrize(
    "value",
    [
        "/data/cookie.json",
        "Asia/Shanghai",
        "true",
        "30 0 * * *",
        '{"name":"sessionid","value":"a b"}',
        "it's a value",
        'say "hi"',
        "100% done",
        "$HOME and `whoami`",
        "line1\nline2",
        "中文值",
    ],
)
def test_sourced_env_file_restores_original_value(tmp_path: Path, value: str) -> None:
    env_file = tmp_path / "env.sh"
    env_file.write_text(setup_cron.render_env_file({"DOUYIN_COOKIE": value}), encoding="utf-8")

    result = subprocess.run(
        ["sh", "-c", '. "$1"; printf "%s" "$DOUYIN_COOKIE"', "sh", str(env_file)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == value
