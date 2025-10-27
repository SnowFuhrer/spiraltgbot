import html
import inspect
import re
from typing import Optional

from telegram import (
    Message,
    Chat,
    Update,
    User,
    ChatPermissions,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes, filters
from telegram.helpers import mention_html

from tg_bot import SARDEGNA_USERS, WHITELIST_USERS
from tg_bot.modules.sql.approve_sql import is_approved
from tg_bot.modules.helper_funcs.chat_status import (
    bot_admin,
    can_restrict,
    connection_status,
    is_user_admin,
    user_admin_no_reply,
)
from tg_bot.modules.log_channel import loggable
from tg_bot.modules.sql import antiflood_sql as sql
from tg_bot.modules.helper_funcs.string_handling import extract_time
from tg_bot.modules.connection import connected
from tg_bot.modules.helper_funcs.alternate import send_message
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, kigcallback, rate_limit

from tg_bot.modules.helper_funcs.anonymous import user_admin, AdminPerms

FLOOD_GROUP = -5


@kigmsg((filters.ALL & ~filters.StatusUpdate.ALL & filters.ChatType.GROUPS), group=FLOOD_GROUP)
@connection_status
@loggable
async def check_flood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    global execstrings
    user: Optional[User] = update.effective_user
    chat: Optional[Chat] = update.effective_chat
    msg: Optional[Message] = update.effective_message

    if not user or not chat or not msg:  # ignore channels or invalid updates
        return ""

    # ignore admins and whitelists
    if (
        await is_user_admin(update, user.id)
        or user.id in WHITELIST_USERS
        or user.id in SARDEGNA_USERS
    ):
        sql.update_flood(chat.id, None)
        return ""

    # ignore approved users
    if is_approved(chat.id, user.id):
        sql.update_flood(chat.id, None)
        return ""

    should_ban = sql.update_flood(chat.id, user.id)
    if not should_ban:
        return ""

    try:
        getmode, getvalue = sql.get_flood_setting(chat.id)

        if getmode == 1:
            await context.bot.ban_chat_member(chat.id, user.id)
            execstrings = "Banned"
            tag = "BANNED"
        elif getmode == 2:
            await context.bot.ban_chat_member(chat.id, user.id)
            await context.bot.unban_chat_member(chat.id, user.id)
            execstrings = "Kicked"
            tag = "KICKED"
        elif getmode == 3:
            await context.bot.restrict_chat_member(
                chat.id, user.id, permissions=ChatPermissions(can_send_messages=False)
            )
            execstrings = "Muted"
            tag = "MUTED"
        elif getmode == 4:
            bantime = extract_time(msg, getvalue)
            await context.bot.ban_chat_member(chat.id, user.id, until_date=bantime)
            execstrings = f"Banned for {getvalue}"
            tag = "TBAN"
        elif getmode == 5:
            mutetime = extract_time(msg, getvalue)
            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                until_date=mutetime,
                permissions=ChatPermissions(can_send_messages=False),
            )
            execstrings = f"Muted for {getvalue}"
            tag = "TMUTE"
        else:
            # Unknown mode, just return
            return ""

        await send_message(msg, f"Beep Boop! Boop Beep!\n{execstrings}!")

        return (
            "<b>{}:</b>"
            "\n#{}"
            "\n<b>User:</b> {}"
            "\nFlooded the group.".format(
                tag, html.escape(chat.title), mention_html(user.id, user.first_name)
            )
        )

    except BadRequest:
        await msg.reply_text(
            "I can't restrict people here, give me permissions first! Until then, I'll disable anti-flood."
        )
        sql.set_flood(chat.id, 0)
        return (
            "<b>{}:</b>"
            "\n#INFO"
            "\nDon't have enough permission to restrict users so automatically disabled anti-flood".format(
                chat.title
            )
        )


