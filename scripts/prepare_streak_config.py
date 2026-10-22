from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.browser import open_douyin, open_private_messages
from app.config import load_settings
from app.streaks import discover_streak_friends


STICKER_NAME = "晚上好"


async def prepare() -> int:
    settings = replace(load_settings(), trace=False)
    async with open_douyin(settings) as session:
        await open_private_messages(session.page)
        friends = await discover_streak_friends(session.page, needs_renewal_only=True)

    if not friends:
        print("未识别到任何今天尚待续火花的好友，保留原配置并停止发送。")
        return 2

    config = {
        "task_id": "auto-streak-goodnight",
        "timezone": "Asia/Shanghai",
        "targets": [
            {
                "name": name,
                "messages": [{"type": "douyin_sticker", "sticker": STICKER_NAME}],
            }
            for name in friends
        ],
        "stickers": {
            STICKER_NAME: {
                "label": STICKER_NAME,
            }
        },
        "send_interval_seconds": {"min": 3, "max": 8},
        "prevent_duplicates": True,
        "continue_on_error": True,
        "target_open_retries": 1,
        "target_open_timeout_seconds": 15,
    }

    destination = settings.task_config_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"已识别 {len(friends)} 位今天尚待续火花的好友并更新发送配置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(prepare()))
