from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.models import Message, Settings, Sticker, Target, TaskConfig


class ConfigError(ValueError):
    pass


def load_settings(env_file: str | Path | None = None) -> Settings:
    load_dotenv(dotenv_path=env_file)
    task_path = Path(os.getenv("TASK_CONFIG", "config.json")).expanduser()
    artifacts_dir = Path(os.getenv("ARTIFACTS_DIR", "artifacts")).expanduser()
    default_state = Path("storage-state.json")
    dingtalk_webhook = _optional_env("DINGTALK_WEBHOOK")
    dingtalk_secret = _optional_env("DINGTALK_SECRET")
    if bool(dingtalk_webhook) != bool(dingtalk_secret):
        raise ConfigError("DINGTALK_WEBHOOK 和 DINGTALK_SECRET 必须同时配置")

    webhook_url = _optional_env("WEBHOOK_URL")
    webhook_headers = _parse_webhook_headers(_optional_env("WEBHOOK_HEADERS"))
    webhook_template = _optional_env("WEBHOOK_TEMPLATE")

    return Settings(
        task_config_path=task_path,
        storage_state=_optional_env("DOUYIN_STORAGE_STATE") or (str(default_state) if default_state.is_file() else None),
        cookie=_optional_env("DOUYIN_COOKIE"),
        headless=_parse_bool(os.getenv("HEADLESS", "false"), "HEADLESS"),
        browser_path=_optional_env("BROWSER_PATH"),
        artifacts_dir=artifacts_dir,
        trace=_parse_bool(os.getenv("TRACE", "true"), "TRACE"),
        dingtalk_webhook=dingtalk_webhook,
        dingtalk_secret=dingtalk_secret,
        webhook_url=webhook_url,
        webhook_headers=webhook_headers,
        webhook_template=webhook_template,
    )


def load_task(settings: Settings) -> TaskConfig:
    raw = _read_json_file(settings.task_config_path, "任务配置")
    if not isinstance(raw, dict):
        raise ConfigError("任务配置必须是 JSON 对象")

    targets_raw = raw.get("targets")
    if targets_raw is None and "friends" in raw:
        friends = raw.get("friends")
        messages = raw.get("messages")
        if not isinstance(friends, list) or not friends:
            raise ConfigError("friends 必须是非空数组")
        if not isinstance(messages, list) or not messages:
            raise ConfigError("messages 必须是非空数组")
        targets_raw = [{"name": name, "messages": messages} for name in friends]
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ConfigError("targets 必须是非空数组")

    targets = tuple(_parse_target(item, index, settings.task_config_path.parent) for index, item in enumerate(targets_raw))
    interval = raw.get("send_interval_seconds", {})
    if not isinstance(interval, dict):
        raise ConfigError("send_interval_seconds 必须是对象")
    interval_min = _number(interval.get("min", 3), "send_interval_seconds.min")
    interval_max = _number(interval.get("max", 8), "send_interval_seconds.max")
    if interval_min < 0 or interval_max < interval_min:
        raise ConfigError("发送间隔必须满足 0 <= min <= max")

    stickers_raw = raw.get("stickers", {})
    if not isinstance(stickers_raw, dict):
        raise ConfigError("stickers 必须是对象")
    stickers = _parse_stickers(stickers_raw)
    legacy_stickers_path = settings.task_config_path.parent / "stickers.json"
    if not stickers and legacy_stickers_path.exists():
        stickers = _load_stickers(legacy_stickers_path)
    target_open_retries = raw.get("target_open_retries", 1)
    if isinstance(target_open_retries, bool) or not isinstance(target_open_retries, int) or target_open_retries < 0:
        raise ConfigError("target_open_retries 必须是非负整数")
    target_open_timeout_seconds = _number(
        raw.get("target_open_timeout_seconds", 15), "target_open_timeout_seconds"
    )
    if target_open_timeout_seconds <= 0:
        raise ConfigError("target_open_timeout_seconds 必须大于 0")

    raw_timeout = raw.get("timeout_seconds")
    env_timeout = os.environ.get("TASK_TIMEOUT") or os.environ.get("RUN_TIMEOUT")
    if env_timeout:
        try:
            timeout_seconds: float | None = float(env_timeout)
        except ValueError as exc:
            raise ConfigError("环境变量 TASK_TIMEOUT / RUN_TIMEOUT 必须是有效数值") from exc
    elif raw_timeout is not None:
        timeout_seconds = _number(raw_timeout, "timeout_seconds")
        if timeout_seconds <= 0:
            raise ConfigError("timeout_seconds 必须大于 0")
    else:
        timeout_seconds = None

    task = TaskConfig(
        task_id=_non_empty_string(raw.get("task_id", "daily-streak"), "task_id"),
        timezone=_non_empty_string(raw.get("timezone", "Asia/Shanghai"), "timezone"),
        targets=targets,
        stickers=stickers,
        interval_min=interval_min,
        interval_max=interval_max,
        continue_on_error=raw.get("continue_on_error", True),
        prevent_duplicates=raw.get("prevent_duplicates", False),
        target_open_retries=target_open_retries,
        target_open_timeout_seconds=target_open_timeout_seconds,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(task.continue_on_error, bool):
        raise ConfigError("continue_on_error 必须是布尔值")
    if not isinstance(task.prevent_duplicates, bool):
        raise ConfigError("prevent_duplicates 必须是布尔值")

    _validate_stickers(task)
    return task


def parse_auth_json(value: str, label: str) -> Any:
    candidate = Path(value).expanduser()
    try:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    except OSError:
        pass
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label} 不是有效 JSON 或可读文件路径") from exc


