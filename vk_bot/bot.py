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


async def run_vk_bot() -> None:
    token = os.getenv("VK_TOKEN")
    if not token:
        logger.warning("VK_TOKEN is not configured; VK bot disabled")
        return

    from vkbottle import Bot
    from vkbottle.bot import Message

    bot = Bot(token=token)
    keyboard = _main_keyboard()

    @bot.on.message()
    async def handle(message: Message):
        logger.info(
            "VK message received: peer_id=%s from_id=%s text=%r",
            getattr(message, "peer_id", None),
            getattr(message, "from_id", None),
            getattr(message, "text", None),
        )

        text = (message.text or "").strip().lower()

        if text in {"/start", "начать", "старт", "🎫 подать заявку"}:
            await message.answer(
                "👋 Добро пожаловать в фан-клуб!\n\n"
                "Здесь можно подать заявку на вступление.\n\n"
                "Нажми кнопку «🎫 Подать заявку», чтобы начать.",
                keyboard=keyboard,
            )
            return

        if text == "📋 моя заявка":
            await message.answer(
                "ℹ️ Сейчас активной заявки нет.",
                keyboard=keyboard,
            )
            return

        await message.answer(
            "👋 Привет! Я бот BeloraSupport.\n\n"
            "Выбери действие:",
            keyboard=keyboard,
        )

    logger.info("VK bot started; message handler registered")
    await bot.run_polling()
