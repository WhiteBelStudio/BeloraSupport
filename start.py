from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

from config import setup_logging
from database import clear_all_applications, init_db
from telegram_bot.bot import run_telegram_bot

load_dotenv()
setup_logging()
logger = logging.getLogger("BeloraSupport")


async def main() -> None:
    logger.info("BeloraSupport v1.0.0 starting...")
    await init_db()

    # One-time cleanup of old test/recorded applications.
    # The marker lives outside the cloned app directory, so the Pterodactyl
    # launcher can safely reclone the repository on every restart.
    reset_marker = "/home/container/.belorasupport_applications_reset_v1"
    if not os.path.exists(reset_marker):
        removed = await clear_all_applications()
        try:
            with open(reset_marker, "w", encoding="utf-8") as marker:
                marker.write("done")
        except OSError:
            logger.warning("Could not create application reset marker")
        logger.info("🧹 One-time application cleanup complete: %s removed", removed)
    tasks = []
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        tasks.append(asyncio.create_task(run_telegram_bot()))
    else:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured")
    if os.getenv("VK_TOKEN"):
        from vk_bot.bot import run_vk_bot
        tasks.append(asyncio.create_task(run_vk_bot()))
    else:
        logger.info("VK_TOKEN is not configured; VK bot disabled")
    if not tasks:
        raise RuntimeError("No bot tokens configured")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
