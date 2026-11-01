import asyncio
import os
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, BigInteger, String, select, Boolean, update, text

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

class ScheduleFile(Base):
    __tablename__ = 'schedule_files'
    id = Column(Integer, primary_key=True)
    file_id = Column(String)
    file_type = Column(String)
    date_added = Column(String)

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        # Таблица студентов
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS students_v3 (
                id SERIAL PRIMARY KEY,
                name VARCHAR,
                birthday VARCHAR,
                telegram_id VARCHAR,
                notify_all BOOLEAN DEFAULT FALSE
            );
        """))
        # Таблица расписания
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_files (
                id SERIAL PRIMARY KEY,
                file_id VARCHAR,
                file_type VARCHAR,
                date_added VARCHAR
            );
        """))
        print("База данных готова!")

# --- БОТ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Машина состояний
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

def get_group_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📝 Зарегистрироваться в группе', callback_data='reg_student')]
    ])

def get_notify_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔔 Получать ВСЕ ДР', callback_data='notify_all_on')],
        [InlineKeyboardButton(text='🔕 Не получать ДР', callback_data='notify_all_off')]
    ])

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

# --- ДОБАВЛЕНИЕ СТУДЕНТА (АДМИН) ---
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
    
    async with async_session() as session:
        new_student = Student(name=name, birthday=birthday)
        session.add(new_student)
        await session.commit()
    
    await message.answer(f"Студент {name} успешно добавлен!")
    await state.clear()
    await message.answer("Вернулись в меню:", reply_markup=get_main_keyboard(is_admin=True))

# --- СПИСОК ГРУППЫ И РЕГИСТРАЦИЯ ---
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
        status = "✅" if student.telegram_id else "❌"
        text += f"• {student.name} — 🎂 {student.birthday} (в боте: {status})\n"
    
    await message.answer(text, parse_mode="Markdown", reply_markup=get_group_keyboard())

# --- РЕГИСТРАЦИЯ СТУДЕНТА ---
@dp.callback_query(F.data == 'reg_student')
async def register_student(callback: types.CallbackQuery):
    try:
        user_id = callback.from_user.id
        async with async_session() as session:
            result = await session.execute(select(Student).where(Student.telegram_id == str(user_id)))
            existing_student = result.scalars().first()
            
            if existing_student:
                await callback.message.answer(f"Ты уже зарегистрирован(а) как {existing_student.name}!")
            else:
                result = await session.execute(select(Student).where(Student.telegram_id.is_(None)))
                unlinked = result.scalars().all()
                
                if not unlinked:
                    await callback.message.answer("Нет свободных студентов в списке. Обратись к старосте!")
                else:
                    text = "Нажми на свое имя в списке, чтобы привязать аккаунт:\n\n"
                    buttons = []
                    for st in unlinked:
                        buttons.append([InlineKeyboardButton(text=st.name, callback_data=f"link_{st.id}")])
                    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"Произошла ошибка: {e}")
        await callback.answer()

@dp.callback_query(F.data.startswith('link_'))
async def link_account(callback: types.CallbackQuery):
    try:
        student_id = int(callback.data.split('_')[1])
        user_id = str(callback.from_user.id)
        
        async with async_session() as session:
            await session.execute(update(Student).where(Student.id == student_id).values(telegram_id=user_id))
            await session.commit()
            
            result = await session.execute(select(Student).where(Student.id == student_id))
            student = result.scalars().first()
            
        await callback.message.edit_text(
            f"Отлично! Теперь ты в системе как {student.name}.\nНастроим уведомления?", 
            reply_markup=get_notify_keyboard()
        )
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"Ошибка при привязке: {e}")
        await callback.answer()

# --- НАСТРОЙКИ УВЕДОМЛЕНИЙ ---
@dp.callback_query(F.data.startswith('notify_all_'))
async def set_notification(callback: types.CallbackQuery):
    try:
        action = callback.data.split('_')[2]
        user_id = str(callback.from_user.id)
        notify_value = True if action == 'on' else False
        
        async with async_session() as session:
            await session.execute(update(Student).where(Student.telegram_id == user_id).values(notify_all=notify_value))
            await session.commit()
            
        status = "включены" if notify_value else "выключены"
        await callback.message.edit_text(f"Уведомления о ДР {status}!")
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"Ошибка с уведомлениями: {e}")
        await callback.answer()

# --- РАСПИСАНИЕ ---
@dp.message(F.text == '📅 Расписание')
async def schedule(message: types.Message):
    async with async_session() as session:
        result = await session.execute(select(ScheduleFile).order_by(ScheduleFile.id.desc()))
        file_record = result.scalars().first()
        
    if not file_record:
        await message.answer("📅 Расписание пока не загружено. Староста скоро его добавит!")
        return
        
    if file_record.file_type == 'photo':
        await message.answer_photo(photo=file_record.file_id, caption=f"📅 Актуальное расписание (от {file_record.date_added})")
    else:
        await message.answer_document(document=file_record.file_id, caption=f"📅 Актуальное расписание (от {file_record.date_added})")

# Обработчик загрузки файлов (только для старосты)
@dp.message(F.photo | F.document)
async def handle_schedule_upload(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return 
    
    file_id = None
    file_type = None
    
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = 'photo'
    elif message.document:
        file_id = message.document.file_id
        file_type = 'document'
        
    if file_id:
        async with async_session() as session:
            await session.execute(text("DELETE FROM schedule_files"))
            
            new_file = ScheduleFile(file_id=file_id, file_type=file_type, date_added=str(datetime.now().date()))
            session.add(new_file)
            await session.commit()
            
        await message.answer("✅ Расписание обновлено! Студенты увидят его в разделе «📅 Расписание».")

# --- ЗАГЛУШКИ ---
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

# --- ФОНОВАЯ ЗАДАЧА ДЛЯ ДР ---
async def birthday_checker():
    while True:
        now = datetime.now()
        if now.hour == 9 and now.minute == 0:
            today = now.strftime("%d.%m")
            async with async_session() as session:
                result = await session.execute(select(Student).where(Student.birthday.like(f"{today}%")))
                bday_people = result.scalars().all()
                
                if bday_people:
                    text = "🎉 **Сегодня день рождения у:**\n\n"
                    for p in bday_people:
                        text += f"• {p.name} 🎂\n"
                    
                    await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
                    
                    result = await session.execute(select(Student).where(Student.notify_all == True))
                    subscribers = result.scalars().all()
                    for sub in subscribers:
                        if sub.telegram_id and sub.telegram_id != ADMIN_ID:
                            try:
                                await bot.send_message(sub.telegram_id, text, parse_mode="Markdown")
                            except:
                                pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)

async def main():
    await init_db()
    asyncio.create_task(web_server())
    asyncio.create_task(birthday_checker())
    print('Бот запущен в облаке с базой данных и расписанием!')
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
