from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_AUTH_PATH = Path("config") / "auth.json"
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 300  # 锁定 5 分钟
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 32
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{3,32}$")


class AuthError(Exception):
    """认证相关基础异常"""


class AccountLockedError(AuthError):
    """账户已锁定异常"""


class AuthenticationFailedError(AuthError):
    """身份验证失败异常"""


def hash_password(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    """使用 PBKDF2-HMAC-SHA256 生成强哈希密码存储字符串。

    格式: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    if salt is None:
        salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """恒定时间比对密码，防范时序侧信道攻击。"""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_dk = bytes.fromhex(parts[3])
    except (ValueError, IndexError):
        return False

    computed_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(computed_dk, expected_dk)


def validate_username(username: str) -> bool:
    """校验用户名规则：3-32位字符，仅允许字母、数字、下划线、短横线、点。"""
    return bool(USERNAME_REGEX.match(username))


def validate_password_complexity(password: str) -> tuple[bool, str]:
    """校验密码强度：长度至少8位，包含字母和数字。"""
    if len(password) < 8:
        return False, "密码长度至少需要 8 个字符"
    if not any(c.isalpha() for c in password):
        return False, "密码需要包含至少一个字母"
    if not any(c.isdigit() for c in password):
        return False, "密码需要包含至少一个数字"
    return True, ""


class AuthManager:
    """负责管理本地鉴权凭证、初始配置、认证校验和防爆破锁定。"""

    def __init__(self, auth_file: Path | str = DEFAULT_AUTH_PATH) -> None:
        self.auth_file = Path(auth_file)

    def is_initialized(self) -> bool:
        """检查凭证文件是否存在且有效。"""
        if not self.auth_file.exists():
            return False
        try:
            data = self._read_data()
            return bool(data.get("username") and data.get("password_hash"))
        except Exception:
            return False

    def _read_data(self) -> dict[str, Any]:
        with self.auth_file.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_data(self, data: dict[str, Any]) -> None:
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        # 原子写入并限制文件权限（仅属主可读写 0600）
        dir_path = self.auth_file.parent
        with tempfile.NamedTemporaryFile("w", dir=dir_path, delete=False, encoding="utf-8") as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp.flush()
            temp_name = tmp.name

        try:
            # POSIX 权限设置，Windows 下尽力生效不报错
            os.chmod(temp_name, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

        # 跨平台原子重命名替换
        os.replace(temp_name, self.auth_file)

    def initialize_credentials(self, username: str, password: str) -> None:
        """首次配置初始化用户名与密码。如果已初始化则抛出异常禁止二次初始化覆盖。"""
        if self.is_initialized():
            raise AuthError("系统凭据已经初始化，禁止重复初始化！如需修改请使用修改密码命令。")

        username = username.strip()
        if not validate_username(username):
            raise AuthError("用户名格式不合法（必须为 3-32 位字母、数字、下划线、短横线或点）")

        ok, msg = validate_password_complexity(password)
        if not ok:
            raise AuthError(f"密码不符合复杂度要求: {msg}")

        data = {
            "username": username,
            "password_hash": hash_password(password),
            "failed_attempts": 0,
            "lockout_until": 0,
            "updated_at": int(time.time()),
        }
        self._write_data(data)

    def change_password(self, new_password: str, target_username: str | None = None) -> None:
        """修改管理员密码，同时重置锁定状态。"""
        if not self.is_initialized():
            raise AuthError("系统尚未初始化凭据，请先启动初始化！")

        data = self._read_data()
        current_username = data.get("username")
        if target_username and target_username.strip() != current_username:
            raise AuthError(f"指定的用户名 '{target_username}' 与当前配置的用户 '{current_username}' 不匹配")

        ok, msg = validate_password_complexity(new_password)
        if not ok:
            raise AuthError(f"新密码不符合复杂度要求: {msg}")

        data["password_hash"] = hash_password(new_password)
        data["failed_attempts"] = 0
        data["lockout_until"] = 0
        data["updated_at"] = int(time.time())
        self._write_data(data)

    def authenticate(self, username: str, password: str) -> bool:
        """执行身份认证，包含防暴力破解锁定机制。"""
        if not self.is_initialized():
            raise AuthError("系统凭据尚未初始化")

        data = self._read_data()
        now = time.time()
        lockout_until = data.get("lockout_until", 0)

        if lockout_until > now:
            remaining = int(lockout_until - now)
            raise AccountLockedError(f"认证失败次数过多，账户已被锁定，请在 {remaining} 秒后再试")

        configured_username = data.get("username", "")
        # 使用恒定时间对比用户名，防止用户枚举计时攻击
        username_match = hmac.compare_digest(username.strip().encode("utf-8"), configured_username.encode("utf-8"))
        stored_hash = data.get("password_hash", "")
        # 即使用户名不匹配也计算密码比对，保证无论用户名是否正确都消耗接近相同的计算时间
        password_match = verify_password(password, stored_hash)

        if username_match and password_match:
            # 登录成功，重置失败次数
            if data.get("failed_attempts", 0) > 0 or data.get("lockout_until", 0) > 0:
                data["failed_attempts"] = 0
                data["lockout_until"] = 0
                self._write_data(data)
            return True

        # 认证失败，累加计数器并实施锁定
        attempts = data.get("failed_attempts", 0) + 1
        data["failed_attempts"] = attempts
        if attempts >= MAX_FAILED_ATTEMPTS:
            data["lockout_until"] = int(now + LOCKOUT_DURATION_SECONDS)
            self._write_data(data)
            raise AccountLockedError(f"连续失败 {attempts} 次，账户已被锁定 {LOCKOUT_DURATION_SECONDS} 秒")
        else:
            self._write_data(data)
            remaining_attempts = MAX_FAILED_ATTEMPTS - attempts
            raise AuthenticationFailedError(f"用户名或密码错误！剩余尝试次数: {remaining_attempts}")


def prompt_for_initialization(auth_mgr: AuthManager) -> None:
    """交互式或通过环境变量引导首次初始化。"""
    # 优先检查非交互式环境变量
    env_user = os.environ.get("APP_AUTH_USERNAME")
    env_pwd = os.environ.get("APP_AUTH_PASSWORD")
    if env_user and env_pwd:
        auth_mgr.initialize_credentials(env_user, env_pwd)
        print("✓ 已通过环境变量完成首次凭据初始化喵～")
        return

    print("=" * 60)
    print("【安全提示】检测到系统首次启动，请先设置登录凭证喵～")
    print("说明: 用户名为 3-32 位字母/数字/下划线，密码需至少 8 位包含字母与数字。")
    print("=" * 60)

    while True:
        try:
            username = input("请输入初始用户名: ").strip()
            if not validate_username(username):
                print("❌ 用户名格式不合法，请重新输入（3-32位字符，仅限字母/数字/下划线/短横线/点）")
                continue

            pwd1 = getpass.getpass("请输入初始密码: ")
            ok, msg = validate_password_complexity(pwd1)
            if not ok:
                print(f"❌ 密码不合规: {msg}")
                continue

            pwd2 = getpass.getpass("请再次确认密码: ")
            if pwd1 != pwd2:
                print("❌ 两次密码输入不一致，请重新输入！")
                continue

            auth_mgr.initialize_credentials(username, pwd1)
            print("✓ 初始化凭据成功！请妥善保管好您的凭据喵～\n")
            break
        except (KeyboardInterrupt, EOFError):
            print("\n初始化已被用户中断")
            sys.exit(130)


def prompt_for_login(auth_mgr: AuthManager) -> None:
    """交互式或环境变量登录。"""
    # 优先检查非交互式自动化登录环境变量
    env_user = os.environ.get("APP_AUTH_USERNAME")
    env_pwd = os.environ.get("APP_AUTH_PASSWORD")
    if env_user and env_pwd:
        auth_mgr.authenticate(env_user, env_pwd)
        return

    print("=" * 60)
    print("【系统鉴权】请输入系统凭据进行身份验证喵～")
    print("=" * 60)

    while True:
        try:
            username = input("用户名: ").strip()
            password = getpass.getpass("密码: ")
            auth_mgr.authenticate(username, password)
            print("✓ 身份验证通过喵～\n")
            return
        except AuthenticationFailedError as exc:
            print(f"❌ {exc}\n")
        except AccountLockedError as exc:
            print(f"🚫 {exc}\n")
            raise
        except (KeyboardInterrupt, EOFError):
            print("\n登录已被用户中断")
            sys.exit(130)


def ensure_authenticated(auth_file: Path | str = DEFAULT_AUTH_PATH) -> None:
    """入口守卫函数：未初始化则引导初始化，初始化后必须完成登录。"""
    auth_mgr = AuthManager(auth_file)
    if not auth_mgr.is_initialized():
        prompt_for_initialization(auth_mgr)
    prompt_for_login(auth_mgr)
