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
    __tablename__ = 'schedule_items_v2'
    id = Column(Integer, primary_key=True)
    week_type = Column(Integer) # 1 - Верхняя, 2 - Нижняя
    day_of_week = Column(Integer)
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
            CREATE TABLE IF NOT EXISTS schedule_items_v2 (
                id SERIAL PRIMARY KEY, week_type INTEGER, day_of_week INTEGER, lesson_num INTEGER, 
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
    week = State()
    day = State()
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
        [InlineKeyboardButton(text='📝 Зарегистрироваться в группе', callback_data='reg_student')]
    ])

def get_notify_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔔 Получать ВСЕ ДР', callback_data='notify_all_on')],
        [InlineKeyboardButton(text='🔕 Не получать ДР', callback_data='notify_all_off')]
    ])

DAYS = {1: "Понедельник", 2: "Вторник", 3: "Среда", 4: "Четверг", 5: "Пятница", 6: "Суббота"}
WEEKS = {1: "Верхняя (нечетная)", 2: "Нижняя (четная)"}

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
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin=True))
    await callback.answer()

# --- СТУДЕНТЫ (АДМИН) ---
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
    await message.answer(f"Студент {data['name']} добавлен!", reply_markup=get_main_keyboard(is_admin=True))
    await state.clear()

@dp.callback_query(F.data == 'admin_del_student')
async def admin_del_student(callback: types.CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(Student).order_by(Student.name))
        students = result.scalars().all()
    if not students:
        await callback.message.answer("Список студентов пуст."); return
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
    await callback.message.answer("Студент удален.")
    await admin_del_student(callback)

