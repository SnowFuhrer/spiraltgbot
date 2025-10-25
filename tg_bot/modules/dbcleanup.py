from __future__ import annotations

import asyncio
from typing import List

import tg_bot.modules.sql.antispam_sql as gban_sql
import tg_bot.modules.sql.users_sql as user_sql
from tg_bot import DEV_USERS, OWNER_ID, application
from tg_bot.modules.helper_funcs.chat_status import dev_plus
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, TimedOut, NetworkError, TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes


async def get_invalid_chats(update: Update, context: ContextTypes.DEFAULT_TYPE, remove: bool = False) -> int:
    bot = context.bot
    chat_id = update.effective_chat.id
    chats = user_sql.get_all_chats()
    kicked_chats = 0
    chat_list: List[int] = []
    progress = 0
    progress_message = None

    total = len(chats) or 1

    for idx, chat in enumerate(chats):
        percent = int((100 * idx) / total)
        if percent >= progress + 5:
            progress_bar = f"{percent}% completed in getting invalid chats."
            try:
                if progress_message:
                    await progress_message.edit_text(progress_bar)
                else:
                    progress_message = await bot.send_message(chat_id, progress_bar)
            except TelegramError:
                pass
            progress = percent

        cid = chat.chat_id
        await asyncio.sleep(0.1)
        try:
            await bot.get_chat(cid)
        except (BadRequest, Forbidden, Unauthorized):
            kicked_chats += 1
            chat_list.append(cid)
        except TelegramError:
            pass

    if progress_message:
        with contextlib.suppress(TelegramError):
            await progress_message.delete()

    if remove:
        for muted_chat in chat_list:
            await asyncio.sleep(0.05)
            user_sql.rem_chat(muted_chat)

    return kicked_chats


async def get_invalid_gban(update: Update, context: ContextTypes.DEFAULT_TYPE, remove: bool = False) -> int:
    bot = context.bot
    banned = gban_sql.get_gban_list()
    ungbanned_users = 0
    ungban_list: List[int] = []

    for user in banned:
        user_id = user["user_id"]
        await asyncio.sleep(0.1)
        try:
            await bot.get_chat(user_id)
        except BadRequest:
            ungbanned_users += 1
            ungban_list.append(user_id)
        except TelegramError:
            pass

    if remove:
        for user_id in ungban_list:
            await asyncio.sleep(0.05)
            gban_sql.ungban_user(user_id)

    return ungbanned_users


@dev_plus
async def dbcleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    await msg.reply_text("Getting invalid chat count ...")
    invalid_chat_count = await get_invalid_chats(update, context)

    await msg.reply_text("Getting invalid gbanned count ...")
    invalid_gban_count = await get_invalid_gban(update, context)

    reply = f"Total invalid chats - {invalid_chat_count}\n"
    reply += f"Total invalid gbanned users - {invalid_gban_count}"

    buttons = [[InlineKeyboardButton("Cleanup DB", callback_data="db_cleanup")]]

    await update.effective_message.reply_text(
        reply, reply_markup=InlineKeyboardMarkup(buttons)
    )


async def callback_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    query = update.callback_query
    message = query.message
    chat_id = update.effective_chat.id
    query_type = query.data

    admin_list = [OWNER_ID] + DEV_USERS

    await query.answer()

    if query_type == "db_leave_chat" and query.from_user.id in admin_list:
        # Optional feature placeholder: implement if needed
        await bot.edit_message_text("Leaving chats is not implemented.", chat_id, message.message_id)
    elif (query_type == "db_leave_chat" or query_type == "db_cleanup") and query.from_user.id not in admin_list:
        await query.answer("You are not allowed to use this.", show_alert=True)
    elif query_type == "db_cleanup":
        await bot.edit_message_text("Cleaning up DB ...", chat_id, message.message_id)
        invalid_chat_count = await get_invalid_chats(update, context, True)
        invalid_gban_count = await get_invalid_gban(update, context, True)
        reply = f"Cleaned up {invalid_chat_count} chats and {invalid_gban_count} gbanned users from db."
        await bot.send_message(chat_id, reply)


DB_CLEANUP_HANDLER = CommandHandler("dbcleanup", dbcleanup)
BUTTON_HANDLER = CallbackQueryHandler(callback_button, pattern=r"^db_.*$")

application.add_handler(DB_CLEANUP_HANDLER)
application.add_handler(BUTTON_HANDLER)

__mod_name__ = "DB Cleanup"
__handlers__ = [DB_CLEANUP_HANDLER, BUTTON_HANDLER]
