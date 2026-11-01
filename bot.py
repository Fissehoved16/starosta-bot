import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ⚠️ ВСТАВЬ СЮДА НОВЫЙ ТОКЕН
TOKEN = '9003221863:AAFxgNJNlwejxnkYVhnuYtsWREa3mNWEMnM'

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📅 Расписание', callback_data='schedule')],
        [InlineKeyboardButton(text='📚 ДЗ и заметки', callback_data='homework')],
        [InlineKeyboardButton(text='🎉 Мероприятия', callback_data='events')],
        [InlineKeyboardButton(text='👥 Список группы', callback_data='group')],
    ])
    await message.answer(
        f'Привет, {message.from_user.first_name}! 👋\n'
        f'Я бот-староста. Выбери, что тебе нужно:',
        reply_markup=keyboard
    )

@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    if callback.data == 'schedule':
        await callback.message.answer('📅 Здесь будет расписание (пока в разработке)')
    elif callback.data == 'homework':
        await callback.message.answer('📚 Здесь будет ДЗ (пока в разработке)')
    elif callback.data == 'events':
        await callback.message.answer('🎉 Здесь будут мероприятия (пока в разработке)')
    elif callback.data == 'group':
        await callback.message.answer('👥 Здесь будет список группы (пока в разработке)')
    
    await callback.answer()

# Заглушка, чтобы хостинг не засыпал
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
    asyncio.create_task(web_server())
    print('Бот запущен в облаке!')
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
