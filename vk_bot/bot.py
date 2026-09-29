from __future__ import annotations

import json
import logging
import os
import secrets

from database import add_admin, application_stats, ban_user, count_applications, create_application, get_application, get_ban, has_pending, is_banned, list_admins, list_applications, list_bans, remove_admin, set_status, unban_user, add_ticket_message, assign_ticket, close_ticket, create_ticket, get_open_ticket_by_user, get_ticket, list_ticket_messages, list_tickets, start_conversation, close_conversation, get_active_conversation_by_admin, get_active_conversation_by_user
from config import effective_admin_ids, is_admin, is_owner

logger = logging.getLogger("BeloraSupport.VK")

VK_STATES: dict[str, dict] = {}
VK_ADMIN_PAGES: dict[str, dict[str, int]] = {}


def _main_keyboard(is_admin_user: bool = False) -> str:
    buttons = [
        [{"action": {"type": "text", "label": "🎫 Подать заявку"}, "color": "primary"}],
        [{"action": {"type": "text", "label": "📋 Моя заявка"}, "color": "secondary"}],
        [{"action": {"type": "text", "label": "📋 Правила"}, "color": "secondary"}],
        [{"action": {"type": "text", "label": "🆘 Техподдержка"}, "color": "secondary"}],
    ]
    if is_admin_user:
        buttons.append([{"action": {"type": "text", "label": "🛠 Админ-панель"}, "color": "secondary"}])
    return json.dumps({"one_time": False, "inline": False, "buttons": buttons}, ensure_ascii=False)


