import contextlib
import inspect
from functools import wraps

from cachetools import TTLCache
from telegram import Chat, ChatMember, Update, User
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError

from tg_bot import (
    DEL_CMDS,
    DEV_USERS,
    SUDO_USERS,
    SUPPORT_USERS,
    SARDEGNA_USERS,
    WHITELIST_USERS,
)

# stores admin in memory for 10 min.
ADMIN_CACHE = TTLCache(maxsize=512, ttl=60 * 10)


async def is_anon(user: User, chat: Chat):
    member = await chat.get_member(user.id)
    return getattr(member, "is_anonymous", False)


def is_whitelist_plus(_: Chat, user_id: int) -> bool:
    return any(
        user_id in group
        for group in [
            WHITELIST_USERS,
            SARDEGNA_USERS,
            SUPPORT_USERS,
            SUDO_USERS,
            DEV_USERS,
        ]
    )


def is_support_plus(_: Chat, user_id: int) -> bool:
    return user_id in SUPPORT_USERS or user_id in SUDO_USERS or user_id in DEV_USERS


def is_sudo_plus(_: Chat, user_id: int) -> bool:
    return user_id in SUDO_USERS or user_id in DEV_USERS


def _is_admin_status(status) -> bool:
    # Works for both enums and strings
    return str(status) in ("administrator", "creator")


async def is_user_admin(update: Update, user_id: int, member: ChatMember = None) -> bool:
    chat = update.effective_chat
    msg = update.effective_message
    if (
        chat.type == "private"
        or user_id in SUDO_USERS
        or user_id in DEV_USERS
        or getattr(chat, "all_members_are_administrators", False)
        or (
            msg
            and msg.reply_to_message
            and msg.reply_to_message.sender_chat is not None
            and msg.reply_to_message.sender_chat.type != "channel"
        )
    ):
        return True

    if member is None:
        try:
            return user_id in ADMIN_CACHE[chat.id]
        except KeyError:
            chat_admins = await chat.get_administrators()
            admin_list = [x.user.id for x in chat_admins]
            ADMIN_CACHE[chat.id] = admin_list
            return user_id in admin_list

    return _is_admin_status(member.status)


async def is_bot_admin(chat: Chat, bot_id: int, bot_member: ChatMember = None) -> bool:
    if chat.type == "private" or getattr(chat, "all_members_are_administrators", False):
        return True

    if bot_member is None:
        bot_member = await chat.get_member(bot_id)

    return _is_admin_status(bot_member.status)


async def can_delete(chat: Chat, bot_id: int) -> bool:
    member = await chat.get_member(bot_id)
    return bool(getattr(member, "can_delete_messages", False))


async def is_user_ban_protected(update: Update, user_id: int, member: ChatMember = None) -> bool:
    chat = update.effective_chat
    msg = update.effective_message
    if (
        chat.type == "private"
        or user_id in SUDO_USERS
        or user_id in DEV_USERS
        or user_id in WHITELIST_USERS
        or user_id in SARDEGNA_USERS
        or getattr(chat, "all_members_are_administrators", False)
        or (
            msg
            and msg.reply_to_message
            and msg.reply_to_message.sender_chat is not None
            and msg.reply_to_message.sender_chat.type != "channel"
        )
    ):
        return True

    if member is None:
        member = await chat.get_member(user_id)

    return _is_admin_status(member.status)


async def is_user_in_chat(chat: Chat, user_id: int) -> bool:
    member = await chat.get_member(user_id)
    return str(member.status) not in ("left", "kicked")


def dev_plus(func):
    @wraps(func)
    async def is_dev_plus_func(update: Update, context, *args, **kwargs):
        user = update.effective_user

        if user and user.id in DEV_USERS:
            return await func(update, context, *args, **kwargs)
        elif not user:
            return
        elif DEL_CMDS and update.effective_message and update.effective_message.text and " " not in update.effective_message.text:
            with contextlib.suppress(TelegramError):
                await update.effective_message.delete()
        else:
            await update.effective_message.reply_text(
                "This is a developer restricted command."
                " You do not have permissions to run this."
            )

    return is_dev_plus_func


