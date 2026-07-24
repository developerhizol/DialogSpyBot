import asyncio
import logging
import sys
import os
import re
from pathlib import Path
from uuid import uuid4
from datetime import datetime
import aiohttp

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message as MessageType
from aiogram.types import BusinessMessagesDeleted, FSInputFile, BusinessConnection
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.types import CopyTextButton, LinkPreviewOptions
from sqlmodel import Session as SQLSession
from sqlmodel import select

import db
from db.models.message import Message

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = "DialogSpyBotRobot"
ADMIN_ID = 7752488661
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
    "plug": "5269312693323469565"
}


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
        return html.quote(new_text)
    
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
        result.append(html.quote(unchanged_start))
    
    if old_changed:
        result.append(f'<s>{html.quote(old_changed)}</s>')
    
    if new_changed:
        result.append(f'<b>{html.quote(new_changed)}</b>')
    
    if unchanged_end:
        result.append(html.quote(unchanged_end))
    
    return ' '.join(result)


def get_welcome_keyboard() -> InlineKeyboardMarkup:
    copy_button = InlineKeyboardButton(
        text="Скопировать username",
        copy_text=CopyTextButton(text=f"@{BOT_USERNAME}")
    )
    
    connect_button = InlineKeyboardButton(
        text=f'<tg-emoji emoji-id="{PREMIUM_EMOJI["plug"]}">🔌</tg-emoji> Подключить',
        callback_data="connect_bot"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [copy_button],
        [connect_button]
    ])
    return keyboard


def get_connect_keyboard() -> InlineKeyboardMarkup:
    copy_button = InlineKeyboardButton(
        text="Скопировать username",
        copy_text=CopyTextButton(text=f"@{BOT_USERNAME}")
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [copy_button]
    ])
    return keyboard


def get_welcome_text() -> str:
    return (
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI["ninja"]}">🥷</tg-emoji> Добро пожаловать!\n\n'
        f'🕵️‍♂️ <b>Этот бот создан, чтобы помогать вам в переписке.</b>\n\n'
        f'<i>Возможности бота:</i>\n'
        f'• Моментально пришлёт уведомление, если ваш собеседник изменит или удалит сообщение 🔔\n'
        f'• Скачает одноразовое (с таймером) фото или видео, которое пришлёт ваш собеседник '
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI["ninja"]}">🥷</tg-emoji>\n\n'
        f'<blockquote>'
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI["question"]}">❓</tg-emoji> Подключить бот:\n'
        f'1: Нажмите «Скопировать username»\n'
        f'2: Нажмите кнопку '
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI["plug"]}">🔌</tg-emoji> Подключить\n'
        f'3: Выберите "Автоматизация чатов"\n'
        f'4: В поле для ввода вставьте скопированный username'
        f'</blockquote>'
    )


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
            parse_mode=ParseMode.HTML
        )


@dp.message(Command("start"))
async def start_command_handler(message: MessageType) -> None:
    await command_start_handler(message)


