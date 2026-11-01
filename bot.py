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
from sqlalchemy import Column, Integer, String, select, Boolean, update, text, delete
import calendar

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN", "9003221863:AAFxgNJNlwejxnkYVhnuYtsWREa3mNWEMnM")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 8493824882 

# --- ШАБЛОНЫ ВРЕМЕНИ ---
TIME_SLOTS = {
    1: "09:00 - 10:30",
    2: "10:40 - 12:10",
    3: "13:00 - 14:30",
    4: "14:40 - 16:10",
    5: "16:20 - 17:50",
    6: "18:00 - 19:30",
}

# --- ШАБЛОНЫ ПРЕДМЕТОВ (ДОБАВЛЯЙ СЮДА СВОИ) ---
SUBJECTS = [
    "История России",
    "Информатика и программирование",
    "Основы Российской государственности",
    "Математический анализ",
    "Дискретная математика",
    "Алгебра и теория чисел",
    "Базовая физическая культура",
    "Архитектура вычислительных систем и компьютерных систем",
    "Иностранный язык",
    "Факультатив:система рельефно-точечного шрифта",
    "Безопастность жизнедеятельности",
    "Психологический тренинг рублево"
]

LESSON_TYPES = ["Лекция", "Семинар", "Практика"]

# Эмодзи для цветовой маркировки
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

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS students_v3 (id SERIAL PRIMARY KEY, name VARCHAR, birthday VARCHAR, telegram_id VARCHAR, notify_all BOOLEAN DEFAULT FALSE);"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_dates (
                id SERIAL PRIMARY KEY, date_str VARCHAR, lesson_num INTEGER, 
                subject VARCHAR, lesson_type VARCHAR, time_start VARCHAR, time_end VARCHAR
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

# --- КЛАВИАТУРЫ ---
def get_main_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton(text='📅 Расписание')],
        [KeyboardButton(text='👥 Список группы')],
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
        [InlineKeyboardButton(text='🔙 Назад', callback_data='admin_back')]
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
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"),
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
    
    buttons = []
    for num, time in TIME_SLOTS.items():
        buttons.append([InlineKeyboardButton(text=f"{num} пара ({time})", callback_data=f"setnum_{num}")])
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
        # Обрезаем длинные названия для кнопки
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
    
    buttons = []
    for l_type in LESSON_TYPES:
        emoji = TYPE_EMOJI.get(l_type, "")
        buttons.append([InlineKeyboardButton(text=f"{emoji} {l_type}", callback_data=f"type_{l_type}")])
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    
    await callback.message.edit_text(f"Предмет: {subject}\nВыбери тип пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('type_'))
async def process_sched_type(callback: types.CallbackQuery, state: FSMContext):
    lesson_type = callback.data.split('_')[1]
    data = await state.get_data()
    time_slot = TIME_SLOTS[data['num']].split(' - ')
    
    async with async_session() as session:
        new_item = ScheduleItem(
            date_str=data['date'], lesson_num=data['num'], 
            subject=data['subject'], lesson_type=lesson_type, 
            time_start=time_slot[0], time_end=time_slot[1]
        )
        session.add(new_item)
        await session.commit()
    
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить ещё на эту дату", callback_data="add_more_sched")],
        [InlineKeyboardButton(text="✅ В админ-панель", callback_data="admin_back")]
    ]
    await callback.message.edit_text(
        f"✅ Пара добавлена:\n{data['date']}, {data['num']} пара\n{data['subject']} ({lesson_type})", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.update_data(date=data['date']) 
    await callback.answer()

@dp.callback_query(F.data == 'add_more_sched')
async def add_more_sched(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date_str = data.get('date')
    
    buttons = []
    for num, time in TIME_SLOTS.items():
        buttons.append([InlineKeyboardButton(text=f"{num} пара ({time})", callback_data=f"setnum_{num}")])
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
    
    buttons = []
    for i in items:
        text = f"{i.date_str} | {i.lesson_num}. {i.subject}"
        buttons.append([InlineKeyboardButton(text=f"🗑 {text}", callback_data=f"del_sched_{i.id}")])
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
    
    # Выводим каждую пару отдельно (без объединения)
    for item in items:
        emoji = TYPE_EMOJI.get(item.lesson_type, "⚪")
        text += f"{item.lesson_num}. {item.time_start}-{item.time_end} {emoji} **{item.subject}** ({item.lesson_type})\n"
        
        # Текст для кнопки обрезаем, чтобы влез
        btn_text = f"{emoji} {item.subject}"
        if len(btn_text) > 30:
            btn_text = btn_text[:27] + "..."
        
        # В callback_data передаем ID пары
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"viewsub_{item.id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="viewnav_back")])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'viewnav_back')
async def back_to_calendar(callback: types.CallbackQuery):
    now = datetime.now()
    kb = get_calendar_keyboard(now.year, now.month, action="view")
    await callback.message.edit_text("Выбери дату, чтобы посмотреть расписание:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith('viewsub_'))
async def show_subject_details(callback: types.CallbackQuery):
    item_id = int(callback.data.split('_')[1])
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).where(ScheduleItem.id == item_id))
        item = result.scalars().first()
    
    buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data=f"view_{item.date_str[6:]}_{item.date_str[3:5]}_{item.date_str[:2]}")]]
    emoji = TYPE_EMOJI.get(item.lesson_type, "⚪")
    await callback.message.edit_text(f"{emoji} **{item.subject}** ({item.lesson_type})\n\n📚 Материалы по этому предмету скоро появятся тут!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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
    print('Бот запущен (цветные пары и отдельные кнопки)!')
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
