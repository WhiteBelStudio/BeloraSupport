from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

from config import setup_logging
from database import init_db
from telegram_bot.bot import run_telegram_bot

load_dotenv()
setup_logging()
logger = logging.getLogger("BeloraSupport")


async def main() -> None:
    logger.info("BeloraSupport v1.0.0 starting...")
    await init_db()
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
