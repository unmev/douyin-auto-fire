import json
from pathlib import Path

import pytest

from app.accounts import load_accounts
from app.config import ConfigError


def write_accounts(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_missing_file_means_single_account_mode(tmp_path: Path) -> None:
    assert load_accounts(tmp_path / "missing.json") is None


def test_loads_enabled_accounts_only(tmp_path: Path) -> None:
    path = write_accounts(
        tmp_path,
        {
            "accounts": [
                {"id": "account1", "enabled": True, "env_file": ".env.account1"},
                {"id": "account2", "enabled": False, "env_file": ".env.account2"},
                {"id": "account3", "env_file": ".env.account3"},
            ]
        },
    )

    accounts = load_accounts(path)

    assert [account.id for account in accounts] == ["account1", "account3"]
    assert accounts[0].env_file == Path(".env.account1")


def test_all_disabled_returns_empty_list(tmp_path: Path) -> None:
    path = write_accounts(tmp_path, {"accounts": [{"id": "a", "enabled": False, "env_file": ".env.a"}]})

    assert load_accounts(path) == []


def test_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="不是有效 JSON"):
        load_accounts(path)


def test_rejects_missing_accounts_key(tmp_path: Path) -> None:
    path = write_accounts(tmp_path, {"foo": []})

    with pytest.raises(ConfigError, match="缺少 accounts 数组"):
        load_accounts(path)


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = write_accounts(
        tmp_path,
        {"accounts": [{"id": "a", "env_file": ".env.a"}, {"id": "a", "env_file": ".env.b"}]},
    )

    with pytest.raises(ConfigError, match="id 重复"):
        load_accounts(path)


def test_rejects_invalid_enabled_type(tmp_path: Path) -> None:
    path = write_accounts(tmp_path, {"accounts": [{"id": "a", "enabled": "yes", "env_file": ".env.a"}]})

    with pytest.raises(ConfigError, match="enabled 必须是布尔值"):
        load_accounts(path)


def test_rejects_missing_env_file_field(tmp_path: Path) -> None:
    path = write_accounts(tmp_path, {"accounts": [{"id": "a", "enabled": True}]})

    with pytest.raises(ConfigError, match="env_file 必须是非空字符串"):
        load_accounts(path)
