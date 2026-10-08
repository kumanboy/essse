from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_keyboard():
    buttons = [("🚀 Global bepul rejimni boshlash", "start"), ("📅 Boshlanish vaqtini belgilash", "access_start"),
               ("📅 Bepul kunlar soni", "free_access_days"), ("🕐 Ochilish vaqti", "daily_open_time"),
               ("🕚 Yopilish vaqti", "daily_close_time"), ("🌐 Vaqt mintaqasi", "timezone"),
               ("📊 Holat", "status"), ("🟢 Botni yoqish", "on"), ("🔴 Botni o‘chirish", "off"), ("⬅️ Orqaga", "back")]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data="admin:" + a)] for t, a in buttons])
