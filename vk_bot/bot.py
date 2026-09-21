from __future__ import annotations
import logging, os
logger=logging.getLogger("BeloraSupport.VK")

async def run_vk_bot() -> None:
    token=os.getenv("VK_TOKEN")
    if not token: return
    from vkbottle import Bot
    bot=Bot(token=token)
    @bot.on.message()
    async def handle(message):
        await message.answer("👋 Привет! BeloraSupport VK подключён. Подача заявки будет синхронизирована с общей системой.")
    logger.info("VK bot started")
    await bot.run_polling()
