from __future__ import annotations

import logging
import os

logger = logging.getLogger("BeloraSupport.VK")


def _main_keyboard():
    from vkbottle import Keyboard, Text

    keyboard = Keyboard(one_time=False)
    keyboard.add(Text("🎫 Подать заявку"))
    keyboard.row()
    keyboard.add(Text("📋 Моя заявка"))
    return keyboard.get_json()


async def _prepare_vk_group(bot) -> int | None:
    """Verify VK community identity and Long Poll message events."""
    try:
        groups = await bot.api.request("groups.getById", {"fields": "name,screen_name"})
        logger.info("🔎 Raw VK getById response: %r", groups)
        response = groups.get("response", groups)
        if isinstance(response, dict):
            items = response.get("groups") or response.get("items") or []
            group = items[0] if items else response
        elif isinstance(response, list):
            group = response[0] if response else {}
        else:
            group = {}

        group_id = int(group["id"])
        group_name = group.get("name", "VK community")

        logger.info("🔎 VK community detected: %s (id=%s)", group_name, group_id)

        await bot.api.request(
            "groups.setSettings",
            {
                "group_id": group_id,
                "messages": 1,
                "bots_capabilities": 1,
                "bots_start_button": 1,
                "bots_add_to_chat": 1,
            },
        )

        await bot.api.request(
            "groups.setLongPollSettings",
            {
                "group_id": group_id,
                "enabled": 1,
                "api_version": "5.199",
                "message_new": 1,
                "message_reply": 0,
                "message_edit": 0,
                "message_allow": 1,
                "message_deny": 1,
            },
        )

        settings = await bot.api.request(
            "groups.getLongPollSettings",
            {"group_id": group_id},
        )
        logger.info("✅ VK Long Poll settings: %s", settings.get("response", settings))

        try:
            bot_settings = await bot.api.request(
                "groups.getSettings",
                {"group_id": group_id},
            )
            logger.info("🔧 VK bot settings after setup: %s", bot_settings.get("response", bot_settings))
        except Exception as exc:
            # groups.getSettings is not available with group authorization (VK error 27).
            # This diagnostic call must not mark the whole VK setup as failed.
            logger.warning("⚠️ VK settings verification unavailable: %s", exc)
        return group_id
    except Exception:
        logger.exception("❌ VK API setup failed; polling will still start")
        return None


async def run_vk_bot() -> None:
    token = os.getenv("VK_TOKEN")
    if not token:
        logger.warning("VK_TOKEN is not configured; VK bot disabled")
        return

    from vkbottle import Bot
    from vkbottle.bot import Message

    bot = Bot(token=token)

    await _prepare_vk_group(bot)

    keyboard = _main_keyboard()

    async def _answer(message: Message, text: str) -> None:
        try:
            await message.answer(text, keyboard=keyboard)
        except Exception as exc:
            # VK error 912 means community bot capabilities are disabled.
            # Keep the bot functional with plain text instead of failing.
            if "912" not in str(exc) and "chat bot feature" not in str(exc).lower():
                raise
            logger.warning("⚠️ VK keyboard unavailable (API 912); using text fallback")
            await message.answer(text)

    @bot.on.message()
    async def handle(message: Message):
        logger.info(
            "📩 VK message received: peer_id=%s from_id=%s text=%r",
            getattr(message, "peer_id", None),
            getattr(message, "from_id", None),
            getattr(message, "text", None),
        )

        text = (message.text or "").strip().lower()

        if text in {"/start", "начать", "старт", "🎫 подать заявку"}:
            await _answer(
                message,
                "👋 Добро пожаловать в фан-клуб!\n\n"
                "Здесь можно подать заявку на вступление.\n\n"
                "Нажми кнопку «🎫 Подать заявку», чтобы начать.",
            )
            return

        if text == "📋 моя заявка":
            await _answer(message, "ℹ️ Сейчас активной заявки нет.")
            return

        await _answer(
            message,
            "👋 Привет! Я бот BeloraSupport.\n\n"
            "Выбери действие:",
        )


    logger.info("VK bot started; message handler registered")
    await bot.run_polling()
