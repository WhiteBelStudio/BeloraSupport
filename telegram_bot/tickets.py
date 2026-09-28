from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import effective_admin_ids, is_admin
from database import add_ticket_message, assign_ticket, close_ticket, create_ticket, get_open_ticket_by_user, get_ticket, list_ticket_messages, list_tickets
from .keyboards import ticket_admin_keyboard, ticket_keyboard

logger = logging.getLogger("BeloraSupport.Tickets")
router = Router()

class TicketForm(StatesGroup):
    subject = State()
    message = State()

@router.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    existing = await get_open_ticket_by_user("telegram", callback.from_user.id)
    if existing:
        return await callback.message.answer(f"🎫 У тебя уже открыт тикет <b>#{existing['id']}</b>.\n\nТема: {existing['subject']}", parse_mode="HTML", reply_markup=ticket_keyboard(existing["id"]))
    await state.clear(); await state.set_state(TicketForm.subject)
    await callback.message.answer("🎫 <b>Создание тикета</b>\n\nНапиши тему обращения одним сообщением.", parse_mode="HTML")

@router.message(TicketForm.subject)
async def ticket_subject(message: Message, state: FSMContext):
    text=(message.text or "").strip()
    if not 3 <= len(text) <= 120: return await message.answer("Тема должна быть от 3 до 120 символов.")
    await state.update_data(subject=text); await state.set_state(TicketForm.message)
    await message.answer("📝 Теперь подробно опиши вопрос или уточнение.")

@router.message(TicketForm.message)
async def ticket_message(message: Message, state: FSMContext):
    text=(message.text or "").strip()
    if not 3 <= len(text) <= 3000: return await message.answer("Сообщение должно быть от 3 до 3000 символов.")
    data=await state.get_data(); user=message.from_user
    ticket_id=await create_ticket("telegram",user.id,user.username,data["subject"])
    await add_ticket_message(ticket_id,"telegram","user",user.id,text)
    await state.clear()
    await message.answer(f"✅ Тикет <b>#{ticket_id}</b> создан.\n\nАдминистратор ответит сюда, когда рассмотрит обращение.",parse_mode="HTML",reply_markup=ticket_keyboard(ticket_id))
    notification=f"🎫 <b>Новый тикет #{ticket_id}</b>\n\n👤 Пользователь: {user.full_name}\n🆔 <code>{user.id}</code>\n📌 Тема: {data['subject']}\n\n{text}"
    for admin_id in effective_admin_ids("telegram"):
        try: await message.bot.send_message(admin_id,notification,parse_mode="HTML",reply_markup=ticket_admin_keyboard(ticket_id))
        except Exception: logger.exception("Failed to notify admin %s about ticket #%s",admin_id,ticket_id)

@router.callback_query(F.data.startswith("ticket_reply:"))
async def ticket_reply_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin("telegram",callback.from_user.id): return await callback.answer("Нет доступа.",show_alert=True)
    ticket_id=int(callback.data.split(":",1)[1]); ticket=await get_ticket(ticket_id)
    if not ticket or ticket["status"] != "open": return await callback.answer("Тикет закрыт или не найден.",show_alert=True)
    await assign_ticket(ticket_id,callback.from_user.id); await state.clear(); await state.update_data(ticket_id=ticket_id); await state.set_state(TicketForm.message)
    await callback.answer(); await callback.message.answer(f"💬 Ответ на тикет <b>#{ticket_id}</b>.\n\nНапиши сообщение.",parse_mode="HTML")

@router.callback_query(F.data.startswith("ticket_close:"))
async def ticket_close_handler(callback: CallbackQuery):
    if not is_admin("telegram",callback.from_user.id): return await callback.answer("Нет доступа.",show_alert=True)
    ticket_id=int(callback.data.split(":",1)[1]); ticket=await get_ticket(ticket_id)
    if not ticket: return await callback.answer("Тикет не найден.",show_alert=True)
    changed=await close_ticket(ticket_id)
    if changed:
        try: await callback.bot.send_message(int(ticket["user_id"]),f"🔴 Тикет <b>#{ticket_id}</b> закрыт администратором.\n\nЕсли появится новый вопрос — создай новый тикет.",parse_mode="HTML")
        except Exception: logger.exception("Failed to notify ticket user")
    await callback.answer("Тикет закрыт" if changed else "Тикет уже закрыт")

@router.callback_query(F.data.startswith("ticket_open:"))
async def ticket_open_handler(callback: CallbackQuery):
    if not is_admin("telegram",callback.from_user.id): return await callback.answer("Нет доступа.",show_alert=True)
    ticket_id=int(callback.data.split(":",1)[1]); ticket=await get_ticket(ticket_id)
    if not ticket: return await callback.answer("Тикет не найден.",show_alert=True)
    messages=await list_ticket_messages(ticket_id)
    lines=[f"🎫 <b>Тикет #{ticket_id}</b>",f"📌 {ticket['subject']}",f"👤 ID: <code>{ticket['user_id']}</code>",""]
    for row in messages: lines.append(("👤" if row["sender_type"]=="user" else "🛠")+f" <b>{row['sender_type']}</b>: {row['text']}")
    await callback.answer(); await callback.message.answer("\n".join(lines),parse_mode="HTML",reply_markup=ticket_admin_keyboard(ticket_id))

@router.message(TicketForm.message)
async def ticket_message_state(message: Message, state: FSMContext):
    if not is_admin("telegram",message.from_user.id): return
    data=await state.get_data(); ticket_id=data.get("ticket_id")
    if not ticket_id: return
    ticket=await get_ticket(int(ticket_id))
    if not ticket or ticket["status"] != "open": await state.clear(); return await message.answer("Тикет закрыт.")
    text=(message.text or "").strip()
    if not text: return await message.answer("Напиши текст ответа.")
    await assign_ticket(int(ticket_id),message.from_user.id); await add_ticket_message(int(ticket_id),"telegram","admin",message.from_user.id,text)
    try: await message.bot.send_message(int(ticket["user_id"]),f"💬 <b>Ответ по тикету #{ticket_id}</b>\n\n{text}",parse_mode="HTML",reply_markup=ticket_keyboard(int(ticket_id)))
    except Exception: logger.exception("Failed to send ticket reply"); return await message.answer("❌ Не удалось отправить ответ пользователю.")
    await state.clear(); await message.answer("📨 Ответ отправлен.")

@router.message(F.text == "/tickets")
async def tickets_command(message: Message):
    if not is_admin("telegram",message.from_user.id): return
    tickets=await list_tickets("open",20)
    if not tickets: return await message.answer("🎫 Открытых тикетов нет.")
    await message.answer("🎫 <b>Открытые тикеты</b>\n\n"+"\n".join(f"#{t['id']} — {t['subject']} — ID {t['user_id']}" for t in tickets),parse_mode="HTML")