def sudo_plus(func):
    @wraps(func)
    async def is_sudo_plus_func(update: Update, context, *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat

        if user and is_sudo_plus(chat, user.id):
            return await func(update, context, *args, **kwargs)
        elif not user:
            return
        elif DEL_CMDS and update.effective_message and update.effective_message.text and " " not in update.effective_message.text:
            with contextlib.suppress(TelegramError):
                await update.effective_message.delete()
        else:
            await update.effective_message.reply_text(
                "Who dis non-admin telling me what to do?"
            )

    return is_sudo_plus_func


def support_plus(func):
    @wraps(func)
    async def is_support_plus_func(update: Update, context, *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat

        if user and is_support_plus(chat, user.id):
            return await func(update, context, *args, **kwargs)
        elif DEL_CMDS and update.effective_message and update.effective_message.text and " " not in update.effective_message.text:
            with contextlib.suppress(TelegramError):
                await update.effective_message.delete()

    return is_support_plus_func


def whitelist_plus(func):
    @wraps(func)
    async def is_whitelist_plus_func(update: Update, context, *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat

        if user and is_whitelist_plus(chat, user.id):
            return await func(update, context, *args, **kwargs)
        else:
            await update.effective_message.reply_text(
                "You don't have access to use this.\nVisit @spiralsupport"
            )

    return is_whitelist_plus_func


def user_admin(func):
    @wraps(func)
    async def is_admin(update: Update, context, *args, **kwargs):
        user = update.effective_user

        if user and await is_user_admin(update, user.id):
            return await func(update, context, *args, **kwargs)
        elif not user:
            return
        elif DEL_CMDS and update.effective_message and update.effective_message.text and " " not in update.effective_message.text:
            with contextlib.suppress(TelegramError):
                await update.effective_message.delete()
        else:
            await update.effective_message.reply_text(
                "Who dis non-admin telling me what to do?"
            )

    return is_admin


def is_user_admin_callback_query(func):
    @wraps(func)
    async def is_admin(update: Update, context, *args, **kwargs):
        user = update.callback_query.from_user
        chat = update.effective_chat

        member = await chat.get_member(user.id)
        if _is_admin_status(member.status):
            return await func(update, context, *args, **kwargs)

        if user.id in DEV_USERS:
            return await func(update, context, *args, **kwargs)
        elif not user:
            return
        else:
            await update.callback_query.answer(
                "You don't have access to use this."
            )

    return is_admin


def user_admin_no_reply(func):
    @wraps(func)
    async def is_not_admin_no_reply(update: Update, context, *args, **kwargs):
        user = update.effective_user

        if user and await is_user_admin(update, user.id):
            return await func(update, context, *args, **kwargs)
        elif not user:
            return
        elif DEL_CMDS and update.effective_message and update.effective_message.text and " " not in update.effective_message.text:
            with contextlib.suppress(TelegramError):
                await update.effective_message.delete()

    return is_not_admin_no_reply


def user_not_admin(func):
    @wraps(func)
    async def is_not_admin(update: Update, context, *args, **kwargs):
        message = update.effective_message
        user = update.effective_user

        if message.is_automatic_forward:
            return
        if message.sender_chat and message.sender_chat.type != "channel":
            return
        elif user and not await is_user_admin(update, user.id):
            return await func(update, context, *args, **kwargs)
        elif not user:
            return

    return is_not_admin


def bot_admin(func):
    @wraps(func)
    async def is_admin(update: Update, context, *args, **kwargs):
        bot = context.bot
        chat = update.effective_chat
        update_chat_title = chat.title
        message_chat_title = update.effective_message.chat.title

        if update_chat_title == message_chat_title:
            not_admin = "I'm not admin! - REEEEEE"
        else:
            not_admin = f"I'm not admin in <b>{update_chat_title}</b>! - REEEEEE"

        if await is_bot_admin(chat, bot.id):
            return await func(update, context, *args, **kwargs)
        else:
            await update.effective_message.reply_text(not_admin, parse_mode=ParseMode.HTML)

    return is_admin


def bot_can_delete(func):
    @wraps(func)
    async def delete_rights(update: Update, context, *args, **kwargs):
        bot = context.bot
        chat = update.effective_chat
        update_chat_title = chat.title
        message_chat_title = update.effective_message.chat.title

        if update_chat_title == message_chat_title:
            cant_delete = "I can't delete messages here!\nMake sure I'm admin and can delete other user's messages."
        else:
            cant_delete = (
                f"I can't delete messages in <b>{update_chat_title}</b>!\n"
                f"Make sure I'm admin and can delete other user's messages there. "
            )

        if await can_delete(chat, bot.id):
            return await func(update, context, *args, **kwargs)
        else:
            await update.effective_message.reply_text(cant_delete, parse_mode=ParseMode.HTML)

    return delete_rights


def can_pin(func):
    @wraps(func)
    async def pin_rights(update: Update, context, *args, **kwargs):
        bot = context.bot
        chat = update.effective_chat
        update_chat_title = chat.title
        message_chat_title = update.effective_message.chat.title

        if update_chat_title == message_chat_title:
            cant_pin = "I can't pin messages here!\nMake sure I'm admin and can pin messages."
        else:
            cant_pin = (
                f"I can't pin messages in <b>{update_chat_title}</b>!\n"
                f"Make sure I'm admin and can pin messages there. "
            )

        member = await chat.get_member(bot.id)
        if getattr(member, "can_pin_messages", False):
            return await func(update, context, *args, **kwargs)
        else:
            await update.effective_message.reply_text(cant_pin, parse_mode=ParseMode.HTML)

    return pin_rights


def can_promote(func):
    @wraps(func)
    async def promote_rights(update: Update, context, *args, **kwargs):
        bot = context.bot
        chat = update.effective_chat
        update_chat_title = chat.title
        message_chat_title = update.effective_message.chat.title

        if update_chat_title == message_chat_title:
            cant_promote = "I can't promote/demote people here!\nMake sure I'm admin and can appoint new admins."
        else:
            cant_promote = (
                f"I can't promote/demote people in <b>{update_chat_title}</b>!\n"
                f"Make sure I'm admin there and can appoint new admins."
            )

        member = await chat.get_member(bot.id)
        if getattr(member, "can_promote_members", False):
            return await func(update, context, *args, **kwargs)
        else:
            await update.effective_message.reply_text(cant_promote, parse_mode=ParseMode.HTML)

    return promote_rights


def can_restrict(func):
    @wraps(func)
    async def restrict_rights(update: Update, context, *args, **kwargs):
        bot = context.bot
        chat = update.effective_chat
        update_chat_title = chat.title
        message_chat_title = update.effective_message.chat.title

        if update_chat_title == message_chat_title:
            cant_restrict = "I can't restrict people here!\nMake sure I'm admin and can restrict users."
        else:
            cant_restrict = (
                f"I can't restrict people in <b>{update_chat_title}</b>!\n"
                f"Make sure I'm admin there and can restrict users. "
            )

        member = await chat.get_member(bot.id)
        if getattr(member, "can_restrict_members", False):
            return await func(update, context, *args, **kwargs)
        else:
            await update.effective_message.reply_text(cant_restrict, parse_mode=ParseMode.HTML)

    return restrict_rights


def user_can_ban(func):
    @wraps(func)
    async def user_is_banhammer(update: Update, context, *args, **kwargs):
        user_id = update.effective_user.id
        member = await update.effective_chat.get_member(user_id)

        if not (getattr(member, "can_restrict_members", False) or str(member.status) == "creator") and user_id not in SUDO_USERS:
            await update.effective_message.reply_text(
                "Sorry son, but you're not worthy to wield the banhammer."
            )
            return ""

        return await func(update, context, *args, **kwargs)

    return user_is_banhammer


async def _maybe_await(x):
    if inspect.isawaitable(x):
        return await x
    return x


def connection_status(func):
    @wraps(func)
    async def connected_status(update: Update, context, *args, **kwargs):
        conn = await _maybe_await(
            connected(
                context.bot,
                update,
                update.effective_chat,
                update.effective_user.id,
                need_admin=False,
            )
        )

        if conn:
            chat = await context.bot.get_chat(conn)
            update.__setattr__("_effective_chat", chat)
            return await func(update, context, *args, **kwargs)
        else:
            if update.effective_message.chat.type == "private":
                await update.effective_message.reply_text(
                    "Send /connect in a group that you and I have in common first."
                )
                return connected_status

            return await func(update, context, *args, **kwargs)

    return connected_status


# Workaround for circular import with connection.py
from tg_bot.modules import connection

connected = connection.connected
