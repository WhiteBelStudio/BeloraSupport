from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def ticket_keyboard(ticket_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Мой тикет", callback_data=f"ticket_my:{ticket_id}")]])

def ticket_admin_keyboard(ticket_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📖 Открыть тикет", callback_data=f"ticket_open:{ticket_id}")],[InlineKeyboardButton(text="💬 Ответить", callback_data=f"ticket_reply:{ticket_id}"),InlineKeyboardButton(text="🔴 Закрыть", callback_data=f"ticket_close:{ticket_id}")]])