@dp.callback_query()
async def handle_callback_query(callback: CallbackQuery):
    if callback.data == "connect_bot":
        await callback.message.answer(
            text=get_welcome_text(),
            reply_markup=get_connect_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()


async def save_message_to_archive(message: MessageType, user_chat_id: int, session: SQLSession):
    unique_id = f"{message.chat.id}_{message.message_id}"
    
    existing = session.exec(
        select(Message).where(Message.unique_id == unique_id)
    ).first()
    
    if existing:
        return
    
    username = message.from_user.username if message.from_user.username else None
    full_name = message.from_user.full_name if message.from_user.full_name else username or "пользователь"
    
    if message.text:
        msg = Message(
            unique_id=unique_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_chat_id,
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
            from_username=username,
            from_full_name=full_name,
            content=message.sticker.file_id,
            caption=None,
            type="sticker"
        )
        session.add(msg)
        session.commit()


async def save_auto_delete_media(message: MessageType, reply_to: MessageType, user_chat_id: int):
    user_link = get_user_link(
        reply_to.from_user.id,
        reply_to.from_user.username,
        reply_to.from_user.first_name
    )
    
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
            text=f"❌ Не удалось сохранить сгорающее сообщение от {user_link}",
            parse_mode=ParseMode.HTML
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
        
        caption = f"✅ Сохранено сгорающее сообщение от {user_link}"
        
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
            text=f"❌ Не удалось сохранить сгорающее сообщение от {user_link}",
            parse_mode=ParseMode.HTML
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
                        f'✅ Бот успешно привязан\n\n'
                        f'Как использовать?\n'
                        f'➖ Если ваш собеседник удалит сообщение, бот сразу же пришлёт вам копию этого сообщения '
                        f'<b>(работает только с сообщениями, которые отправлены ПОСЛЕ подключения бота)</b>\n'
                        f'➖ Чтобы скачивать фото/видео с таймером, необходимо ответить на них в диалоге с вашим собеседником '
                        f'<b>(на видео</b> ☝️ <b>показан пример)</b> любым сообщением '
                        f'<b>(ДО ОТКРЫТИЯ, ЭТО ВАЖНО!)</b>\n\n'
                        f'<blockquote>❗ Бот работает только с <b>НОВЫМИ</b> сообщениями, которые вы получили после подключения бота</blockquote>'
                    ),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            else:
                await business_connection.bot.send_message(
                    chat_id=business_connection.user_chat_id,
                    text=(
                        f'✅ Бот успешно привязан\n\n'
                        f'Как использовать?\n'
                        f'➖ Если ваш собеседник удалит сообщение, бот сразу же пришлёт вам копию этого сообщения '
                        f'<b>(работает только с сообщениями, которые отправлены ПОСЛЕ подключения бота)</b>\n'
                        f'➖ Чтобы скачивать фото/видео с таймером, необходимо ответить на них в диалоге с вашим собеседником '
                        f'<b>(на видео</b> ☝️ <b>показан пример)</b> любым сообщением '
                        f'<b>(ДО ОТКРЫТИЯ, ЭТО ВАЖНО!)</b>\n\n'
                        f'<blockquote>❗ Бот работает только с <b>НОВЫМИ</b> сообщениями, которые вы получили после подключения бота</blockquote>'
                    ),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
    except Exception as e:
        print(f"Error in business_connection: {e}")


@dp.business_message()
async def handle_business_message(message: MessageType):
    session = SQLSession(db.engine)
    
    try:
        business_connection = await message.bot.get_business_connection(message.business_connection_id)
        user_chat_id = business_connection.user_chat_id
        
        if message.from_user.id != user_chat_id:
            await save_message_to_archive(message, user_chat_id, session)
        
        if message.reply_to_message:
            reply_to = message.reply_to_message
            
            if message.from_user.id == user_chat_id and reply_to.from_user.id != user_chat_id:
                if reply_to.has_protected_content:
                    await save_auto_delete_media(message, reply_to, user_chat_id)
        
    except Exception as e:
        print(f"Error in business_message: {e}")
    finally:
        session.close()


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
            user_link = get_user_link(
                message.from_user.id, 
                message.from_user.username,
                message.from_user.first_name
            )
            
            diff_html = generate_diff_html(old_text, new_text)
            
            edit_text = (
                f"🔏 {user_link} изменил(а) сообщение:\n\n"
                f"<b>Старый текст:</b>\n"
                f"<blockquote>{html.quote(old_text)}</blockquote>\n\n"
                f"<b>Новый текст:</b>\n"
                f"<blockquote>{html.quote(new_text)}</blockquote>\n\n"
                f"<b>Изменилось:</b>\n"
                f"<blockquote>{diff_html}</blockquote>\n\n"
                f'<i>powered by DialogSpyBotRobot</i>'
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
            
            user_link = get_user_link(None, msg.from_username, msg.from_full_name)
            
            if msg.type == "text":
                text = f"🗑 {user_link} удалил(а) сообщение\n\n<blockquote>{html.quote(msg.content)}</blockquote>\n\n<i>powered by DialogSpyBotRobot</i>"
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            
            elif msg.type == "photo":
                caption = f"🗑 {user_link} удалил(а) фото\n\n<i>powered by DialogSpyBotRobot</i>"
                if msg.caption:
                    caption = f"🗑 {user_link} удалил(а) фото\n\n{html.quote(msg.caption)}\n\n<i>powered by DialogSpyBotRobot</i>"
                await deleted_messages.bot.send_photo(
                    chat_id=user_chat_id,
                    photo=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "video":
                caption = f"🗑 {user_link} удалил(а) видео\n\n<i>powered by DialogSpyBotRobot</i>"
                if msg.caption:
                    caption = f"🗑 {user_link} удалил(а) видео\n\n{html.quote(msg.caption)}\n\n<i>powered by DialogSpyBotRobot</i>"
                await deleted_messages.bot.send_video(
                    chat_id=user_chat_id,
                    video=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "video_note":
                await deleted_messages.bot.send_video_note(
                    chat_id=user_chat_id,
                    video_note=msg.content
                )
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=f"🗑 {user_link} удалил(а) видео-кружок\n\n<i>powered by DialogSpyBotRobot</i>",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                
            elif msg.type == "voice":
                caption = f"🗑 {user_link} удалил(а) голосовое сообщение\n\n<i>powered by DialogSpyBotRobot</i>"
                if msg.caption:
                    caption = f"🗑 {user_link} удалил(а) голосовое сообщение\n\n{html.quote(msg.caption)}\n\n<i>powered by DialogSpyBotRobot</i>"
                await deleted_messages.bot.send_voice(
                    chat_id=user_chat_id,
                    voice=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "audio":
                caption = f"🗑 {user_link} удалил(а) аудио\n\n<i>powered by DialogSpyBotRobot</i>"
                if msg.caption:
                    caption = f"🗑 {user_link} удалил(а) аудио\n\n{html.quote(msg.caption)}\n\n<i>powered by DialogSpyBotRobot</i>"
                await deleted_messages.bot.send_audio(
                    chat_id=user_chat_id,
                    audio=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "sticker":
                await deleted_messages.bot.send_sticker(
                    chat_id=user_chat_id,
                    sticker=msg.content
                )
                await deleted_messages.bot.send_message(
                    chat_id=user_chat_id,
                    text=f"🗑 {user_link} удалил(а) стикер\n\n<i>powered by DialogSpyBotRobot</i>",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                
            elif msg.type == "document":
                caption = f"🗑 {user_link} удалил(а) файл\n\n<i>powered by DialogSpyBotRobot</i>"
                if msg.caption:
                    caption = f"🗑 {user_link} удалил(а) файл\n\n{html.quote(msg.caption)}\n\n<i>powered by DialogSpyBotRobot</i>"
                await deleted_messages.bot.send_document(
                    chat_id=user_chat_id,
                    document=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
            elif msg.type == "animation":
                caption = f"🗑 {user_link} удалил(а) гифку\n\n<i>powered by DialogSpyBotRobot</i>"
                if msg.caption:
                    caption = f"🗑 {user_link} удалил(а) гифку\n\n{html.quote(msg.caption)}\n\n<i>powered by DialogSpyBotRobot</i>"
                await deleted_messages.bot.send_animation(
                    chat_id=user_chat_id,
                    animation=msg.content,
                    caption=caption,
                    parse_mode=ParseMode.HTML
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