import asyncio
import os
import re
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, select, Boolean, update, text, delete
import calendar

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN", "9280509373:AAG1-6DJiYDwDJ8fOVsTsfxrrcDlpdCB2oY")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 8493824882 

# --- ШАБЛОНЫ ВРЕМЕНИ ---
TIME_SLOTS = {
    1: "09:00 - 10:30", 2: "10:40 - 12:10", 3: "13:00 - 14:30",
    4: "14:40 - 16:10", 5: "16:20 - 17:50", 6: "18:00 - 19:30",
}

# --- ШАБЛОНЫ ПРЕДМЕТОВ ---
SUBJECTS = [
    "История России", "Информатика и программирование", "Основы Российской государственности",
    "Математический анализ", "Дискретная математика", "Алгебра и теория чисел",
    "Базовая физическая культура", "Архитектура вычислительных систем и компьютерных систем",
    "Иностранный язык", "Факультатив:система рельефно-точечного шрифта",
    "Безопастность жизнедеятельности", "Психологический тренинг рублево"
]

LESSON_TYPES = ["Лекция", "Семинар", "Практика"]

TYPE_EMOJI = {
    "Лекция": "🔵",
    "Семинар": "🟢",
    "Практика": "🟡"
}

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
    __tablename__ = 'schedule_dates'
    id = Column(Integer, primary_key=True)
    date_str = Column(String)
    lesson_num = Column(Integer)
    subject = Column(String)
    lesson_type = Column(String)
    time_start = Column(String)
    time_end = Column(String)

class Homework(Base):
    __tablename__ = 'homeworks_v1'
    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer)
    content = Column(String)
    file_id = Column(String, nullable=True)

class CompletedHomework(Base):
    __tablename__ = 'completed_homeworks'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    homework_id = Column(Integer)

class Note(Base):
    __tablename__ = 'notes'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String, nullable=True)
    content = Column(String)
    is_from_admin = Column(Boolean, default=False) # <-- НОВАЯ СТРОКА
    
