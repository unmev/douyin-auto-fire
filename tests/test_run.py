from pathlib import Path

import run as run_module


def _write_accounts(tmp_path: Path, content: str) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "accounts.json").write_text(content, encoding="utf-8")


def test_no_accounts_file_uses_single_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_module, "run_single", lambda: 42)
    monkeypatch.setattr(run_module, "run_all_accounts", lambda: 7)

    assert run_module.main() == 42


def test_accounts_file_uses_multi_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write_accounts(tmp_path, '{"accounts": [{"id": "a", "env_file": ".env.a"}]}')
    monkeypatch.setattr(run_module, "run_single", lambda: 42)
    monkeypatch.setattr(run_module, "run_all_accounts", lambda: 7)

    assert run_module.main() == 7


def test_broken_accounts_file_returns_2(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write_accounts(tmp_path, "not json")
    monkeypatch.setattr(run_module, "run_single", lambda: 42)
    monkeypatch.setattr(run_module, "run_all_accounts", lambda: 7)

    assert run_module.main() == 2


def test_multi_mode_interrupt_returns_130(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write_accounts(tmp_path, '{"accounts": []}')
    monkeypatch.setattr(run_module, "run_single", lambda: 42)

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "run_all_accounts", interrupted)

    assert run_module.main() == 130
