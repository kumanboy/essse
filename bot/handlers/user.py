from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, Update
from bot.keyboards.main import main_menu, ESSAY, COURSE, TEMPLATE, SAMPLES, HELP
from bot.keyboards.subscribe import subscribe_keyboard
from bot.states import EssayStates
from bot.services.jobs import ActiveJob, ServiceClosed

CLOSED = "⏰ Esse tekshirish xizmati hozir yopiq.\n\nXizmat belgilangan ish vaqtida faol bo‘ladi. Belgilangan vaqtda qayta urinib ko‘ring."
BUSY = "⏳ Oldingi essengiz hali tekshiruv jarayonida.\n\nNatija yuborilgach, yangi esse topshirishingiz mumkin."
FOLLOW = "Davom etish uchun Telegram kanalimiz va Instagram sahifamizga obuna bo‘ling. So‘ng «Obunani tekshirish» tugmasini bosing."
PRODUCTS = {
    COURSE: "🎓 ESSE KURSI\n\nEsse yozishni bosqichma-bosqich o‘rganish uchun maxsus video darslik mavjud.\n\nKursda esse tuzilishi, fikrni rivojlantirish, sabab va dalillar keltirish, ikki qarashni yoritish, shaxsiy fikr hamda xulosani to‘g‘ri yozishni o‘rganasiz.\n\nSotib olish uchun @surayyo_utkirovna ga murojaat qiling.",
    TEMPLATE: "📄 MUKAMMAL ESSE SHABLONI\n\nEsse yozishda foydalanish uchun maxsus tayyorlangan mukammal esse shablonini alohida sotib olishingiz mumkin.\n\nShablonda kirish, asosiy qism, ikki qarash, dalillash, shaxsiy fikr va xulosani qanday tuzish tartibli ko‘rsatilgan.\n\nSotib olish uchun @surayyo_utkirovna ga murojaat qiling.",
    SAMPLES: "📚 NAMUNAVIY ESSELAR\n\n20 xil mavzu bo‘yicha namunaviy esselar to‘plami mavjud.\n\nTo‘plamda turli mavzularda fikrni ochish, sabab va dalillarni bog‘lash hamda yuqori darajadagi esse tuzishni amalda ko‘rasiz.\n\nSotib olish uchun @surayyo_utkirovna ga murojaat qiling.",
    HELP: "🆘 YORDAM\n\n«📝 Esse tekshirish» tugmasini bosing. Avval mavzuni (bo‘lsa, vaziyat matni bilan), so‘ng esse matnini yuboring.\n\nEssengiz qabul qilingach, natija shu chatga avtomatik keladi. Natija topshirilgan vaqtdan kamida 10 daqiqa o‘tgach, tekshiruv yakunlanganida yuboriladi.\n\nBekor qilish: /cancel. Murojaat: @surayyo_utkirovna.",
}


def build_router():
    router = Router(name="user")
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    @router.message(Command("start", "cancel"))
    async def start(message: Message, state: FSMContext, config, subscription):
        await state.clear()
        if not await subscription.allowed(message.from_user.id):
            await message.answer("Assalomu alaykum!\n\n" + FOLLOW, reply_markup=subscribe_keyboard(config.channel_username))
            return
        await message.answer("Assalomu alaykum! Kerakli bo‘limni tanlang.", reply_markup=main_menu(message.from_user.id, config.admin_id))

    @router.callback_query(F.data == "check_subscription")
    async def check(callback: CallbackQuery, config, subscription):
        if not await subscription.allowed(callback.from_user.id):
            await callback.answer("Telegram kanaliga obuna bo‘ling va qayta tekshiring.", show_alert=True)
            return
        await callback.answer("Telegram obunangiz tasdiqlandi.")
        await callback.message.answer("Instagram sahifamizga ham obuna bo‘lishni unutmang. Kerakli bo‘limni tanlang.", reply_markup=main_menu(callback.from_user.id, config.admin_id))

    @router.message(F.text.in_(PRODUCTS))
    async def product(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(PRODUCTS[message.text])

    @router.message(F.text == ESSAY)
    async def begin(message: Message, state: FSMContext, config, subscription, access, jobs):
        if not await subscription.allowed(message.from_user.id):
            await message.answer(FOLLOW, reply_markup=subscribe_keyboard(config.channel_username))
        elif not await access.available():
            await message.answer(CLOSED)
        elif await jobs.active(message.from_user.id):
            await message.answer(BUSY)
        else:
            await state.clear()
            await state.set_state(EssayStates.waiting_for_topic)
            await message.answer("Mavzuni yuboring. Vaziyat matni berilgan bo‘lsa, uni ham mavzu bilan birga kiriting.")

    @router.message(EssayStates.waiting_for_topic)
    async def topic(message: Message, state: FSMContext):
        if not message.text or not message.text.strip():
            await message.answer("Iltimos, mavzuni matn ko‘rinishida yuboring.")
            return
        await state.update_data(topic=message.text.strip())
        await state.set_state(EssayStates.waiting_for_essay)
        await message.answer("Endi esse matnini bitta xabar qilib yuboring.")

    @router.message(EssayStates.waiting_for_essay)
    async def essay(message: Message, state: FSMContext, event_update: Update, subscription, config, jobs):
        if message.text is None:
            await message.answer("Iltimos, esseni matn ko‘rinishida yuboring.")
            return
        if not await subscription.allowed(message.from_user.id):
            await message.answer(FOLLOW, reply_markup=subscribe_keyboard(config.channel_username))
            return
        data = await state.get_data()
        if not data.get("topic"):
            await state.clear()
            await message.answer("Qaytadan «📝 Esse tekshirish» tugmasini bosing.")
            return
        try:
            await jobs.submit(message.from_user.id, message.chat.id, data["topic"], message.text, event_update.update_id)
        except ServiceClosed:
            await message.answer(CLOSED)
        except ActiveJob:
            await message.answer(BUSY)
        await state.clear()
        # Acceptance is inserted atomically with the job and delivered by the outbox.

    return router
