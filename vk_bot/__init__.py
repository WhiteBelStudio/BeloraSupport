from __future__ import annotations

import json
import logging
import secrets

from config import is_admin
from database import close_conversation, get_active_conversation_by_admin, get_active_conversation_by_user, get_application, start_conversation

logger = logging.getLogger("BeloraSupport.VKChat")

try:
    from vkbottle import Bot as _VKBot
except Exception:
    _VKBot = None


def _keyboard(app_id: int, active: bool = False) -> str:
    buttons = [[{"action": {"type": "text", "label": f"🔴 Завершить переписку #{app_id}"}, "color": "negative"}], [{"action": {"type": "text", "label": f"📋 Заявка #{app_id}"}, "color": "secondary"}]] if active else [[{"action": {"type": "text", "label": f"💬 Написать пользователю #{app_id}"}, "color": "primary"}], [{"action": {"type": "text", "label": "🏠 Панель"}, "color": "secondary"}]]
    return json.dumps({"one_time": False, "inline": False, "buttons": buttons}, ensure_ascii=False)


async def _send(bot, peer_id: int, text: str, keyboard: str | None = None) -> bool:
    try:
        params = {"peer_id": int(peer_id), "random_id": secrets.randbelow(2_000_000_000), "message": text}
        if keyboard:
            params["keyboard"] = keyboard
        await bot.api.request("messages.send", params)
        return True
    except Exception:
        logger.exception("Failed to send VK chat message to peer_id=%s", peer_id)
        return False


async def _chat_handler(message):
    user_id = int(getattr(message, "from_id", 0) or 0)
    text = (message.text or "").strip()
    if not user_id:
        return

    if is_admin("vk", user_id) and text.startswith("#") and " • " in text:
        try:
            app_id = int(text[1:].split(" ", 1)[0])
            app = await get_application(app_id)
            if app and app["platform"] == "vk":
                await _send(message.ctx_api, user_id, f"🎫 Заявка #{app_id}\n\n👤 Имя: {app['name']}\n🎂 Возраст: {app['age']}\n📍 Город: {app['city']}\n💬 Почему: {app['reason']}\n⭐ Интересы: {app['interests']}\n\nСтатус: {app['status']}\nVK ID: {app['user_id']}", _keyboard(app_id))
                return True
        except (ValueError, TypeError):
            pass

    if is_admin("vk", user_id) and text.startswith("💬 Написать пользователю #"):
        try:
            app_id = int(text.rsplit("#", 1)[1])
            app = await get_application(app_id)
            if not app or app["platform"] != "vk":
                await _send(message.ctx_api, user_id, "❌ VK-заявка не найдена.")
                return True
            target_id = int(app["user_id"])
            await start_conversation("vk", app_id, user_id, target_id)
            if not await _send(message.ctx_api, target_id, f"💬 Администратор начал переписку по заявке #{app_id}.\n\nОтправь сообщение сюда — оно будет передано администратору."):
                await close_conversation("vk", app_id)
                await _send(message.ctx_api, user_id, "❌ Не удалось связаться с пользователем.")
                return True
            await _send(message.ctx_api, user_id, f"💬 Переписка по заявке #{app_id} начата.\n\nПиши сообщение обычным текстом — бот передаст его пользователю.", _keyboard(app_id, True))
            return True
        except ValueError:
            return True

    if is_admin("vk", user_id) and text.startswith("🔴 Завершить переписку #"):
        try:
            app_id = int(text.rsplit("#", 1)[1])
            app = await get_application(app_id)
            await close_conversation("vk", app_id)
            if app and app["platform"] == "vk":
                await _send(message.ctx_api, int(app["user_id"]), f"🔴 Переписка по заявке #{app_id} завершена администратором.")
            await _send(message.ctx_api, user_id, f"✅ Переписка по заявке #{app_id} завершена.", _keyboard(app_id, False))
            return True
        except ValueError:
            return True

    if text.startswith("/"):
        return False

    conversation = await get_active_conversation_by_admin("vk", user_id) if is_admin("vk", user_id) else None
    if conversation:
        if await _send(message.ctx_api, int(conversation["user_id"]), message.text or ""):
            await _send(message.ctx_api, user_id, "📨 Доставлено пользователю.")
        else:
            await _send(message.ctx_api, user_id, "❌ Не удалось доставить сообщение пользователю.")
        return True

    conversation = await get_active_conversation_by_user("vk", user_id)
    if conversation:
        payload = f"📩 Ответ пользователя по заявке #{conversation['application_id']}:\n\n{message.text or ''}"
        if await _send(message.ctx_api, int(conversation["admin_id"]), payload):
            await _send(message.ctx_api, user_id, "📨 Сообщение передано администратору.")
        else:
            await _send(message.ctx_api, user_id, "❌ Не удалось передать сообщение администратору.")
        return True

    return False


if _VKBot is not None:
    _original_init = _VKBot.__init__

    def _patched_init(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        self.on.message()(_chat_handler)

    _VKBot.__init__ = _patched_init
