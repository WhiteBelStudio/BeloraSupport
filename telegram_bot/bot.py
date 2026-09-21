from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from .handlers import router


logger = logging.getLogger("BeloraSupport.Telegram")


async def _delete_webhook_with_retry(bot: Bot) -> None:
    """
    Telegram API can be temporarily unreachable from a Pterodactyl node.
    Retry the initial webhook cleanup instead of immediately killing the
    whole application.
    """
    attempts = int(os.getenv("TELEGRAM_CONNECT_RETRIES", "5"))
    delay = float(os.getenv("TELEGRAM_RETRY_DELAY", "5"))

    for attempt in range(1, attempts + 1):
        try:
            await bot.delete_webhook(
                drop_pending_updates=True,
                request_timeout=120,
            )
            logger.info("✅ Telegram webhook removed")
            return

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            if attempt >= attempts:
                logger.error(
                    "❌ Telegram API недоступен после %s попыток: %s",
                    attempts,
                    exc,
                )
                raise

            logger.warning(
                "⚠️ Telegram API недоступен "
                "(попытка %s/%s): %s. Повтор через %.1f сек.",
                attempt,
                attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)


async def run_telegram_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    # 120 seconds gives the Pterodactyl host more time to establish
    # an HTTPS connection to api.telegram.org.
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

        await _delete_webhook_with_retry(bot)

        logger.info("✅ Telegram polling started")
        await dp.start_polling(
            bot,
            close_bot_session=False,
        )

    except asyncio.CancelledError:
        logger.info("🛑 Telegram bot stopping...")
        raise

    finally:
        # Explicitly close the aiohttp session so Pterodactyl does not
        # report "Unclosed client session" during shutdown.
        await bot.session.close()
        logger.info("✅ Telegram HTTP session closed")
