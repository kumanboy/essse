from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.services.permissions import is_admin
from bot.services.access import current_mode, free_period_end
from bot.keyboards.admin import admin_keyboard
from bot.keyboards.main import ADMIN, main_menu
from bot.states import AdminStates


async def status_text(access):
    s = await access.get_settings()
    tz = ZoneInfo(s["timezone"])
    def stamp(value):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M") if value else "Belgilanmagan"
    modes = {"promotion": "24/7 bepul davr", "daily_open": "Ish vaqti — ochiq", "daily_closed": "Ish vaqtidan tashqari", "disabled": "O‘chirilgan", "not_started": "Boshlanish kutilmoqda"}
    return (f"⚙️ Admin panel\n\nHolat: {modes[current_mode(s,s['db_now'])]}\n"
            f"Xizmat yoqilgan: {'Ha' if s['bot_enabled'] else 'Yo‘q'}\n"
            f"Boshlanish: {stamp(s['access_start'])}\nBepul kunlar: {s['free_access_days']}\n"
            f"Bepul davr tugashi: {stamp(free_period_end(s))}\n"
            f"Ish vaqti: {s['daily_open_time']:%H:%M}–{s['daily_close_time']:%H:%M}\n"
            f"Vaqt mintaqasi: {s['timezone']}\nYangilangan: {stamp(s['updated_at'])}\n"
            f"O‘zgartirgan: {s['updated_by'] or '—'}")


def build_router():
    router = Router(name="admin")
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    async def panel(message, state, config, access):
        if not is_admin(message.from_user.id, config.admin_id):
            return
        await state.clear()
        await message.answer(await status_text(access), reply_markup=admin_keyboard())

    router.message.register(panel, F.text == ADMIN)
    router.message.register(panel, Command("admin"))

    @router.callback_query(F.data.startswith("admin:"))
    async def action(callback: CallbackQuery, state: FSMContext, config, access):
        if not is_admin(callback.from_user.id, config.admin_id):
            await callback.answer("Ruxsat yo‘q.", show_alert=True)
            return
        await state.clear()
        action = callback.data.split(":", 1)[1]
        if action == "back":
            await callback.answer()
            await callback.message.answer("Asosiy menyu", reply_markup=main_menu(callback.from_user.id, config.admin_id))
            return
        if action in {"start", "on", "off"}:
            if action == "start":
                s = await access.get_settings()
                await access.update(callback.from_user.id, access_start=s["db_now"])
            else:
                await access.update(callback.from_user.id, bot_enabled=action == "on")
            await callback.answer("✅ Saqlandi.")
        elif action == "status":
            await callback.answer()
        elif action in {"access_start", "free_access_days", "daily_open_time", "daily_close_time", "timezone"}:
            prompts = {"access_start": "Boshlanish: YYYY-MM-DD HH:MM (sozlangan vaqt mintaqasida).",
                       "free_access_days": "Bepul kunlar sonini kiriting (1–365).",
                       "timezone": "IANA vaqt mintaqasini kiriting, masalan Asia/Tashkent."}
            await state.update_data(setting=action)
            await state.set_state(AdminStates.editing)
            await callback.answer()
            await callback.message.answer(prompts.get(action, "Vaqtni HH:MM shaklida kiriting."))
            return
        else:
            await callback.answer("Noma’lum amal.")
            return
        await callback.message.answer(await status_text(access), reply_markup=admin_keyboard())

    @router.message(AdminStates.editing, ~F.text.startswith("/"))
    async def edit(message: Message, state: FSMContext, config, access):
        if not is_admin(message.from_user.id, config.admin_id):
            return
        field = (await state.get_data()).get("setting")
        raw = (message.text or "").strip()
        try:
            if field == "free_access_days":
                value = int(raw)
            elif field in {"daily_open_time", "daily_close_time"}:
                if len(raw) != 5:
                    raise ValueError()
                value = time.fromisoformat(raw)
            elif field == "access_start":
                s = await access.get_settings()
                value = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(s["timezone"]))
            elif field == "timezone":
                ZoneInfo(raw)
                value = raw
            else:
                raise ValueError()
            await access.update(message.from_user.id, **{field: value})
        except (ValueError, ZoneInfoNotFoundError):
            await message.answer("Qiymat noto‘g‘ri. Ko‘rsatilgan shaklda qayta kiriting yoki /cancel bosing.")
            return
        await state.clear()
        await message.answer("✅ Sozlama saqlandi.\n\n" + await status_text(access), reply_markup=admin_keyboard())

    return router
