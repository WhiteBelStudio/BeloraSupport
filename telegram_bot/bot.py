from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from .handlers import router


logger = logging.getLogger("BeloraSupport.Telegram")


async def _cleanup_webhook(bot: Bot) -> None:
    # Do not let a broken connection to api.telegram.org prevent polling.
    timeout = float(os.getenv("TELEGRAM_WEBHOOK_TIMEOUT", "10"))

    try:
        await asyncio.wait_for(
            bot.delete_webhook(drop_pending_updates=True),
            timeout=timeout,
        )
        logger.info("✅ Telegram webhook removed")
    except asyncio.TimeoutError:
        logger.warning(
            "⚠️ Telegram webhook cleanup timed out after %.0f sec.; "
            "starting polling anyway.",
            timeout,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(
            "⚠️ Telegram webhook cleanup failed: %s; starting polling anyway.",
            exc,
        )


async def run_telegram_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    proxy = os.getenv("TELEGRAM_PROXY", "").strip() or None
    if proxy:
        logger.info("🌐 Telegram proxy enabled")

    session = AiohttpSession(timeout=30, proxy=proxy)
    bot = Bot(token=token, session=session)

    dp = Dispatcher()
    dp.include_router(router)

    try:
        logger.info("🤖 Telegram bot starting...")
        await _cleanup_webhook(bot)

        logger.info("📡 Telegram polling starting...")
        await dp.start_polling(
            bot,
            close_bot_session=False,
            polling_timeout=20,
        )

    except asyncio.CancelledError:
        logger.info("🛑 Telegram bot stopping...")
        raise
    except Exception:
        logger.exception("❌ Telegram polling stopped with an error")
        raise
    finally:
        try:
            await bot.session.close()
        except Exception:
            logger.exception("⚠️ Failed to close Telegram HTTP session")
        else:
            logger.info("✅ Telegram HTTP session closed")
