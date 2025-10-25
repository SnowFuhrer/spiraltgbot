import ast
import html
from typing import Optional

from alphabet_detector import AlphabetDetector
from telegram import Message, Chat, Update, ChatPermissions
from telegram.constants import ParseMode, MessageEntityType
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes, filters as tg_filters
from telegram.helpers import mention_html

import tg_bot.modules.sql.locks_sql as sql
from tg_bot import log
from tg_bot.modules.connection import connected
from tg_bot.modules.helper_funcs.alternate import send_message, typing_action
from tg_bot.modules.helper_funcs.chat_status import (
    can_delete,
    user_not_admin,
    is_bot_admin,
    user_admin as u_admin,
)
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, rate_limit
from tg_bot.modules.log_channel import loggable
from tg_bot.modules.sql.approve_sql import is_approved
from ..modules.helper_funcs.anonymous import user_admin, AdminPerms

ad = AlphabetDetector()

# PTB compatibility shim for "document" filter
try:
    DOCUMENT_FILTER = tg_filters.DOCUMENT  # some builds export this
except AttributeError:
    DOCUMENT_FILTER = getattr(getattr(tg_filters, "Document", None), "ALL", None) or getattr(tg_filters, "ATTACHMENT", None)

LOCK_TYPES = {
    "audio": tg_filters.AUDIO,
    "voice": tg_filters.VOICE,
    "document": DOCUMENT_FILTER,
    "video": tg_filters.VIDEO,
    "contact": tg_filters.CONTACT,
    "photo": tg_filters.PHOTO,
    "url": tg_filters.Entity(MessageEntityType.URL) | tg_filters.CaptionEntity(MessageEntityType.URL),
    "bots": tg_filters.StatusUpdate.NEW_CHAT_MEMBERS,
    "forward": tg_filters.FORWARDED & ~tg_filters.IS_AUTOMATIC_FORWARD,
    "game": tg_filters.GAME,
    "location": tg_filters.LOCATION,
    "egame": tg_filters.Dice,
    "rtl": "rtl",
    "button": "button",
    "inline": "inline",
}

LOCK_CHAT_RESTRICTION = {
    "all": {
        "can_send_messages": False,
        "can_send_media_messages": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
        "can_change_info": False,
        "can_invite_users": False,
        "can_pin_messages": False,
    },
    "messages": {"can_send_messages": False},
    "media": {"can_send_media_messages": False},
    "sticker": {"can_send_other_messages": False},
    "gif": {"can_send_other_messages": False},
    "poll": {"can_send_polls": False},
    "other": {"can_send_other_messages": False},
    "previews": {"can_add_web_page_previews": False},
    "info": {"can_change_info": False},
    "invite": {"can_invite_users": False},
    "pin": {"can_pin_messages": False},
}

UNLOCK_CHAT_RESTRICTION = {
    "all": {
        "can_send_messages": True,
        "can_send_media_messages": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
        "can_invite_users": True,
    },
    "messages": {"can_send_messages": True},
    "media": {"can_send_media_messages": True},
    "sticker": {"can_send_other_messages": True},
    "gif": {"can_send_other_messages": True},
    "poll": {"can_send_polls": True},
    "other": {"can_send_other_messages": True},
    "previews": {"can_add_web_page_previews": True},
    "info": {"can_change_info": True},
    "invite": {"can_invite_users": True},
    "pin": {"can_pin_messages": True},
}

PERM_GROUP = -8
REST_GROUP = -12


async def restr_members(
    bot, chat_id, members, messages=False, media=False, other=False, previews=False
):
    perms = ChatPermissions(
        can_send_messages=messages,
        can_send_media_messages=media,
        can_send_other_messages=other,
        can_add_web_page_previews=previews,
    )
    for mem in members:
        try:
            await bot.restrict_chat_member(chat_id, mem.user, permissions=perms)
        except TelegramError:
            pass


async def unrestr_members(
    bot, chat_id, members, messages=True, media=True, other=True, previews=True
):
    perms = ChatPermissions(
        can_send_messages=messages,
        can_send_media_messages=media,
        can_send_other_messages=other,
        can_add_web_page_previews=previews,
    )
    for mem in members:
        try:
            await bot.restrict_chat_member(chat_id, mem.user, permissions=perms)
        except TelegramError:
            pass


