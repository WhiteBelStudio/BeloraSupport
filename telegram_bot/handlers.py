from __future__ import annotations

import logging
import html

logger = logging.getLogger(__name__)

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import admin_ids, effective_admin_ids, is_admin, is_owner, register_admin, unregister_admin
from database import add_admin, application_stats, ban_user, count_applications, create_application, get_application, get_ban, has_pending, is_banned, list_admins, list_applications, list_bans, remove_admin, set_status, unban_user, count_tickets, get_ticket, list_tickets, list_ticket_messages
from .keyboards import admin_keyboard, admin_list_keyboard, admin_panel_keyboard, application_admin_keyboard, confirm_keyboard, main_keyboard
from .ticket_keyboards import ticket_admin_keyboard

router = Router()

class ApplicationForm(StatesGroup):
    name = State()
    age = State()
    city = State()
    reason = State()
    interests = State()
    confirm = State()
    reject_reason = State()


class AdminManageForm(StatesGroup):
    user_id = State()

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    ban = await get_ban("telegram", message.from_user.id)
    if ban:
        return await message.answer("🚫 <b>Доступ ограничен</b>\n\nПричина: " + ban["reason"], parse_mode="HTML")
    await message.answer("👋 Добро пожаловать в фан-клуб!\n\nЗдесь можно подать заявку на вступление.", reply_markup=main_keyboard(is_admin("telegram", message.from_user.id)))

RULES_TEXT = (
    "📋 <b>Правила создания анкеты</b>\n\n"
    "• Указывай достоверную информацию о себе.\n"
    "• Запрещены оскорбления, угрозы, травля и дискриминация.\n"
    "• Запрещён сексуальный и другой неподходящий контент.\n"
    "• Запрещены реклама, спам, мошенничество и обман.\n"
    "• Не публикуй чужие персональные данные без разрешения.\n"
    "• Фотография, имя и описание анкеты не должны нарушать правила платформы.\n"
    "• Администрация может отклонить анкету или ограничить доступ при нарушении правил.\n\n"
    "Нажимая «✅ Принимаю правила», ты подтверждаешь, что ознакомился с правилами."
)

@router.callback_query(F.data.in_({"apply", "rules"}))
async def rules_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ban = await get_ban("telegram", callback.from_user.id)
    if ban:
        return await callback.message.answer("🚫 <b>Доступ ограничен</b>\n\nПричина: " + html.escape(ban["reason"]), parse_mode="HTML")
    await state.clear()
    from .keyboards import rules_keyboard
    await callback.message.answer(RULES_TEXT, parse_mode="HTML", reply_markup=rules_keyboard())