@user_admin_no_reply
@bot_admin
@kigcallback(pattern=r"unmute_flooder")
@rate_limit(40, 60)
async def flood_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    match = re.match(r"unmute_flooder\((.+?)\)", query.data or "")
    if match:
        user_id = match.group(1)
        chat_id = update.effective_chat.id
        try:
            # PTB 22+: granular media permissions only (can_send_media_messages removed)
            await bot.restrict_chat_member(
                chat_id,
                int(user_id),
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
            await update.effective_message.edit_text(
                f"Unmuted by {mention_html(user.id, user.first_name)}.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


@kigcmd(command='setflood', filters=filters.ChatType.GROUPS)
@connection_status
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@can_restrict
@loggable
async def set_flood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:  # sourcery no-metrics
    chat: Optional[Chat] = update.effective_chat
    user: Optional[User] = update.effective_user
    message: Optional[Message] = update.effective_message
    args = context.args or []

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if inspect.isawaitable(conn):
        conn = await conn
    if conn:
        chat_id = conn
        chat_obj = await context.bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if update.effective_message.chat.type == "private":
            await send_message(
                update.effective_message,
                "This command is meant to use in group not in PM",
            )
            return ""
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    if len(args) >= 1:
        val = args[0].lower()
        if val in ["off", "no", "0"]:
            sql.set_flood(chat_id, 0)
            if conn:
                await message.reply_text(f"Antiflood has been disabled in {chat_name}.")
            else:
                await message.reply_text("Antiflood has been disabled.")

        elif val.isdigit():
            amount = int(val)
            if amount <= 0:
                sql.set_flood(chat_id, 0)
                if conn:
                    await message.reply_text(f"Antiflood has been disabled in {chat_name}.")
                else:
                    await message.reply_text("Antiflood has been disabled.")
                return (
                    "<b>{}:</b>"
                    "\n#SETFLOOD"
                    "\n<b>Admin:</b> {}"
                    "\nDisable antiflood.".format(
                        html.escape(chat_name), mention_html(user.id, user.first_name)
                    )
                )

            elif amount <= 3:
                await send_message(
                    update.effective_message,
                    "Antiflood must be either 0 (disabled) or number greater than 3!",
                )
                return ""

            else:
                sql.set_flood(chat_id, amount)
                if conn:
                    await message.reply_text(
                        f"Anti-flood has been set to {amount} in chat: {chat_name}"
                    )
                else:
                    await message.reply_text(
                        f"Successfully updated anti-flood limit to {amount}!"
                    )
                return (
                    "<b>{}:</b>"
                    "\n#SETFLOOD"
                    "\n<b>Admin:</b> {}"
                    "\nSet antiflood to <code>{}</code>.".format(
                        html.escape(chat_name),
                        mention_html(user.id, user.first_name),
                        amount,
                    ),
                )

        else:
            await message.reply_text("Invalid argument please use a number, 'off' or 'no'")
    else:
        await message.reply_text(
            "Use <code>/setflood number</code> to enable antiflood.\n"
            "Or use <code>/setflood off</code> to disable antiflood!.",
            parse_mode=ParseMode.HTML,
        )
    return ""


@kigcmd(command="flood", filters=filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@connection_status
async def flood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat: Optional[Chat] = update.effective_chat
    user: Optional[User] = update.effective_user
    msg = update.effective_message

    conn = connected(context.bot, update, chat, user.id, need_admin=False)
    if inspect.isawaitable(conn):
        conn = await conn
    if conn:
        chat_id = conn
        chat_obj = await context.bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if update.effective_message.chat.type == "private":
            await send_message(
                update.effective_message,
                "This command is meant to use in group not in PM",
            )
            return
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    limit = sql.get_flood_limit(chat_id)
    if limit == 0:
        if conn:
            await msg.reply_text(f"I'm not enforcing any flood control in {chat_name}!")
        else:
            await msg.reply_text("I'm not enforcing any flood control here!")
    elif conn:
        await msg.reply_text(
            f"I'm currently restricting members after {limit} consecutive messages in {chat_name}."
        )
    else:
        await msg.reply_text(
            f"I'm currently restricting members after {limit} consecutive messages."
        )


@kigcmd(command="setfloodmode", filters=filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
async def set_flood_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    global settypeflood
    chat: Optional[Chat] = update.effective_chat
    user: Optional[User] = update.effective_user
    msg: Optional[Message] = update.effective_message
    args = context.args or []

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if inspect.isawaitable(conn):
        conn = await conn
    if conn:
        chat = await context.bot.get_chat(conn)
        chat_id = conn
        chat_name = chat.title
    else:
        if update.effective_message.chat.type == "private":
            await send_message(
                update.effective_message,
                "This command is meant to use in group not in PM",
            )
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    if args:
        if args[0].lower() == "ban":
            settypeflood = "ban"
            sql.set_flood_strength(chat_id, 1, "0")
        elif args[0].lower() == "kick":
            settypeflood = "kick"
            sql.set_flood_strength(chat_id, 2, "0")
        elif args[0].lower() == "mute":
            settypeflood = "mute"
            sql.set_flood_strength(chat_id, 3, "0")
        elif args[0].lower() == "tban":
            if len(args) == 1:
                teks = (
                    "It looks like you tried to set time value for antiflood but you didn't specified time; "
                    "Try, <code>/setfloodmode tban &lt;timevalue&gt;</code>.\n"
                    "Examples of time value: <code>4m</code> = 4 minutes, <code>3h</code> = 3 hours, "
                    "<code>6d</code> = 6 days, <code>5w</code> = 5 weeks."
                )
                await send_message(update.effective_message, teks, parse_mode=ParseMode.HTML)
                return ""
            settypeflood = f"tban for {args[1]}"
            sql.set_flood_strength(chat_id, 4, str(args[1]))
        elif args[0].lower() == "tmute":
            if len(args) == 1:
                teks = (
                    "It looks like you tried to set time value for antiflood but you didn't specified time; "
                    "Try, <code>/setfloodmode tmute &lt;timevalue&gt;</code>.\n"
                    "Examples of time value: <code>4m</code> = 4 minutes, <code>3h</code> = 3 hours, "
                    "<code>6d</code> = 6 days, <code>5w</code> = 5 weeks."
                )
                await send_message(update.effective_message, teks, parse_mode=ParseMode.HTML)
                return ""
            settypeflood = f"tmute for {args[1]}"
            sql.set_flood_strength(chat_id, 5, str(args[1]))
        else:
            await send_message(
                update.effective_message, "I only understand ban/kick/mute/tban/tmute!"
            )
            return ""

        if conn:
            await msg.reply_text(
                f"Exceeding consecutive flood limit will result in {settypeflood} in {chat_name}!"
            )
        else:
            await msg.reply_text(
                f"Exceeding consecutive flood limit will result in {settypeflood}!"
            )
        return (
            "<b>{}:</b>\n"
            "<b>Admin:</b> {}\n"
            "Has changed antiflood mode. User will {}.".format(
                html.escape(chat.title),
                mention_html(user.id, user.first_name),
                settypeflood,
            )
        )
    else:
        getmode, getvalue = sql.get_flood_setting(chat.id)
        if getmode == 1:
            settypeflood = "ban"
        elif getmode == 2:
            settypeflood = "kick"
        elif getmode == 3:
            settypeflood = "mute"
        elif getmode == 4:
            settypeflood = f"tban for {getvalue}"
        elif getmode == 5:
            settypeflood = f"tmute for {getvalue}"
        if conn:
            await msg.reply_text(
                f"Sending more messages than flood limit will result in {settypeflood} in {chat_name}."
            )
        else:
            await msg.reply_text(
                f"Sending more message than flood limit will result in {settypeflood}."
            )
    return ""


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    limit = sql.get_flood_limit(chat_id)
    if limit == 0:
        return "Not enforcing flood control."
    else:
        return "Antiflood has been set to <code>{}</code>.".format(limit)


from tg_bot.modules.language import gs


def get_help(chat):
    return gs(chat, "antiflood_help")


__mod_name__ = "Anti-Flood"
