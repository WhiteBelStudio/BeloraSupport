from __future__ import annotations

import logging
import os


# Runtime cache of administrators loaded from SQLite.
_DB_ADMINS: dict[str, set[int]] = {"telegram": set(), "vk": set()}


def _platform(platform: str) -> str:
    value = str(platform).strip().lower()
    if value in {"tg", "telegram"}:
        return "telegram"
    if value in {"vk", "vkontakte"}:
        return "vk"
    raise ValueError(f"Unknown platform: {platform}")


def _ids(name: str) -> set[int]:
    result: set[int] = set()
    raw = os.getenv(name, "")
    for value in raw.replace(";", ",").split(","):
        value = value.strip()
        if value and value.lstrip("-").isdigit():
            try:
                result.add(int(value))
            except ValueError:
                pass
    return result


def owner_ids(platform: str) -> set[int]:
    platform = _platform(platform)
    return _ids("OWNER_TG_ID" if platform == "telegram" else "OWNER_VK_ID")


def admin_ids(platform: str = "telegram") -> set[int]:
    """Return all explicitly configured/database administrators for a platform."""
    platform = _platform(platform)
    env_name = "ADMIN_TG_IDS" if platform == "telegram" else "ADMIN_VK_IDS"
    result = _ids(env_name)
    # ADMIN_IDS is the legacy Telegram bootstrap variable.
    if platform == "telegram":
        result |= _ids("ADMIN_IDS")
    result |= _DB_ADMINS.get(platform, set())
    return {int(value) for value in result}


def effective_admin_ids(platform: str = "telegram") -> set[int]:
    """Return owners + administrators; useful for displaying the real access list."""
    platform = _platform(platform)
    return owner_ids(platform) | admin_ids(platform)


def register_admin(platform: str, user_id: int) -> None:
    platform = _platform(platform)
    _DB_ADMINS[platform].add(int(user_id))


def unregister_admin(platform: str, user_id: int) -> None:
    platform = _platform(platform)
    _DB_ADMINS[platform].discard(int(user_id))


async def load_admin_cache() -> None:
    """Load database administrators into the authorization cache at startup."""
    from database import list_admins

    for platform in ("telegram", "vk"):
        _DB_ADMINS[platform].clear()
        rows = await list_admins(platform)
        for row in rows:
            try:
                user_id = row["user_id"]
                _DB_ADMINS[platform].add(int(str(user_id).strip()))
            except (KeyError, TypeError, ValueError):
                continue


def is_owner(platform: str, user_id: int | str) -> bool:
    try:
        return int(str(user_id).strip()) in owner_ids(platform)
    except (TypeError, ValueError):
        return False


def is_admin(platform: str, user_id: int | str) -> bool:
    """Single authorization function used by both Telegram and VK."""
    try:
        normalized_id = int(str(user_id).strip())
    except (TypeError, ValueError):
        return False
    platform = _platform(platform)
    return normalized_id in effective_admin_ids(platform)


def setup_logging() -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
