from app.accounts import load_accounts
from app.account_runner import run_all_accounts
from app.config import ConfigError
from app.main import main as run_single


def main() -> int:
    try:
        accounts = load_accounts()
    except ConfigError as exc:
        print(f"错误: {exc}")
        return 2
    if accounts is None:
        # 没有 config/accounts.json：旧单账号模式，行为不变。
        return run_single()
    try:
        return run_all_accounts()
    except KeyboardInterrupt:
        print("任务已取消")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
