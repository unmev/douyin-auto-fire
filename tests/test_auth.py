import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.auth import (
    AccountLockedError,
    AuthError,
    AuthenticationFailedError,
    AuthManager,
    hash_password,
    validate_password_complexity,
    validate_username,
    verify_password,
)
import run as run_module


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.tmp_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_password_hash_and_verification(self):
        raw = "MySecurePass123"
        hashed = hash_password(raw, iterations=10_000)
        self.assertTrue(hashed.startswith("pbkdf2_sha256$10000$"))
        self.assertTrue(verify_password(raw, hashed))
        self.assertFalse(verify_password("WrongPass123", hashed))
        self.assertFalse(verify_password("", hashed))
        self.assertFalse(verify_password(raw, "invalid_hash_string"))

    def test_username_validation(self):
        self.assertTrue(validate_username("admin"))
        self.assertTrue(validate_username("admin_01"))
        self.assertTrue(validate_username("user.name-123"))
        # 格式或长度不符合
        self.assertFalse(validate_username("a"))
        self.assertFalse(validate_username("a" * 33))
        self.assertFalse(validate_username("admin@domain"))
        self.assertFalse(validate_username("user name"))
        self.assertFalse(validate_username("admin;rm -rf"))

    def test_password_complexity_validation(self):
        ok, _ = validate_password_complexity("ValidPass123")
        self.assertTrue(ok)

        ok, msg = validate_password_complexity("short1A")
        self.assertFalse(ok)
        self.assertIn("8", msg)

        ok, msg = validate_password_complexity("1234567890")
        self.assertFalse(ok)
        self.assertIn("字母", msg)

        ok, msg = validate_password_complexity("onlylettersPureAlpha")
        self.assertFalse(ok)
        self.assertIn("数字", msg)

    def test_auth_manager_initialization_and_duplicate_prevention(self):
        auth_file = self.tmp_path / "auth.json"
        mgr = AuthManager(auth_file)
        self.assertFalse(mgr.is_initialized())

        mgr.initialize_credentials("admin", "AdminPass123")
        self.assertTrue(mgr.is_initialized())

        # 验证文件结构与哈希内容，不存明文
        content = json.loads(auth_file.read_text(encoding="utf-8"))
        self.assertEqual(content["username"], "admin")
        self.assertNotIn("AdminPass123", auth_file.read_text(encoding="utf-8"))
        self.assertTrue(content["password_hash"].startswith("pbkdf2_sha256$"))

        # 重复初始化必须被拒绝
        with self.assertRaises(AuthError) as ctx:
            mgr.initialize_credentials("admin", "AnotherPass123")
        self.assertIn("已经初始化，禁止重复初始化", str(ctx.exception))

    def test_auth_manager_authenticate_success(self):
        auth_file = self.tmp_path / "auth.json"
        mgr = AuthManager(auth_file)
        mgr.initialize_credentials("master", "MasterPass123")

        self.assertTrue(mgr.authenticate("master", "MasterPass123"))

    def test_auth_manager_lockout_mechanism(self):
        auth_file = self.tmp_path / "auth.json"
        mgr = AuthManager(auth_file)
        mgr.initialize_credentials("victim", "SecureVictim123")

        # 连续失败 4 次
        for i in range(1, 5):
            with self.assertRaises(AuthenticationFailedError) as ctx:
                mgr.authenticate("victim", "WrongPass123")
            self.assertIn(f"剩余尝试次数: {5 - i}", str(ctx.exception))

        # 第 5 次失败，触发锁定
        with self.assertRaises(AccountLockedError) as ctx:
            mgr.authenticate("victim", "WrongPass123")
        self.assertIn("连续失败 5 次，账户已被锁定", str(ctx.exception))

        # 锁定期间即使输入正确密码也应当拒绝
        with self.assertRaises(AccountLockedError) as ctx:
            mgr.authenticate("victim", "SecureVictim123")
        self.assertIn("账户已被锁定", str(ctx.exception))

    def test_change_password_and_reset_lockout(self):
        auth_file = self.tmp_path / "auth.json"
        mgr = AuthManager(auth_file)
        mgr.initialize_credentials("admin", "OldPass123")

        # 触发锁定
        for _ in range(5):
            try:
                mgr.authenticate("admin", "WrongPass123")
            except AuthError:
                pass

        with self.assertRaises(AccountLockedError):
            mgr.authenticate("admin", "OldPass123")

        # 用命令修改密码，解除锁定
        mgr.change_password("NewSecurePass456", target_username="admin")

        # 新密码能够正常登录
        self.assertTrue(mgr.authenticate("admin", "NewSecurePass456"))

        # 旧密码不再有效
        with self.assertRaises(AuthenticationFailedError):
            mgr.authenticate("admin", "OldPass123")

    def test_cli_subcommand_change_password(self):
        auth_file = self.tmp_path / "auth.json"
        mgr = AuthManager(auth_file)
        mgr.initialize_credentials("root", "RootPass123")

        ret = run_module.main([
            "change-password",
            "--auth-file", str(auth_file),
            "--username", "root",
            "--new-password", "ResetPass789",
        ])
        self.assertEqual(ret, 0)

        # 验证新密码能通过认证
        self.assertTrue(mgr.authenticate("root", "ResetPass789"))

    def test_cli_subcommand_init_auth(self):
        auth_file = self.tmp_path / "auth.json"
        ret = run_module.main([
            "init-auth",
            "--auth-file", str(auth_file),
            "--username", "cli_user",
            "--password", "CliPass123",
        ])
        self.assertEqual(ret, 0)
        mgr = AuthManager(auth_file)
        self.assertTrue(mgr.is_initialized())
        self.assertTrue(mgr.authenticate("cli_user", "CliPass123"))

    def test_cli_main_run_with_env_auth(self):
        auth_file = self.tmp_path / "auth.json"
        mgr = AuthManager(auth_file)
        mgr.initialize_credentials("env_user", "EnvPass123")

        env_backup = dict(os.environ)
        try:
            os.environ["APP_AUTH_USERNAME"] = "env_user"
            os.environ["APP_AUTH_PASSWORD"] = "EnvPass123"
            with patch("run.run_single", return_value=0), patch("run.load_accounts", return_value=None):
                ret = run_module.main(["--auth-file", str(auth_file)])
                self.assertEqual(ret, 0)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


if __name__ == "__main__":
    unittest.main()
