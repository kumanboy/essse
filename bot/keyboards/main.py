from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from bot.services.permissions import is_admin

ESSAY = "📝 Esse tekshirish"
COURSE = "🎓 Esse kursi"
TEMPLATE = "📄 Esse shabloni"
SAMPLES = "📚 Namunaviy esselar"
HELP = "🆘 Yordam"
ADMIN = "⚙️ Admin panel"


def main_menu(user_id: int, admin_id: int):
    rows = [[ESSAY], [COURSE, TEMPLATE], [SAMPLES], [HELP]]
    if is_admin(user_id, admin_id):
        rows.append([ADMIN])
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in rows], resize_keyboard=True)
