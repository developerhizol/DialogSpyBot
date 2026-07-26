import asyncio
import logging
import sys
import os
import re
import random
import html as html_lib
import tempfile
import shutil
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta
import aiohttp
import yt_dlp

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message as MessageType
from aiogram.types import BusinessMessagesDeleted, FSInputFile, BusinessConnection
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.types import CopyTextButton, LinkPreviewOptions, URLInputFile
from aiogram.types import InputMediaVideo, InputMediaPhoto
from sqlmodel import Session as SQLSession
from sqlmodel import select, func

import db
from db.models.message import Message
from db.models.usage import Usage

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7752488661
BOT_USERNAME = "DialogSpyBotRobot"
GROQ_API_KEY = ""
GROQ_MODEL = "llama-3.1-8b-instant"

MEDIA_DIR = Path("media")
MEDIA_DIR.mkdir(exist_ok=True)

TEMP_DIR = Path("/tmp/temp_media")
TEMP_DIR.mkdir(exist_ok=True)

dp = Dispatcher()

WELCOME_IMAGE_PATH = MEDIA_DIR / "welcome.jpg"
TUTORIAL_VIDEO_PATH = MEDIA_DIR / "tutorial.mp4"

PREMIUM_EMOJI = {
    "ninja": "5454339064096366207",
    "question": "5382187118216879236",
    "plug": "5082539494926713909",
    "notsave": "5229056621988028983",
    "trash": "5408832111773757273",
    "lock": "5470060791883374114",
    "thinking": "5573473356579078196",
    "commands": "5864127571754489150"
}

YDL_OPTS = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'force_generic_extractor': False,
}

async def search_and_download_audio(query: str) -> tuple[str | None, str | None]:
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'extract_flat': False,
        'noplaylist': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            
            if not info or 'entries' not in info or not info['entries']:
                return None, None
            
            video = info['entries'][0]
            title = video.get('title', query)
            
            for f in os.listdir(temp_dir):
                if f.endswith(('.mp3', '.m4a', '.webm', '.opus', '.mp4')):
                    full_path = os.path.join(temp_dir, f)
                    if os.path.exists(full_path):
                        return full_path, title
            
            return None, None
            
    except Exception as e:
        print(f"Error downloading: {e}")
        try:
            shutil.rmtree(temp_dir)
        except:
            pass
        return None, None

def get_user_link(user_id: int = None, username: str = None, first_name: str = None) -> str:
    if first_name:
        display_name = first_name
    elif username:
        display_name = username
    else:
        display_name = "пользователь"
    
    if username:
        return f'<a href="https://t.me/{username}">{display_name}</a>'
    elif user_id:
        return f'<a href="tg://user?id={user_id}">{display_name}</a>'
    else:
        return display_name

def generate_diff_html(old_text: str, new_text: str) -> str:
    if old_text == new_text:
        return html_lib.escape(new_text)
    
    old_words = old_text.split()
    new_words = new_text.split()
    
    i = 0
    while i < len(old_words) and i < len(new_words) and old_words[i] == new_words[i]:
        i += 1
    
    j = 0
    while j < len(old_words) - i and j < len(new_words) - i and old_words[-(j+1)] == new_words[-(j+1)]:
        j += 1
    
    unchanged_start = ' '.join(old_words[:i]) if i > 0 else ''
    unchanged_end = ' '.join(old_words[len(old_words)-j:]) if j > 0 else ''
    
    old_changed = ' '.join(old_words[i:len(old_words)-j]) if i + j < len(old_words) else ''
    new_changed = ' '.join(new_words[i:len(new_words)-j]) if i + j < len(new_words) else ''
    
    result = []
    if unchanged_start:
        result.append(html_lib.escape(unchanged_start))
    
    if old_changed:
        result.append(f'<s>{html_lib.escape(old_changed)}</s>')
    
    if new_changed:
        result.append(f'<b>{html_lib.escape(new_changed)}</b>')
    
    if unchanged_end:
        result.append(html_lib.escape(unchanged_end))
    
    return ' '.join(result)

def get_welcome_keyboard() -> InlineKeyboardMarkup:
    copy_button = InlineKeyboardButton(
        text="Скопировать username",
        copy_text=CopyTextButton(text=f"@{BOT_USERNAME}"),
        style="primary"
    )
    
    connect_button = InlineKeyboardButton(
        text=f'Подключить',
        url="tg://settings/edit",
        style="success",
        icon_custom_emoji_id="5082539494926713909"
    )
    
    commands_button = InlineKeyboardButton(
        text=f'Доступные команды',
        callback_data="show_commands",
        style="default",
        icon_custom_emoji_id=PREMIUM_EMOJI["commands"]
    )
    
    example_button = InlineKeyboardButton(
        text="Демонстрация работы",
        callback_data="demo",
        style="danger",
        icon_custom_emoji_id="5305557136355370145"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [copy_button],
        [connect_button],
        [commands_button],
        [example_button]
    ])
    return keyboard

def get_welcome_text() -> str:
    return (
        f'Добро пожаловать!\n'
        f'🕵️‍♂️ <b>Этот бот создан, чтобы помогать вам в переписке.</b>\n\n'
        f'<i>Возможности бота:</i>\n'
        f'• Моментально пришлёт уведомление, если ваш собеседник изменит или удалит сообщение 🔔\n'
        f'• Скачает одноразовое (с таймером) фото или видео, которое пришлёт ваш собеседник '
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI["ninja"]}">🥷</tg-emoji>\n\n'
        f'<blockquote>'
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI["question"]}">❓</tg-emoji> Подключить бот:\n'
        f'1: Нажмите «Скопировать username»\n'
        f'2: Нажмите кнопку «<tg-emoji emoji-id="{PREMIUM_EMOJI["plug"]}">🔌</tg-emoji> Подключить»\n'
        f'3: Выберите "Автоматизация чатов"\n'
        f'4: В поле для ввода вставьте скопированный username'
        f'</blockquote>'
    )

