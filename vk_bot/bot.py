from __future__ import annotations

import logging
import os

logger = logging.getLogger("BeloraSupport.VK")


def _main_keyboard():
    from vkbottle import Keyboard, Text

    return (
        Keyboard(one_time=False)
        .add(Text("🎫 Подать заявку"))
        .row()
        .add(Text("📋 Моя заявка"))
        .get_json()
    )


async def run_vk_bot() -> None:
    token = os.getenv("VK_TOKEN")
    if not token:
        return

    from vkbottle import Bot

    bot = Bot(token=token)
    keyboard = _main_keyboard()

    @bot.on.message()
    async def handle(message):
        text = (message.text or "").strip().lower()

        if text in {"/start", "начать", "старт", "🎫 подать заявку"}:
            await message.answer(
                "👋 Добро пожаловать в фан-клуб!\n\n"
                "Здесь можно подать заявку на вступление.\n"
                "Нажми «🎫 Подать заявку», чтобы начать.",
                keyboard=keyboard,
            )
            return

        if text == "📋 моя заявка":
            await message.answer(
                "ℹ️ Проверка заявки доступна после её отправки.",
                keyboard=keyboard,
            )
            return

        # Show the menu for any ordinary incoming message so a new user
        # always receives the VK controls.
        await message.answer(
            "👋 Привет! Выбери действие ниже.",
            keyboard=keyboard,
        )

    logger.info("VK bot started")
    await bot.run_polling()
