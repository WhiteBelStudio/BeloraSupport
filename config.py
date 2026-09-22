from __future__ import annotations

import logging
import os


# Runtime cache of administrators stored in SQLite.
# This keeps the existing synchronous is_admin() API used by both bots,
# while making /addadmin effective immediately and after restart.
_DB_ADMINS: dict[str, set[int]] = {"telegram": set(), "vk": set()}


def _ids(name: str) -> set[int]:
    return {int(x.strip()) for x in os.getenv(name, "").split(",") if x.strip().isdigit()}


def owner_ids(platform: str) -> set[int]:
    return _ids("OWNER_TG_ID" if platform == "telegram" else "OWNER_VK_ID")


def admin_ids(platform: str = "telegram") -> set[int]:
    # Environment/bootstrap administrators plus administrators loaded from DB.
    env_name = "ADMIN_TG_IDS" if platform == "telegram" else "ADMIN_VK_IDS"
    result = _ids(env_name)
    if platform == "telegram":
        result |= _ids("ADMIN_IDS")
    result |= _DB_ADMINS.get(platform, set())
    return result


def register_admin(platform: str, user_id: int) -> None:
    if platform in _DB_ADMINS:
        _DB_ADMINS[platform].add(int(user_id))


def unregister_admin(platform: str, user_id: int) -> None:
    if platform in _DB_ADMINS:
        _DB_ADMINS[platform].discard(int(user_id))


async def load_admin_cache() -> None:
    """Load database administrators into the authorization cache at startup."""
    from database import list_admins

    for platform in ("telegram", "vk"):
        _DB_ADMINS[platform].clear()
        for row in await list_admins(platform):
            try:
                _DB_ADMINS[platform].add(int(row["user_id"]))
            except (KeyError, TypeError, ValueError):
                continue


def is_owner(platform: str, user_id: int) -> bool:
    return int(user_id) in owner_ids(platform)


def is_admin(platform: str, user_id: int) -> bool:
    return is_owner(platform, user_id) or int(user_id) in admin_ids(platform)


def setup_logging() -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