def get_commands_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=".love", callback_data="cmd_love"),
            InlineKeyboardButton(text=".p", callback_data="cmd_p")
        ],
        [
            InlineKeyboardButton(text=".-7", callback_data="cmd_-7"),
            InlineKeyboardButton(text=".calc", callback_data="cmd_calc")
        ],
        [
            InlineKeyboardButton(text=".ai", callback_data="cmd_ai"),
            InlineKeyboardButton(text=".sm", callback_data="cmd_sm")
        ],
        [
            InlineKeyboardButton(text=".info", callback_data="cmd_info"),
            InlineKeyboardButton(text=".spam", callback_data="cmd_spam")
        ],
        [
            InlineKeyboardButton(text=".crash", callback_data="cmd_crash")
        ],
        [
            InlineKeyboardButton(text="« Назад", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_back_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="« Назад", callback_data="back_to_commands")
        ]
    ])
    return keyboard

@dp.message(CommandStart())
async def command_start_handler(message: MessageType) -> None:
    if WELCOME_IMAGE_PATH.exists():
        photo = FSInputFile(WELCOME_IMAGE_PATH)
        await message.answer_photo(
            photo=photo,
            caption=get_welcome_text(),
            reply_markup=get_welcome_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            text=get_welcome_text(),
            reply_markup=get_welcome_keyboard(),
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

@dp.message(Command("start"))
async def start_command_handler(message: MessageType) -> None:
    await command_start_handler(message)

@dp.callback_query()
async def handle_callback_query(callback: CallbackQuery):
    if callback.data == "show_commands":
        await callback.answer()
        
        caption = f'<b>Нажмите на кнопку чтобы узнать информацию о команде</b>'
        
        if WELCOME_IMAGE_PATH.exists():
            photo = FSInputFile(WELCOME_IMAGE_PATH)
            await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=get_commands_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=caption,
                reply_markup=get_commands_keyboard(),
                parse_mode=ParseMode.HTML
            )
        return
    
    if callback.data == "back_to_menu":
        await callback.answer()
        if WELCOME_IMAGE_PATH.exists():
            photo = FSInputFile(WELCOME_IMAGE_PATH)
            await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=get_welcome_text(),
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=get_welcome_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=get_welcome_text(),
                reply_markup=get_welcome_keyboard(),
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        return
    
    if callback.data == "back_to_commands":
        await callback.answer()
        caption = f'<b>Нажмите на кнопку чтобы узнать информацию о команде</b>'
        if WELCOME_IMAGE_PATH.exists():
            photo = FSInputFile(WELCOME_IMAGE_PATH)
            await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=get_commands_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=caption,
                reply_markup=get_commands_keyboard(),
                parse_mode=ParseMode.HTML
            )
        return
    
    commands_info = {
        "cmd_love": {
            "name": ".love",
            "desc": "Магическая анимация любви сердечками ❤️"
        },
        "cmd_info": {
            "name": ".info",
            "desc": "Показывает метаданные пользователя, на чьё сообщение вы ответили"
        },
        "cmd_-7": {
            "name": ".-7",
            "desc": "Анимация «1000-7»"
        },
        "cmd_sm": {
            "name": ".sm",
            "desc": "Найти и скачать трек с YouTube (пример: .sm Imagine Dragons Believer)"
        },
        "cmd_ai": {
            "name": ".ai",
            "desc": "Запрос к нейросети (лимиты: 10 запросов в минуту, 50 запросов в день)"
        },
        "cmd_p": {
            "name": ".p",
            "desc": "Анимация печатания текста"
        },
        "cmd_spam": {
            "name": ".spam",
            "desc": "Спам вашим сообщением (пример: .spam 10 привет)"
        },
        "cmd_crash": {
            "name": ".crash",
            "desc": "Крашит Telegram отправкой 20 стикеров"
        },
        "cmd_calc": {
            "name": ".calc",
            "desc": "Калькулятор (пример: .calc 2+2*3)"
        }
    }
    
    if callback.data in commands_info:
        await callback.answer()
        cmd_info = commands_info[callback.data]
        
        if callback.data == "cmd_sm":
            text = (
                f'<b>Команда:</b> <code>{cmd_info["name"]}</code>\n\n'
                f'<blockquote>{cmd_info["desc"]}</blockquote>\n\n'
                f'<b>Примеры:</b>\n'
                f'<code>.sm Bohemian Rhapsody</code>\n'
                f'<code>.sm Metallica Nothing Else Matters</code>\n'
                f'<code>.sm ЛСП Монетка</code>'
            )
        else:
            text = (
                f'<b>Команда:</b> <code>{cmd_info["name"]}</code>\n\n'
                f'<blockquote>{cmd_info["desc"]}</blockquote>'
            )
        
        if WELCOME_IMAGE_PATH.exists():
            photo = FSInputFile(WELCOME_IMAGE_PATH)
            await callback.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=text,
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=get_back_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=text,
                reply_markup=get_back_keyboard(),
                parse_mode=ParseMode.HTML
            )
        return
    
    if callback.data == "demo":
        await callback.answer()
        
        video1_path = MEDIA_DIR / "tutorial.mp4"
        video2_path = MEDIA_DIR / "tutorial2.mp4"
        video3_path = MEDIA_DIR / "tutorial3.mp4"
        video4_path = MEDIA_DIR / "tutorial4.mp4"
        
        missing = []
        if not video1_path.exists(): missing.append("tutorial.mp4")
        if not video2_path.exists(): missing.append("tutorial2.mp4")
        if not video3_path.exists(): missing.append("tutorial3.mp4")
        if not video4_path.exists(): missing.append("tutorial4.mp4")
        
        if missing:
            await callback.message.answer(f"❌ Отсутствуют видео:\n" + "\n".join(f"• {m}" for m in missing))
            return
        
        video1 = FSInputFile(video1_path)
        video2 = FSInputFile(video2_path)
        video3 = FSInputFile(video3_path)
        video4 = FSInputFile(video4_path)
        
        caption = (
            f'<b>Демонстрация работы бота</b>\n\n'
            f'<b>Видео 1:</b> Скачивание медиа с таймером\n'
            f'<b>Видео 2:</b> Уведомление об изменении сообщения собеседником\n'
            f'<b>Видео 3:</b> Уведомление об удалении сообщения собеседником\n'
            f'<b>Видео 4:</b> Использование команд в диалоге с пользователем\n\n'
            f'<b>Бот работает даже когда вы оффлайн!</b>'
        )
        
        media_group = [
            InputMediaVideo(media=video1, caption=caption, parse_mode=ParseMode.HTML),
            InputMediaVideo(media=video2),
            InputMediaVideo(media=video3),
            InputMediaVideo(media=video4)
        ]
        
        try:
            await callback.message.answer_media_group(media=media_group)
        except Exception as e:
            await callback.message.answer(f"❌ Ошибка при отправке видео: {e}")
        return