class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer) # Привязка к конкретной паре (дата + предмет)
    student_id = Column(Integer)  # Кто присутствовал

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS students_v3 (id SERIAL PRIMARY KEY, name VARCHAR, birthday VARCHAR, telegram_id VARCHAR, notify_all BOOLEAN DEFAULT FALSE);"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS schedule_dates (id SERIAL PRIMARY KEY, date_str VARCHAR, lesson_num INTEGER, subject VARCHAR, lesson_type VARCHAR, time_start VARCHAR, time_end VARCHAR);"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS homeworks_v1 (id SERIAL PRIMARY KEY, schedule_id INTEGER, content VARCHAR, file_id VARCHAR);"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS completed_homeworks (id SERIAL PRIMARY KEY, student_id INTEGER, homework_id INTEGER);"))
        
        # Создаем/обновляем таблицу заметок
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY, student_id INTEGER, subject VARCHAR, content VARCHAR
            );
        """))
        
        # Добавляем новые колонки (если их нет)
        try:
            await conn.execute(text("ALTER TABLE notes ADD COLUMN IF NOT EXISTS subject VARCHAR;"))
            await conn.execute(text("ALTER TABLE notes ADD COLUMN IF NOT EXISTS is_from_admin BOOLEAN DEFAULT FALSE;"))
        except Exception as e:
            print(f"Ошибка при обновлении колонок: {e}")
        
        # Создаем таблицу посещаемости
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY, schedule_id INTEGER, student_id INTEGER
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
    date = State()
    num = State()

class AddHomework(StatesGroup):
    waiting_for_content = State()

class AddNote(StatesGroup):
    waiting_for_content = State()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton(text='📅 Расписание'), KeyboardButton(text='📚 ДЗ')],
        [KeyboardButton(text='👥 Список группы'), KeyboardButton(text='📝 Заметки')],
        [KeyboardButton(text='📊 Посещаемость')], # <-- НОВАЯ КНОПКА
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text='⚙️ Админ-панель')])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Добавить студента', callback_data='admin_add_student')],
        [InlineKeyboardButton(text='❌ Удалить студента', callback_data='admin_del_student')],
        [InlineKeyboardButton(text='📅 Добавить пару', callback_data='admin_add_schedule')],
        [InlineKeyboardButton(text='🗑 Удалить пару', callback_data='admin_del_schedule')],
        [InlineKeyboardButton(text='📝 Удалить ДЗ', callback_data='admin_del_hw')],
        [InlineKeyboardButton(text='✍️ Заметки студентам', callback_data='admin_notes')], # <-- НОВАЯ КНОПКА
        [InlineKeyboardButton(text='🔙 Назад', callback_data='admin_back')],
        [InlineKeyboardButton(text='📊 Посещаемость', callback_data='admin_attendance')]
    ])

def get_group_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📝 Зарегистрироваться в группе', callback_data='reg_student')],
        [InlineKeyboardButton(text='🔙 Назад', callback_data='admin_back')]
    ])

def get_notify_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔔 Получать ВСЕ ДР', callback_data='notify_all_on')],
        [InlineKeyboardButton(text='🔕 Не получать ДР', callback_data='notify_all_off')],
        [InlineKeyboardButton(text='🔙 Назад', callback_data='admin_back')]
    ])

# --- КАЛЕНДАРЬ ---
def get_calendar_keyboard(year: int, month: int, action: str = "cal"):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", 
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    
    kb.inline_keyboard.append([InlineKeyboardButton(text=f"{month_names[month-1]} {year}", callback_data="ignore")])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="Пн", callback_data="ignore"), InlineKeyboardButton(text="Вт", callback_data="ignore"),
        InlineKeyboardButton(text="Ср", callback_data="ignore"), InlineKeyboardButton(text="Чт", callback_data="ignore"),
        InlineKeyboardButton(text="Пт", callback_data="ignore"), InlineKeyboardButton(text="Сб", callback_data="ignore"),
        InlineKeyboardButton(text="Вс", callback_data="ignore"),
    ])
    
    month_days = calendar.monthcalendar(year, month)
    for week in month_days:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
            else:
                row.append(InlineKeyboardButton(text=str(day), callback_data=f"{action}_{year}_{month}_{day}"))
        kb.inline_keyboard.append(row)
        
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="◀️", callback_data=f"{action}nav_{prev_year}_{prev_month}"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="exit_to_menu"),
        InlineKeyboardButton(text="▶️", callback_data=f"{action}nav_{next_year}_{next_month}")
    ])
    return kb

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
async def admin_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=get_admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == 'exit_to_menu')
async def exit_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id == ADMIN_ID
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin))
    await callback.answer()
    
@dp.callback_query(F.data.endswith('_exit_calendar'))
async def exit_calendar(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id == ADMIN_ID
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin))
    await callback.answer()

# --- БЫСТРЫЙ ВВОД ДЗ ---
@dp.message(F.text.regexp(r'(?i)^\d{1,2}\s+[а-яА-Я]+\s+дз$'))
async def quick_homework_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    date_text = message.text.lower().replace("дз", "").strip()
    now = datetime.now()
    year = now.year
    months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
        "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12
    }
    match = re.search(r'(\d{1,2})\s+([а-яА-Я]+)', date_text)
    if not match:
        await message.answer("Не смог распознать дату. Попробуй в формате '3 ноября дз'.")
        return
    day = int(match.group(1))
    month_name = match.group(2).lower()
    if month_name not in months:
        await message.answer("Не знаю такой месяц. Попробуй '3 ноября дз'.")
        return
    month = months[month_name]
    date_str = f"{day:02d}.{month:02d}.{year}"
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).where(ScheduleItem.date_str == date_str).order_by(ScheduleItem.lesson_num))
        items = result.scalars().all()
    if not items:
        await message.answer(f"На {date_str} нет пар. Сначала добавь расписание на этот день.")
        return
    buttons = []
    for item in items:
        emoji = TYPE_EMOJI.get(item.lesson_type, "⚪")
        buttons.append([InlineKeyboardButton(text=f"{item.lesson_num}. {emoji} {item.subject}", callback_data=f"addhw_{item.id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    await message.answer(f"К какой паре на {date_str} добавить ДЗ?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# --- ДОБАВЛЕНИЕ ДЗ ---
@dp.callback_query(F.data.startswith('addhw_'))
async def ask_homework(callback: types.CallbackQuery, state: FSMContext):
    schedule_id = int(callback.data.split('_')[1])
    await state.update_data(schedule_id=schedule_id)
    buttons = [[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")]]
    await callback.message.edit_text("Отправь мне текст ДЗ или прикрепи файл (фото/документ):", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AddHomework.waiting_for_content)
    await callback.answer()

@dp.message(AddHomework.waiting_for_content)
async def save_homework(message: types.Message, state: FSMContext):
    data = await state.get_data()
    schedule_id = data['schedule_id']
    content = ""
    file_id = None
    if message.text:
        content = message.text
    elif message.photo:
        file_id = message.photo[-1].file_id
        content = message.caption if message.caption else "Фото"
    elif message.document:
        file_id = message.document.file_id
        content = message.caption if message.caption else message.document.file_name
    async with async_session() as session:
        new_hw = Homework(schedule_id=schedule_id, content=content, file_id=file_id)
        session.add(new_hw)
        await session.commit()
    await message.answer("✅ ДЗ успешно сохранено!", reply_markup=get_main_keyboard(is_admin=True))
    await state.clear()

# --- УДАЛЕНИЕ ДЗ ---
@dp.callback_query(F.data == 'admin_del_hw')
async def admin_del_hw(callback: types.CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(Homework, ScheduleItem).join(ScheduleItem, Homework.schedule_id == ScheduleItem.id).order_by(ScheduleItem.date_str, ScheduleItem.lesson_num))
        records = result.all()
    if not records:
        await callback.message.edit_text("Список ДЗ пуст.", reply_markup=get_admin_keyboard()); return
    buttons = []
    for hw, sched in records:
        preview = hw.content[:15] + "..." if len(hw.content) > 15 else hw.content
        btn_text = f"🗑 {sched.date_str} | {sched.lesson_num}. {sched.subject} ({preview})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_hw_{hw.id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text("Нажми на ДЗ, чтобы удалить его:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('del_hw_'))
async def process_del_hw(callback: types.CallbackQuery):
    hw_id = int(callback.data.split('_')[2])
    async with async_session() as session:
        await session.execute(delete(Homework).where(Homework.id == hw_id))
        await session.execute(delete(CompletedHomework).where(CompletedHomework.homework_id == hw_id))
        await session.commit()
    await callback.message.answer("✅ ДЗ удалено.")
    await admin_del_hw(callback)

# --- НОВЫЙ РАЗДЕЛ ДЗ ДЛЯ ВСЕХ ---
@dp.message(F.text == '📚 ДЗ')
async def hw_menu(message: types.Message):
    now = datetime.now()
    kb = get_calendar_keyboard(now.year, now.month, action="hwcal")
    await message.answer("Выбери дату, чтобы посмотреть ДЗ на этот день:", reply_markup=kb)

@dp.message(F.text == '📊 Посещаемость')
async def student_attendance(message: types.Message):
    await view_attendance_stats_msg(message)
    
@dp.callback_query(F.data.startswith('hwcalnav_'))
async def hw_calendar_navigate(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    
    # Если это кнопка "Назад", пропускаем её (её ловит другая функция)
    if parts[1] == 'back':
        return
        
    year, month = int(parts[1]), int(parts[2])
    kb = get_calendar_keyboard(year, month, action="hwcal")
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()
    
@dp.callback_query(F.data.startswith('hwcal_'))
async def process_hw_date(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    year, month, day = int(parts[1]), int(parts[2]), int(parts[3])
    date_str = f"{day:02d}.{month:02d}.{year}"
    await render_hw_list(callback, date_str, is_edit=True)
    await callback.answer()

@dp.callback_query(F.data.startswith('check_'))
async def mark_hw_done(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    hw_id = int(parts[1])
    date_str = parts[2]
    user_id = str(callback.from_user.id)
    async with async_session() as session:
        result = await session.execute(select(Student).where(Student.telegram_id == user_id))
        student = result.scalars().first()
        if student:
            res = await session.execute(select(CompletedHomework).where(CompletedHomework.student_id == student.id, CompletedHomework.homework_id == hw_id))
            if not res.scalars().first():
                session.add(CompletedHomework(student_id=student.id, homework_id=hw_id))
                await session.commit()
    await render_hw_list(callback, date_str, is_edit=True)
    await callback.answer()

@dp.callback_query(F.data.startswith('uncheck_'))
async def mark_hw_undone(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    hw_id = int(parts[1])
    date_str = parts[2]
    user_id = str(callback.from_user.id)
    async with async_session() as session:
        result = await session.execute(select(Student).where(Student.telegram_id == user_id))
        student = result.scalars().first()
        if student:
            await session.execute(delete(CompletedHomework).where(CompletedHomework.student_id == student.id, CompletedHomework.homework_id == hw_id))
            await session.commit()
    await render_hw_list(callback, date_str, is_edit=True)
    await callback.answer()

@dp.callback_query(F.data == 'hwcalnav_back')
async def back_to_hw_calendar(callback: types.CallbackQuery):
    now = datetime.now()
    kb = get_calendar_keyboard(now.year, now.month, action="hwcal")
    await callback.message.edit_text("Выбери дату, чтобы посмотреть ДЗ на этот день:", reply_markup=kb)
    await callback.answer()

# --- ПРОСМОТР ДЗ ЧЕРЕЗ РАСПИСАНИЕ ---
@dp.callback_query(F.data.startswith('viewsub_'))
async def show_subject_details(callback: types.CallbackQuery):
    item_id = int(callback.data.split('_')[1])
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).where(ScheduleItem.id == item_id))
        item = result.scalars().first()
        result = await session.execute(select(Homework).where(Homework.schedule_id == item_id))
        hws = result.scalars().all()
    emoji = TYPE_EMOJI.get(item.lesson_type, "⚪")
    text = f"{emoji} **{item.subject}** ({item.lesson_type})\nДата: {item.date_str}\n\n"
    buttons = []
    if not hws:
        text += "ДЗ пока нет."
    else:
        text += "📚 **Домашнее задание:**\n"
        for hw in hws:
            text += f"• {hw.content}\n"
            if hw.file_id:
                buttons.append([InlineKeyboardButton(text="📎 Прикрепленный файл", callback_data=f"sendfile_{hw.id}")])
    if callback.from_user.id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="📝 Добавить ДЗ", callback_data=f"addhw_{item.id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"view_{item.date_str[6:]}_{item.date_str[3:5]}_{item.date_str[:2]}")])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('sendfile_'))
async def send_hw_file(callback: types.CallbackQuery):
    hw_id = int(callback.data.split('_')[1])
    async with async_session() as session:
        result = await session.execute(select(Homework).where(Homework.id == hw_id))
        hw = result.scalars().first()
    if hw and hw.file_id:
        try: await callback.message.answer_document(document=hw.file_id)
        except: await callback.message.answer_photo(photo=hw.file_id)
    await callback.answer()

# --- ПОСЕЩАЕМОСТЬ (АДМИН) ---
@dp.callback_query(F.data == 'admin_attendance')
async def admin_attendance_menu(callback: types.CallbackQuery):
    now = datetime.now()
    # Используем уникальный префикс "attcal"
    kb = get_calendar_keyboard(now.year, now.month, action="attcal")
    await callback.message.edit_text("Выбери дату, чтобы отметить посещаемость:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith('attcalnav_'))
async def att_calendar_navigate(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    year, month = int(parts[1]), int(parts[2])
    kb = get_calendar_keyboard(year, month, action="attcal")
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith('attcal_'))
async def process_att_date(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    year, month, day = int(parts[1]), int(parts[2]), int(parts[3])
    date_str = f"{day:02d}.{month:02d}.{year}"
    
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).where(ScheduleItem.date_str == date_str).order_by(ScheduleItem.lesson_num))
        items = result.scalars().all()
        
    if not items:
        await callback.answer(f"На {date_str} пар нет.", show_alert=True)
        return
        
    buttons = []
    for item in items:
        emoji = TYPE_EMOJI.get(item.lesson_type, "⚪")
        # Уникальный префикс для выбора пары
        buttons.append([InlineKeyboardButton(text=f"{item.lesson_num}. {emoji} {item.subject}", callback_data=f"attselect_{item.id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="exit_to_menu")])
    await callback.message.edit_text(f"Выбери пару на {date_str} для отметки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('attselect_'))
async def mark_attendance(callback: types.CallbackQuery):
    try:
        schedule_id = int(callback.data.split('_')[1])
        
        async with async_session() as session:
            result = await session.execute(select(ScheduleItem).where(ScheduleItem.id == schedule_id))
            item = result.scalars().first()
            
            result = await session.execute(select(Student).order_by(Student.name))
            students = result.scalars().all()
            
            result = await session.execute(select(Attendance).where(Attendance.schedule_id == schedule_id))
            att_records = result.scalars().all()
            present_ids = [a.student_id for a in att_records]

        if not item:
            await callback.answer("Пара не найдена в базе.", show_alert=True)
            return

        text = f"📊 **Посещаемость:** {item.subject} ({item.date_str})\n\n"
        buttons = []
        for s in students:
            status = "✅" if s.id in present_ids else "❌"
            # Уникальный префикс для переключения статуса
            buttons.append([InlineKeyboardButton(text=f"{status} {s.name}", callback_data=f"atttoggle_{schedule_id}_{s.id}")])
        
        buttons.append([InlineKeyboardButton(text="🔙 Готово", callback_data="exit_to_menu")])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"ОШИБКА ПОСЕЩАЕМОСТИ: {e}")
        await callback.answer()

@dp.callback_query(F.data.startswith('atttoggle_'))
async def toggle_attendance(callback: types.CallbackQuery):
    try:
        parts = callback.data.split('_')
        schedule_id = int(parts[1])
        student_id = int(parts[2])
        
        async with async_session() as session:
            result = await session.execute(select(Attendance).where(Attendance.schedule_id == schedule_id, Attendance.student_id == student_id))
            existing = result.scalars().first()
            
            if existing:
                await session.execute(delete(Attendance).where(Attendance.id == existing.id))
            else:
                session.add(Attendance(schedule_id=schedule_id, student_id=student_id))
            await session.commit()
            
        # Перерисовываем сообщение
        await mark_attendance(callback)
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"ОШИБКА ПРИ ОТМЕТКЕ: {e}")
        await callback.answer()

# --- ПРОСМОТР СТАТИСТИКИ (ВСЕ) ---
@dp.callback_query(F.data == 'view_attendance_stats')
async def view_attendance_stats(callback: types.CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(Student).order_by(Student.name))
        students = result.scalars().all()
        
        result = await session.execute(select(ScheduleItem))
        all_lessons = result.scalars().all()
        
        result = await session.execute(select(Attendance))
        all_att = result.scalars().all()
        
    text = "📊 **Статистика посещаемости:**\n\n"
    
    # Считаем общее количество пар по предметам
    total_lessons_by_subject = {}
    for lesson in all_lessons:
        if lesson.subject not in total_lessons_by_subject:
            total_lessons_by_subject[lesson.subject] = 0
        total_lessons_by_subject[lesson.subject] += 1
        
    # Считаем посещения каждого студента по предметам
    for s in students:
        text += f"👤 **{s.name}**\n"
        student_att = [a for a in all_att if a.student_id == s.id]
        
        for subj, total in total_lessons_by_subject.items():
            # Сколько пар посетил
            attended = 0
            for att in student_att:
                lesson = next((l for l in all_lessons if l.id == att.schedule_id), None)
                if lesson and lesson.subject == subj:
                    attended += 1
            
            if attended > 0 or total > 0:
                hours = attended * 2
                total_hours = total * 2
                text += f"  • {subj}: {attended}/{total} пар ({hours}/{total_hours} акад. часов)\n"
        text += "\n"
        
    buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def view_attendance_stats_msg(message: types.Message):
    async with async_session() as session:
        result = await session.execute(select(Student).order_by(Student.name))
        students = result.scalars().all()
        result = await session.execute(select(ScheduleItem))
        all_lessons = result.scalars().all()
        result = await session.execute(select(Attendance))
        all_att = result.scalars().all()
        
    text = "📊 **Статистика посещаемости:**\n\n"
    total_lessons_by_subject = {}
    for lesson in all_lessons:
        if lesson.subject not in total_lessons_by_subject:
            total_lessons_by_subject[lesson.subject] = 0
        total_lessons_by_subject[lesson.subject] += 1
        
    for s in students:
        text += f"👤 **{s.name}**\n"
        student_att = [a for a in all_att if a.student_id == s.id]
        for subj, total in total_lessons_by_subject.items():
            attended = 0
            for att in student_att:
                lesson = next((l for l in all_lessons if l.id == att.schedule_id), None)
                if lesson and lesson.subject == subj:
                    attended += 1
            if attended > 0 or total > 0:
                hours = attended * 2
                total_hours = total * 2
                text += f"  • {subj}: {attended}/{total} пар ({hours}/{total_hours} акад. часов)\n"
        text += "\n"
        
    buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data="exit_to_menu")]]
    await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    
# --- СТУДЕНТЫ ---
@dp.callback_query(F.data == 'admin_add_student')
async def admin_add_student(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи имя и фамилию студента:\n(Для отмены нажми /start)")
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
    await message.answer(f"Студент {data['name']} добавлен!", reply_markup=get_main_keyboard(is_admin=True))
    await state.clear()

@dp.callback_query(F.data == 'admin_del_student')
async def admin_del_student(callback: types.CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(Student).order_by(Student.name))
        students = result.scalars().all()
    if not students:
        await callback.message.edit_text("Список студентов пуст.", reply_markup=get_admin_keyboard()); return
    buttons = [[InlineKeyboardButton(text=f"❌ {s.name}", callback_data=f"del_stud_{s.id}")] for s in students]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text("Нажми на студента, чтобы удалить его:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('del_stud_'))
async def process_del_student(callback: types.CallbackQuery):
    student_id = int(callback.data.split('_')[2])
    async with async_session() as session:
        await session.execute(delete(Student).where(Student.id == student_id))
        await session.commit()
    await admin_del_student(callback)


# --- ЗАМЕТКИ ---
@dp.message(F.text.in_({'📝 Заметки', '📝 Заметки'}))
async def notes_menu(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text="👤 Личные заметки", callback_data="notes_personal")],
        [InlineKeyboardButton(text="📚 Заметки по предметам", callback_data="notes_subjects")],
        [InlineKeyboardButton(text="📢 Заметки от старосты", callback_data="notes_from_admin")] # <-- НОВАЯ КНОПКА
    ]
    await message.answer("Выбери тип заметок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@dp.callback_query(F.data == 'notes_from_admin')
async def show_admin_notes(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    async with async_session() as session:
        result = await session.execute(select(Student).where(Student.telegram_id == user_id))
        student = result.scalars().first()
        
    if not student:
        await callback.answer("Сначала зарегистрируйся!", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(Note).where(Note.student_id == student.id, Note.is_from_admin == True))
        notes = result.scalars().all()
        
    text = "📢 **Заметки от старосты:**\n\n"
    buttons = []
    if not notes:
        text += "Пока заметок от старосты нет."
    else:
        for note in notes:
            subj = f" ({note.subject})" if note.subject else ""
            text += f"• {note.content}{subj}\n"
            
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="notes_back")])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'notes_personal')
async def show_personal_notes(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    async with async_session() as session:
        result = await session.execute(select(Student).where(Student.telegram_id == user_id))
        student = result.scalars().first()
        
    if not student:
        await callback.answer("Сначала зарегистрируйся!", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(Note).where(Note.student_id == student.id, Note.subject.is_(None)))
        notes = result.scalars().all()
        
    text = "👤 **Твои личные заметки:**\n\n"
    buttons = []
    if not notes:
        text += "У тебя пока нет личных заметок."
    else:
        for note in notes:
            text += f"• {note.content}\n"
            buttons.append([InlineKeyboardButton(text=f"❌ Удалить: {note.content[:15]}...", callback_data=f"del_note_{note.id}")])
            
    buttons.append([InlineKeyboardButton(text="➕ Добавить личную заметку", callback_data="add_personal_note")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="notes_back")])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'notes_subjects')
async def show_subject_notes(callback: types.CallbackQuery):
    buttons = []
    for idx, subj in enumerate(SUBJECTS):
        btn_text = subj if len(subj) < 25 else subj[:22] + "..."
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"viewnotes_{idx}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="notes_back")])
    await callback.message.edit_text("Выбери предмет:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('viewnotes_'))
async def show_notes_for_subject(callback: types.CallbackQuery):
    idx = int(callback.data.split('_')[1])
    subject = SUBJECTS[idx]
    user_id = str(callback.from_user.id)
    
    async with async_session() as session:
        result = await session.execute(select(Student).where(Student.telegram_id == user_id))
        student = result.scalars().first()
        if not student:
            await callback.answer("Сначала зарегистрируйся!", show_alert=True)
            return
            
        result = await session.execute(select(Note).where(Note.student_id == student.id, Note.subject == subject))
        notes = result.scalars().all()

    text = f"📚 **Заметки по предмету: {subject}**\n\n"
    buttons = []
    if not notes:
        text += "Заметок пока нет."
    else:
        for note in notes:
            text += f"• {note.content}\n"
            buttons.append([InlineKeyboardButton(text=f"❌ Удалить: {note.content[:15]}...", callback_data=f"del_note_{note.id}")])
            
    buttons.append([InlineKeyboardButton(text="➕ Добавить заметку", callback_data=f"add_subj_note_{idx}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="notes_subjects")])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'notes_back')
async def notes_back(callback: types.CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="👤 Личные заметки", callback_data="notes_personal")],
        [InlineKeyboardButton(text="📚 Заметки по предметам", callback_data="notes_subjects")],
        [InlineKeyboardButton(text="📢 Заметки от старосты", callback_data="notes_from_admin")] # <-- ДОБАВИТЬ
    ]
    await callback.message.edit_text("Выбери тип заметок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'add_personal_note')
async def add_personal_note_start(callback: types.CallbackQuery, state: FSMContext):
    buttons = [[InlineKeyboardButton(text="🔙 Отмена", callback_data="notes_back")]]
    await callback.message.edit_text("Напиши текст личной заметки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.update_data(note_subject=None)
    await state.set_state(AddNote.waiting_for_content)
    await callback.answer()

@dp.callback_query(F.data.startswith('add_subj_note_'))
async def add_subject_note_start(callback: types.CallbackQuery, state: FSMContext):
    idx = int(callback.data.split('_')[3])
    subject = SUBJECTS[idx]
    buttons = [[InlineKeyboardButton(text="🔙 Отмена", callback_data=f"viewnotes_{idx}")]]
    await callback.message.edit_text(f"Напиши заметку по предмету **{subject}**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.update_data(note_subject=subject)
    await state.set_state(AddNote.waiting_for_content)
    await callback.answer()

@dp.callback_query(F.data.startswith('del_note_'))
async def delete_note(callback: types.CallbackQuery):
    note_id = int(callback.data.split('_')[2])
    async with async_session() as session:
        await session.execute(delete(Note).where(Note.id == note_id))
        await session.commit()
    await callback.message.answer("Заметка удалена.")
    await callback.answer()
    buttons = [
        [InlineKeyboardButton(text="👤 Личные заметки", callback_data="notes_personal")],
        [InlineKeyboardButton(text="📚 Заметки по предметам", callback_data="notes_subjects")]
    ]
    await callback.message.edit_text("Выбери тип заметок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(AddNote.waiting_for_content)
async def save_note(message: types.Message, state: FSMContext):
    content = message.text
    data = await state.get_data()
    subject = data.get('note_subject')
    target_student_id = data.get('target_student_id')
    
    async with async_session() as session:
        if target_student_id:
            student_id = target_student_id
            is_from_admin = True
        else:
            user_id = str(message.from_user.id)
            result = await session.execute(select(Student).where(Student.telegram_id == user_id))
            student = result.scalars().first()
            if not student:
                await message.answer("Ошибка: ты не зарегистрирован!")
                return
            student_id = student.id
            is_from_admin = False
            
        session.add(Note(student_id=student_id, subject=subject, content=content, is_from_admin=is_from_admin))
        await session.commit()
        
        # Если это староста, отправляем уведомление студенту
        if is_from_admin:
            result = await session.execute(select(Student).where(Student.id == student_id))
            student = result.scalars().first()
            if student and student.telegram_id:
                try:
                    note_preview = f"📢 **Староста добавил(а) вам заметку:**\n\n"
                    if subject:
                        note_preview += f"📚 По предмету: *{subject}*\n"
                    note_preview += f"💬 {content}"
                    await bot.send_message(student.telegram_id, note_preview, parse_mode="Markdown")
                except Exception as e:
                    print(f"Не удалось отправить уведомление студенту: {e}")

    await message.answer("✅ Заметка добавлена!")
    await state.clear()
    
    if message.from_user.id == ADMIN_ID:
        await message.answer("Заметка сохранена для студента.", reply_markup=get_main_keyboard(is_admin=True))
    else:
        await notes_menu(message)
        
# --- ЗАМЕТКИ ДЛЯ СТУДЕНТОВ ОТ СТАРОСТЫ ---
@dp.callback_query(F.data == 'admin_notes')
async def admin_notes_menu(callback: types.CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(Student).order_by(Student.name))
        students = result.scalars().all()
    if not students:
        await callback.message.edit_text("Список студентов пуст.", reply_markup=get_admin_keyboard()); return
    
    buttons = [[InlineKeyboardButton(text=f"👤 {s.name}", callback_data=f"admin_note_stud_{s.id}")] for s in students]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text("Выбери студента, которому хочешь оставить заметку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('admin_note_stud_'))
async def admin_note_choose_type(callback: types.CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split('_')[3])
    await state.update_data(target_student_id=student_id)
    
    buttons = [
        [InlineKeyboardButton(text="👤 Личная заметка", callback_data="admin_note_type_personal")],
        [InlineKeyboardButton(text="📚 Заметка по предмету", callback_data="admin_note_type_subject")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_notes")]
    ]
    await callback.message.edit_text("Какую заметку добавить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'admin_note_type_personal')
async def admin_note_personal_start(callback: types.CallbackQuery, state: FSMContext):
    buttons = [[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_notes")]]
    await callback.message.edit_text("Напиши текст заметки для студента:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.update_data(note_subject=None)
    await state.set_state(AddNote.waiting_for_content)
    await callback.answer()

@dp.callback_query(F.data == 'admin_note_type_subject')
async def admin_note_subject_choose(callback: types.CallbackQuery):
    buttons = []
    for idx, subj in enumerate(SUBJECTS):
        btn_text = subj if len(subj) < 25 else subj[:22] + "..."
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_note_subj_{idx}")])
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_notes")])
    await callback.message.edit_text("Выбери предмет:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('admin_note_subj_'))
async def admin_note_subject_start(callback: types.CallbackQuery, state: FSMContext):
    idx = int(callback.data.split('_')[3])
    subject = SUBJECTS[idx]
    buttons = [[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_notes")]]
    await callback.message.edit_text(f"Напиши заметку по предмету **{subject}**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.update_data(note_subject=subject)
    await state.set_state(AddNote.waiting_for_content)
    await callback.answer()
    
# --- ДОБАВЛЕНИЕ ПАРЫ ---
@dp.callback_query(F.data == 'admin_add_schedule')
async def admin_add_schedule(callback: types.CallbackQuery, state: FSMContext):
    now = datetime.now()
    kb = get_calendar_keyboard(now.year, now.month, action="add")
    await callback.message.edit_text("Выбери дату для новой пары:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith('addnav_'))
async def calendar_navigate_add(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    year, month = int(parts[1]), int(parts[2])
    kb = get_calendar_keyboard(year, month, action="add")
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith('add_'))
async def process_sched_date(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    year, month, day = int(parts[1]), int(parts[2]), int(parts[3])
    date_str = f"{day:02d}.{month:02d}.{year}"
    await state.update_data(date=date_str)
    buttons = [[InlineKeyboardButton(text=f"{num} пара ({time})", callback_data=f"setnum_{num}")] for num, time in TIME_SLOTS.items()]
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    await callback.message.edit_text(f"Дата: {date_str}\nВыбери номер пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AddSchedule.num)
    await callback.answer()

@dp.callback_query(F.data.startswith('setnum_'))
async def process_sched_num(callback: types.CallbackQuery, state: FSMContext):
    num = int(callback.data.split('_')[1])
    await state.update_data(num=num)
    buttons = []
    for idx, subj in enumerate(SUBJECTS):
        btn_text = subj if len(subj) < 25 else subj[:22] + "..."
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"subj_{idx}")])
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    await callback.message.edit_text("Выбери предмет:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('subj_'))
async def process_sched_subject(callback: types.CallbackQuery, state: FSMContext):
    idx = int(callback.data.split('_')[1])
    subject = SUBJECTS[idx]
    await state.update_data(subject=subject)
    buttons = [[InlineKeyboardButton(text=f"{TYPE_EMOJI.get(l_type, '')} {l_type}", callback_data=f"type_{l_type}")] for l_type in LESSON_TYPES]
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    await callback.message.edit_text(f"Предмет: {subject}\nВыбери тип пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('type_'))
async def process_sched_type(callback: types.CallbackQuery, state: FSMContext):
    lesson_type = callback.data.split('_')[1]
    data = await state.get_data()
    time_slot = TIME_SLOTS[data['num']].split(' - ')
    
    async with async_session() as session:
        new_item = ScheduleItem(date_str=data['date'], lesson_num=data['num'], subject=data['subject'], lesson_type=lesson_type, time_start=time_slot[0], time_end=time_slot[1])
        session.add(new_item)
        await session.commit()
    
    # Очищаем состояние, чтобы кнопки работали корректно
    await state.set_state(AddSchedule.date) # Сбрасываем на начальное состояние выбора
    await state.update_data(date=data['date']) 
    
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить ещё на эту дату", callback_data="addmore_custom")], 
        [InlineKeyboardButton(text="✅ В админ-панель", callback_data="admin_back")]
    ]
    
    await callback.message.edit_text(
        f"✅ Пара добавлена:\n{data['date']}, {data['num']} пара\n{data['subject']} ({lesson_type})", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@dp.callback_query(F.data == 'addmore_custom')
async def add_more_sched(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date_str = data.get('date')
    
    if not date_str:
        await callback.message.edit_text("Ошибка: дата потерялась. Вернись в админку.", reply_markup=get_admin_keyboard())
        await callback.answer()
        return

    buttons = [[InlineKeyboardButton(text=f"{num} пара ({time})", callback_data=f"setnum_{num}")] for num, time in TIME_SLOTS.items()]
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    
    await callback.message.edit_text(f"Дата: {date_str}\nВыбери номер следующей пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AddSchedule.num)
    await callback.answer()

# --- УДАЛЕНИЕ ПАРЫ ---
@dp.callback_query(F.data == 'admin_del_schedule')
async def admin_del_schedule(callback: types.CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).order_by(ScheduleItem.date_str, ScheduleItem.lesson_num))
        items = result.scalars().all()
    if not items:
        await callback.message.edit_text("Расписание пусто.", reply_markup=get_admin_keyboard()); return
    buttons = [[InlineKeyboardButton(text=f"🗑 {i.date_str} | {i.lesson_num}. {i.subject}", callback_data=f"del_sched_{i.id}")] for i in items]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text("Нажми на пару, чтобы удалить её:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('del_sched_'))
async def process_del_schedule(callback: types.CallbackQuery):
    item_id = int(callback.data.split('_')[2])
    async with async_session() as session:
        await session.execute(delete(ScheduleItem).where(ScheduleItem.id == item_id))
        await session.commit()
    await admin_del_schedule(callback)

# --- ПРОСМОТР РАСПИСАНИЯ ---
@dp.message(F.text == '📅 Расписание')
async def schedule_menu(message: types.Message):
    now = datetime.now()
    kb = get_calendar_keyboard(now.year, now.month, action="view")
    await message.answer("Выбери дату, чтобы посмотреть расписание:", reply_markup=kb)

@dp.callback_query(F.data.startswith('viewnav_'))
async def calendar_navigate_view(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    year, month = int(parts[1]), int(parts[2])
    kb = get_calendar_keyboard(year, month, action="view")
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith('view_'))
async def process_view_date(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    year, month, day = int(parts[1]), int(parts[2]), int(parts[3])
    date_str = f"{day:02d}.{month:02d}.{year}"
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).where(ScheduleItem.date_str == date_str).order_by(ScheduleItem.lesson_num))
        items = result.scalars().all()
    if not items:
        await callback.answer(f"На {date_str} пар нет.", show_alert=True)
        return
    text = f"📅 **Расписание на {date_str}**\n\n"
    buttons = []
    for item in items:
        emoji = TYPE_EMOJI.get(item.lesson_type, "⚪")
        text += f"{item.lesson_num}. {item.time_start}-{item.time_end} {emoji} **{item.subject}** ({item.lesson_type})\n"
        btn_text = f"{emoji} {item.subject}"
        if len(btn_text) > 30: btn_text = btn_text[:27] + "..."
        
        # Если это староста, добавляем кнопку посещаемости
         if callback.from_user.id == ADMIN_ID:
            buttons.append([InlineKeyboardButton(text=f"📊 {item.lesson_num}. {item.subject}", callback_data=f"attselect_{item.id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_calendar_custom")])
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()
    
@dp.callback_query(F.data == 'back_to_calendar_custom')
async def back_to_calendar(callback: types.CallbackQuery):
    now = datetime.now()
    kb = get_calendar_keyboard(now.year, now.month, action="view")
    await callback.message.edit_text("Выбери дату, чтобы посмотреть расписание:", reply_markup=kb)
    await callback.answer()

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
    await message.answer(text, parse_mode="Markdown", reply_markup=get_group_keyboard())

@dp.callback_query(F.data == 'reg_student')
async def register_student(callback: types.CallbackQuery):
    try:
        user_id = str(callback.from_user.id)
        async with async_session() as session:
            result = await session.execute(select(Student).where(Student.telegram_id == user_id))
            existing_student = result.scalars().first()
            if existing_student:
                await callback.message.edit_text(f"Ты уже зарегистрирован(а) как {existing_student.name}!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
            else:
                result = await session.execute(select(Student).where(Student.telegram_id.is_(None)))
                unlinked = result.scalars().all()
                if not unlinked:
                    await callback.message.edit_text("Нет свободных студентов в списке. Обратись к старосте!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
                else:
                    text = "Нажми на свое имя в списке, чтобы привязать аккаунт:\n\n"
                    buttons = []
                    for st in unlinked:
                        buttons.append([InlineKeyboardButton(text=st.name, callback_data=f"link_{st.id}")])
                    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
                    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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
        await callback.message.edit_text(f"Отлично! Теперь ты в системе как {student.name}.\nНастроим уведомления?", reply_markup=get_notify_keyboard())
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"Ошибка при привязке: {e}")
        await callback.answer()

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
        await callback.message.edit_text(f"Уведомления о ДР {status}!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"Ошибка с уведомлениями: {e}")
        await callback.answer()

# --- ВЕБ-СЕРВЕР ---
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
    print('Бот запущен!')
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