# --- РАСПИСАНИЕ (ДОБАВЛЕНИЕ) ---
@dp.callback_query(F.data == 'admin_add_schedule')
async def admin_add_schedule(callback: types.CallbackQuery, state: FSMContext):
    buttons = [
        [InlineKeyboardButton(text=WEEKS[1], callback_data=f"setweek_1")],
        [InlineKeyboardButton(text=WEEKS[2], callback_data=f"setweek_2")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")]
    ]
    await callback.message.edit_text("Выбери неделю:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AddSchedule.week)
    await callback.answer()

@dp.callback_query(F.data.startswith('setweek_'))
async def process_sched_week(callback: types.CallbackQuery, state: FSMContext):
    week_num = int(callback.data.split('_')[1])
    await state.update_data(week=week_num)
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"setday_{num}")] for num, name in DAYS.items()]
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    await callback.message.edit_text(f"Неделя: {WEEKS[week_num]}\nВыбери день:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AddSchedule.day)
    await callback.answer()

@dp.callback_query(F.data.startswith('setday_'))
async def process_sched_day(callback: types.CallbackQuery, state: FSMContext):
    day_num = int(callback.data.split('_')[1])
    await state.update_data(day=day_num)
    buttons = []
    for num, time in TIME_SLOTS.items():
        buttons.append([InlineKeyboardButton(text=f"{num} пара ({time})", callback_data=f"setnum_{num}")])
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_back")])
    await callback.message.edit_text("Выбери номер пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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
    buttons = [[InlineKeyboardButton(text=l_type, callback_data=f"type_{l_type}")] for l_type in LESSON_TYPES]
    await callback.message.edit_text(f"Предмет: {subject}\nВыбери тип пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('type_'))
async def process_sched_type(callback: types.CallbackQuery, state: FSMContext):
    lesson_type = callback.data.split('_')[1]
    data = await state.get_data()
    time_slot = TIME_SLOTS[data['num']].split(' - ')
    async with async_session() as session:
        new_item = ScheduleItem(
            week_type=data['week'], day_of_week=data['day'], lesson_num=data['num'], 
            subject=data['subject'], lesson_type=lesson_type, 
            time_start=time_slot[0], time_end=time_slot[1]
        )
        session.add(new_item)
        await session.commit()
    await callback.message.edit_text(f"✅ Пара добавлена:\n{WEEKS[data['week']]}, {DAYS[data['day']]}, {data['num']} пара\n{data['subject']} ({lesson_type})")
    await state.clear()
    await callback.answer()

# --- РАСПИСАНИЕ (УДАЛЕНИЕ) ---
@dp.callback_query(F.data == 'admin_del_schedule')
async def admin_del_schedule(callback: types.CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).order_by(ScheduleItem.week_type, ScheduleItem.day_of_week, ScheduleItem.lesson_num))
        items = result.scalars().all()
    if not items:
        await callback.message.answer("Расписание пусто."); return
    buttons = []
    for i in items:
        text = f"{WEEKS[i.week_type][:3]} | {DAYS[i.day_of_week]} | {i.lesson_num}. {i.subject}"
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
    await callback.message.answer("Пара удалена.")
    await admin_del_schedule(callback)

# --- ПРОСМОТР РАСПИСАНИЯ (ДЛЯ ВСЕХ) ---
@dp.message(F.text == '📅 Расписание')
async def schedule_menu(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text=WEEKS[1], callback_data="view_week_1")],
        [InlineKeyboardButton(text=WEEKS[2], callback_data="view_week_2")]
    ]
    await message.answer("Выбери неделю:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith('view_week_'))
async def show_week_days(callback: types.CallbackQuery):
    week_num = int(callback.data.split('_')[2])
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"viewday_{week_num}_{num}")] for num, name in DAYS.items()]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")])
    await callback.message.edit_text(f"Неделя: {WEEKS[week_num]}\nВыбери день:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == 'back_to_main')
async def back_to_main(callback: types.CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text=WEEKS[1], callback_data="view_week_1")],
        [InlineKeyboardButton(text=WEEKS[2], callback_data="view_week_2")]
    ]
    await callback.message.edit_text("Выбери неделю:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('viewday_'))
async def show_day_schedule(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    week_num = int(parts[1])
    day_num = int(parts[2])
    
    async with async_session() as session:
        result = await session.execute(
            select(ScheduleItem).where(ScheduleItem.week_type == week_num, ScheduleItem.day_of_week == day_num).order_by(ScheduleItem.lesson_num)
        )
        items = result.scalars().all()
    
    text = f"📅 **{DAYS[day_num]}** ({WEEKS[week_num]})\n\n"
    buttons = []
    if not items:
        text += "Пар нет."
    else:
        unique_items = []
        for item in items:
            if not any(u.subject == item.subject for u in unique_items):
                unique_items.append(item)
            text += f"{item.lesson_num}. {item.time_start}-{item.time_end} — {item.subject} ({item.lesson_type})\n"
        for item in unique_items:
            buttons.append([InlineKeyboardButton(text=item.subject, callback_data=f"viewsub_{item.id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"view_week_{week_num}")])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith('viewsub_'))
async def show_subject_details(callback: types.CallbackQuery):
    item_id = int(callback.data.split('_')[1])
    async with async_session() as session:
        result = await session.execute(select(ScheduleItem).where(ScheduleItem.id == item_id))
        item = result.scalars().first()
    await callback.message.answer(f"📚 Материалы по предмету **{item.subject}** ({item.lesson_type}) скоро появятся тут!", parse_mode="Markdown")
    await callback.answer()

# --- СПИСОК ГРУППЫ И РЕГИСТРАЦИЯ (ДЛЯ ВСЕХ) ---
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
    # Кнопка регистрации видна ВСЕМ (включая старосту)
    await message.answer(text, parse_mode="Markdown", reply_markup=get_group_keyboard())

@dp.callback_query(F.data == 'reg_student')
async def register_student(callback: types.CallbackQuery):
    try:
        user_id = str(callback.from_user.id)
        async with async_session() as session:
            result = await session.execute(select(Student).where(Student.telegram_id == user_id))
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
        await callback.message.edit_text(f"Уведомления о ДР {status}!")
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
