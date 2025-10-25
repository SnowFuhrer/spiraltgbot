import inspect
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from tg_bot import DEV_USERS, SUDO_USERS, dispatcher
from .decorators import kigcallback


class AdminPerms(Enum):
    CAN_RESTRICT_MEMBERS = "can_restrict_members"
    CAN_PROMOTE_MEMBERS = "can_promote_members"
    CAN_INVITE_USERS = "can_invite_users"
    CAN_DELETE_MESSAGES = "can_delete_messages"
    CAN_CHANGE_INFO = "can_change_info"
    CAN_PIN_MESSAGES = "can_pin_messages"


class ChatStatus(Enum):
    CREATOR = "creator"
    ADMIN = "administrator"


anon_callbacks = {}
anon_callback_messages = {}


def user_admin(permission: AdminPerms):
    def wrapper(func):
        async_mode = inspect.iscoroutinefunction(func)

        async def _call(update, context, *args, **kwargs):
            if async_mode:
                return await func(update, context, *args, **kwargs)
            return func(update, context, *args, **kwargs)

        async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            nonlocal permission
            if update.effective_chat.type == "private":
                return await _call(update, context, *args, **kwargs)

            message = update.effective_message
            is_anon = message.sender_chat

            if is_anon:
                callback_id = f"anoncb/{message.chat.id}/{message.message_id}/{permission.value}"
                anon_callbacks[(message.chat.id, message.message_id)] = ((update, context), func)
                sent = await message.reply_text(
                    "Seems like you're anonymous, click the button below to prove your identity",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(text="Prove identity", callback_data=callback_id)]]
                    ),
                )
                anon_callback_messages[(message.chat.id, message.message_id)] = sent.message_id
                return

            user_id = message.from_user.id
            chat_id = message.chat.id
            mem = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)

            has_perm = getattr(mem, permission.value, False) is True
            is_creator = (mem.status == "creator") or (getattr(mem.status, "value", "") == "creator")
            if has_perm or is_creator or user_id in SUDO_USERS:
                return await _call(update, context, *args, **kwargs)
            else:
                return await message.reply_text(
                    f"You lack the permission: `{permission.name}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

        return _handler

    return wrapper


@kigcallback(pattern=r"^anoncb/")
async def anon_callback_handler1(upd: Update, context: ContextTypes.DEFAULT_TYPE):
    callback = upd.callback_query
    parts = callback.data.split("/")
    # Format: anoncb/{chat_id}/{message_id}/{perm_name}
    if len(parts) < 4:
        await callback.answer("Malformed callback.", show_alert=True)
        return

    perm = parts[3]
    chat_id = int(parts[1])
    message_id = int(parts[2])

    try:
        mem = await context.bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)
        return

    status_val = mem.status if isinstance(mem.status, str) else getattr(mem.status, "value", "")
    if status_val not in [ChatStatus.ADMIN.value, ChatStatus.CREATOR.value]:
        await callback.answer("You aren't admin.")
        mid = anon_callback_messages.pop((chat_id, message_id), None)
        if mid is not None:
            try:
                await dispatcher.bot.delete_message(chat_id, mid)
            except Exception:
                pass
        await dispatcher.bot.send_message(chat_id, "You lack the permissions required for this command")
        return

    if getattr(mem, perm, False) is True or status_val == "creator" or getattr(mem, "user", None) and mem.user.id in DEV_USERS:
        cb = anon_callbacks.pop((chat_id, message_id), None)
        if cb:
            mid = anon_callback_messages.pop((chat_id, message_id), None)
            if mid is not None:
                try:
                    await dispatcher.bot.delete_message(chat_id, mid)
                except Exception:
                    pass
            original_func = cb[1]
            original_update, original_context = cb[0]
            if inspect.iscoroutinefunction(original_func):
                return await original_func(original_update, original_context)
            else:
                return original_func(original_update, original_context)
    else:
        await callback.answer("This isn't for ya")
