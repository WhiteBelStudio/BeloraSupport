from __future__ import annotations

import json
import logging
import os
import secrets

from database import application_stats, count_applications, create_application, get_application, has_pending, list_admins, list_applications, set_status
from config import admin_ids, is_admin

logger = logging.getLogger("BeloraSupport.VK")

VK_STATES: dict[str, dict] = {}
VK_ADMIN_PAGES: dict[str, dict[str, int]] = {}


def _main_keyboard() -> str:
    keyboard = {
        "one_time": False,
        "inline": False,
        "buttons": [
            [{"action": {"type": "text", "label": "🎫 Подать заявку"}, "color": "primary"}],
            [{"action": {"type": "text", "label": "📋 Моя заявка"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": "🛠 Админ-панель"}, "color": "secondary"}],
        ],
    }
    return json.dumps(keyboard, ensure_ascii=False)


def _confirm_keyboard() -> str:
    keyboard = {
        "one_time": True,
        "inline": False,
        "buttons": [
            [
                {"action": {"type": "text", "label": "✅ Отправить"}, "color": "positive"},
                {"action": {"type": "text", "label": "✏️ Заново"}, "color": "secondary"},
            ],
            [{"action": {"type": "text", "label": "❌ Отмена"}, "color": "negative"}],
        ],
    }
    return json.dumps(keyboard, ensure_ascii=False)


def _admin_keyboard(app_id: int) -> str:
    keyboard = {
        "one_time": False,
        "inline": False,
        "buttons": [
            [
                {"action": {"type": "text", "label": f"✅ Одобрить #{app_id}"}, "color": "positive"},
                {"action": {"type": "text", "label": f"❌ Отклонить #{app_id}"}, "color": "negative"},
            ]
        ],
    }
    return json.dumps(keyboard, ensure_ascii=False)


async def _prepare_vk_group(bot) -> int | None:
    try:
        groups = await bot.api.request("groups.getById", {"fields": "name,screen_name"})
        response = groups.get("response", groups)
        if isinstance(response, dict):
            items = response.get("groups") or response.get("items") or []
            group = items[0] if items else response
        elif isinstance(response, list):
            group = response[0] if response else {}
        else:
            group = {}

        group_id = int(group["id"])
        logger.info("🔎 VK community detected: %s (id=%s)", group.get("name", "VK community"), group_id)

        await bot.api.request(
            "groups.setSettings",
            {
                "group_id": group_id,
                "messages": 1,
                "bots_capabilities": 1,
                "bots_start_button": 1,
                "bots_add_to_chat": 1,
            },
        )
        await bot.api.request(
            "groups.setLongPollSettings",
            {
                "group_id": group_id,
                "enabled": 1,
                "api_version": "5.199",
                "message_new": 1,
                "message_reply": 0,
                "message_edit": 0,
                "message_allow": 1,
                "message_deny": 1,
            },
        )
        settings = await bot.api.request("groups.getLongPollSettings", {"group_id": group_id})
        logger.info("✅ VK Long Poll settings: %s", settings.get("response", settings))
        return group_id
    except Exception:
        logger.exception("❌ VK API setup failed; polling will still start")
        return None


async def run_vk_bot() -> None:
    token = os.getenv("VK_TOKEN")
    if not token:
        logger.warning("VK_TOKEN is not configured; VK bot disabled")
        return

    from vkbottle import Bot
    from vkbottle.bot import Message

    bot = Bot(token=token)
    await _prepare_vk_group(bot)

    main_keyboard = _main_keyboard()
    logger.info("⌨️ VK keyboard prepared")

    async def _answer(message: Message, text: str, keyboard: str | None = None) -> None:
        try:
            await message.answer(text, keyboard=keyboard or main_keyboard)
        except Exception as exc:
            if "912" not in str(exc) and "chat bot feature" not in str(exc).lower():
                raise
            logger.warning("⚠️ VK keyboard unavailable (API 912); using text fallback")
            await message.answer(text)

    async def _send_vk(peer_id: int, text: str, keyboard: str | None = None) -> None:
        try:
            await bot.api.request(
                "messages.send",
                {
                    "peer_id": peer_id,
                    "random_id": secrets.randbelow(2_000_000_000),
                    "message": text,
                    **({"keyboard": keyboard} if keyboard else {}),
                },
            )
        except Exception:
            logger.exception("❌ Failed to send VK message to peer_id=%s", peer_id)

    def _admin_panel_keyboard() -> str:
        keyboard = {
            "one_time": False,
            "inline": False,
            "buttons": [
                [
                    {"action": {"type": "text", "label": "📥 Новые"}, "color": "primary"},
                    {"action": {"type": "text", "label": "📋 Все"}, "color": "secondary"},
                ],
                [
                    {"action": {"type": "text", "label": "📊 Статистика"}, "color": "secondary"},
                    {"action": {"type": "text", "label": "👥 Админы"}, "color": "secondary"},
                ],
                [
                    {"action": {"type": "text", "label": "🏠 Главное меню"}, "color": "secondary"},
                ],
            ],
        }
        return json.dumps(keyboard, ensure_ascii=False)

    def _admin_list_keyboard(apps, page: int, total: int, status_prefix: str) -> str:
        buttons = [[{"action": {"type": "text", "label": f"#{row['id']} • {row['name']} • {row['status']}"}, "color": "secondary"}] for row in apps]
        nav = []
        if page > 0:
            nav.append({"action": {"type": "text", "label": "⬅️ Предыдущая"}, "color": "secondary"})
        if (page + 1) * 10 < total:
            nav.append({"action": {"type": "text", "label": "➡️ Следующая"}, "color": "secondary"})
        if nav: buttons.append(nav)
        buttons.append([{ "action": {"type": "text", "label": "🏠 Панель"}, "color": "secondary" }])
        return json.dumps({"one_time": False, "inline": False, "buttons": buttons}, ensure_ascii=False)

    def _application_keyboard(app_id: int, status: str) -> str:
        buttons = []
        if status == "pending":
            buttons.append([
                {"action": {"type": "text", "label": f"✅ Одобрить #{app_id}"}, "color": "positive"},
                {"action": {"type": "text", "label": f"❌ Отклонить #{app_id}"}, "color": "negative"},
            ])
        buttons.append([{ "action": {"type": "text", "label": "🏠 Панель"}, "color": "secondary" }])
        return json.dumps({"one_time": False, "inline": False, "buttons": buttons}, ensure_ascii=False)

    async def _send_application_to_admins(app_id: int, data: dict, user_id: int) -> None:
        text = (
            f"🎫 Новая заявка #{app_id}\n\n"
            f"👤 {data['name']}\n"
            f"🎂 {data['age']}\n"
            f"📍 {data['city']}\n"
            f"💬 {data['reason']}\n"
            f"⭐ {data['interests']}\n\n"
            f"VK ID: {user_id}"
        )
        recipients = set(admin_ids("vk"))
        recipients.update(int(row["user_id"]) for row in await list_admins("vk"))
        for admin_id in recipients:
            await _send_vk(admin_id, text, _admin_keyboard(app_id))

    async def _finish_application(message: Message, data: dict) -> None:
        user_id = int(message.from_id)
        app_id = await create_application(
            "vk",
            str(user_id),
            None,
            data["name"],
            data["age"],
            data["city"],
            data["reason"],
            data["interests"],
        )
        VK_STATES.pop(str(user_id), None)
        await _answer(
            message,
            f"✅ Заявка #{app_id} отправлена администраторам.\n\n"
            "Теперь дождись решения — мы сообщим результат здесь.",
            main_keyboard,
        )
        await _send_application_to_admins(app_id, data, user_id)

    @bot.on.message()
    async def handle(message: Message):
        user_id = int(getattr(message, "from_id", 0) or 0)
        text = (message.text or "").strip()
        normalized = text.lower()

        logger.info(
            "📩 VK message received: peer_id=%s from_id=%s text=%r",
            getattr(message, "peer_id", None),
            user_id,
            text,
        )

        if normalized in {"/start", "начать", "старт"}:
            VK_STATES.pop(str(user_id), None)
            await _answer(
                message,
                "👋 Добро пожаловать в фан-клуб!\n\n"
                "Здесь можно подать заявку на вступление.\n\n"
                "Нажми «🎫 Подать заявку», чтобы начать.",
                main_keyboard,
            )
            return

        if normalized in {"🛠 админ-панель", "/panel"}:
            if not is_admin("vk", user_id):
                await _answer(message, "⛔ Доступ только для администраторов.", main_keyboard)
                return
            stats = await application_stats()
            await _answer(message, f"🛠 АДМИН-ПАНЕЛЬ\n\n📥 Ожидают: {stats['pending']}\n✅ Одобрено: {stats['approved']}\n❌ Отклонено: {stats['rejected']}\n📊 Всего: {stats['total']}\n\nВыбери раздел:", _admin_panel_keyboard())
            return

        if normalized in {"📊 статистика", "статистика"} and is_admin("vk", user_id):
            stats = await application_stats()
            await _answer(message, f"📊 СТАТИСТИКА\n\n📋 Всего: {stats['total']}\n📥 Ожидают: {stats['pending']}\n✅ Одобрено: {stats['approved']}\n❌ Отклонено: {stats['rejected']}", _admin_panel_keyboard())
            return

        if normalized in {"📥 новые", "ожидают"} and is_admin("vk", user_id):
            apps = await list_applications("pending", limit=10, offset=0)
            total = await count_applications("pending")
            await _answer(message, "📥 <b>Новых заявок нет.</b>" if not apps else "📥 НОВЫЕ ЗАЯВКИ\n\nВыбери заявку:", _admin_panel_keyboard() if not apps else _admin_list_keyboard(apps, 0, total, "pending"))
            return

        if normalized in {"📋 все заявки", "все заявки"} and is_admin("vk", user_id):
            apps = await list_applications(limit=10, offset=0)
            total = await count_applications()
            await _answer(message, "📋 Заявок пока нет." if not apps else "📋 ВСЕ ЗАЯВКИ\n\nВыбери заявку:", _admin_panel_keyboard() if not apps else _admin_list_keyboard(apps, 0, total, "all"))
            return

        if normalized in {"👥 администраторы", "администраторы"} and is_admin("vk", user_id):
            tg = await list_admins("telegram")
            vk = await list_admins("vk")
            await _answer(message, "👥 АДМИНИСТРАТОРЫ\n\n" + f"Telegram: {', '.join(r['user_id'] for r in tg) or 'нет'}\nVK: {', '.join(r['user_id'] for r in vk) or 'нет'}", _admin_panel_keyboard())
            return

        if normalized in {"⬅️ предыдущая", "➡️ следующая"} and is_admin("vk", user_id):
            info = VK_ADMIN_PAGES.get(str(user_id), {"mode": "pending", "page": 0})
            page = max(0, info["page"] + (1 if normalized == "➡️ следующая" else -1))
            mode = info["mode"]
            VK_ADMIN_PAGES[str(user_id)] = {"mode": mode, "page": page}
            status = "pending" if mode == "pending" else None
            total = await count_applications(status)
            apps = await list_applications(status, limit=10, offset=page * 10)
            if not apps and page > 0:
                page -= 1
                VK_ADMIN_PAGES[str(user_id)]["page"] = page
                apps = await list_applications(status, limit=10, offset=page * 10)
            title = "📥 НОВЫЕ ЗАЯВКИ" if mode == "pending" else "📋 ВСЕ ЗАЯВКИ"
            await _answer(message, title + "\n\nВыбери заявку:", _admin_panel_keyboard() if not apps else _admin_list_keyboard(apps, page, total, mode))
            return

        if normalized in {"🏠 главное меню", "🏠 панель"} and is_admin("vk", user_id):
            if normalized == "🏠 главное меню":
                await _answer(message, "👋 Главное меню:", main_keyboard)
            else:
                stats = await application_stats()
                await _answer(message, f"🛠 АДМИН-ПАНЕЛЬ\n\n📥 Ожидают: {stats['pending']}\n✅ Одобрено: {stats['approved']}\n❌ Отклонено: {stats['rejected']}\n📊 Всего: {stats['total']}", _admin_panel_keyboard())
            return

        if is_admin("vk", user_id) and normalized.startswith("#") and normalized[1:].split()[0].isdigit():
            app_id = int(normalized[1:].split()[0])
            app = await get_application(app_id)
            if app:
                import html
                await _answer(message, f"🎫 ЗАЯВКА #{app_id}\n\n👤 {html.escape(app['name'])}\n🎂 {app['age']}\n📍 {html.escape(app['city'])}\n💬 {html.escape(app['reason'])}\n⭐ {html.escape(app['interests'])}\n\n🌐 Платформа: {app['platform']}\n🆔 ID: {app['user_id']}\n📌 Статус: {app['status']}\n📝 Причина отказа: {html.escape(app['reject_reason'] or '—')}", _application_keyboard(app_id, app['status']))
                return

        if is_admin("vk", user_id) and normalized.startswith("✅ одобрить #"):
            try: app_id = int(normalized.split("#", 1)[1])
            except ValueError: app_id = 0
            app = await get_application(app_id) if app_id else None
            if not app:
                await _answer(message, "❌ Заявка не найдена.", _admin_panel_keyboard())
                return
            if await set_status(app_id, "approved"):
                if app["platform"] == "vk":
                    await _send_vk(int(app["user_id"]), f"🎉 Твоя заявка #{app_id} одобрена! Добро пожаловать в фан-клуб.", main_keyboard)
                await _answer(message, f"✅ Заявка #{app_id} одобрена.", _admin_panel_keyboard())
            else:
                await _answer(message, "ℹ️ Заявка уже обработана.", _admin_panel_keyboard())
            return

        if is_admin("vk", user_id) and normalized.startswith("❌ отклонить #"):
            try: app_id = int(normalized.split("#", 1)[1])
            except ValueError: app_id = 0
            if app_id:
                VK_STATES[str(user_id)] = {"step": "admin_reject_reason", "app_id": app_id}
                await _answer(message, f"📝 Напиши причину отклонения заявки #{app_id}.", _admin_panel_keyboard())
            return

        state = VK_STATES.get(str(user_id))
        if state and state.get("step") == "admin_reject_reason" and is_admin("vk", user_id):
            reason = text
            if not 2 <= len(reason) <= 500:
                await _answer(message, "Причина должна быть от 2 до 500 символов.", _admin_panel_keyboard())
                return
            app_id = int(state["app_id"])
            app = await get_application(app_id)
            VK_STATES.pop(str(user_id), None)
            if app and await set_status(app_id, "rejected", reason):
                if app["platform"] == "vk":
                    await _send_vk(int(app["user_id"]), f"❌ Заявка #{app_id} отклонена.\nПричина: {reason}", main_keyboard)
                await _answer(message, f"❌ Заявка #{app_id} отклонена.", _admin_panel_keyboard())
            else:
                await _answer(message, "ℹ️ Заявка уже обработана или не найдена.", _admin_panel_keyboard())
            return

        if normalized == "🎫 подать заявку":
            if await has_pending("vk", str(user_id)):
                await _answer(message, "⏳ У тебя уже есть заявка на рассмотрении.", main_keyboard)
                return
            VK_STATES[str(user_id)] = {"step": "name"}
            await _answer(message, "1/5. Как тебя зовут или как к тебе обращаться?", main_keyboard)
            return

        if normalized == "📋 моя заявка":
            if await has_pending("vk", str(user_id)):
                await _answer(message, "⏳ Твоя заявка сейчас находится на рассмотрении.", main_keyboard)
            else:
                await _answer(message, "ℹ️ Активной заявки нет.", main_keyboard)
            return

        state = VK_STATES.get(str(user_id))
        if not state:
            await _answer(message, "👋 Привет! Выбери действие:", main_keyboard)
            return

        step = state["step"]

        if step == "name":
            if not 2 <= len(text) <= 80:
                await _answer(message, "Имя/ник должен быть от 2 до 80 символов.", main_keyboard)
                return
            state["name"] = text
            state["step"] = "age"
            await _answer(message, "2/5. Сколько тебе лет? Введи число.", main_keyboard)
            return

        if step == "age":
            try:
                age = int(text)
            except ValueError:
                await _answer(message, "Введи возраст числом.", main_keyboard)
                return
            if not 10 <= age <= 100:
                await _answer(message, "Введи корректный возраст.", main_keyboard)
                return
            state["age"] = age
            state["step"] = "city"
            await _answer(message, "3/5. Из какого ты города?", main_keyboard)
            return

        if step == "city":
            if not 2 <= len(text) <= 100:
                await _answer(message, "Напиши город.", main_keyboard)
                return
            state["city"] = text
            state["step"] = "reason"
            await _answer(message, "4/5. Почему хочешь вступить в фан-клуб?", main_keyboard)
            return

        if step == "reason":
            if not 5 <= len(text) <= 1000:
                await _answer(message, "Ответ должен быть от 5 до 1000 символов.", main_keyboard)
                return
            state["reason"] = text
            state["step"] = "interests"
            await _answer(message, "5/5. Что тебе интересно в фан-клубе?", main_keyboard)
            return

        if step == "interests":
            if not 2 <= len(text) <= 1000:
                await _answer(message, "Ответ должен быть от 2 до 1000 символов.", main_keyboard)
                return
            state["interests"] = text
            state["step"] = "confirm"
            preview = (
                "📋 Предпросмотр заявки\n\n"
                f"👤 Имя: {state['name']}\n"
                f"🎂 Возраст: {state['age']}\n"
                f"📍 Город: {state['city']}\n"
                f"💬 Почему: {state['reason']}\n"
                f"⭐ Интересы: {state['interests']}\n\n"
                "Всё верно?"
            )
            await _answer(message, preview, _confirm_keyboard())
            return

        if step == "confirm":
            if normalized == "✏️ заново":
                VK_STATES[str(user_id)] = {"step": "name"}
                await _answer(message, "Начинаем заново. 1/5. Как тебя зовут или как к тебе обращаться?", main_keyboard)
                return
            if normalized == "❌ отмена":
                VK_STATES.pop(str(user_id), None)
                await _answer(message, "Заявка отменена.", main_keyboard)
                return
            if normalized == "✅ отправить":
                await _finish_application(message, state.copy())
                return
            await _answer(message, "Выбери «✅ Отправить», «✏️ Заново» или «❌ Отмена».", _confirm_keyboard())
            return

        await _answer(message, "Произошла ошибка состояния анкеты. Начни заново кнопкой «🎫 Подать заявку».", main_keyboard)
        VK_STATES.pop(str(user_id), None)

    logger.info("VK bot started; message handler registered")
    await bot.run_polling()