def _parse_target(raw: Any, index: int, config_dir: Path) -> Target:
    label = f"targets[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} 必须是对象")
    name = _non_empty_string(raw.get("name"), f"{label}.name")
    messages_raw = raw.get("messages")
    if not isinstance(messages_raw, list) or not messages_raw:
        raise ConfigError(f"{label}.messages 必须是非空数组")
    return Target(name=name, messages=tuple(_parse_message(item, f"{label}.messages[{i}]", config_dir) for i, item in enumerate(messages_raw)))


def _parse_message(raw: Any, label: str, config_dir: Path) -> Message:
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} 必须是对象")
    message_type = raw.get("type")
    value = raw.get("value")
    if message_type == "text":
        return Message(type="text", content=_non_empty_string(raw.get("content", value), f"{label}.value"))
    if message_type == "image":
        image_value = _non_empty_string(raw.get("path", value), f"{label}.value")
        path = Path(image_value).expanduser()
        if not path.is_absolute():
            project_relative = config_dir.parent / path
            path = project_relative if project_relative.exists() else config_dir / path
        if not path.is_file():
            raise ConfigError(f"{label}.path 文件不存在: {path}")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            raise ConfigError(f"{label}.path 仅支持 PNG、JPG、GIF、WEBP")
        return Message(type="image", path=path.resolve())
    if message_type in {"douyin_sticker", "sticker"}:
        return Message(type="douyin_sticker", sticker=_non_empty_string(raw.get("sticker", value), f"{label}.value"))
    if message_type == "random":
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ConfigError(f"{label}.choices 必须是非空数组")
        parsed = tuple(_parse_message(item, f"{label}.choices[{i}]", config_dir) for i, item in enumerate(choices))
        if any(item.type == "random" for item in parsed):
            raise ConfigError(f"{label} 不支持嵌套 random")
        return Message(type="random", choices=parsed)
    raise ConfigError(f"{label}.type 不支持: {message_type!r}")


def _load_stickers(path: Path) -> dict[str, Sticker]:
    raw = _read_json_file(path, "表情配置")
    if not isinstance(raw, dict):
        raise ConfigError("表情配置必须是 JSON 对象")
    return _parse_stickers(raw)


def _parse_stickers(raw: dict[str, Any]) -> dict[str, Sticker]:
    result: dict[str, Sticker] = {}
    for name, item in raw.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(item, dict):
            raise ConfigError("表情配置名称必须为非空字符串，值必须为对象")
        fallback_index = item.get("fallback_index")
        if fallback_index is not None and (not isinstance(fallback_index, int) or fallback_index < 0):
            raise ConfigError(f"表情 {name} 的 fallback_index 必须是非负整数")
        result[name] = Sticker(
            name=name,
            category=_optional_string(item.get("category")),
            accessible_name=_optional_string(item.get("accessible_name", item.get("label"))),
            fallback_index=fallback_index,
        )
    return result


def _validate_stickers(task: TaskConfig) -> None:
    def visit(message: Message) -> None:
        if message.type == "douyin_sticker" and message.sticker not in task.stickers:
            raise ConfigError(f"原生表情未在 config.json 的 stickers 中配置: {message.sticker}")
        for choice in message.choices:
            visit(choice)

    for target in task.targets:
        for message in target.messages:
            visit(message)


def _read_json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{label}文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label}不是有效 JSON: {path}") from exc


def _parse_bool(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{label} 必须是 true 或 false")


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} 必须是非空字符串")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_env(name: str) -> str | None:
    return _optional_string(os.getenv(name))


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} 必须是数字")
    return float(value)


def _parse_webhook_headers(value: str | None) -> dict[str, str] | None:
    """解析 WEBHOOK_HEADERS 环境变量为字典。

    支持格式：
    - JSON 对象: {"Content-Type": "application/json", "Authorization": "Bearer token"}
    - 键值对: Content-Type=application/json,Authorization=Bearer token
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None

    # 尝试 JSON 格式（数组或对象都尝试解析）
    if value.startswith("{") or value.startswith("["):
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ConfigError("WEBHOOK_HEADERS JSON 必须是对象，不能是数组")
            return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError as exc:
            raise ConfigError(f"WEBHOOK_HEADERS JSON 格式错误: {exc}") from exc

    # 尝试键值对格式 key1=value1,key2=value2
    headers = {}
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ConfigError(f"WEBHOOK_HEADERS 键值对格式错误，应为 key=value: {pair}")
        key, val = pair.split("=", 1)
        headers[key.strip()] = val.strip()
    return headers if headers else None