def _rules_keyboard() -> str:
    return json.dumps({
        "one_time": True,
        "inline": False,
        "buttons": [[{"action": {"type": "text", "label": "✅ Принимаю правила"}, "color": "positive"}]],
    }, ensure_ascii=False)


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
            default_keyboard = _main_keyboard(is_admin("vk", getattr(message, "from_id", 0)))
            await message.answer(text, keyboard=keyboard or default_keyboard)
        except Exception as exc:
            if "912" not in str(exc) and "chat bot feature" not in str(exc).lower():
                raise
            logger.warning("⚠️ VK keyboard unavailable (API 912); using text fallback")
            await message.answer(text)

    async def _send_vk(peer_id: int, text: str, keyboard: str | None = None) -> bool:
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
            return True
        except Exception:
            logger.exception("❌ Failed to send VK message to peer_id=%s", peer_id)
            return False

    def _vk_ticket_user_keyboard(ticket_id: int) -> str:
        return json.dumps({"one_time": False, "inline": False, "buttons": [
            [{"action": {"type": "text", "label": f"📖 Тикет #{ticket_id}"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": f"💬 Ответить в тикет #{ticket_id}"}, "color": "primary"}],
        ]}, ensure_ascii=False)

    def _vk_ticket_admin_keyboard(ticket_id: int) -> str:
        return json.dumps({"one_time": False, "inline": False, "buttons": [
            [{"action": {"type": "text", "label": f"📖 Тикет #{ticket_id}"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": f"💬 Ответить #{ticket_id}"}, "color": "primary"},
             {"action": {"type": "text", "label": f"🔴 Закрыть #{ticket_id}"}, "color": "negative"}],
        ]}, ensure_ascii=False)

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
                    {"action": {"type": "text", "label": "🎫 Тикеты"}, "color": "primary"},
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
        if status in {"pending", "approved", "rejected"}:
            buttons.append([{"action": {"type": "text", "label": f"💬 Написать пользователю #{app_id}"}, "color": "primary"}])
        buttons.append([{ "action": {"type": "text", "label": "🏠 Панель"}, "color": "secondary" }])
        return json.dumps({"one_time": False, "inline": False, "buttons": buttons}, ensure_ascii=False)

    def _vk_application_chat_keyboard(app_id: int) -> str:
        return json.dumps({"one_time": False, "inline": False, "buttons": [
            [{"action": {"type": "text", "label": f"🔴 Завершить переписку #{app_id}"}, "color": "negative"}],
            [{"action": {"type": "text", "label": "🏠 Панель"}, "color": "secondary"}],
        ]}, ensure_ascii=False)

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
        recipients = effective_admin_ids("vk")
        delivered = 0
        for admin_id in recipients:
            if await _send_vk(admin_id, text, _admin_keyboard(app_id)):
                delivered += 1
        if delivered == 0:
            logger.error("No VK admin notifications delivered for application #%s; recipients=%s", app_id, sorted(recipients))
        else:
            logger.info("VK application #%s notification delivered to %s/%s admins", app_id, delivered, len(recipients))

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

    class _RawVKMessage:
        def __init__(self, bot_instance, from_id: int, peer_id: int, text: str):
            self.bot = bot_instance
            self.from_id = from_id
            self.peer_id = peer_id
            self.text = text

        async def answer(self, text: str, keyboard: str | None = None):
            if not await _send_vk(self.peer_id, text, keyboard):
                raise RuntimeError(f"VK message delivery failed for peer_id={self.peer_id}")

    @bot.on.raw_event("message_new")
    async def handle(event):
        try:
            if not isinstance(event, dict):
                logger.warning("⚠️ Unexpected VK event type: %s", type(event).__name__)
                return

            event_object = event.get("object", {})
            if not isinstance(event_object, dict):
                logger.warning("⚠️ VK event object is not dict: %r", event_object)
                return

            payload = event_object.get("message", event_object)
            if not isinstance(payload, dict):
                logger.warning("⚠️ VK message payload is not dict: %r", payload)
                return

            user_id = int(payload.get("from_id", 0) or 0)
            peer_id = int(payload.get("peer_id", user_id) or user_id)
            text = str(payload.get("text", "") or "").strip()
        except Exception:
            logger.exception("❌ Failed to parse VK message_new event")
            return

        if not user_id:
            logger.warning("⚠️ VK message_new event has no from_id: %r", payload)
            return

        message = _RawVKMessage(bot, user_id, peer_id, text)
        normalized = text.lower()

        logger.info(
            "📩 VK message received: peer_id=%s from_id=%s text=%r",
            peer_id,
            user_id,
            text,
        )

        if await is_banned("vk", user_id) and not is_admin("vk", user_id):
            ban = await get_ban("vk", user_id)
            await _answer(message, "🚫 ДОСТУП ОГРАНИЧЕН\n\nПричина: " + ban["reason"], main_keyboard)
            return

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

        if is_admin("vk", user_id) and normalized.startswith("💬 написать пользователю #"):
            try:
                app_id = int(normalized.split("#", 1)[1].strip())
            except (TypeError, ValueError):
                app_id = 0
            if app_id <= 0:
                await _answer(message, "❌ Некорректный ID заявки.", _admin_panel_keyboard())
                return
            app = await get_application(app_id)
            if not app or app["platform"] != "vk":
                await _answer(message, "❌ VK-пользователь заявки не найден.", _admin_panel_keyboard())
                return
            await start_conversation("vk", app_id, user_id, int(app["user_id"]))
            if not await _send_vk(int(app["user_id"]), f"💬 Администратор начал переписку по заявке #{app_id}.\\n\\nМожешь отправить сообщение сюда — оно будет передано администратору.", _main_keyboard(False)):
                await close_conversation("vk", app_id)
                await _answer(message, "❌ Не удалось связаться с пользователем.", _admin_panel_keyboard())
                return
            await _answer(message, f"💬 Переписка по заявке #{app_id} активна.\\n\\nОтправляй сообщения сюда.", _vk_application_chat_keyboard(app_id))
            return

        if is_admin("vk", user_id) and normalized.startswith("🔴 завершить переписку #"):
            try:
                app_id = int(normalized.split("#", 1)[1].strip())
            except (TypeError, ValueError):
                app_id = 0
            if app_id <= 0:
                await _answer(message, "❌ Некорректный ID заявки.", _admin_panel_keyboard())
                return
            app = await get_application(app_id)
            await close_conversation("vk", app_id)
            if app and app["platform"] == "vk":
                await _send_vk(int(app["user_id"]), f"🔴 Переписка по заявке #{app_id} завершена администратором.", _main_keyboard(False))
            await _answer(message, f"🔴 Переписка по заявке #{app_id} завершена.", _admin_panel_keyboard())
            return

        if is_admin("vk", user_id):
            active_admin_chat = await get_active_conversation_by_admin("vk", user_id)
            if active_admin_chat and not normalized.startswith("💬 написать пользователю #") and not normalized.startswith("🔴 завершить переписку #"):
                if await _send_vk(int(active_admin_chat["user_id"]), f"💬 Администратор: {text}", _main_keyboard(False)):
                    await _answer(message, "📨 Доставлено пользователю.", _vk_application_chat_keyboard(int(active_admin_chat["application_id"])))
                else:
                    await _answer(message, "❌ Не удалось доставить сообщение пользователю.", _vk_application_chat_keyboard(int(active_admin_chat["application_id"])))
                return

        active_user_chat = await get_active_conversation_by_user("vk", user_id)
        if active_user_chat and not is_admin("vk", user_id):
            if await _send_vk(int(active_user_chat["admin_id"]), f"💬 Пользователь по заявке #{active_user_chat['application_id']}:\\n{text}", _admin_panel_keyboard()):
                await _answer(message, "📨 Сообщение передано администратору.", _main_keyboard(False))
            else:
                await _answer(message, "❌ Не удалось передать сообщение администратору.", _main_keyboard(False))
            return

        if normalized == "🆘 техподдержка":
            existing = await get_open_ticket_by_user("vk", user_id)
            if existing:
                await _answer(message, f"🎫 У тебя уже открыт тикет #{existing['id']}.\n\n📌 {existing['subject']}\n\nМожно продолжить переписку.", _vk_ticket_user_keyboard(int(existing["id"])))
            else:
                VK_STATES[str(user_id)] = {"step": "ticket_subject"}
                await _answer(message, "🎫 Создание тикета\n\nНапиши тему обращения.", main_keyboard)
            return

        if normalized == "🎫 тикеты" and is_admin("vk", user_id):
            tickets = await list_tickets("open", 20)
            if not tickets:
                await _answer(message, "🎫 Открытых тикетов нет.", _admin_panel_keyboard())
            else:
                await _answer(message, "🎫 ОТКРЫТЫЕ ТИКЕТЫ\n\n" + "\n".join(f"#{t['id']} • {t['subject'][:45]} • ID {t['user_id']}" for t in tickets), _admin_panel_keyboard())
            return

        if normalized.startswith("📖 тикет #") and not is_admin("vk", user_id):
            try: ticket_id=int(normalized.split("#",1)[1])
            except ValueError: ticket_id=0
            ticket=await get_ticket(ticket_id) if ticket_id else None
            if not ticket or int(ticket["user_id"])!=user_id:
                await _answer(message,"❌ Тикет не найден.",main_keyboard); return
            messages=await list_ticket_messages(ticket_id)
            lines=[f"🎫 Тикет #{ticket_id}",f"📌 {ticket['subject']}",f"Статус: {ticket['status']}",""]
            lines += [("👤 Ты: " if row["sender_type"]=="user" else "🛠 Администратор: ")+row["text"] for row in messages]
            await _answer(message,"\n".join(lines),_vk_ticket_user_keyboard(ticket_id)); return

        if normalized.startswith("💬 ответить в тикет #") and not is_admin("vk", user_id):
            try: ticket_id=int(normalized.split("#",1)[1])
            except ValueError: ticket_id=0
            ticket=await get_ticket(ticket_id) if ticket_id else None
            if not ticket or int(ticket["user_id"])!=user_id or ticket["status"]!="open":
                await _answer(message,"❌ Тикет закрыт или не найден.",main_keyboard); return
            VK_STATES[str(user_id)]={"step":"ticket_reply","ticket_id":ticket_id}
            await _answer(message,f"💬 Напиши сообщение в тикет #{ticket_id}.",main_keyboard); return

        if is_admin("vk", user_id) and normalized.startswith("📖 тикет #"):
            try: ticket_id=int(normalized.split("#",1)[1])
            except ValueError: ticket_id=0
            ticket=await get_ticket(ticket_id) if ticket_id else None
            if not ticket:
                await _answer(message,"❌ Тикет не найден.",_admin_panel_keyboard()); return
            messages=await list_ticket_messages(ticket_id)
            lines=[f"🎫 Тикет #{ticket_id}",f"📌 {ticket['subject']}",f"👤 ID: {ticket['user_id']}",f"Статус: {ticket['status']}",""]
            lines += [("👤 Пользователь: " if row["sender_type"]=="user" else "🛠 Администратор: ")+row["text"] for row in messages]
            await _answer(message,"\n".join(lines),_vk_ticket_admin_keyboard(ticket_id)); return

        if is_admin("vk", user_id) and normalized.startswith("💬 ответить #"):
            try: ticket_id=int(normalized.split("#",1)[1])
            except ValueError: ticket_id=0
            ticket=await get_ticket(ticket_id) if ticket_id else None
            if not ticket or ticket["status"]!="open":
                await _answer(message,"❌ Тикет закрыт или не найден.",_admin_panel_keyboard()); return
            await assign_ticket(ticket_id,user_id)
            VK_STATES[str(user_id)]={"step":"admin_ticket_reply","ticket_id":ticket_id}
            await _answer(message,f"💬 Ответ на тикет #{ticket_id}.\n\nНапиши сообщение.",_admin_panel_keyboard()); return

        if is_admin("vk", user_id) and normalized.startswith("🔴 закрыть #"):
            try: ticket_id=int(normalized.split("#",1)[1])
            except ValueError: ticket_id=0
            ticket=await get_ticket(ticket_id) if ticket_id else None
            if ticket:
                changed=await close_ticket(ticket_id)
                if changed: await _send_vk(int(ticket["user_id"]),f"🔴 Тикет #{ticket_id} закрыт администратором.",main_keyboard)
                await _answer(message,"✅ Тикет закрыт." if changed else "ℹ️ Тикет уже закрыт.",_admin_panel_keyboard())
            return

        if normalized in {"🛠 админ-панель", "/panel"}:
            if not is_admin("vk", user_id):
                await _answer(message, "⛔ Доступ только для администраторов.", main_keyboard)
                return
            logger.info("🛠 VK admin panel opened: user_id=%s", user_id)
            stats = await application_stats()
            await _answer(
                message,
                f"🛠 АДМИН-ПАНЕЛЬ\n\n📥 Ожидают: {stats['pending']}\n✅ Одобрено: {stats['approved']}\n❌ Отклонено: {stats['rejected']}\n📊 Всего: {stats['total']}\n\nВыбери раздел:",
                _admin_panel_keyboard(),
            )
            return

        if normalized == "/addadmin" or normalized.startswith("/addadmin "):
            if not is_owner("vk", user_id):
                await _answer(message, "⛔ Только владелец VK может управлять администраторами.", _admin_panel_keyboard())
                return
            parts = text.split()
            if len(parts) != 3 or parts[1].lower() not in {"tg", "telegram", "vk", "vkontakte"} or not parts[2].isdigit():
                await _answer(message, "Использование: /addadmin tg ID или /addadmin vk ID", _admin_panel_keyboard())
                return
            platform = "telegram" if parts[1].lower() in {"tg", "telegram"} else "vk"
            target_id = int(parts[2])
            if is_owner(platform, target_id):
                await _answer(message, "👑 Этот ID уже является владельцем и имеет полный доступ.", _admin_panel_keyboard())
                return
            changed = await add_admin(platform, target_id, user_id)
            await _answer(message, "✅ Администратор добавлен." if changed else "ℹ️ Этот ID уже является администратором. Права синхронизированы.", _admin_panel_keyboard())
            return

        if normalized == "/deladmin" or normalized.startswith("/deladmin "):
            if not is_owner("vk", user_id):
                await _answer(message, "⛔ Только владелец VK может управлять администраторами.", _admin_panel_keyboard())
                return
            parts = text.split()
            if len(parts) != 3 or parts[1].lower() not in {"tg", "telegram", "vk", "vkontakte"} or not parts[2].isdigit():
                await _answer(message, "Использование: /deladmin tg ID или /deladmin vk ID", _admin_panel_keyboard())
                return
            platform = "telegram" if parts[1].lower() in {"tg", "telegram"} else "vk"
            target_id = int(parts[2])
            if is_owner(platform, target_id):
                await _answer(message, "⛔ Владельца удалить нельзя.", _admin_panel_keyboard())
                return
            changed = await remove_admin(platform, target_id)
            await _answer(message, "🗑 Администратор удалён." if changed else "ℹ️ Такой администратор не найден.", _admin_panel_keyboard())
            return

        if normalized == "/ban" or normalized.startswith("/ban "):
            if not is_admin("vk", user_id):
                await _answer(message, "⛔ Доступ только для администраторов.", main_keyboard)
                return
            parts = text.split(maxsplit=3)
            if len(parts) < 4 or parts[1].lower() not in {"tg", "telegram", "vk"} or not parts[2].isdigit():
                await _answer(message, "Использование: /ban tg ID причина или /ban vk ID причина", main_keyboard)
                return
            platform = "telegram" if parts[1].lower() in {"tg", "telegram"} else "vk"
            target_id = int(parts[2])
            from config import owner_ids
            if target_id in owner_ids(platform):
                await _answer(message, "⛔ Владельца заблокировать нельзя.", main_keyboard)
                return
            if is_admin(platform, target_id):
                await _answer(message, "⛔ Администратора заблокировать нельзя.", main_keyboard)
                return
            reason = parts[3].strip()
            if not 2 <= len(reason) <= 500:
                await _answer(message, "Причина бана: от 2 до 500 символов.", main_keyboard)
                return
            await ban_user(platform, target_id, reason, user_id)
            if platform == "vk":
                if not await _send_vk(target_id, "🚫 ДОСТУП ОГРАНИЧЕН\n\nПричина: " + reason, main_keyboard):
                    logger.warning("VK user %s could not be notified about ban", target_id)
            await _answer(message, f"🚫 Пользователь {target_id} заблокирован.\nПлатформа: {platform}\nПричина: {reason}", _admin_panel_keyboard())
            return

        if normalized == "/unban" or normalized.startswith("/unban "):
            if not is_admin("vk", user_id):
                await _answer(message, "⛔ Доступ только для администраторов.", main_keyboard)
                return
            parts = text.split()
            if len(parts) != 3 or parts[1].lower() not in {"tg", "telegram", "vk"} or not parts[2].isdigit():
                await _answer(message, "Использование: /unban tg ID или /unban vk ID", main_keyboard)
                return
            platform = "telegram" if parts[1].lower() in {"tg", "telegram"} else "vk"
            target_id = int(parts[2])
            result = await unban_user(platform, target_id)
            if result and platform == "vk":
                if not await _send_vk(target_id, "✅ ДОСТУП ВОССТАНОВЛЕН\n\nОграничение с твоего аккаунта снято.", main_keyboard):
                    logger.warning("VK user %s could not be notified about unban", target_id)
            await _answer(message, "✅ Пользователь разблокирован." if result else "ℹ️ Такой пользователь не заблокирован.", _admin_panel_keyboard())
            return

        if normalized == "/banned":
            if not is_admin("vk", user_id):
                await _answer(message, "⛔ Доступ только для администраторов.", main_keyboard)
                return
            rows = await list_bans()
            if not rows:
                await _answer(message, "🚫 Заблокированных пользователей нет.", _admin_panel_keyboard())
                return
            lines = ["🚫 ЗАБЛОКИРОВАННЫЕ ПОЛЬЗОВАТЕЛИ", ""]
            for row in rows[:50]:
                lines.append(f"• {row['user_id']} — {row['platform']} — {row['reason']}")
            await _answer(message, "\n".join(lines), _admin_panel_keyboard())
            return

        if normalized in {"📊 статистика", "статистика"} and is_admin("vk", user_id):
            stats = await application_stats()
            await _answer(
                message,
                f"📊 СТАТИСТИКА\n\n"
                f"📋 Всего: {stats['total']}\n"
                f"📥 Ожидают: {stats['pending']}\n"
                f"✅ Одобрено: {stats['approved']}\n"
                f"❌ Отклонено: {stats['rejected']}\n\n"
                f"🤖 Telegram: {stats['telegram_total']} "
                f"(📥 {stats['telegram_pending']} / ✅ {stats['telegram_approved']} / ❌ {stats['telegram_rejected']})\n"
                f"🔵 VK: {stats['vk_total']} "
                f"(📥 {stats['vk_pending']} / ✅ {stats['vk_approved']} / ❌ {stats['vk_rejected']})",
                _admin_panel_keyboard(),
            )
            return

        if normalized in {"📥 новые", "ожидают"} and is_admin("vk", user_id):
            VK_ADMIN_PAGES[str(user_id)] = {"mode": "pending", "page": 0}
            apps = await list_applications("pending", limit=10, offset=0)
            total = await count_applications("pending")
            if not apps:
                await _answer(message, "📥 НОВЫЕ ЗАЯВКИ\n\nНовых заявок на рассмотрении нет.", _admin_panel_keyboard())
            else:
                await _answer(message, f"📥 НОВЫЕ ЗАЯВКИ\n\nВсего на рассмотрении: {total}\nСтраница 1\n\nВыбери заявку:", _admin_list_keyboard(apps, 0, total, "pending"))
            return

        if normalized in {"📋 все заявки", "все заявки"} and is_admin("vk", user_id):
            VK_ADMIN_PAGES[str(user_id)] = {"mode": "all", "page": 0}
            total = await count_applications()
            if total <= 0:
                await _answer(message, "📋 ВСЕ ЗАЯВКИ\n\nЗаявок пока нет.", _admin_panel_keyboard())
                return
            apps = await list_applications(limit=10, offset=0)
            max_page = (total - 1) // 10
            if not apps:
                await _answer(message, "📋 ВСЕ ЗАЯВКИ\n\nНа первой странице заявок нет.", _admin_panel_keyboard())
                return
            await _answer(
                message,
                f"📋 ВСЕ ЗАЯВКИ\n\nВсего: {total}\nСтраница 1 из {max_page + 1}\n\nВыбери заявку:",
                _admin_list_keyboard(apps, 0, total, "all"),
            )
            return

        if normalized in {"👥 администраторы", "администраторы"} and is_admin("vk", user_id):
            from config import owner_ids
            tg_owner = ", ".join(str(x) for x in sorted(owner_ids("telegram"))) or "не задан"
            vk_owner = ", ".join(str(x) for x in sorted(owner_ids("vk"))) or "не задан"
            tg_access = ", ".join(str(x) for x in sorted(effective_admin_ids("telegram"))) or "нет"
            vk_access = ", ".join(str(x) for x in sorted(effective_admin_ids("vk"))) or "нет"
            text_admins = (
                "👥 АДМИНИСТРАТОРЫ\n\n"
                f"👑 Telegram-владелец: {tg_owner}\n"
                f"👑 VK-владелец: {vk_owner}\n\n"
                f"📱 Telegram-доступ: {tg_access}\n"
                f"💬 VK-доступ: {vk_access}\n\n"
                "Управление только владельцем VK:\n"
                "/addadmin tg ID\n/addadmin vk ID\n/deladmin tg ID\n/deladmin vk ID"
            )
            await _answer(message, text_admins, _admin_panel_keyboard())
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

        if is_admin("vk", user_id) and normalized.startswith("#"):
            parts = normalized[1:].split()
            if parts and parts[0].isdigit():
                app_id = int(parts[0])
                if app_id <= 0:
                    await _answer(message, "❌ Некорректный ID заявки.", _admin_panel_keyboard())
                    return
                app = await get_application(app_id)
                if not app:
                    await _answer(message, f"❌ Заявка #{app_id} не найдена.", _admin_panel_keyboard())
                    return
                import html
                await _answer(
                    message,
                    f"🎫 ЗАЯВКА #{app_id}\n\n👤 {html.escape(app['name'])}\n🎂 {app['age']}\n📍 {html.escape(app['city'])}\n💬 {html.escape(app['reason'])}\n⭐ {html.escape(app['interests'])}\n\n🌐 Платформа: {app['platform']}\n🆔 ID: {app['user_id']}\n📌 Статус: {app['status']}\n📝 Причина отказа: {html.escape(app['reject_reason'] or '—')}\n🕒 Создана: {html.escape(app['created_at'])}",
                    _application_keyboard(app_id, app['status']),
                )
                return

        if is_admin("vk", user_id) and normalized.startswith("✅ одобрить #"):
            try:
                app_id = int(normalized.split("#", 1)[1].strip())
            except (TypeError, ValueError):
                app_id = 0
            if app_id <= 0:
                await _answer(message, "❌ Некорректный ID заявки.", _admin_panel_keyboard())
                return
            app = await get_application(app_id)
            if not app:
                await _answer(message, "❌ Заявка не найдена.", _admin_panel_keyboard())
                return
            if app["status"] != "pending":
                await _answer(message, f"ℹ️ Заявка уже обработана: {app['status']}.", _admin_panel_keyboard())
                return
            if await set_status(app_id, "approved"):
                notification_failed = False
                if app["platform"] == "vk":
                    try:
                        notification_failed = not await _send_vk(
                            int(app["user_id"]),
                            f"🎉 Твоя заявка #{app_id} одобрена! Добро пожаловать в фан-клуб.",
                            main_keyboard,
                        )
                    except Exception:
                        notification_failed = True
                suffix = "\n⚠️ Уведомление пользователю не доставлено." if notification_failed else ""
                await _answer(message, f"✅ Заявка #{app_id} одобрена.{suffix}", _admin_panel_keyboard())
            else:
                await _answer(message, "ℹ️ Заявка уже обработана.", _admin_panel_keyboard())
            return

        if is_admin("vk", user_id) and normalized.startswith("❌ отклонить #"):
            try:
                app_id = int(normalized.split("#", 1)[1].strip())
            except (TypeError, ValueError):
                app_id = 0
            if app_id <= 0:
                await _answer(message, "❌ Некорректный ID заявки.", _admin_panel_keyboard())
                return
            app = await get_application(app_id)
            if not app:
                await _answer(message, "❌ Заявка не найдена.", _admin_panel_keyboard())
                return
            if app["status"] != "pending":
                await _answer(message, f"ℹ️ Заявка уже обработана: {app['status']}.", _admin_panel_keyboard())
                return
            VK_STATES[str(user_id)] = {"step": "admin_reject_reason", "app_id": app_id}
            await _answer(message, f"📝 Напиши причину отклонения заявки #{app_id}. От 2 до 500 символов.", _admin_panel_keyboard())
            return

        state = VK_STATES.get(str(user_id))
        if state and state.get("step") == "ticket_subject":
            if not 3 <= len(text) <= 120:
                await _answer(message, "Тема должна быть от 3 до 120 символов.", main_keyboard); return
            state["subject"]=text; state["step"]="ticket_message"
            await _answer(message,"📝 Теперь подробно опиши вопрос или уточнение.",main_keyboard); return

        if state and state.get("step") == "ticket_message":
            if not 3 <= len(text) <= 3000:
                await _answer(message,"Сообщение должно быть от 3 до 3000 символов.",main_keyboard); return
            ticket_id=await create_ticket("vk",user_id,None,state["subject"])
            await add_ticket_message(ticket_id,"vk","user",user_id,text); VK_STATES.pop(str(user_id),None)
            await _answer(message,f"✅ Тикет #{ticket_id} создан. Администратор ответит сюда.",_vk_ticket_user_keyboard(ticket_id))
            notice=f"🎫 Новый тикет #{ticket_id}\n\n👤 VK ID: {user_id}\n📌 {state['subject']}\n\n{text}"
            for admin_id in effective_admin_ids("vk"):
                await _send_vk(admin_id,notice,_vk_ticket_admin_keyboard(ticket_id))
            return

        if state and state.get("step") == "ticket_reply":
            ticket_id=int(state["ticket_id"]); ticket=await get_ticket(ticket_id)
            if not ticket or ticket["status"]!="open":
                VK_STATES.pop(str(user_id),None); await _answer(message,"Тикет закрыт.",main_keyboard); return
            await add_ticket_message(ticket_id,"vk","user",user_id,text); VK_STATES.pop(str(user_id),None)
            notice=f"📩 Новое сообщение в тикете #{ticket_id}\n\n👤 VK ID: {user_id}\n\n{text}"
            for admin_id in effective_admin_ids("vk"):
                await _send_vk(admin_id,notice,_vk_ticket_admin_keyboard(ticket_id))
            await _answer(message,"📨 Сообщение передано администратору.",_vk_ticket_user_keyboard(ticket_id)); return

        if state and state.get("step") == "admin_ticket_reply" and is_admin("vk", user_id):
            ticket_id=int(state["ticket_id"]); ticket=await get_ticket(ticket_id)
            if not ticket or ticket["status"]!="open":
                VK_STATES.pop(str(user_id),None); await _answer(message,"Тикет закрыт.",_admin_panel_keyboard()); return
            await assign_ticket(ticket_id,user_id); await add_ticket_message(ticket_id,"vk","admin",user_id,text)
            if await _send_vk(int(ticket["user_id"]),f"💬 Ответ по тикету #{ticket_id}\n\n{text}",_vk_ticket_user_keyboard(ticket_id)):
                VK_STATES.pop(str(user_id),None); await _answer(message,"📨 Ответ отправлен.",_admin_panel_keyboard())
            else:
                await _answer(message,"❌ Не удалось отправить ответ.",_admin_panel_keyboard())
            return

        state = VK_STATES.get(str(user_id))
        if state and state.get("step") == "admin_reject_reason" and is_admin("vk", user_id):
            reason = text.strip()
            if not 2 <= len(reason) <= 500:
                await _answer(message, "Причина должна быть от 2 до 500 символов.", _admin_panel_keyboard())
                return
            try:
                app_id = int(state["app_id"])
            except (KeyError, TypeError, ValueError):
                VK_STATES.pop(str(user_id), None)
                await _answer(message, "❌ Сессия отклонения заявки недействительна. Открой заявку заново.", _admin_panel_keyboard())
                return
            if app_id <= 0:
                VK_STATES.pop(str(user_id), None)
                await _answer(message, "❌ Некорректный ID заявки.", _admin_panel_keyboard())
                return
            app = await get_application(app_id)
            if not app:
                VK_STATES.pop(str(user_id), None)
                await _answer(message, "❌ Заявка не найдена.", _admin_panel_keyboard())
                return
            if app["status"] != "pending":
                VK_STATES.pop(str(user_id), None)
                await _answer(message, f"ℹ️ Заявка уже обработана: {app['status']}.", _admin_panel_keyboard())
                return
            if not await set_status(app_id, "rejected", reason):
                VK_STATES.pop(str(user_id), None)
                await _answer(message, "ℹ️ Заявка уже обработана или не найдена.", _admin_panel_keyboard())
                return
            VK_STATES.pop(str(user_id), None)
            notification_failed = False
            if app["platform"] == "vk":
                try:
                    notification_failed = not await _send_vk(
                        int(app["user_id"]),
                        f"❌ Заявка #{app_id} отклонена.\nПричина: {reason}",
                        main_keyboard,
                    )
                except Exception:
                    notification_failed = True
            suffix = "\n⚠️ Уведомление пользователю не доставлено." if notification_failed else ""
            await _answer(message, f"❌ Заявка #{app_id} отклонена.{suffix}", _admin_panel_keyboard())
            return

        if normalized == "📋 правила":
            await _answer(
                message,
                "📋 ПРАВИЛА СОЗДАНИЯ АНКЕТЫ\n\n"
                "• Указывай достоверную информацию о себе.\n"
                "• Запрещены оскорбления, угрозы, травля и дискриминация.\n"
                "• Запрещён сексуальный и другой неподходящий контент.\n"
                "• Запрещены реклама, спам, мошенничество и обман.\n"
                "• Не публикуй чужие персональные данные без разрешения.\n"
                "• Фотография, имя и описание анкеты не должны нарушать правила платформы.\n"
                "• Администрация может отклонить анкету или ограничить доступ при нарушении правил.\n\n"
                "Нажимая «✅ Принимаю правила», ты подтверждаешь, что ознакомился с правилами.",
                _rules_keyboard(),
            )
            return

        if normalized in {"🎫 подать заявку"}:
            if await has_pending("vk", str(user_id)):
                await _answer(message, "⏳ У тебя уже есть заявка на рассмотрении.", main_keyboard)
                return
            VK_STATES[str(user_id)] = {"step": "rules"}
            await _answer(message, "📋 Перед созданием анкеты ознакомься с правилами.", _rules_keyboard())
            return

        if normalized == "✅ принимаю правила":
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

