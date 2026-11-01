import asyncio
import os
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, select, Boolean, update, text

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN", "9003221863:AAFxgNJNlwejxnkYVhnuYtsWREa3mNWEMnM")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 8493824882 

# --- БАЗА ДАННЫХ ---
Base = declarative_base()

class Student(Base):
    __tablename__ = 'students_v3'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    birthday = Column(String)
    telegram_id = Column(String, nullable=True)
    notify_all = Column(Boolean, default=False)

class ScheduleItem(Base):
    __tablename__ = 'schedule_items'
    id = Column(Integer, primary_key=True)
    day_of_week = Column(Integer) # 1 - Пн, 2 - Вт и т.д.
    lesson_num = Column(Integer)  # 1, 2, 3...
    subject = Column(String)      # Название (например, "История России")
    lesson_type = Column(String)  # Лекция / Семинар
    time_start = Column(String)   # "09:00"
    time_end = Column(String)     # "10:30"

class Homework(Base):
    __tablename__ = 'homeworks'
    id = Column(Integer, primary_key=True)
    day_of_week = Column(Integer)
    subject = Column(String)
    lesson_type = Column(String)
    text_content = Column(String, nullable=True)

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS students_v3 (
                id SERIAL PRIMARY KEY, name VARCHAR, birthday VARCHAR, telegram_id VARCHAR, notify_all BOOLEAN DEFAULT FALSE
            );
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_items (
                id SERIAL PRIMARY KEY, day_of_week INTEGER, lesson_num INTEGER, subject VARCHAR, lesson_type VARCHAR, time_start VARCHAR, time_end VARCHAR
            );
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS homeworks (
                id SERIAL PRIMARY KEY, day_of_week INTEGER, subject VARCHAR, lesson_type VARCHAR, text_content VARCHAR
            );
        """))
        print("База данных готова!")

# --- БОТ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

class AddStudent(StatesGroup):
    name = State()
    birthday = State()

class AddSchedule(StatesGroup):
    subject = State()
    lesson_type = State()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton(text='📅 Расписание')],
        [KeyboardButton(text='👥 Список группы'), KeyboardButton(text='📚 ДЗ')],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text='⚙️ Админ-панель')])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Добавить студента', callback_data='admin_add_student')],
        [InlineKeyboardButton(text='📅 Заполнить расписание', callback_data='admin_fill_schedule')],
        [InlineKeyboardButton(text='🔙 Назад', callback_data='admin_back')]
    ])

# --- ХЭНДЛЕРЫ ---
@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(f'Привет, {message.from_user.first_name}! 👋\nЯ бот-староста.', reply_markup=get_main_keyboard(is_admin))

# --- АДМИН-ПАНЕЛЬ ---
@dp.message(F.text == '⚙️ Админ-панель')
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Админ-панель:", reply_markup=get_admin_keyboard())

@dp.callback_query(F.data == 'admin_back')
async def admin_back(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin=True))
    await callback.answer()

# --- ДОБАВЛЕНИЕ СТУДЕНТА (АДМИН) ---
@dp.callback_query(F.data == 'admin_add_student')
async def admin_add_student(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи имя и фамилию студента:")
    await state.set_state(AddStudent.name)
    await callback.answer()

@dp.message(AddStudent.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Теперь введи дату рождения (ДД.ММ.ГГГГ):")
    await state.set_state(AddStudent.birthday)

@dp.message(AddStudent.birthday)
async def process_birthday(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        session.add(Student(name=data['name'], birthday=message.text))
        await session.commit()
    await message.answer(f"Студент {data['name']} добавлен!")
    await state.clear()
    await message.answer("В меню:", reply_markup=get_main_keyboard(is_admin=True))

# --- СПИСОК ГРУППЫ ---
@dp.message(F.text == '👥 Список группы')
async def show_group(message: types.Message):
    async with async_session() as session:
        result = await session.execute(select(Student).order_by(Student.name))
        students = result.scalars().all()
    if not students:
        await message.answer("Список пуст."); return
    text = "👥 **Список группы:**\n\n"
    for s in students:
        status = "✅" if s.telegram_id else "❌"
        text += f"• {s.name} — 🎂 {s.birthday} (в боте: {status})\n"
    await message.answer(text, parse_mode="Markdown")

# --- РАСПИСАНИЕ ---
DAYS = {1: "Понедельник", 2: "Вторник", 3: "Среда", 4: "Четверг", 5: "Пятница", 6: "Суббота"}

@dp.message(F.text == '📅 Расписание')
async def schedule_menu(message: types.Message):
    buttons = []
    for day_num, day_name in DAYS.items():
        buttons.append([InlineKeyboardButton(text=day_name, callback_data=f"day_{day_num}")])
    await message.answer("Выбери день недели:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith('day_'))
async def show_day_schedule(callback: types.CallbackQuery):
    day_num = int(callback.data.split('_')[1])
    
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).where(ScheduleItem.day_of_week == day_num).order_by(ScheduleItem.lesson_num))
        items = result.scalars().all()
    
    text = f"📅 **{DAYS[day_num]}**\n\n"
    buttons = []
    
    # Группируем одинаковые предметы (чтобы не было двух кнопок "История")
    unique_items = []
    for item in items:
        if not any(u.subject == item.subject for u in unique_items):
            unique_items.append(item)
        text += f"{item.lesson_num}. {item.time_start}-{item.time_end} — {item.subject} ({item.lesson_type})\n"
    
    for item in unique_items:
        buttons.append([InlineKeyboardButton(text=item.subject, callback_data=f"sub_{day_num}_{item.subject}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_days")])
    
    if not items:
        text = f"📅 **{DAYS[day_num]}**\n\nПар нет."
        buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_days")]]

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'back_to_days')
async def back_to_days(callback: types.CallbackQuery):
    buttons = []
    for day_num, day_name in DAYS.items():
        buttons.append([InlineKeyboardButton(text=day_name, callback_data=f"day_{day_num}")])
    await callback.message.edit_text("Выбери день недели:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('sub_'))
async def show_subject_details(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    day_num = int(parts[1])
    subject_name = parts[2]
    
    async with async_session() as session:
        result = await session.execute(select(Homework).where(Homework.day_of_week == day_num, Homework.subject == subject_name))
        hws = result.scalars().all()
    
    text = f"📚 **{subject_name}** ({DAYS[day_num]})\n\n"
    if not hws:
        text += "ДЗ пока нет."
    else:
        for hw in hws:
            text += f"*{hw.lesson_type}*: {hw.text_content}\n"
            
    buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data=f"day_{day_num}")]]
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

# --- ЗАПОЛНЕНИЕ РАСПИСАНИЯ АДМИНОМ (УПРОЩЕННОЕ) ---
@dp.callback_query(F.data == 'admin_fill_schedule')
async def admin_fill_schedule(callback: types.CallbackQuery):
    await callback.message.answer("Функция в разработке. Пока вы можете загружать расписание картинкой.")
    await callback.answer()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await init_db()
    asyncio.create_task(web_server())
    print('Бот запущен с системой расписания!')
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
