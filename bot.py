import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from yookassa import Payment, Configuration
import asyncio
from dotenv import load_dotenv
import os
import sys
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

# Настройка логирования с поддержкой cp1251 для Windows
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='cp1251')

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
YOOMONEY_ACCOUNT_ID = os.getenv("YOOMONEY_ACCOUNT_ID")
YOOMONEY_SECRET_KEY = os.getenv("YOOMONEY_SECRET_KEY")

Configuration.account_id = YOOMONEY_ACCOUNT_ID
Configuration.secret_key = YOOMONEY_SECRET_KEY

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    payment_method_id TEXT,
    email TEXT
)''')
conn.commit()

# Список активных пользователей
active_users = set()

class PaymentStates(StatesGroup):
    waiting_for_email = State()

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

async def set_bot_commands():
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Начать работу с ботом"),
        types.BotCommand(command="buy", description="Купить подписку"),
    ])

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    active_users.add(user_id)  # Добавляем пользователя
    intro_text = (
        "Привет! Я Ольга Абакумова, врач-эндокринолог, нутрициолог, тренер с 25-летним опытом и просто энергичная девушка, которая живёт свою лучшую жизнь! "
        "Если ты здесь, значит хочешь похудеть и стать более энергичной. И моя задача — помочь тебе в этом ❤️"
    )
    await bot.send_message(chat_id=user_id, text=intro_text)
    marathon_text = (
        "Тысячи женщин мечтают похудеть, вернуть энергию и почувствовать себя уверенно. Но…\n"
        "❌ Диеты не работают.\n"
        "❌ Спортзал кажется адом.\n"
        "❌ Вес уходит медленно (или не уходит вообще).\n"
        "❌ Каждый день похож на день сурка.\n"
        "❌ И сил изменить жизнь с каждым днём всё меньше...\n\n"
        "Что если я скажу, что проблема – не в вас? А в том, что вам навязали подходы, которые не работают. "
        "За десятки лет работы с пациентами, которые суммарно похудели на тонны и вернули в свою жизнь энергию и счастье, я разработала свою методологию. "
        "Именно ей я поделюсь на моем новом марафоне.\n\n"
        "🔥 СБРОС: 50 шагов к стройности, энергии и счастью 🔥\n\n"
        "Марафон стартует уже 2 марта — и да начнутся 2 недели продуктивной работы над мышлением, образом жизни и привычками! "
        "Я уже подготовила 50 материалов и 20 заданий — всё для того, чтобы ты смогла наконец почувствовать себя стройной, желанной и энергичной!\n\n"
        "Что вас ждет?\n"
        "✅ 14 дней чёткого плана действий – без догадок, что делать дальше.\n"
        "✅ Эфиры, лекции и подкасты – простыми словами о сложном.\n"
        "✅ Поддержка и мотивация – вы не одна, мы проходим этот путь вместе.\n\n"
        "Какие вопросы закроет марафон?\n"
        "— Как изменить своё питание, чтобы похудеть и быть энергичной\n"
        "— Гормоны и метаболизм – почему ваше тело «не хочет» худеть\n"
        "— Питание и движение – как вернуть стройность без голодовок и жести?\n"
        "— Эмоциональное переедание и стресс – как убрать корень проблемы?\n"
        "— Витамины и минералы – что нужно вашему телу?\n"
        "— Генетика и психика — как они влияют на качество жизни?\n"
        "— План и мотивация — как поменять жизнь и закрепить результат?\n\n"
        "Для кого этот марафон?\n"
        "✔ Если ты хочешь сбросить вес и больше его не набирать.\n"
        "✔ Если чувствуешь усталость и потерю энергии.\n"
        "✔ Если хочешь понять своё тело и дать ему то, что нужно.\n\n"
        "Стартуем совсем скоро! Ты с нами?"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="КУПИТЬ", callback_data="buy_subscription")
    await bot.send_message(chat_id=user_id, text=marathon_text, reply_markup=builder.as_markup())
    cursor.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        asyncio.create_task(send_reminder_after_2_hours(user_id))

@dp.callback_query(F.data == "buy_subscription")
async def process_buy_callback(callback: types.CallbackQuery, state: FSMContext):
    await handle_buy_command(callback.message, state)
    await callback.answer()

@dp.message(Command("buy"))
async def handle_buy_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    cursor.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
    if cursor.fetchone():
        await message.reply("❌ У вас уже есть активная подписка.")
        return
    await message.reply("📧 Пожалуйста, введите ваш email для отправки чека:")
    await state.set_state(PaymentStates.waiting_for_email)

@dp.message(PaymentStates.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    user_id = message.from_user.id
    if "@" not in email or "." not in email:
        await message.reply("❌ Неверный формат email. Попробуйте еще раз:")
        return
    try:
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        payment = Payment.create({
            "amount": {"value": "2999.00", "currency": "RUB"},  # Изменено на 2999 рублей
            "confirmation": {"type": "redirect", "return_url": "https://t.me/your_bot"},
            "capture": True,
            "description": "Подписка на приватный канал",
            "expires_at": expires_at,
            "receipt": {
                "customer": {"email": email},
                "items": [{"description": "Подписка на приватный канал", "quantity": "1.00", "amount": {"value": "2999.00", "currency": "RUB"}, "vat_code": 1, "payment_subject": "service", "payment_mode": "full_payment"}]  # Изменено на 2999 рублей
            }
        }, str(uuid.uuid4()))
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Оплатить 2999 рублей", url=payment.confirmation.confirmation_url)  # Обновлён текст кнопки
        await message.reply("✅ Ссылка для оплаты (действительна 5 минут):", reply_markup=builder.as_markup())
        await state.update_data(payment_id=payment.id, email=email)
        asyncio.create_task(check_payment_status(user_id, payment.id, email))
        await state.set_state(None)
    except Exception as e:
        logging.error(f"Payment error: {e}")
        await message.reply("❌ Ошибка при создании платежа. Попробуйте позже.")
        await state.clear()

async def check_payment_status(user_id: int, payment_id: str, email: str):
    for _ in range(30):
        await asyncio.sleep(10)
        payment = Payment.find_one(payment_id)
        if payment.status == 'succeeded':
            try:
                cursor.execute('INSERT OR REPLACE INTO subscriptions (user_id, email) VALUES (?, ?)', (user_id, email))
                conn.commit()
                invite_link = await bot.create_chat_invite_link(chat_id=CHANNEL_ID, member_limit=1)
                await bot.send_message(chat_id=user_id, text=f"✅ Оплата прошла успешно!\n📧 Чек отправлен на вашу почту: {email}\n🔗 Ссылка для запроса доступа к каналу: {invite_link.invite_link}\n\nПожалуйста, перейдите по ссылке и отправьте запрос на присоединение.", disable_web_page_preview=True)
            except Exception as e:
                logging.error(f"Ошибка: {str(e)}")
                await bot.send_message(chat_id=user_id, text="❌ Ошибка при создании ссылки. Свяжитесь с администратором.")
            return
        elif payment.status == 'canceled':
            await bot.send_message(user_id, "❌ Платеж отменен.")
            return
    await bot.send_message(user_id, "⌛️ Время оплаты истекло.")

async def send_reminder_after_2_hours(user_id: int):
    await asyncio.sleep(2 * 60)  # 2 минуты для теста
    cursor.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        reminder_text = (
            "СБРОС: веса, убеждений и страхов. Откажись от жизни, которая уже давно не вдохновляет и закончи день сурка — стань, наконец, стройной, энергичной и счастливой! "
            "Ты всего в шаге от картинки, которую так часто прокручиваешь в голове. Может быть хватит откладывать себя на потом? Ты у себя одна, другие подождут, а ты — нет!\n\n"
            "Заходи на мой марафон\n🔥 СБРОС: 50 шагов к стройности, энергии и счастью 🔥"
        )
        await bot.send_message(chat_id=user_id, text=reminder_text)

async def send_spring_message():
    text = (
        "Весна на календаре, но бесконечная хандра в душе? А что если я скажу, что в любое время года, в любом возрасте и при любых обстоятельствах можно чувствовать себя счастливой. "
        "Да, я знаю, о чем говорю: даже когда тебя предают и жизнь по щелчку пальцев меняется, не потерять себя МОЖНО И НУЖНО. Начни, наконец, жить для себя. Похудей, приведи в порядок мысли, дыши полной грудью! "
        "Всему этому уже с завтрашнего дня будем учиться на моём новом марафоне\n\n🔥 СБРОС: 50 шагов к стройности, энергии и счастью 🔥"
    )
    for user_id in active_users:
        cursor.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            await bot.send_message(chat_id=user_id, text=text)

async def send_last_chance_message():
    text = (
        "БОЛЬШЕ ШАНСА НЕ БУДЕТ! Заботливо напоминаю, что сейчас — последняя возможность присоединиться к марафону.\n\n🔥 СБРОС: 50 шагов к стройности, энергии и счастью 🔥"
    )
    for user_id in active_users:
        cursor.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            await bot.send_message(chat_id=user_id, text=text)

async def send_we_started_message():
    text = "Мы уже начали, но ждём именно тебя!"
    for user_id in active_users:
        cursor.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            await bot.send_message(chat_id=user_id, text=text)

scheduler.add_job(
    send_spring_message,
    CronTrigger.from_crontab("0 12 1 3 *", timezone="Europe/Moscow")  # 1 марта 2025, 12:00 MSK
)
scheduler.add_job(
    send_last_chance_message,
    CronTrigger.from_crontab("0 12 2 3 *", timezone="Europe/Moscow")  # 2 марта 2025, 12:00 MSK
)
scheduler.add_job(
    send_we_started_message,
    CronTrigger.from_crontab("0 12 3 3 *", timezone="Europe/Moscow")  # 3 марта 2025, 12:00 MSK
)

async def main():
    await set_bot_commands()
    scheduler.start()
    logging.info("Планировщик запущен")
    await asyncio.sleep(5)  # Задержка 5 секунд перед поллингом
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())