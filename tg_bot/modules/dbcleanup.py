from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import tg_bot.modules.sql.antispam_sql as gban_sql
import tg_bot.modules.sql.users_sql as user_sql
from tg_bot import DEV_USERS, OWNER_ID, application
from tg_bot.modules.helper_funcs.chat_status import dev_plus
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, constants
from telegram.error import BadRequest, Forbidden, TelegramError, RetryAfter, TimedOut, NetworkError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

# Tuning knobs
THROTTLE_INTERVAL = 0.35       # seconds between API calls (~3 req/s)
PROGRESS_MIN_INTERVAL = 3.0    # min seconds between progress edits
NETWORK_BACKOFF = 1.0          # backoff after transient network issues


def _extract_chat_id(chat: Any) -> Any:
    if chat is None:
        return None
    if hasattr(chat, "chat_id"):
        return getattr(chat, "chat_id")
    if hasattr(chat, "id"):
        return getattr(chat, "id")
    if isinstance(chat, dict):
        for k in ("chat_id", "id", "chat"):
            if k in chat:
                return chat[k]
    if isinstance(chat, (list, tuple)) and chat:
        return chat[0]
    return chat  # assume raw id (int/str)


def _extract_user_id(u: Any) -> Any:
    if u is None:
        return None
    if isinstance(u, (int, str)):
        return u
    if hasattr(u, "user_id"):
        return getattr(u, "user_id")
    if hasattr(u, "id"):
        return getattr(u, "id")
    if isinstance(u, dict):
        for k in ("user_id", "id", "user"):
            if k in u:
                return u[k]
    if isinstance(u, (list, tuple)) and u:
        return u[0]
    return None


async def _get_chat_with_backoff(bot, cid) -> tuple[bool, bool]:
    """
    Returns (exists, invalid_flagged).
    exists=True if bot.get_chat succeeded.
    invalid_flagged=True if BadRequest/Forbidden (i.e., should be removed).
    """
    while True:
        try:
            await bot.get_chat(cid)
            return True, False
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            continue
        except (TimedOut, NetworkError):
            await asyncio.sleep(NETWORK_BACKOFF)
            continue
        except (BadRequest, Forbidden):
            return False, True
        except TelegramError:
            # Unknown error -> skip without flagging invalid
            return False, False


async def get_invalid_chats(
    update: Update, context: ContextTypes.DEFAULT_TYPE, remove: bool = False
) -> int:
    bot = context.bot
    chat_id = update.effective_chat.id
    chats = user_sql.get_all_chats()
    kicked_chats = 0
    chat_list: list[Any] = []

    total = len(chats) or 1
    progress_message = None
    last_progress_ts = 0.0

    for idx, chat in enumerate(chats):
        # Progress update (time-gated)
        now = time.monotonic()
        percent = int((100 * (idx + 1)) / total)
        if (now - last_progress_ts >= PROGRESS_MIN_INTERVAL) or (idx + 1 == total):
            progress_bar = f"{percent}% completed in getting invalid chats."
            try:
                if progress_message:
                    await progress_message.edit_text(progress_bar)
                else:
                    progress_message = await bot.send_message(chat_id, progress_bar)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramError:
                pass
            last_progress_ts = time.monotonic()

        cid = _extract_chat_id(chat)
        if cid is None:
            await asyncio.sleep(THROTTLE_INTERVAL)
            continue

        exists, invalid = await _get_chat_with_backoff(bot, cid)
        if invalid:
            kicked_chats += 1
            chat_list.append(cid)

        # Baseline throttle to avoid flood limits
        await asyncio.sleep(THROTTLE_INTERVAL)

    if progress_message:
        with contextlib.suppress(TelegramError):
            await progress_message.delete()

    if remove and chat_list:
        for muted_chat in chat_list:
            await asyncio.sleep(THROTTLE_INTERVAL)
            user_sql.rem_chat(muted_chat)

    return kicked_chats


async def get_invalid_gban(
    update: Update, context: ContextTypes.DEFAULT_TYPE, remove: bool = False
) -> int:
    bot = context.bot
    banned = gban_sql.get_gban_list()
    ungbanned_users = 0
    ungban_list: list[Any] = []

    total = len(banned) or 1
    last_progress_ts = 0.0
    progress_message = None
    chat_id = update.effective_chat.id

    for idx, u in enumerate(banned):
        # Optional progress for gbans too (time-gated)
        now = time.monotonic()
        percent = int((100 * (idx + 1)) / total)
        if (now - last_progress_ts >= PROGRESS_MIN_INTERVAL) or (idx + 1 == total):
            progress_bar = f"{percent}% completed in checking gbanned users."
            try:
                if progress_message:
                    await progress_message.edit_text(progress_bar)
                else:
                    progress_message = await bot.send_message(chat_id, progress_bar)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramError:
                pass
            last_progress_ts = time.monotonic()

        user_id = _extract_user_id(u)
        if user_id is None:
            await asyncio.sleep(THROTTLE_INTERVAL)
            continue

        exists, invalid = await _get_chat_with_backoff(bot, user_id)
        if invalid:
            ungbanned_users += 1
            ungban_list.append(user_id)

        await asyncio.sleep(THROTTLE_INTERVAL)

    if progress_message:
        with contextlib.suppress(TelegramError):
            await progress_message.delete()

    if remove and ungban_list:
        for user_id in ungban_list:
            await asyncio.sleep(THROTTLE_INTERVAL)
            gban_sql.ungban_user(user_id)

    return ungbanned_users


@dev_plus
async def dbcleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    await msg.reply_text("Getting invalid chat count ...")
    invalid_chat_count = await get_invalid_chats(update, context)

    await msg.reply_text("Getting invalid gbanned count ...")
    invalid_gban_count = await get_invalid_gban(update, context)

    reply = (
        f"<b>Total invalid chats</b>: {invalid_chat_count}\n"
        f"<b>Total invalid gbanned users</b>: {invalid_gban_count}"
    )

    buttons = [[InlineKeyboardButton(text="Cleanup DB", callback_data="db_cleanup")]]

    await msg.reply_text(
        reply,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=constants.ParseMode.HTML,
    )


async def callback_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = query.message
    chat_id = update.effective_chat.id
    query_type = query.data

    admin_list = [OWNER_ID] + DEV_USERS

    await query.answer()

    if query_type == "db_leave_chat" and query.from_user.id in admin_list:
        await message.edit_text("Leaving chats is not implemented.")
    elif (query_type in {"db_leave_chat", "db_cleanup"}) and query.from_user.id not in admin_list:
        await query.answer("You are not allowed to use this.", show_alert=True)
    elif query_type == "db_cleanup":
        await message.edit_text("Cleaning up DB ...")
        invalid_chat_count = await get_invalid_chats(update, context, True)
        invalid_gban_count = await get_invalid_gban(update, context, True)
        reply = f"Cleaned up {invalid_chat_count} chats and {invalid_gban_count} gbanned users from db."
        await context.bot.send_message(chat_id, reply)


DB_CLEANUP_HANDLER = CommandHandler("dbcleanup", dbcleanup)
BUTTON_HANDLER = CallbackQueryHandler(callback_button, pattern=r"^db_.*$")

application.add_handler(DB_CLEANUP_HANDLER)
application.add_handler(BUTTON_HANDLER)

__mod_name__ = "DB Cleanup"
__handlers__ = [DB_CLEANUP_HANDLER, BUTTON_HANDLER]
