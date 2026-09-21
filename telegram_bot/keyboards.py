from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎫 Подать заявку", callback_data="apply")],[InlineKeyboardButton(text="📋 Моя заявка", callback_data="my_application")]])


def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Отправить", callback_data="apply_confirm"),InlineKeyboardButton(text="✏️ Заново", callback_data="apply_restart")],[InlineKeyboardButton(text="❌ Отмена", callback_data="apply_cancel")]])


def admin_keyboard(app_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"app_approve:{app_id}"),InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_reject:{app_id}")]])
