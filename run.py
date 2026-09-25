from __future__ import annotations

import argparse
import getpass
import sys

from app.accounts import load_accounts
from app.account_runner import run_all_accounts
from app.auth import (
    AccountLockedError,
    AuthError,
    AuthManager,
    DEFAULT_AUTH_PATH,
    ensure_authenticated,
    validate_password_complexity,
)
from app.config import ConfigError
from app.interrupt import ExecutionInterruptedError, ExecutionTimeoutError, signal_interrupt_handler
from app.main import main as run_single



def _handle_change_password(args: argparse.Namespace) -> int:
    auth_mgr = AuthManager(args.auth_file or DEFAULT_AUTH_PATH)
    if not auth_mgr.is_initialized():
        print("错误: 系统凭据尚未初始化，请直接运行程序以完成首次初始化喵～", file=sys.stderr)
        return 1

    new_pwd = args.new_password
    if not new_pwd:
        try:
            pwd1 = getpass.getpass("请输入新密码: ")
            ok, msg = validate_password_complexity(pwd1)
            if not ok:
                print(f"错误: 密码不符合复杂度要求: {msg}", file=sys.stderr)
                return 1
            pwd2 = getpass.getpass("请再次确认新密码: ")
            if pwd1 != pwd2:
                print("错误: 两次输入的密码不一致！", file=sys.stderr)
                return 1
            new_pwd = pwd1
        except (KeyboardInterrupt, EOFError):
            print("\n操作已取消")
            return 130

    try:
        auth_mgr.change_password(new_pwd, target_username=args.username)
        print("✓ 密码修改成功！锁定状态已重置喵～")
        return 0
    except AuthError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def _handle_init_auth(args: argparse.Namespace) -> int:
    auth_mgr = AuthManager(args.auth_file or DEFAULT_AUTH_PATH)
    if auth_mgr.is_initialized():
        print("错误: 系统凭据已经初始化，禁止重复初始化！如需修改请使用 change-password 命令喵～", file=sys.stderr)
        return 1

    username = args.username
    password = args.password
    if not username or not password:
        print("错误: init-auth 命令需要提供 --username 和 --password 参数喵～", file=sys.stderr)
        return 1

    try:
        auth_mgr.initialize_credentials(username, password)
        print("✓ 初始化凭据成功喵～")
        return 0
    except AuthError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="抖音自动发消息系统 (含系统安全认证与凭证管理)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="子命令")

    # change-password 子命令
    change_pwd_parser = subparsers.add_parser(
        "change-password",
        help="修改系统管理员密码（可用于重置忘记的密码并解除爆破锁定）",
    )
    change_pwd_parser.add_argument("--username", help="需要修改密码的目标用户名（可选）")
    change_pwd_parser.add_argument("--new-password", help="新密码（若未提供将在交互提示中安全输入）")
    change_pwd_parser.add_argument("--auth-file", help="指定 auth.json 凭证文件路径")

    # init-auth 子命令（主要供自动化/脚本使用，常规交互式运行直接启动即可引导初始化）
    init_auth_parser = subparsers.add_parser(
        "init-auth",
        help="命令行非交互式初始化用户名与密码",
    )
    init_auth_parser.add_argument("--username", required=True, help="初始用户名")
    init_auth_parser.add_argument("--password", required=True, help="初始密码")
    init_auth_parser.add_argument("--auth-file", help="指定 auth.json 凭证文件路径")

    # 发送任务相关参数（兼容直接透传）
    parser.add_argument("--dry-run", action="store_true", help="只验证登录和好友，不发送消息（测试模式）")
    parser.add_argument("--env-file", help="指定 .env 文件路径")
    parser.add_argument("--auth-file", help="指定 auth.json 凭证文件路径")
    parser.add_argument("--timeout", type=float, default=None, help="最大执行超时秒数，超时后自动中断并退出")
    parser.add_argument("--fail-fast", action="store_true", help="遇到首个目标失败或配置错误时立即中断退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)

    if args.subcommand == "change-password":
        return _handle_change_password(args)
    if args.subcommand == "init-auth":
        return _handle_init_auth(args)

    # 默认运行发消息主程序前进行身份鉴权
    try:
        ensure_authenticated(args.auth_file or DEFAULT_AUTH_PATH)
    except AccountLockedError as exc:
        print(f"认证失败: {exc}", file=sys.stderr)
        return 2
    except AuthError as exc:
        print(f"认证错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n操作已取消")
        return 130

    try:
        with signal_interrupt_handler():
            accounts = load_accounts()
            if accounts is None:
                # 没有 config/accounts.json：单账号模式
                return run_single()
            return run_all_accounts()
    except ConfigError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except ExecutionTimeoutError as exc:
        print(f"执行超时中断: {exc}", file=sys.stderr)
        return 124
    except (KeyboardInterrupt, ExecutionInterruptedError):
        print("\n任务已由用户或系统中断取消")
        return 130

if __name__ == "__main__":
    raise SystemExit(main())
