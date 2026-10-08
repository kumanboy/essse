from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def subscribe_keyboard(channel_username="@sardortoshmuhammad_onatili"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Telegram kanalga obuna bo‘lish", url="https://t.me/" + channel_username.lstrip("@"))],
        [InlineKeyboardButton(text="📸 Instagramga obuna bo‘lish", url="https://www.instagram.com/sardor_toshmuhammadov/")],
        [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_subscription")],
    ])