@kigcmd(command='locktypes')
@rate_limit(40, 60)
async def locktypes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "\n • ".join(
            ["Locks available: "]
            + sorted(list(LOCK_TYPES) + list(LOCK_CHAT_RESTRICTION))
        )
    )


@kigcmd(command='lock')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
@typing_action
async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:  # sourcery no-metrics
    args = context.args
    chat = update.effective_chat
    user = update.effective_user

    if (
        can_delete(chat, context.bot.id)
        or update.effective_message.chat.type == "private"
    ):
        if len(args) >= 1:
            ltype = args[0].lower()
            if ltype in LOCK_TYPES:
                # Connection check
                conn = connected(context.bot, update, chat, user.id, need_admin=True)
                if conn:
                    chat = await context.bot.get_chat(conn)
                    text = f"Locked {ltype} for non-admins in {chat.title}!"
                else:
                    if update.effective_message.chat.type == "private":
                        await send_message(
                            update.effective_message,
                            "This command is meant to use in group not in PM",
                        )
                        return ""
                    chat = update.effective_chat
                    text = f"Locked {ltype} for non-admins!"
                sql.update_lock(chat.id, ltype, locked=True)
                await send_message(update.effective_message, text, parse_mode="markdown")

                return (
                    f"<b>{html.escape(chat.title)}:</b>"
                    "\n#LOCK"
                    f"\n<b>Admin:</b> {mention_html(user.id, user.first_name)}"
                    f"\nLocked <code>{ltype}</code>."
                )

            elif ltype in LOCK_CHAT_RESTRICTION:
                # Connection check
                conn = connected(context.bot, update, chat, user.id, need_admin=True)
                if conn:
                    chat = await context.bot.get_chat(conn)
                    chat_id = conn
                    text = f"Locked {ltype} for all non-admins in {chat.title}!"
                else:
                    if update.effective_message.chat.type == "private":
                        await send_message(
                            update.effective_message,
                            "This command is meant to use in group not in PM",
                        )
                        return ""
                    chat = update.effective_chat
                    chat_id = update.effective_chat.id
                    text = f"Locked {ltype} for all non-admins!"

                current_permission = (await context.bot.get_chat(chat_id)).permissions
                await context.bot.set_chat_permissions(
                    chat_id=chat_id,
                    permissions=get_permission_list(
                        ast.literal_eval(str(current_permission)),
                        LOCK_CHAT_RESTRICTION[ltype.lower()],
                    ),
                )

                await send_message(update.effective_message, text, parse_mode="markdown")
                return (
                    f"<b>{html.escape(chat.title)}:</b>"
                    "\n#Permission_LOCK"
                    f"\n<b>Admin:</b> {mention_html(user.id, user.first_name)}"
                    f"\nLocked <code>{ltype}</code>."
                )

            else:
                await send_message(
                    update.effective_message,
                    "What are you trying to lock...? Try /locktypes for the list of lockables",
                )
        else:
            await send_message(update.effective_message, "What are you trying to lock...?")

    else:
        await send_message(
            update.effective_message,
            "I am not administrator or haven't got enough rights.",
        )

    return ""