@router.callback_query(F.data == "rules_accept")
async def rules_accept(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    ban = await get_ban("telegram", callback.from_user.id)
    if ban:
        return await callback.message.answer("🚫 <b>Доступ ограничен</b>\n\nПричина: " + ban["reason"], parse_mode="HTML")
    if await has_pending("telegram", str(callback.from_user.id)):
        return await callback.message.answer("⏳ У тебя уже есть заявка на рассмотрении.")
    await state.clear()
    await state.set_state(ApplicationForm.name)
    await callback.message.answer("1/5. Как тебя зовут или как к тебе обращаться?")

@router.message(F.text == "🎫 Подать заявку")
async def menu_apply(message: Message, state: FSMContext):
    ban = await get_ban("telegram", message.from_user.id)
    if ban:
        return await message.answer("🚫 Доступ ограничен.\\n\\nПричина: " + html.escape(ban["reason"]), parse_mode="HTML")
    if await has_pending("telegram", str(message.from_user.id)):
        return await message.answer("⏳ У тебя уже есть заявка на рассмотрении.", reply_markup=main_keyboard(is_admin("telegram", message.from_user.id)))
    await state.clear()
    from .keyboards import rules_keyboard
    await message.answer(RULES_TEXT, parse_mode="HTML", reply_markup=rules_keyboard())


@router.message(F.text == "📋 Правила")
async def menu_rules(message: Message, state: FSMContext):
    await state.clear()
    from .keyboards import rules_keyboard
    await message.answer(RULES_TEXT, parse_mode="HTML", reply_markup=rules_keyboard())


@router.message(F.text == "📋 Моя заявка")
async def menu_my_application(message: Message):
    await message.answer(
        "⏳ Твоя заявка на рассмотрении." if await has_pending("telegram", str(message.from_user.id))
        else "ℹ️ Активной заявки нет.",
        reply_markup=main_keyboard(is_admin("telegram", message.from_user.id)),
    )


@router.message(F.text == "🛠 Админ-панель")
async def menu_admin_panel(message: Message):
    if not is_admin("telegram", message.from_user.id):
        return await message.answer("⛔ Доступ только для администраторов.")
    logger.info("🛠 Telegram admin panel opened: user_id=%s", message.from_user.id)
    await message.answer(
        _panel_text(await application_stats()),
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )


@router.message(ApplicationForm.name)
async def form_name(message: Message, state: FSMContext):
    value=(message.text or "").strip()
    if not 2 <= len(value) <= 80: return await message.answer("Имя/ник: от 2 до 80 символов.")
    await state.update_data(name=value); await state.set_state(ApplicationForm.age)
    await message.answer("2/5. Сколько тебе лет? Введи число.")

@router.message(ApplicationForm.age)
async def form_age(message: Message, state: FSMContext):
    try: age=int((message.text or "").strip())
    except ValueError: return await message.answer("Введи возраст числом.")
    if not 10 <= age <= 100: return await message.answer("Введи корректный возраст.")
    await state.update_data(age=age); await state.set_state(ApplicationForm.city)
    await message.answer("3/5. Из какого ты города?")

@router.message(ApplicationForm.city)
async def form_city(message: Message, state: FSMContext):
    value=(message.text or "").strip()
    if not 2 <= len(value) <= 100: return await message.answer("Напиши город.")
    await state.update_data(city=value); await state.set_state(ApplicationForm.reason)
    await message.answer("4/5. Почему хочешь вступить в фан-клуб?")

@router.message(ApplicationForm.reason)
async def form_reason(message: Message, state: FSMContext):
    value=(message.text or "").strip()
    if not 5 <= len(value) <= 1000: return await message.answer("Ответ должен быть от 5 до 1000 символов.")
    await state.update_data(reason=value); await state.set_state(ApplicationForm.interests)
    await message.answer("5/5. Что тебе интересно в фан-клубе?")

@router.message(ApplicationForm.interests)
async def form_interests(message: Message, state: FSMContext):
    value=(message.text or "").strip()
    if not 2 <= len(value) <= 1000: return await message.answer("Ответ должен быть от 2 до 1000 символов.")
    await state.update_data(interests=value); data=await state.get_data(); await state.set_state(ApplicationForm.confirm)
    preview=(f"📋 <b>Предпросмотр заявки</b>\n\n👤 <b>Имя:</b> {html.escape(data['name'])}\n🎂 <b>Возраст:</b> {data['age']}\n📍 <b>Город:</b> {html.escape(data['city'])}\n💬 <b>Почему:</b> {html.escape(data['reason'])}\n⭐ <b>Интересы:</b> {html.escape(data['interests'])}\n\nВсё верно?")
    await message.answer(preview, reply_markup=confirm_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "apply_confirm", ApplicationForm.confirm)
async def apply_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if await is_banned("telegram", callback.from_user.id):
        await state.clear()
        return await callback.message.answer("🚫 Доступ ограничен.")
    data=await state.get_data(); user=callback.from_user
    app_id=await create_application("telegram",str(user.id),user.username,data["name"],data["age"],data["city"],data["reason"],data["interests"])
    await state.clear()
    await callback.message.answer(f"✅ Заявка <b>#{app_id}</b> отправлена администраторам.",parse_mode="HTML",reply_markup=main_keyboard(is_admin("telegram", callback.from_user.id)))
    username = html.escape(user.username) if user.username else "нет"
    text=(f"🎫 <b>Новая заявка #{app_id}</b>\n\n👤 {html.escape(data['name'])}\n🎂 {data['age']}\n📍 {html.escape(data['city'])}\n💬 {html.escape(data['reason'])}\n⭐ {html.escape(data['interests'])}\n\nTelegram ID: <code>{user.id}</code>\nUsername: @{username}")
    recipient_ids = effective_admin_ids("telegram")
    delivered = 0
    for admin_id in recipient_ids:
        try:
            await callback.bot.send_message(admin_id,text,parse_mode="HTML",reply_markup=admin_keyboard(app_id))
            delivered += 1
        except Exception:
            logger.exception("Failed to notify Telegram admin %s about application #%s", admin_id, app_id)
    if delivered == 0:
        logger.error("No Telegram admin notifications delivered for application #%s; recipients=%s", app_id, sorted(recipient_ids))
    else:
        logger.info("Telegram application #%s notification delivered to %s/%s admins", app_id, delivered, len(recipient_ids))

@router.callback_query(F.data == "apply_restart")
async def restart(callback: CallbackQuery,state:FSMContext):
    await callback.answer(); await state.clear(); await state.set_state(ApplicationForm.name); await callback.message.answer("Начинаем заново. 1/5. Как тебя зовут или как к тебе обращаться?")

@router.callback_query(F.data == "apply_cancel")
async def cancel(callback: CallbackQuery,state:FSMContext):
    await callback.answer(); await state.clear(); await callback.message.answer("Заявка отменена.",reply_markup=main_keyboard())

@router.callback_query(F.data == "my_application")
async def my_application(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("⏳ Твоя заявка на рассмотрении." if await has_pending("telegram",str(callback.from_user.id)) else "ℹ️ Активной заявки нет.",reply_markup=main_keyboard())

@router.callback_query(F.data.startswith("app_approve:"))
async def approve(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id): return await callback.answer("Нет доступа.",show_alert=True)
    try:
        app_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        return await callback.answer("Некорректный ID заявки.", show_alert=True)
    if app_id <= 0:
        return await callback.answer("Некорректный ID заявки.", show_alert=True)
    app = await get_application(app_id)
    if not app:
        return await callback.answer("Заявка не найдена.", show_alert=True)
    if app["status"] != "pending":
        return await callback.answer(f"Заявка уже обработана: {app['status']}.", show_alert=True)
    if not await set_status(app_id, "approved"):
        return await callback.answer("Заявка уже обработана.", show_alert=True)
    notification_failed = False
    if app["platform"] == "telegram":
        try:
            await callback.bot.send_message(
                int(app["user_id"]),
                f"🎉 Твоя заявка #{app_id} одобрена! Добро пожаловать в фан-клуб.",
            )
        except Exception:
            notification_failed = True
    await callback.message.edit_reply_markup(reply_markup=None)
    suffix = "\n⚠️ Уведомление пользователю не доставлено." if notification_failed else ""
    await callback.message.answer(f"✅ Заявка #{app_id} одобрена.{suffix}")

@router.callback_query(F.data.startswith("app_reject:"))
async def reject(callback: CallbackQuery,state:FSMContext):
    if not is_admin("telegram", callback.from_user.id): return await callback.answer("Нет доступа.",show_alert=True)
    try:
        app_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        return await callback.answer("Некорректный ID заявки.", show_alert=True)
    if app_id <= 0:
        return await callback.answer("Некорректный ID заявки.", show_alert=True)
    app = await get_application(app_id)
    if not app:
        return await callback.answer("Заявка не найдена.", show_alert=True)
    if app["status"] != "pending":
        return await callback.answer(f"Заявка уже обработана: {app['status']}.", show_alert=True)
    await state.update_data(reject_app_id=app_id)
    await state.set_state(ApplicationForm.reject_reason)
    await callback.answer()
    await callback.message.answer("📝 Напиши причину отклонения. От 2 до 500 символов.")

@router.message(ApplicationForm.reject_reason)
async def reject_reason(message: Message,state:FSMContext):
    if not is_admin("telegram", message.from_user.id): return await state.clear()
    reason=(message.text or "").strip()
    if not 2 <= len(reason) <= 500: return await message.answer("Причина: от 2 до 500 символов.")
    data = await state.get_data()
    try:
        app_id = int(data["reject_app_id"])
    except (KeyError, TypeError, ValueError):
        await state.clear()
        return await message.answer("❌ Сессия отклонения заявки недействительна. Открой заявку заново.")
    if app_id <= 0:
        await state.clear()
        return await message.answer("❌ Некорректный ID заявки.")
    app = await get_application(app_id)
    if not app:
        await state.clear()
        return await message.answer("❌ Заявка не найдена.")
    if app["status"] != "pending":
        await state.clear()
        return await message.answer(f"ℹ️ Заявка уже обработана: {app['status']}.")
    if not await set_status(app_id, "rejected", reason):
        await state.clear()
        return await message.answer("ℹ️ Заявка уже обработана или не найдена.")
    notification_failed = False
    if app["platform"] == "telegram":
        try:
            await message.bot.send_message(
                int(app["user_id"]),
                f"❌ Заявка #{app_id} отклонена.\nПричина: {reason}",
            )
        except Exception:
            notification_failed = True
    await state.clear()
    suffix = "\n⚠️ Уведомление пользователю не доставлено." if notification_failed else ""
    await message.answer(f"❌ Заявка #{app_id} отклонена.{suffix}")


@router.message(F.text.startswith("/addadmin"))
async def add_admin_command(message: Message):
    if not is_owner("telegram", message.from_user.id):
        return await message.answer("⛔ Только владелец может управлять администраторами.")
    parts=(message.text or "").split()
    if len(parts)!=3 or parts[1].lower() not in {"tg","telegram","vk"} or not parts[2].isdigit():
        return await message.answer("Использование: /addadmin tg ID или /addadmin vk ID")
    platform="telegram" if parts[1].lower() in {"tg","telegram"} else "vk"
    user_id=int(parts[2])
    if user_id in __import__("config").owner_ids(platform):
        return await message.answer("👑 Этот ID уже является владельцем и имеет полный доступ.")
    added = await add_admin(platform, user_id, message.from_user.id)
    register_admin(platform, user_id)
    if added:
        await message.answer(f"✅ Администратор добавлен.\nПлатформа: {platform}\nID: <code>{user_id}</code>", parse_mode="HTML")
    else:
        await message.answer(f"ℹ️ Этот ID уже был администратором.\nКэш прав обновлён.\nПлатформа: {platform}\nID: <code>{user_id}</code>", parse_mode="HTML")


@router.message(F.text.startswith("/deladmin"))
async def del_admin_command(message: Message):
    if not is_owner("telegram", message.from_user.id):
        return await message.answer("⛔ Только владелец может управлять администраторами.")
    parts=(message.text or "").split()
    if len(parts)!=3 or parts[1].lower() not in {"tg","telegram","vk"} or not parts[2].isdigit():
        return await message.answer("Использование: /deladmin tg ID или /deladmin vk ID")
    platform="telegram" if parts[1].lower() in {"tg","telegram"} else "vk"
    user_id=int(parts[2])
    if user_id in __import__("config").owner_ids(platform):
        return await message.answer("⛔ Владельца удалить нельзя.")
    removed = await remove_admin(platform,user_id)
    if removed:
        unregister_admin(platform, user_id)
    await message.answer("✅ Администратор удалён." if removed else "ℹ️ Такой администратор не найден.")


@router.message(F.text == "/admins")
async def admins_command(message: Message):
    if not is_owner("telegram", message.from_user.id):
        return await message.answer("⛔ Только владелец может смотреть список администраторов.")
    tg=await list_admins("telegram")
    vk=await list_admins("vk")
    lines=["👑 <b>Администраторы BeloraSupport</b>","",f"Telegram: {', '.join(r['user_id'] for r in tg) or 'нет'}",f"VK: {', '.join(r['user_id'] for r in vk) or 'нет'}"]
    await message.answer("\n".join(lines),parse_mode="HTML")


@router.message(F.text.regexp(r"^/ban(?:\s|$)"))
async def ban_command(message: Message):
    if not is_admin("telegram", message.from_user.id):
        return await message.answer("⛔ Доступ только для администраторов.")
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 4 or parts[1].lower() not in {"tg", "telegram", "vk"} or not parts[2].isdigit():
        return await message.answer("Использование: /ban tg ID причина или /ban vk ID причина")
    platform = "telegram" if parts[1].lower() in {"tg", "telegram"} else "vk"
    user_id = int(parts[2])
    from config import owner_ids
    if user_id in owner_ids(platform):
        return await message.answer("⛔ Владельца заблокировать нельзя.")
    if is_admin(platform, user_id):
        return await message.answer("⛔ Администратора заблокировать нельзя.")
    reason = parts[3].strip()
    if not 2 <= len(reason) <= 500:
        return await message.answer("Причина бана: от 2 до 500 символов.")
    await ban_user(platform, user_id, reason, message.from_user.id)
    if platform == "telegram":
        try:
            await message.bot.send_message(user_id, f"🚫 <b>Доступ ограничен</b>\n\nПричина: {html.escape(reason)}", parse_mode="HTML")
        except Exception:
            logger.exception("Failed to notify Telegram user %s about ban", user_id)
    await message.answer(f"🚫 Пользователь <code>{user_id}</code> заблокирован.\nПлатформа: {platform}\nПричина: {reason}", parse_mode="HTML")

@router.message(F.text.regexp(r"^/unban(?:\s|$)"))
async def unban_command(message: Message):
    if not is_admin("telegram", message.from_user.id):
        return await message.answer("⛔ Доступ только для администраторов.")
    parts = (message.text or "").split()
    if len(parts) != 3 or parts[1].lower() not in {"tg", "telegram", "vk"} or not parts[2].isdigit():
        return await message.answer("Использование: /unban tg ID или /unban vk ID")
    platform = "telegram" if parts[1].lower() in {"tg", "telegram"} else "vk"
    user_id = int(parts[2])
    if await unban_user(platform, user_id):
        if platform == "telegram":
            try:
                await message.bot.send_message(user_id, "✅ <b>Доступ восстановлен</b>\n\nОграничение с твоего аккаунта снято.", parse_mode="HTML")
            except Exception:
                logger.exception("Failed to notify Telegram user %s about unban", user_id)
        await message.answer(f"✅ Пользователь <code>{user_id}</code> разблокирован.", parse_mode="HTML")
    else:
        await message.answer("ℹ️ Такой пользователь не заблокирован.")

@router.message(F.text == "/banned")
async def banned_command(message: Message):
    if not is_admin("telegram", message.from_user.id):
        return await message.answer("⛔ Доступ только для администраторов.")
    rows = await list_bans()
    if not rows:
        return await message.answer("🚫 Заблокированных пользователей нет.")
    lines = ["🚫 <b>Заблокированные пользователи</b>", ""]
    for row in rows[:50]:
        lines.append(f"• <code>{row['user_id']}</code> — {html.escape(row['platform'])} — {html.escape(row['reason'])}")
    await message.answer("\n".join(lines), parse_mode="HTML")

# ===== Telegram admin panel =====

def _panel_text(stats: dict[str, int]) -> str:
    return (
        "🛠 <b>BeloraSupport • Admin Center</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📥 <b>Новые заявки:</b> {stats['pending']}\n"
        f"📊 <b>Всего заявок:</b> {stats['total']}\n"
        f"✅ <b>Одобрено:</b> {stats['approved']}\n"
        f"❌ <b>Отклонено:</b> {stats['rejected']}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>Управление</b>\n"
        "Выбери нужный раздел ниже:"
    )


@router.message(F.text == "/panel")
async def admin_panel_command(message: Message):
    if not is_admin("telegram", message.from_user.id):
        return await message.answer("⛔ Доступ только для администраторов.")
    await message.answer(_panel_text(await application_stats()), parse_mode="HTML", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "panel_home")
async def panel_home(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer()
    await callback.message.edit_text(_panel_text(await application_stats()), parse_mode="HTML", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "panel_stats")
async def panel_stats(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer()
    stats = await application_stats()
    await callback.message.edit_text(
        "📊 <b>Статистика BeloraSupport</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Всего: <b>{stats['total']}</b>\n"
        f"📥 Ожидают: <b>{stats['pending']}</b>\n"
        f"✅ Одобрено: <b>{stats['approved']}</b>\n"
        f"❌ Отклонено: <b>{stats['rejected']}</b>\n\n"
        f"🤖 Telegram: <b>{stats['telegram_total']}</b> "
        f"(📥 {stats['telegram_pending']} / ✅ {stats['telegram_approved']} / ❌ {stats['telegram_rejected']})\n"
        f"🔵 VK: <b>{stats['vk_total']}</b> "
        f"(📥 {stats['vk_pending']} / ✅ {stats['vk_approved']} / ❌ {stats['vk_rejected']})",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data.startswith("panel_pending:"))
async def panel_pending(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer()
    page = max(0, int(callback.data.split(":", 1)[1]))
    total = await count_applications("pending")
    apps = await list_applications("pending", limit=10, offset=page * 10)
    if not apps:
        return await callback.message.edit_text("📥 <b>Ожидающих заявок нет.</b>", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    text = f"📥 <b>Заявки на рассмотрении</b>\nСтраница {page + 1}\n\nВыбери заявку:"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_list_keyboard(apps, page, total, "panel_pending"))


@router.callback_query(F.data.startswith("panel_all:"))
async def panel_all(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer()
    try:
        page = max(0, int(callback.data.split(":", 1)[1]))
    except (TypeError, ValueError):
        page = 0
    total = await count_applications()
    if total <= 0:
        return await callback.message.edit_text("📋 <b>Заявок пока нет.</b>", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    max_page = (total - 1) // 10
    page = min(page, max_page)
    apps = await list_applications(limit=10, offset=page * 10)
    if not apps:
        return await callback.message.edit_text("📋 <b>Заявок на этой странице нет.</b>", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    await callback.message.edit_text(
        f"📋 <b>Все заявки</b>\nВсего: {total}\nСтраница {page + 1} из {max_page + 1}\n\nВыбери заявку:",
        parse_mode="HTML",
        reply_markup=admin_list_keyboard(apps, page, total, "panel_all"),
    )


@router.callback_query(F.data.startswith("panel_app:"))
async def panel_application(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer()
    try:
        app_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        return await callback.message.edit_text("❌ Некорректный ID заявки.", reply_markup=admin_panel_keyboard())
    if app_id <= 0:
        return await callback.message.edit_text("❌ Некорректный ID заявки.", reply_markup=admin_panel_keyboard())
    app = await get_application(app_id)
    if not app:
        return await callback.message.edit_text("❌ Заявка не найдена.", reply_markup=admin_panel_keyboard())
    import html
    username = f"@{html.escape(app['username'])}" if app['username'] else "нет"
    reject_reason = html.escape(app['reject_reason']) if app['reject_reason'] else "—"
    text = (
        f"🎫 <b>Заявка #{app['id']}</b>\n\n"
        f"👤 <b>Имя:</b> {html.escape(app['name'])}\n"
        f"🎂 <b>Возраст:</b> {app['age']}\n"
        f"📍 <b>Город:</b> {html.escape(app['city'])}\n"
        f"💬 <b>Почему:</b> {html.escape(app['reason'])}\n"
        f"⭐ <b>Интересы:</b> {html.escape(app['interests'])}\n\n"
        f"🌐 <b>Платформа:</b> {html.escape(app['platform'])}\n"
        f"🆔 <b>User ID:</b> <code>{app['user_id']}</code>\n"
        f"👤 <b>Username:</b> {username}\n"
        f"📌 <b>Статус:</b> {html.escape(app['status'])}\n"
        f"📝 <b>Причина отказа:</b> {reject_reason}\n"
        f"🕒 <b>Создана:</b> {html.escape(app['created_at'])}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=application_admin_keyboard(app_id, app["status"]))


@router.callback_query(F.data.startswith("tickets:"))
async def panel_tickets(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer()
    page = max(0, int(callback.data.split(":", 1)[1]))
    total = await count_tickets("open")
    tickets = await list_tickets("open", limit=10, offset=page * 10)
    if not tickets:
        return await callback.message.edit_text("🎫 <b>Открытых тикетов нет.</b>", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    lines = ["🎫 <b>Открытые тикеты</b>", f"Страница {page + 1}", "", "Выбери тикет:"]
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton(text=f"#{t['id']} • {t['subject'][:45]}", callback_data=f"ticket_open:{t['id']}")] for t in tickets]
    nav=[]
    if page>0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"tickets:{page-1}"))
    if (page+1)*10<total: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"tickets:{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Панель", callback_data="panel_home")])
    await callback.message.edit_text("\\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "panel_admins")
async def panel_admins(callback: CallbackQuery):
    if not is_admin("telegram", callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer()
    from config import effective_admin_ids, owner_ids
    tg_owner = ", ".join(str(x) for x in sorted(owner_ids("telegram"))) or "не задан"
    vk_owner = ", ".join(str(x) for x in sorted(owner_ids("vk"))) or "не задан"
    tg_access = ", ".join(str(x) for x in sorted(effective_admin_ids("telegram"))) or "нет"
    vk_access = ", ".join(str(x) for x in sorted(effective_admin_ids("vk"))) or "нет"
    text = (
        "👥 <b>Администраторы</b>\n\n"
        f"👑 Telegram-владелец: <code>{tg_owner}</code>\n"
        f"👑 VK-владелец: <code>{vk_owner}</code>\n\n"
        f"📱 Telegram-доступ: <code>{tg_access}</code>\n"
        f"💬 VK-доступ: <code>{vk_access}</code>\n\n"
        "Управление только владельцем:\n"
        "/addadmin tg ID\n/addadmin vk ID\n/deladmin tg ID\n/deladmin vk ID"
    )
    from .keyboards import admin_management_keyboard
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_management_keyboard())


@router.callback_query(F.data.startswith("admin_add:"))
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner("telegram", callback.from_user.id):
        return await callback.answer("Только владелец может управлять администраторами.", show_alert=True)
    platform = callback.data.split(":", 1)[1]
    await state.update_data(admin_action="add", admin_platform=platform)
    await state.set_state(AdminManageForm.user_id)
    await callback.answer()
    label = "Telegram" if platform == "telegram" else "VK"
    await callback.message.edit_text(
        f"➕ <b>Добавление {label}-администратора</b>\n\nОтправь ID пользователя одним сообщением.\n\n⬅️ Для отмены используй /panel.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_del:"))
async def admin_del_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner("telegram", callback.from_user.id):
        return await callback.answer("Только владелец может управлять администраторами.", show_alert=True)
    platform = callback.data.split(":", 1)[1]
    await state.update_data(admin_action="delete", admin_platform=platform)
    await state.set_state(AdminManageForm.user_id)
    await callback.answer()
    label = "Telegram" if platform == "telegram" else "VK"
    await callback.message.edit_text(
        f"🗑 <b>Удаление {label}-администратора</b>\n\nОтправь ID пользователя одним сообщением.\n\n⬅️ Для отмены используй /panel.",
        parse_mode="HTML",
    )


@router.message(AdminManageForm.user_id)
async def admin_manage_user_id(message: Message, state: FSMContext):
    if not is_owner("telegram", message.from_user.id):
        await state.clear()
        return await message.answer("⛔ Только владелец может управлять администраторами.")
    raw = (message.text or "").strip()
    if not raw.isdigit():
        return await message.answer("❗ ID должен состоять только из цифр. Попробуй ещё раз.")
    data = await state.get_data()
    platform = data["admin_platform"]
    user_id = int(raw)
    from config import owner_ids
    from .keyboards import admin_management_keyboard
    if user_id in owner_ids(platform):
        await state.clear()
        return await message.answer("⛔ Владельца удалить нельзя.", reply_markup=admin_management_keyboard())
    if data["admin_action"] == "add":
        changed = await add_admin(platform, user_id, message.from_user.id)
        result = "✅ Администратор добавлен." if changed else "ℹ️ Этот ID уже является администратором."
    else:
        changed = await remove_admin(platform, user_id)
        result = "🗑 Администратор удалён." if changed else "ℹ️ Такой администратор не найден."
    await state.clear()
    tg = await list_admins("telegram")
    vk = await list_admins("vk")
    tg_owner = ", ".join(str(x) for x in owner_ids("telegram")) or "не задан"
    vk_owner = ", ".join(str(x) for x in owner_ids("vk")) or "не задан"
    text = (
        "👥 <b>Управление администраторами</b>\n\n"
        f"👑 Telegram-владелец: <code>{tg_owner}</code>\n"
        f"👑 VK-владелец: <code>{vk_owner}</code>\n\n"
        f"📱 <b>Telegram:</b> {', '.join(r['user_id'] for r in tg) or 'нет'}\n"
        f"💬 <b>VK:</b> {', '.join(r['user_id'] for r in vk) or 'нет'}\n\n"
        f"{result}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_management_keyboard())
