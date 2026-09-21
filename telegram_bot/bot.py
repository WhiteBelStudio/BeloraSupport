from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from .handlers import router


logger = logging.getLogger("BeloraSupport.Telegram")


async def _cleanup_webhook(bot: Bot) -> None:
    """
    Webhook cleanup must never block the bot from entering polling.
    Some Pterodactyl hosts have unstable access to api.telegram.org.
    """
    timeout = float(os.getenv("TELEGRAM_WEBHOOK_TIMEOUT", "15"))

    try:
        await bot.delete_webhook(
            drop_pending_updates=True,
            request_timeout=timeout,
        )
        logger.info("✅ Telegram webhook removed")

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        # Polling is still allowed to start. If Telegram is reachable,
        # getUpdates will establish the connection itself.
        logger.warning(
            "⚠️ Не удалось удалить Telegram webhook за %.0f сек.: %s",
            timeout,
            exc,
        )
        logger.warning(
            "➡️ Продолжаем запуск Telegram polling без ожидания webhook."
        )


async def run_telegram_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    # A long timeout is useful for long polling, but startup requests must
    # not be allowed to block the whole application indefinitely.
    session = AiohttpSession(
        timeout=120,
    )

    bot = Bot(
        token=token,
        session=session,
    )

    dp = Dispatcher()
    dp.include_router(router)

    try:
        logger.info("🤖 Telegram bot starting...")

        # Do not let webhook cleanup prevent polling from starting.
        await _cleanup_webhook(bot)

        logger.info("📡 Telegram polling starting...")
        await dp.start_polling(
            bot,
            close_bot_session=False,
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