@kigcmd(command='unlock')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
@typing_action
async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:  # sourcery no-metrics
    args = context.args
    chat = update.effective_chat
    user = update.effective_user

    if len(args) >= 1:
        ltype = args[0].lower()
        if ltype in LOCK_TYPES:
            conn = connected(context.bot, update, chat, user.id, need_admin=True)
            if conn:
                chat = await context.bot.get_chat(conn)
                text = f"Unlocked {ltype} for everyone in {chat.title}!"
            else:
                if update.effective_message.chat.type == "private":
                    await send_message(
                        update.effective_message,
                        "This command is meant to use in group not in PM",
                    )
                    return ""
                chat = update.effective_chat
                text = f"Unlocked {ltype} for everyone!"
            sql.update_lock(chat.id, ltype, locked=False)
            await send_message(update.effective_message, text, parse_mode="markdown")
            return (
                f"<b>{html.escape(chat.title)}:</b>"
                "\n#UNLOCK"
                f"\n<b>Admin:</b> {mention_html(user.id, user.first_name)}"
                f"\nUnlocked <code>{ltype}</code>."
            )

        elif ltype in UNLOCK_CHAT_RESTRICTION:
            conn = connected(context.bot, update, chat, user.id, need_admin=True)
            if conn:
                chat = await context.bot.get_chat(conn)
                chat_id = conn
                text = f"Unlocked {ltype} for everyone in {chat.title}!"
            else:
                if update.effective_message.chat.type == "private":
                    await send_message(
                        update.effective_message,
                        "This command is meant to use in group not in PM",
                    )
                    return ""
                chat = update.effective_chat
                chat_id = update.effective_chat.id
                text = f"Unlocked {ltype} for everyone!"

            current_permission = (await context.bot.get_chat(chat_id)).permissions
            await context.bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=get_permission_list(
                    ast.literal_eval(str(current_permission)),
                    UNLOCK_CHAT_RESTRICTION[ltype.lower()],
                ),
            )

            await send_message(update.effective_message, text, parse_mode="markdown")

            return (
                f"<b>{html.escape(chat.title)}:</b>"
                "\n#UNLOCK"
                f"\n<b>Admin:</b> {mention_html(user.id, user.first_name)}"
                f"\nUnlocked <code>{ltype}</code>."
            )
        else:
            await send_message(
                update.effective_message,
                "What are you trying to unlock...? Try /locktypes for the list of lockables.",
            )

    else:
        await send_message(update.effective_message, "What are you trying to unlock...?")

    return ""


