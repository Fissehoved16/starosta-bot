import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, select

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN", "9003221863:AAFxgNJNlwejxnkYVhnuYtsWREa3mNWEMnM") # Замени на свой токен, если не добавил в Environment
DATABASE_URL = os.getenv("DATABASE_URL")

# ID старосты (тебя) - только ты можешь управлять ботом
ADMIN_ID = 8493824882 

# --- БАЗА ДАННЫХ ---
Base = declarative_base()

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    birthday = Column(String)

# Исправляем ссылку для SQLAlchemy (asyncpg)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- БОТ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Машина состояний (для диалогов)
class AddStudent(StatesGroup):
    name = State()
    birthday = State()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton(text='👥 Список группы')],
        [KeyboardButton(text='📅 Расписание'), KeyboardButton(text='📚 ДЗ и заметки')],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text='⚙️ Админ-панель')])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton(text='➕ Добавить студента', callback_data='admin_add_student')],
        [InlineKeyboardButton(text='🔙 Назад', callback_data='admin_back')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- ХЭНДЛЕРЫ ---
@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(
        f'Привет, {message.from_user.first_name}! 👋\n'
        f'Я бот-староста группы.',
        reply_markup=get_main_keyboard(is_admin)
    )

# --- АДМИН-ПАНЕЛЬ ---
@dp.message(F.text == '⚙️ Админ-панель')
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У тебя нет прав для этого действия.")
        return
    await message.answer("Добро пожаловать в админ-панель:", reply_markup=get_admin_keyboard())

@dp.callback_query(F.data == 'admin_back')
async def admin_back(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin=True))
    await callback.answer()

# --- ДОБАВЛЕНИЕ СТУДЕНТА ---
@dp.callback_query(F.data == 'admin_add_student')
async def admin_add_student(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи имя и фамилию студента:")
    await state.set_state(AddStudent.name)
    await callback.answer()

@dp.message(AddStudent.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Теперь введи дату рождения (в формате ДД.ММ.ГГГГ):")
    await state.set_state(AddStudent.birthday)

@dp.message(AddStudent.birthday)
async def process_birthday(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data['name']
    birthday = message.text
    
    # Сохраняем в базу
    async with async_session() as session:
        new_student = Student(name=name, birthday=birthday)
        session.add(new_student)
        await session.commit()
    
    await message.answer(f"Студент {name} успешно добавлен!")
    await state.clear()
    await message.answer("Вернулись в меню:", reply_markup=get_main_keyboard(is_admin=True))

# --- СПИСОК ГРУППЫ ---
@dp.message(F.text == '👥 Список группы')
async def show_group(message: types.Message):
    async with async_session() as session:
        result = await session.execute(select(Student).order_by(Student.name))
        students = result.scalars().all()
        
    if not students:
        await message.answer("Список группы пока пуст.")
        return
        
    text = "👥 **Список группы:**\n\n"
    for student in students:
        text += f"• {student.name} — 🎂 {student.birthday}\n"
    
    await message.answer(text, parse_mode="Markdown")

# --- ЗАГЛУШКИ ---
@dp.message(F.text == '📅 Расписание')
async def schedule(message: types.Message):
    await message.answer("📅 Здесь скоро появится расписание.")

@dp.message(F.text == '📚 ДЗ и заметки')
async def homework(message: types.Message):
    await message.answer("📚 Здесь скоро появится ДЗ.")

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
    await init_db() # Создаем таблицы при запуске
    asyncio.create_task(web_server())
    print('Бот запущен в облаке с базой данных!')
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
