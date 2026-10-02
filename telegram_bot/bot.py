from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from .handlers import router
from .chat import router as chat_router
from .tickets import router as tickets_router

logger = logging.getLogger("BeloraSupport.Telegram")


async def _cleanup_webhook(bot: Bot) -> None:
    timeout = float(os.getenv("TELEGRAM_WEBHOOK_TIMEOUT", "10"))
    try:
        await asyncio.wait_for(
            bot.delete_webhook(drop_pending_updates=True),
            timeout=timeout,
        )
        logger.info("✅ Telegram webhook removed")
    except asyncio.TimeoutError:
        logger.warning("⚠️ Telegram webhook cleanup timed out; starting polling anyway.")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("⚠️ Telegram webhook cleanup failed: %s; starting polling anyway.", exc)


async def _create_telegram_bot(token: str, proxy: str | None) -> Bot:
    """Create a Telegram client and verify connectivity before polling."""
    bot = Bot(
        token=token,
        session=AiohttpSession(timeout=30, proxy=proxy),
    )
    try:
        await asyncio.wait_for(bot.get_me(), timeout=12)
        return bot
    except asyncio.CancelledError:
        await bot.session.close()
        raise
    except Exception:
        try:
            await bot.session.close()
        except Exception:
            logger.exception("⚠️ Failed to close Telegram session after connectivity check")
        raise


async def _build_telegram_bot(token: str) -> Bot:
    """Prefer the configured proxy, but automatically fall back to direct HTTPS."""
    proxy = os.getenv("TELEGRAM_PROXY", "").strip() or None
    fallback_direct = os.getenv("TELEGRAM_PROXY_FALLBACK_DIRECT", "1").strip().lower() not in {
        "0", "false", "no", "off"
    }

    if proxy:
        logger.info("🌐 Telegram proxy configured; checking connectivity...")
        try:
            bot = await _create_telegram_bot(token, proxy)
        except Exception as exc:
            if not fallback_direct:
                raise
            logger.warning(
                "⚠️ Telegram proxy is unreachable (%s). Falling back to direct HTTPS.",
                exc or "connection error",
            )
        else:
            logger.info("✅ Telegram proxy connectivity check passed")
            return bot

    logger.info("🌐 Telegram direct HTTPS mode enabled")
    bot = await _create_telegram_bot(token, None)
    logger.info("✅ Telegram API connectivity check passed")
    return bot


async def run_telegram_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    bot = await _build_telegram_bot(token)
    dp = Dispatcher()

    # The active-chat router contains a catch-all message handler.
    # It must be registered last, otherwise it consumes every message
    # before application/ticket/FSM handlers can process it.
    dp.include_router(tickets_router)
    dp.include_router(router)
    dp.include_router(chat_router)

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
