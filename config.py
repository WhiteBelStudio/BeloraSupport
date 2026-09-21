from __future__ import annotations

import logging
import os


def _ids(name: str) -> set[int]:
    return {int(x.strip()) for x in os.getenv(name, "").split(",") if x.strip().isdigit()}


def owner_ids(platform: str) -> set[int]:
    return _ids("OWNER_TG_ID" if platform == "telegram" else "OWNER_VK_ID")


def admin_ids(platform: str = "telegram") -> set[int]:
    # ADMIN_IDS remains supported as Telegram bootstrap admins.
    env_name = "ADMIN_TG_IDS" if platform == "telegram" else "ADMIN_VK_IDS"
    result = _ids(env_name)
    if platform == "telegram":
        result |= _ids("ADMIN_IDS")
    return result


def is_owner(platform: str, user_id: int) -> bool:
    return user_id in owner_ids(platform)


def is_admin(platform: str, user_id: int) -> bool:
    return is_owner(platform, user_id) or user_id in admin_ids(platform)


def setup_logging() -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
