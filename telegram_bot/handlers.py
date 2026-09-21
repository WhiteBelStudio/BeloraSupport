from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import admin_ids, is_admin
from database import create_application, get_application, has_pending, set_status
from .keyboards import admin_keyboard, confirm_keyboard, main_keyboard

router = Router()

class ApplicationForm(StatesGroup):
    name = State()
    age = State()
    city = State()
    reason = State()
    interests = State()
    confirm = State()
    reject_reason = State()

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Добро пожаловать в фан-клуб!\n\nЗдесь можно подать заявку на вступление.", reply_markup=main_keyboard())

@router.callback_query(F.data == "apply")
async def apply_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if await has_pending("telegram", str(callback.from_user.id)):
        await callback.message.answer("⏳ У тебя уже есть заявка на рассмотрении.")
        return
    await state.clear(); await state.set_state(ApplicationForm.name)
    await callback.message.answer("1/5. Как тебя зовут или как к тебе обращаться?")

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
    preview=(f"📋 <b>Предпросмотр заявки</b>\n\n👤 <b>Имя:</b> {data['name']}\n🎂 <b>Возраст:</b> {data['age']}\n📍 <b>Город:</b> {data['city']}\n💬 <b>Почему:</b> {data['reason']}\n⭐ <b>Интересы:</b> {data['interests']}\n\nВсё верно?")
    await message.answer(preview, reply_markup=confirm_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "apply_confirm", ApplicationForm.confirm)
async def apply_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); data=await state.get_data(); user=callback.from_user
    app_id=await create_application("telegram",str(user.id),user.username,data["name"],data["age"],data["city"],data["reason"],data["interests"])
    await state.clear()
    await callback.message.answer(f"✅ Заявка <b>#{app_id}</b> отправлена администраторам.",parse_mode="HTML",reply_markup=main_keyboard())
    text=(f"🎫 <b>Новая заявка #{app_id}</b>\n\n👤 {data['name']}\n🎂 {data['age']}\n📍 {data['city']}\n💬 {data['reason']}\n⭐ {data['interests']}\n\nTelegram ID: <code>{user.id}</code>\nUsername: @{user.username or 'нет'}")
    for admin_id in admin_ids():
        try: await callback.bot.send_message(admin_id,text,parse_mode="HTML",reply_markup=admin_keyboard(app_id))
        except Exception: pass

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
    if not is_admin(callback.from_user.id): return await callback.answer("Нет доступа.",show_alert=True)
    app_id=int(callback.data.split(":")[1]); app=await get_application(app_id)
    if not app: return await callback.answer("Заявка не найдена.",show_alert=True)
    if not await set_status(app_id,"approved"): return await callback.answer("Заявка уже обработана.",show_alert=True)
    if app["platform"]=="telegram":
        try: await callback.bot.send_message(int(app["user_id"]),f"🎉 Твоя заявка #{app_id} одобрена! Добро пожаловать в фан-клуб.")
        except Exception: pass
    await callback.message.edit_reply_markup(reply_markup=None); await callback.message.answer(f"✅ Заявка #{app_id} одобрена.")

@router.callback_query(F.data.startswith("app_reject:"))
async def reject(callback: CallbackQuery,state:FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("Нет доступа.",show_alert=True)
    await state.update_data(reject_app_id=int(callback.data.split(":")[1])); await state.set_state(ApplicationForm.reject_reason); await callback.answer(); await callback.message.answer("Напиши причину отклонения заявки.")

@router.message(ApplicationForm.reject_reason)
async def reject_reason(message: Message,state:FSMContext):
    if not is_admin(message.from_user.id): return await state.clear()
    reason=(message.text or "").strip()
    if not 2 <= len(reason) <= 500: return await message.answer("Причина: от 2 до 500 символов.")
    app_id=int((await state.get_data())["reject_app_id"]); app=await get_application(app_id)
    if app and await set_status(app_id,"rejected",reason):
        if app["platform"]=="telegram":
            try: await message.bot.send_message(int(app["user_id"]),f"❌ Заявка #{app_id} отклонена.\nПричина: {reason}")
            except Exception: pass
        await message.answer(f"❌ Заявка #{app_id} отклонена.")
    else: await message.answer("Заявка уже обработана или не найдена.")
    await state.clear()
