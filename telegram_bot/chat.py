from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import is_admin
from database import close_conversation, get_active_conversation_by_admin, get_active_conversation_by_user, get_application, start_conversation
from .keyboards import application_admin_keyboard, chat_keyboard

logger = logging.getLogger("BeloraSupport.TelegramChat")
router = Router()


@router.callback_query(F.data.startswith("app_chat:"))
async def start_application_chat(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    app_id = int(callback.data.split(":", 1)[1])
    app = await get_application(app_id)
    if not app or app["platform"] != "telegram":
        return await callback.answer("Telegram-пользователь не найден.", show_alert=True)
    user_id = int(app["user_id"])
    await start_conversation("telegram", app_id, callback.from_user.id, user_id)
    try:
        await callback.bot.send_message(
            user_id,
            f"💬 Администратор начал переписку по заявке #{app_id}.\n\nМожешь отправить сообщение прямо сюда — оно будет передано администратору.",
        )
    except Exception:
        await close_conversation("telegram", app_id)
        logger.exception("Failed to start Telegram application chat #%s", app_id)
        return await callback.answer("Не удалось связаться с пользователем.", show_alert=True)
    await callback.answer("Переписка начата")
    await callback.message.edit_reply_markup(reply_markup=chat_keyboard(app_id))
    await callback.message.answer(f"💬 Переписка с пользователем по заявке #{app_id} активна.\n\nОтправляй сообщения сюда — бот передаст их пользователю.", reply_markup=chat_keyboard(app_id))


@router.callback_query(F.data.startswith("app_chat_close:"))
async def close_application_chat(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    app_id = int(callback.data.split(":", 1)[1])
    app = await get_application(app_id)
    await close_conversation("telegram", app_id)
    if app and app["platform"] == "telegram":
        try:
            await callback.bot.send_message(int(app["user_id"]), f"🔴 Переписка по заявке #{app_id} завершена администратором.")
        except Exception:
            logger.exception("Failed to notify Telegram user about closed chat #%s", app_id)
    await callback.answer("Переписка завершена")
    await callback.message.edit_reply_markup(reply_markup=application_admin_keyboard(app_id, app["status"] if app else "pending"))


@router.message(F.text.startswith("/"))
async def ignore_commands_in_chat(message: Message):
    # Commands are handled by the normal bot handlers, not forwarded to users.
    return None


@router.message()
async def route_active_chat_message(message: Message):
    user = message.from_user
    if not user:
        return

    if is_admin("telegram", user.id):
        conversation = await get_active_conversation_by_admin("telegram", user.id)
        if conversation:
            try:
                await message.bot.copy_message(
                    chat_id=int(conversation["user_id"]),
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
                await message.answer("📨 Доставлено пользователю.")
            except Exception:
                logger.exception("Failed to relay Telegram admin message")
                await message.answer("❌ Не удалось доставить сообщение пользователю.")
            return

    conversation = await get_active_conversation_by_user("telegram", user.id)
    if conversation:
        try:
            await message.bot.copy_message(
                chat_id=int(conversation["admin_id"]),
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            await message.answer("📨 Сообщение передано администратору.")
        except Exception:
            logger.exception("Failed to relay Telegram user message")
        return
