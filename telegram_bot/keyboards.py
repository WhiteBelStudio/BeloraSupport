from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎫 Подать заявку", callback_data="apply")],
            [InlineKeyboardButton(text="📋 Моя заявка", callback_data="my_application")],
        ]
    )


def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="apply_confirm"),
                InlineKeyboardButton(text="✏️ Заново", callback_data="apply_restart"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="apply_cancel")],
        ]
    )


def admin_keyboard(app_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"app_approve:{app_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_reject:{app_id}"),
            ]
        ]
    )


def admin_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📥 Новые заявки", callback_data="panel_pending:0"),
                InlineKeyboardButton(text="📋 Все заявки", callback_data="panel_all:0"),
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="panel_stats"),
                InlineKeyboardButton(text="👥 Администраторы", callback_data="panel_admins"),
            ],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="panel_home")],
        ]
    )


def admin_management_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить Telegram", callback_data="admin_add:telegram")],
            [InlineKeyboardButton(text="➕ Добавить VK", callback_data="admin_add:vk")],
            [InlineKeyboardButton(text="🗑 Удалить Telegram", callback_data="admin_del:telegram")],
            [InlineKeyboardButton(text="🗑 Удалить VK", callback_data="admin_del:vk")],
            [InlineKeyboardButton(text="🔄 Обновить список", callback_data="panel_admins")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="panel_home")],
        ]
    )


def admin_list_keyboard(apps, page: int, total: int, prefix: str):
    rows = [
        [
            InlineKeyboardButton(
                text=f"#{row['id']} • {row['name']} • {row['status']}",
                callback_data=f"panel_app:{row['id']}",
            )
        ]
        for row in apps
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:{page - 1}"))
    if (page + 1) * 10 < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Панель", callback_data="panel_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def application_admin_keyboard(app_id: int, status: str = "pending"):
    rows = []
    if status == "pending":
        rows.append(
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"app_approve:{app_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_reject:{app_id}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ К списку", callback_data="panel_pending:0"),
            InlineKeyboardButton(text="🏠 Панель", callback_data="panel_home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