def check_user_limit(user_id: int) -> tuple[bool, str]:
    session = SQLSession(db.engine)
    
    now = datetime.now()
    minute_ago = now - timedelta(minutes=1)
    day_ago = now - timedelta(days=1)
    
    minute_count = session.exec(
        select(func.count(Usage.id)).where(
            Usage.user_id == user_id,
            Usage.request_time >= minute_ago,
            Usage.type == "groq"
        )
    ).first() or 0
    
    if minute_count >= 10:
        session.close()
        return False, "<b>Превышен лимит: 10 запросов в минуту. Подождите немного...</b>"
    
    day_count = session.exec(
        select(func.count(Usage.id)).where(
            Usage.user_id == user_id,
            Usage.request_time >= day_ago,
            Usage.type == "groq"
        )
    ).first() or 0
    
    if day_count >= 50:
        session.close()
        return False, "<b>Превышен дневной лимит: 50 запросов. Попробуйте завтра...</b>"
    
    session.close()
    return True, ""

def add_usage_record(user_id: int, usage_type: str = "groq"):
    session = SQLSession(db.engine)
    usage = Usage(user_id=user_id, type=usage_type)
    session.add(usage)
    session.commit()
    session.close()

async def get_groq_response(query: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": """Ты полезный и умный ассистент. Отвечай на том языке, на котором тебе задали вопрос!

Используй форматирование для улучшения читаемости ответа:
**жирный** - для важных терминов, ключевых слов, заголовков
*курсив* - для выделения мыслей, цитат
`код` - для команд, путей, имён файлов
~~зачёркнутый~~ - для исправлений
[ссылки](url) - для ссылок
||спойлер|| - для скрытого текста

ВАЖНЫЕ ПРАВИЛА:
1. НЕ создавай вложенное форматирование
2. Используй ТОЛЬКО один уровень форматирования
3. Для списков используй обычные дефисы (-) или цифры (1., 2.)
4. Не используй таблицы и сложные конструкции
5. Пиши формулы ОБЫЧНЫМ ТЕКСТОМ, например: x1 + x2 = -b/a
6. Каждый тег должен быть правильно закрыт"""},
                        {"role": "user", "content": query}
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.7
                }
            ) as resp:
                data = await resp.json()
                if "choices" in data:
                    return data["choices"][0]["message"]["content"]
                else:
                    error_msg = data.get("error", {}).get("message", "Неизвестная ошибка")
                    return f"<b>Ошибка Groq:</b> {error_msg}"
    except Exception as e:
        return f"<b>Ошибка:</b> {str(e)}"

def markdown_to_html(text: str) -> str:
    text = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', r'\1/\2', text)
    text = re.sub(r'\\sqrt\{([^}]*)\}', r'√(\1)', text)
    text = re.sub(r'\\sqrt([a-zA-Z0-9])', r'√\1', text)
    text = text.replace(r'\pm', '±')
    text = text.replace(r'\times', '×')
    text = text.replace(r'\cdot', '·')
    text = text.replace(r'\left', '')
    text = text.replace(r'\right', '')
    text = text.replace(r'\alpha', 'α')
    text = text.replace(r'\beta', 'β')
    text = text.replace(r'\gamma', 'γ')
    text = text.replace(r'\delta', 'δ')
    text = text.replace(r'\pi', 'π')
    text = text.replace(r'\infty', '∞')
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    text = re.sub(r'\$\$(.*?)\$\$', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\\((.*?)\\\)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\$(.*?)\$', r'\1', text)
    text = re.sub(r'\{', '', text)
    text = re.sub(r'\}', '', text)
    text = html_lib.escape(text)
    text = re.sub(r'\|\|(.*?)\|\|', r'<tg-spoiler>\1</tg-spoiler>', text)
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    
    def remove_nested_tags(text, outer_tag, inner_tag):
        pattern = f'<{outer_tag}>.*?<{inner_tag}>.*?</{inner_tag}>.*?</{outer_tag}>'
        while re.search(pattern, text, re.DOTALL):
            text = re.sub(
                f'<{outer_tag}>(.*?)<{inner_tag}>(.*?)</{inner_tag}>(.*?)</{outer_tag}>',
                f'<{outer_tag}>\\1\\2\\3</{outer_tag}>',
                text,
                flags=re.DOTALL
            )
        return text
    
    tags = ['b', 'i', 's', 'code', 'tg-spoiler']
    for outer in tags:
        for inner in tags:
            if outer != inner:
                text = remove_nested_tags(text, outer, inner)
    
    text = re.sub(r'<(b|i|s|code|tg-spoiler|blockquote|a)>\s*</\1>', '', text)
    
    for tag in ['b', 'i', 's', 'code', 'tg-spoiler', 'blockquote']:
        open_count = len(re.findall(f'<{tag}>', text))
        close_count = len(re.findall(f'</{tag}>', text))
        
        if open_count > close_count:
            text += f'</{tag}>' * (open_count - close_count)
        elif close_count > open_count:
            for _ in range(close_count - open_count):
                text = re.sub(f'</{tag}>', '', text, 1)
    
    return text

@dp.business_message()
async def handle_business_message(message: MessageType) -> None:
    session = SQLSession(db.engine)
    
    try:
        feedback = message.business_connection_id
        business_connection = await message.bot.get_business_connection(feedback)
        user_chat_id = business_connection.user.id
        
        if message.from_user.id != user_chat_id:
            await save_message_to_archive(message, user_chat_id, session)
            session.close()
            return
        
        text = message.text
        if not text:
            session.close()
            return
        
        if text == ".ai":
            if not message.reply_to_message:
                await message.edit_text(text="<b>Ответьте на сообщение или напишите запрос после .ai</b>")
                session.close()
                return
            
            user_id = message.from_user.id
            
            can_proceed, error_msg = check_user_limit(user_id)
            if not can_proceed:
                await message.edit_text(text=error_msg, parse_mode=ParseMode.HTML)
                session.close()
                return
            
            replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
            if not replied_text:
                await message.edit_text(text="<b>На сообщение без текста нельзя ответить</b>")
                session.close()
                return
            
            query = f"Ответь на сообщение: {replied_text}"
            
            await message.edit_text(
                f'<tg-emoji emoji-id="{PREMIUM_EMOJI["thinking"]}">✨</tg-emoji> <b>Думаю...</b>',
                parse_mode=ParseMode.HTML
            )
            
            response = await get_groq_response(query)
            
            add_usage_record(user_id, "groq")
            
            html_response = markdown_to_html(response)
            
            await message.edit_text(
                text=html_response,
                parse_mode=ParseMode.HTML
            )
            session.close()
            return
        
        if text.startswith(".ai "):
            user_id = message.from_user.id
            
            can_proceed, error_msg = check_user_limit(user_id)
            if not can_proceed:
                await message.edit_text(text=error_msg, parse_mode=ParseMode.HTML)
                session.close()
                return
            
            query = text[4:].strip()
            if not query:
                await message.edit_text(text="Введите запрос после .ai")
                session.close()
                return
            
            if message.reply_to_message:
                replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
                if replied_text:
                    query = f"Ответь на сообщение: {replied_text}\n\nВопрос: {query}"
            
            await message.edit_text(
                f'<tg-emoji emoji-id="{PREMIUM_EMOJI["thinking"]}">✨</tg-emoji> <b>Думаю...</b>',
                parse_mode=ParseMode.HTML
            )
            
            response = await get_groq_response(query)
            
            add_usage_record(user_id, "groq")
            
            html_response = markdown_to_html(response)
            
            await message.edit_text(
                text=html_response,
                parse_mode=ParseMode.HTML
            )
            session.close()
            return
        
        if text.startswith(".p "):
            command_args = text[3:].strip()
            if not command_args:
                await message.edit_text(text="Введите аргумент.")
                session.close()
                return
            
            loading = ['▌', " "]
            assembled_text = ""
            character_list = []
            
            for char in command_args:
                character_list.append(char)
                assembled_text = "".join(character_list)
                
                for frame in loading:
                    animated_text = f"{assembled_text}{frame}"
                    if message.text != animated_text:
                        try:
                            await message.edit_text(text=animated_text)
                        except Exception:
                            pass
                    await asyncio.sleep(0.15)
            session.close()
            return
        
        if text == ".love":
            arr = ["❤️", "🧡", "💛", "💚", "💙", "💜", "🤎", "🖤", "💖"]
            h = "🤍"
            first = ""
            for i in "".join(
                    [h * 9, "\n", h * 2, arr[0] * 2, h, arr[0] * 2, h * 2, "\n", h, arr[0] * 7, h, "\n", h, arr[0] * 7, h, "\n",
                    h, arr[0] * 7, h, "\n", h * 2, arr[0] * 5, h * 2, "\n", h * 3, arr[0] * 3, h * 3, "\n", h * 4, arr[0],
                    h * 4]).split("\n"):
                first += i + "\n"
                await message.edit_text(first)
                await asyncio.sleep(0.3)
            for i in arr:
                await message.edit_text("".join(
                    [h * 9, "\n", h * 2, i * 2, h, i * 2, h * 2, "\n", h, i * 7, h, "\n", h, i * 7, h, "\n", h, i * 7, h, "\n",
                    h * 2, i * 5, h * 2, "\n", h * 3, i * 3, h * 3, "\n", h * 4, i, h * 4, "\n", h * 9]))
                await asyncio.sleep(0.35)
            for _ in range(8):
                rand = random.choices(arr, k=34)
                await message.edit_text("".join(
                    [h * 9, "\n", h * 2, rand[0], rand[1], h, rand[2], rand[3], h * 2, "\n", h, rand[4], rand[5], rand[6],
                    rand[7], rand[8], rand[9], rand[10], h, "\n", h, rand[11], rand[12], rand[13], rand[14], rand[15],
                    rand[16], rand[17], h, "\n", h, rand[18], rand[19], rand[20], rand[21], rand[22], rand[23], rand[24], h,
                    "\n", h * 2, rand[25], rand[26], rand[27], rand[28], rand[29], h * 2, "\n", h * 3, rand[30], rand[31],
                    rand[32], h * 3, "\n", h * 4, rand[33], h * 4, "\n", h * 9]))
                await asyncio.sleep(0.35)
            fourth = "".join(
                [h * 9, "\n", h * 2, arr[0] * 2, h, arr[0] * 2, h * 2, "\n", h, arr[0] * 7, h, "\n", h, arr[0] * 7, h, "\n", h,
                arr[0] * 7, h, "\n", h * 2, arr[0] * 5, h * 2, "\n", h * 3, arr[0] * 3, h * 3, "\n", h * 4, arr[0], h * 4,
                "\n", h * 9])
            await message.edit_text(fourth)
            for _ in range(47):
                fourth = fourth.replace("🤍", "❤️", 1)
                await message.edit_text(fourth)
                await asyncio.sleep(0.25)
            for i in range(8):
                await message.edit_text((arr[0] * (8 - i) + "\n") * (8 - i))
                await asyncio.sleep(0.4)
            for i in ["Я", "Я ❤️", "Я ❤️ ТЕБЯ"]:
                await message.edit_text(f"<b>{i}</b>", parse_mode="HTML")
                await asyncio.sleep(0.5)
            session.close()
            return
        
        if text == ".info":
            if not message.reply_to_message:
                await message.edit_text(text="Ответьте на сообщение!")
                session.close()
                return
            resp = f"""
<blockquote><i>Metadata:</i> 
<b>├</b> <tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> User id: <b>{message.reply_to_message.from_user.id}</b>
<b>├</b> <tg-emoji emoji-id="5258073068852485953">🆔</tg-emoji> Username: <b>{f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else "Нет"}</b>
<b>└</b> <tg-emoji emoji-id="5253959125838090076">👁</tg-emoji> Full Name: <b>{message.reply_to_message.from_user.full_name}</b>
</blockquote>
            """
            await message.edit_text(text=resp, parse_mode='html')
            session.close()
            return
        
        if text == ".-7":
            a = 1000
            b = 7
            while a > 6:
                c = a - b
                caption = f"""<b>「{a} ➖ {b} = {c}」</b>

<i>Кошмар не уходит, числа остаются.</i>
    
<tg-emoji emoji-id="5318757666800031348">⛓️</tg-emoji> <b>“Числа говорят правду.”</b> <tg-emoji emoji-id="5269535069550162819">🩸</tg-emoji>
    
<tg-emoji emoji-id="5289982210550540252">🤬</tg-emoji> <i>Даже если жизнь исчезает... Ответ один.</i>
<tg-emoji emoji-id="5213333038775151099">🤍</tg-emoji> {c} <tg-emoji emoji-id="5213333038775151099">🤍</tg-emoji>

<tg-emoji emoji-id="5318757666800031348">⛓️</tg-emoji> <b>『Ты готов к этому?』</b> <tg-emoji emoji-id="5269535069550162819">🩸</tg-emoji>"""
                await message.edit_text(text=caption, parse_mode='HTML')
                await asyncio.sleep(0.3)
                a = c
            await message.edit_text(text="<tg-emoji emoji-id='5289923343728781033'>😔</tg-emoji> <b>1000-7, я умер прости</b>", parse_mode='HTML')
            session.close()
            return
        
        if text.startswith(".sm "):
            query = text[4:].strip()
            
            if not query:
                await message.edit_text(
                    text="<b>Использование:</b> <code>.sm [название трека]</code>\n\nПример: <code>.sm Imagine Dragons Believer</code>",
                    parse_mode=ParseMode.HTML
                )
                session.close()
                return
            
            await message.edit_text(
                text=f'🔍 <b>Ищу трек:</b> {html_lib.escape(query)}\n\n<tg-emoji emoji-id="{PREMIUM_EMOJI["thinking"]}">⏳</tg-emoji> Поиск на YouTube...',
                parse_mode=ParseMode.HTML
            )
            
            await asyncio.sleep(0.5)
            
            await message.edit_text(
                text=f'🔍 <b>Ищу трек:</b> {html_lib.escape(query)}\n\n<tg-emoji emoji-id="{PREMIUM_EMOJI["ninja"]}">🎵</tg-emoji> Нашел! Скачиваю аудио...',
                parse_mode=ParseMode.HTML
            )
            
            audio_path, title = await search_and_download_audio(query)
            
            if not audio_path or not os.path.exists(audio_path):
                await message.edit_text(
                    text=f'❌ <b>Не удалось найти или скачать трек</b>\n\nЗапрос: <code>{html_lib.escape(query)}</code>\n\nПопробуйте изменить запрос или проверьте написание.',
                    parse_mode=ParseMode.HTML
                )
                session.close()
                return
            
            await message.edit_text(
                text=f'✅ <b>Трек готов!</b>\n\n🎵 {html_lib.escape(title)}',
                parse_mode=ParseMode.HTML
            )
            
            try:
                await message.bot.send_audio(
                    chat_id=user_chat_id,
                    audio=FSInputFile(audio_path),
                    caption=f'🎵 <b>Нашёл для вас:</b> {html_lib.escape(title)}',
                    parse_mode=ParseMode.HTML
                )
                
                await message.delete()
                
            except Exception as e:
                await message.edit_text(
                    text=f'❌ <b>Ошибка при отправке</b>\n\n{html_lib.escape(str(e))}',
                    parse_mode=ParseMode.HTML
                )
            finally:
                try:
                    os.remove(audio_path)
                    temp_dir = os.path.dirname(audio_path)
                    shutil.rmtree(temp_dir)
                except:
                    pass
            
            session.close()
            return
        
        if text.startswith(".spam "):
            parts = text.split(" ", 2)
            if len(parts) < 3:
                await message.edit_text(text="<b>Использование:</b> <code>.spam [количество] [текст]</code>\n\nПример: <code>.spam 10 привет</code>", parse_mode=ParseMode.HTML)
                session.close()
                return
            
            try:
                count = int(parts[1])
                spam_text = parts[2]
            except ValueError:
                await message.edit_text(text="<b>Ошибка:</b> количество должно быть числом", parse_mode=ParseMode.HTML)
                session.close()
                return
            
            if count < 1 or count > 100:
                await message.edit_text(text="<b>Ошибка:</b> количество должно быть от 1 до 100", parse_mode=ParseMode.HTML)
                session.close()
                return
            
            await message.edit_text(text="⁧")
            
            for _ in range(count):
                await message.answer(spam_text)
                await asyncio.sleep(0.05)
            session.close()
            return
        
        if text == ".crash":
            await message.edit_text(text="⁧")
            
            sticker_id = "CAACAgIAAxkBAAEEzMRnoz32nTWuaO2sbA9nigm0UBcuewACJGsAAioMGEkNNybEUwJtqjYE"
            
            for _ in range(20):
                await message.answer_sticker(sticker=sticker_id)
                await asyncio.sleep(0.05)
            session.close()
            return
        
        if text.startswith(".calc "):
            expression = text[6:].strip()
            try:
                allowed = set("0123456789+-*/(). ")
                if not all(c in allowed for c in expression):
                    await message.edit_text("<b>Используйте только цифры и операторы + - * / ( )</b>")
                    session.close()
                    return
                
                result = eval(expression)
                await message.edit_text(
                    f"🧮 <b>Калькулятор</b>\n\n"
                    f"<code>{html_lib.escape(expression)}</code> = <b>{result}</b>"
                )
            except:
                await message.edit_text("<b>Ошибка в выражении</b>")
            session.close()
            return
        
        if message.reply_to_message:
            reply_to = message.reply_to_message
            if reply_to.from_user.id != user_chat_id and reply_to.has_protected_content:
                await save_auto_delete_media(message, reply_to, user_chat_id)
        
        session.close()
        
    except Exception as e:
        print(f"Error in business_message: {e}")
        session.close()

async def save_message_to_archive(message: MessageType, user_chat_id: int, session: SQLSession):
    unique_id = f"{message.chat.id}_{message.message_id}"
    
    existing = session.exec(
        select(Message).where(Message.unique_id == unique_id)
    ).first()
    
    if existing:
        return
    
    user_id = message.from_user.id
    username = message.from_user.username if message.from_user.username else None
    full_name = message.from_user.full_name if message.from_user.full_name else "пользователь"
    
    if message.text:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.text,
            caption=None,
            type="text"
        )
        session.add(msg)
        session.commit()
    
    elif message.photo:
        largest_photo = message.photo[-1]
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=largest_photo.file_id,
            caption=message.caption if message.caption else None,
            type="photo"
        )
        session.add(msg)
        session.commit()
    
    elif message.video:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.video.file_id,
            caption=message.caption if message.caption else None,
            type="video"
        )
        session.add(msg)
        session.commit()
    
    elif message.video_note:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.video_note.file_id,
            caption=None,
            type="video_note"
        )
        session.add(msg)
        session.commit()
    
    elif message.voice:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.voice.file_id,
            caption=message.caption if message.caption else None,
            type="voice"
        )
        session.add(msg)
        session.commit()
    
    elif message.audio:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.audio.file_id,
            caption=message.caption if message.caption else None,
            type="audio"
        )
        session.add(msg)
        session.commit()
    
    elif message.document:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.document.file_id,
            caption=message.caption if message.caption else None,
            type="document"
        )
        session.add(msg)
        session.commit()
    
    elif message.animation:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.animation.file_id,
            caption=message.caption if message.caption else None,
            type="animation"
        )
        session.add(msg)
        session.commit()
    
    elif message.sticker:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=message.sticker.file_id,
            caption=None,
            type="sticker"
        )
        session.add(msg)
        session.commit()
    
    elif message.location:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content="📍 Геопозиция",
            caption=message.caption if message.caption else None,
            type="location",
            latitude=message.location.latitude,
            longitude=message.location.longitude
        )
        session.add(msg)
        session.commit()
    
    elif message.contact:
        contact_user_id = message.contact.user_id if message.contact.user_id else None
        contact_first_name = message.contact.first_name
        contact_phone = message.contact.phone_number
        
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
            from_user_id=user_id,
            from_username=username,
            from_full_name=full_name,
            content=f"👤 Контакт: {contact_first_name} {message.contact.last_name or ''} ({contact_phone})",
            caption=None,
            type="contact",
            contact_user_id=contact_user_id,
            contact_first_name=contact_first_name,
            contact_phone=contact_phone
        )
        session.add(msg)
        session.commit()

async def save_auto_delete_media(message: MessageType, reply_to: MessageType, user_chat_id: int):
    user_link = get_user_link(reply_to.from_user.id, reply_to.from_user.username, reply_to.from_user.first_name)
    
    file_id = None
    media_type = None
    
    if reply_to.photo:
        file_id = reply_to.photo[-1].file_id
        media_type = "photo"
    elif reply_to.video:
        file_id = reply_to.video.file_id
        media_type = "video"
    elif reply_to.video_note:
        file_id = reply_to.video_note.file_id
        media_type = "video_note"
    elif reply_to.voice:
        file_id = reply_to.voice.file_id
        media_type = "voice"
    elif reply_to.audio:
        file_id = reply_to.audio.file_id
        media_type = "audio"
    elif reply_to.document:
        file_id = reply_to.document.file_id
        media_type = "document"
    elif reply_to.animation:
        file_id = reply_to.animation.file_id
        media_type = "animation"
    elif reply_to.sticker:
        file_id = reply_to.sticker.file_id
        media_type = "sticker"
    
    if not file_id:
        await message.bot.send_message(
            chat_id=user_chat_id,
            text=f'<tg-emoji emoji-id="{PREMIUM_EMOJI["notsave"]}">❌</tg-emoji> <b>Не удалось сохранить сгорающее сообщение от {user_link}</b>',
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    
    try:
        file = await message.bot.get_file(file_id)
        
        ext_map = {
            "photo": ".jpg",
            "video": ".mp4",
            "video_note": ".mp4",
            "voice": ".ogg",
            "audio": ".mp3",
            "document": ".bin",
            "animation": ".gif",
            "sticker": ".webp"
        }
        ext = ext_map.get(media_type, ".bin")
        file_name = f"{uuid4()}{ext}"
        file_path = TEMP_DIR / file_name
        
        await message.bot.download_file(file.file_path, file_path)
        
        caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["ninja"]}">🥷</tg-emoji> <b>Сохранено сгорающее сообщение от {user_link}</b>'
        
        if media_type == "photo":
            await message.bot.send_photo(
                chat_id=user_chat_id,
                photo=FSInputFile(file_path),
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        elif media_type == "video":
            await message.bot.send_video(
                chat_id=user_chat_id,
                video=FSInputFile(file_path),
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        elif media_type == "video_note":
            await message.bot.send_video_note(
                chat_id=user_chat_id,
                video_note=FSInputFile(file_path)
            )
            await message.bot.send_message(
                chat_id=user_chat_id,
                text=caption,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        elif media_type == "voice":
            await message.bot.send_voice(
                chat_id=user_chat_id,
                voice=FSInputFile(file_path),
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        elif media_type == "audio":
            await message.bot.send_audio(
                chat_id=user_chat_id,
                audio=FSInputFile(file_path),
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        elif media_type == "sticker":
            await message.bot.send_sticker(
                chat_id=user_chat_id,
                sticker=FSInputFile(file_path)
            )
            await message.bot.send_message(
                chat_id=user_chat_id,
                text=caption,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        elif media_type in ["document", "animation"]:
            await message.bot.send_document(
                chat_id=user_chat_id,
                document=FSInputFile(file_path),
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        
        os.remove(file_path)
        
    except Exception as e:
        await message.bot.send_message(
            chat_id=user_chat_id,
            text=f'<tg-emoji emoji-id="{PREMIUM_EMOJI["notsave"]}">❌</tg-emoji> <b>Не удалось сохранить сгорающее сообщение от {user_link}</b>',
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    finally:
        if TEMP_DIR.exists():
            for f in TEMP_DIR.iterdir():
                try:
                    f.unlink()
                except:
                    pass

@dp.business_connection()
async def handle_business_connection(business_connection: BusinessConnection):
    try:
        if business_connection.is_enabled:
            if TUTORIAL_VIDEO_PATH.exists():
                video = FSInputFile(TUTORIAL_VIDEO_PATH)
                await business_connection.bot.send_video(
                    chat_id=business_connection.user_chat_id,
                    video=video,
                    caption=(
                        f'✅ <b>Бот успешно привязан</b>\n\n'
                        f'<i>Как использовать?</i>\n'
                        f'➖ Если ваш собеседник удалит сообщение, бот сразу же пришлёт вам копию этого сообщения '
                        f'<b>(работает только с сообщениями, которые отправлены ПОСЛЕ подключения бота)</b>\n'
                        f'➖ Чтобы скачивать фото/видео с таймером, необходимо ответить на них в диалоге с вашим собеседником '
                        f'<b>(на видео</b> ☝️ <b>показан пример)</b> любым сообщением '
                        f'<b>(ДО ОТКРЫТИЯ, ЭТО ВАЖНО!)</b>\n'
                        f'➖ Доступные команды: <code>.ai</code>, <code>.p</code>, <code>.love</code>, <code>.info</code>, <code>.-7</code>, <code>.sm</code>, <code>.spam</code>, <code>.crash</code>, <code>.calc</code>\n'
                        f'<blockquote>❗ Бот работает только с <b>НОВЫМИ</b> сообщениями, которые вы получили после подключения бота</blockquote>'
                    ),
                    parse_mode=ParseMode.HTML
                )
            else:
                await business_connection.bot.send_message(
                    chat_id=business_connection.user_chat_id,
                    text=(
                        f'✅ <b>Бот успешно привязан</b>\n\n'
                        f'<i>Как использовать?</i>\n'
                        f'➖ Если ваш собеседник удалит сообщение, бот сразу же пришлёт вам копию этого сообщения '
                        f'<b>(работает только с сообщениями, которые отправлены ПОСЛЕ подключения бота)</b>\n'
                        f'➖ Чтобы скачивать фото/видео с таймером, необходимо ответить на них в диалоге с вашим собеседником '
                        f'<b>(на видео</b> ☝️ <b>показан пример)</b> любым сообщением '
                        f'<b>(ДО ОТКРЫТИЯ, ЭТО ВАЖНО!)</b>\n'
                        f'➖ Доступные команды: <code>.ai</code>, <code>.p</code>, <code>.love</code>, <code>.info</code>, <code>.-7</code>, <code>.sm</code>, <code>.spam</code>, <code>.crash</code>, <code>.calc</code>\n'
                        f'<blockquote>❗ Бот работает только с <b>НОВЫМИ</b> сообщениями, которые вы получили после подключения бота</blockquote>'
                    ),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
    except Exception as e:
        print(f"Error in business_connection: {e}")

@dp.edited_business_message()
async def handle_edited_business_message(message: MessageType) -> None:
    session = SQLSession(db.engine)
    
    try:
        business_connection = await message.bot.get_business_connection(message.business_connection_id)
        user_chat_id = business_connection.user_chat_id
        
        if message.from_user.id == user_chat_id:
            session.close()
            return
        
        unique_id = f"{message.chat.id}_{message.message_id}"
        old_msg = session.exec(
            select(Message).where(Message.unique_id == unique_id)
        ).first()
        
        if not old_msg:
            session.close()
            return
        
        old_text = old_msg.content
        new_text = message.text
        
        if old_text != new_text:
            old_msg.content = new_text
            session.commit()
        
        if old_text != new_text:
            user_link = get_user_link(message.from_user.id, message.from_user.username, message.from_user.first_name)
            
            diff_html = generate_diff_html(old_text, new_text)
            
            edit_text = (
                f'<tg-emoji emoji-id="{PREMIUM_EMOJI["lock"]}">🔏</tg-emoji> {user_link} изменил(а) сообщение:\n\n'
                f"<b>Старый текст:</b>\n"
                f"<blockquote>{html_lib.escape(old_text)}</blockquote>\n\n"
                f"<b>Новый текст:</b>\n"
                f"<blockquote>{html_lib.escape(new_text)}</blockquote>\n\n"
                f"<b>Изменилось:</b>\n"
                f"<blockquote>{diff_html}</blockquote>\n\n"
                f'<i>powered by @DialogSpyBotRobot</i>'
            )
            
            await message.bot.send_message(
                chat_id=user_chat_id,
                text=edit_text,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
            
    except Exception as e:
        print(f"Error in edited_business_message: {e}")
    finally:
        session.close()

@dp.deleted_business_messages()
async def handle_business_message_deleted(deleted_messages: BusinessMessagesDeleted):
    session = SQLSession(db.engine)
    
    try:
        business_connection = await deleted_messages.bot.get_business_connection(
            deleted_messages.business_connection_id
        )
        user_chat_id = business_connection.user_chat_id
        
        for message_id in deleted_messages.message_ids:
            unique_id = f"{deleted_messages.chat.id}_{message_id}"
            msg = session.exec(
                select(Message).where(Message.unique_id == unique_id)
            ).first()
            
            if not msg:
                continue
            
            user_link = get_user_link(msg.from_user_id, msg.from_username, msg.from_full_name)
            
            if msg.type == "text":
                text = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) сообщение\n\n<blockquote>{html_lib.escape(msg.content)}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            
            elif msg.type == "photo":
                if msg.caption:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) фото\n\n<blockquote>{html_lib.escape(msg.caption)}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                else:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) фото\n\n<i>powered by @DialogSpyBotRobot</i>'
                sent_msg = await deleted_messages.bot.send_photo(
                    chat_id=user_chat_id,
                    photo=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "video":
                if msg.caption:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) видео\n\n<blockquote>{html_lib.escape(msg.caption)}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                else:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) видео\n\n<i>powered by @DialogSpyBotRobot</i>'
                sent_msg = await deleted_messages.bot.send_video(
                    chat_id=user_chat_id,
                    video=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "video_note":
                sent_msg = await deleted_messages.bot.send_video_note(
                    chat_id=user_chat_id,
                    video_note=msg.content
                )
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) видео-кружок\n\n<i>powered by @DialogSpyBotRobot</i>',
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=sent_msg.message_id,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                
            elif msg.type == "voice":
                if msg.caption:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) голосовое сообщение\n\n<blockquote>{html_lib.escape(msg.caption)}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                else:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) голосовое сообщение\n\n<i>powered by @DialogSpyBotRobot</i>'
                sent_msg = await deleted_messages.bot.send_voice(
                    chat_id=user_chat_id,
                    voice=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "audio":
                if msg.caption:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) аудио\n\n<blockquote>{html_lib.escape(msg.caption)}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                else:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) аудио\n\n<i>powered by @DialogSpyBotRobot</i>'
                sent_msg = await deleted_messages.bot.send_audio(
                    chat_id=user_chat_id,
                    audio=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "sticker":
                sent_msg = await deleted_messages.bot.send_sticker(
                    chat_id=user_chat_id,
                    sticker=msg.content
                )
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) стикер\n\n<i>powered by @DialogSpyBotRobot</i>',
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=sent_msg.message_id,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                
            elif msg.type == "document":
                if msg.caption:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) файл\n\n<blockquote>{html_lib.escape(msg.caption)}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                else:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) файл\n\n<i>powered by @DialogSpyBotRobot</i>'
                sent_msg = await deleted_messages.bot.send_document(
                    chat_id=user_chat_id,
                    document=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "animation":
                if msg.caption:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) гифку\n\n<blockquote>{html_lib.escape(msg.caption)}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                else:
                    caption = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) гифку\n\n<i>powered by @DialogSpyBotRobot</i>'
                sent_msg = await deleted_messages.bot.send_animation(
                    chat_id=user_chat_id,
                    animation=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "location":
                location_msg = await deleted_messages.bot.send_location(
                    chat_id=user_chat_id,
                    latitude=msg.latitude,
                    longitude=msg.longitude
                )
                text = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) геопозицию\n\n<i>powered by @DialogSpyBotRobot</i>'
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=location_msg.message_id,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                
            elif msg.type == "contact":
                if msg.contact_user_id:
                    contact_link = get_user_link(msg.contact_user_id, None, msg.contact_first_name or "контакт")
                    contact_text = f"👤 <b>Контакт:</b> {contact_link} ({msg.contact_phone})"
                else:
                    contact_text = msg.content
                
                text = f'<tg-emoji emoji-id="{PREMIUM_EMOJI["trash"]}">🗑</tg-emoji> {user_link} удалил(а) контакт\n\n<blockquote>{contact_text}</blockquote>\n\n<i>powered by @DialogSpyBotRobot</i>'
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                        
    except Exception as e:
        print(f"Error in deleted_business_messages: {e}")
    finally:
        session.close()

async def main() -> None:
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    db.init()
    asyncio.run(main())