@kigmsg((tg_filters.ALL & tg_filters.ChatType.GROUPS), group=PERM_GROUP)
@user_not_admin
@rate_limit(50, 60)
async def del_lockables(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user = update.effective_user
    if not chat or not message:
        return

    if is_approved(chat.id, user.id):
        return

    for lockable, filter_ in LOCK_TYPES.items():
        if lockable == "rtl":
            if sql.is_locked(chat.id, lockable) and can_delete(chat, context.bot.id):
                if message.caption:
                    check = ad.detect_alphabet(u"{}".format(message.caption))
                    if "ARABIC" in check:
                        try:
                            await message.delete()
                        except BadRequest as excp:
                            if excp.message != "Message to delete not found":
                                log.exception("ERROR in lockables")
                        break
                if message.text:
                    check = ad.detect_alphabet(u"{}".format(message.text))
                    if "ARABIC" in check:
                        try:
                            await message.delete()
                        except BadRequest as excp:
                            if excp.message != "Message to delete not found":
                                log.exception("ERROR in lockables")
                        break
            continue

        if lockable == "button":
            if (
                sql.is_locked(chat.id, lockable)
                and can_delete(chat, context.bot.id)
                and message.reply_markup
                and message.reply_markup.inline_keyboard
            ):
                try:
                    await message.delete()
                except BadRequest as excp:
                    if excp.message != "Message to delete not found":
                        log.exception("ERROR in lockables")
                break
            continue

        if lockable == "inline":
            if (
                sql.is_locked(chat.id, lockable)
                and can_delete(chat, context.bot.id)
                and message
                and message.via_bot
            ):
                try:
                    await message.delete()
                except BadRequest as excp:
                    if excp.message != "Message to delete not found":
                        log.exception("ERROR in lockables")
                break
            continue

        # Apply filter on the Message (not the Update)
        try:
            matched = (filter_ is not None) and callable(filter_) and filter_(message)
        except Exception:
            matched = False

        if matched and sql.is_locked(chat.id, lockable) and can_delete(chat, context.bot.id):
            if lockable == "bots":
                new_members = update.effective_message.new_chat_members
                for new_mem in new_members:
                    if new_mem.is_bot:
                        if not is_bot_admin(chat, context.bot.id):
                            await send_message(
                                update.effective_message,
                                "I see a bot and I've been told to stop them from joining..."
                                "but I'm not admin!",
                            )
                            return

                        await context.bot.ban_chat_member(chat.id, new_mem.id)
                        await send_message(
                            update.effective_message,
                            "Only admins are allowed to add bots in this chat! Get outta here.",
                        )
                        break
            else:
                try:
                    await message.delete()
                except BadRequest as excp:
                    if excp.message != "Message to delete not found":
                        log.exception("ERROR in lockables")
                break


async def build_lock_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    locks = sql.get_locks(chat_id)
    res = "*" + "These are the current locks in this Chat:" + "*"
    locklist = []
    permslist = []

    if locks:
        locklist.append(f"sticker = `{locks.sticker}`")
        locklist.append(f"audio = `{locks.audio}`")
        locklist.append(f"voice = `{locks.voice}`")
        locklist.append(f"document = `{locks.document}`")
        locklist.append(f"video = `{locks.video}`")
        locklist.append(f"contact = `{locks.contact}`")
        locklist.append(f"photo = `{locks.photo}`")
        locklist.append(f"gif = `{locks.gif}`")
        locklist.append(f"url = `{locks.url}`")
        locklist.append(f"bots = `{locks.bots}`")
        locklist.append(f"forward = `{locks.forward}`")
        locklist.append(f"game = `{locks.game}`")
        locklist.append(f"location = `{locks.location}`")
        locklist.append(f"rtl = `{locks.rtl}`")
        locklist.append(f"button = `{locks.button}`")
        locklist.append(f"egame = `{locks.egame}`")
        locklist.append(f"inline = `{locks.inline}`")

    permissions = (await context.bot.get_chat(chat_id)).permissions
    permslist.append(f"messages = `{permissions.can_send_messages}`")
    permslist.append(f"media = `{permissions.can_send_media_messages}`")
    permslist.append(f"poll = `{permissions.can_send_polls}`")
    permslist.append(f"other = `{permissions.can_send_other_messages}`")
    permslist.append(f"previews = `{permissions.can_add_web_page_previews}`")
    permslist.append(f"info = `{permissions.can_change_info}`")
    permslist.append(f"invite = `{permissions.can_invite_users}`")
    permslist.append(f"pin = `{permissions.can_pin_messages}`")

    if locklist:
        locklist.sort()
        for x in locklist:
            res += f"\n • {x}"
    res += "\n\n*" + "These are the current chat permissions:" + "*"
    for x in permslist:
        res += f"\n • {x}"
    return res


@kigcmd(command='locks')
@u_admin
@typing_action
@rate_limit(40, 60)
async def list_locks(update, context: ContextTypes.DEFAULT_TYPE):
    chat: Optional[Chat] = update.effective_chat
    user = update.effective_user

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = await context.bot.get_chat(conn)
        chat_name = chat.title
    else:
        if update.effective_message.chat.type == "private":
            await send_message(
                update.effective_message,
                "This command is meant to use in group not in PM",
            )
            return ""
        chat = update.effective_chat
        chat_name = update.effective_message.chat.title

    res = await build_lock_message(context, chat.id)
    await send_message(update.effective_message, res, parse_mode=ParseMode.MARKDOWN)


def get_permission_list(current, new):
    permissions = {
        "can_send_messages": None,
        "can_send_media_messages": None,
        "can_send_polls": None,
        "can_send_other_messages": None,
        "can_add_web_page_previews": None,
        "can_change_info": None,
        "can_invite_users": None,
        "can_pin_messages": None,
    }
    permissions.update(current)
    permissions.update(new)
    return ChatPermissions(**permissions)


def __import_data__(chat_id, data):
    # set chat locks
    locks = data.get("locks", {})
    for itemlock in locks:
        if itemlock in LOCK_TYPES:
            sql.update_lock(chat_id, itemlock, locked=True)
        elif itemlock in LOCK_CHAT_RESTRICTION:
            sql.update_restriction(chat_id, itemlock, locked=True)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


async def __chat_settings__(chat_id, user_id, context: ContextTypes.DEFAULT_TYPE):
    return await build_lock_message(context, chat_id)


from tg_bot.modules.language import gs


def get_help(chat):
    return gs(chat, "locks_help")


__mod_name__ = "Locks"
