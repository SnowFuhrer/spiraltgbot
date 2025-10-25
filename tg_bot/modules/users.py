import contextlib
from io import BytesIO
from asyncio import sleep

import tg_bot.modules.sql.users_sql as sql
from tg_bot import DEV_USERS, log, OWNER_ID, dispatcher
from tg_bot.modules.helper_funcs.chat_status import dev_plus, sudo_plus
from tg_bot.modules.sql.users_sql import get_all_users
from telegram import Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
)
from telegram.constants import ChatMemberStatus
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, kigcallback, rate_limit

USERS_GROUP = 4
CHAT_GROUP = 5
DEV_AND_MORE = DEV_USERS.append(int(OWNER_ID))  # unchanged

try:
    BAN_STATUS = ChatMemberStatus.BANNED
except AttributeError:
    # Older PTB/Bot API
    BAN_STATUS = ChatMemberStatus.KICKED

def is_message_forwarded(msg) -> bool:
    # New-style (Bot API >= 7.5)
    if getattr(msg, "forward_origin", None) is not None:
        return True
    # Legacy fields (older Bot API/PTB)
    if getattr(msg, "forward_from", None) is not None:
        return True
    if getattr(msg, "forward_from_chat", None) is not None:
        return True
    if getattr(msg, "is_automatic_forward", False):
        return True
    return False

async def get_user_id(username):
    # ensure valid userid
    if not username or len(username) <= 5:
        return None

    if username.startswith("@"):
        username = username[1:]

    users = sql.get_userid_by_name(username)

    if not users:
        return None

    elif len(users) == 1:
        return users[0].user_id

    else:
        for user_obj in users:
            try:
                userdat = await dispatcher.bot.get_chat(user_obj.user_id)
                if userdat.username == username:
                    return userdat.id

            except BadRequest as excp:
                if excp.message != "Chat not found":
                    log.exception("Error extracting user ID")

    return None


@dev_plus
@rate_limit(40, 60)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    to_send = update.effective_message.text.split(None, 1)

    if len(to_send) >= 2:
        to_group = False
        to_user = False
        if to_send[0] == "/broadcastgroups":
            to_group = True
        if to_send[0] == "/broadcastusers":
            to_user = True
        else:
            to_group = to_user = True

        chats = sql.get_all_chats() or []
        users = get_all_users()
        failed = 0
        failed_user = 0

        if to_group:
            for chat in chats:
                try:
                    await context.bot.send_message(
                        int(chat.chat_id),
                        to_send[1],
                        parse_mode="MARKDOWN",
                        disable_web_page_preview=True,
                    )
                    await sleep(0.1)
                except TelegramError:
                    failed += 1
        if to_user:
            for user in users:
                try:
                    await context.bot.send_message(
                        int(user.user_id),
                        to_send[1],
                        parse_mode="MARKDOWN",
                        disable_web_page_preview=True,
                    )
                    await sleep(0.1)
                except TelegramError:
                    failed_user += 1

        await update.effective_message.reply_text(
            f"Broadcast complete.\nGroups failed: {failed}.\nUsers failed: {failed_user}."
        )


def welcomeFilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    if update.chat_member and update.chat_member.new_chat_member:
        nm = update.chat_member.new_chat_member
        om = update.chat_member.old_chat_member
    else:
        return

    if (nm.status, om.status) in [
        (ChatMemberStatus.MEMBER, BAN_STATUS),
        (ChatMemberStatus.MEMBER, ChatMemberStatus.LEFT),
        (BAN_STATUS, ChatMemberStatus.MEMBER),
        (BAN_STATUS, ChatMemberStatus.ADMINISTRATOR),
        (BAN_STATUS, ChatMemberStatus.OWNER),
        (ChatMemberStatus.LEFT, ChatMemberStatus.MEMBER),
        (ChatMemberStatus.LEFT, ChatMemberStatus.ADMINISTRATOR),
        (ChatMemberStatus.LEFT, ChatMemberStatus.OWNER),
    ]:
        return log_user(update, context)


@rate_limit(30, 60)
async def log_user(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message

    if not msg and update.chat_member:  # ChatMemberUpdate for join/leave
        sql.update_user(
            update.effective_user.id, update.effective_user.username, chat.id, chat.title
        )
        return

    sql.update_user(msg.from_user.id, msg.from_user.username, chat.id, chat.title)

    if rep := msg.reply_to_message:
        sql.update_user(
            rep.from_user.id,
            rep.from_user.username,
            chat.id,
            chat.title,
        )

        if is_message_forwarded(msg):
            sql.update_user(
                rep.forward_from.id,
                rep.forward_from.username,
            )

        if rep.entities:
            for entity in rep.entities:
                if entity.type in ["text_mention", "mention"]:
                    with contextlib.suppress(AttributeError):
                        sql.update_user(entity.user.id, entity.user.username)
        if rep.sender_chat and not rep.is_automatic_forward:
            sql.update_user(
                rep.sender_chat.id,
                rep.sender_chat.username,
                chat.id,
                chat.title,
            )

    if is_message_forwarded(msg):
        sql.update_user(msg.forward_from.id, msg.forward_from.username)

    if msg.entities:
        for entity in msg.entities:
            if entity.type in ["text_mention", "mention"]:
                with contextlib.suppress(AttributeError):
                    sql.update_user(entity.user.id, entity.user.username)
    if msg.sender_chat and not msg.is_automatic_forward:
        sql.update_user(msg.sender_chat.id, msg.sender_chat.username, chat.id, chat.title)

    if msg.new_chat_members:
        for user in msg.new_chat_members:
            if user.id == msg.from_user.id:  # we already added that in the first place
                continue
            sql.update_user(user.id, user.username, chat.id, chat.title)


@sudo_plus
@rate_limit(40, 60)
async def chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_chats = sql.get_all_chats() or []
    chatfile = "List of chats.\n0. Chat name | Chat ID | Members count\n"
    P = 1
    for chat in all_chats:
        try:
            curr_chat = await context.bot.get_chat(chat.chat_id)
            # bot_member = await curr_chat.get_member(context.bot.id)  # not used
            chat_members = await context.bot.get_chat_member_count(chat.chat_id)
            chatfile += "{}. {} | {} | {}\n".format(
                P, chat.chat_name, chat.chat_id, chat_members
            )
            P += 1
        except Exception:
            pass

    with BytesIO(str.encode(chatfile)) as output:
        output.name = "glist.txt"
        await update.effective_message.reply_document(
            document=output,
            filename="glist.txt",
            caption="Here be the list of groups in my database.",
        )


@rate_limit(50, 60)
async def chat_checker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    member = await update.effective_chat.get_member(bot.id)
    can_send = getattr(member, "can_send_messages", None)
    if can_send is False:
        await bot.leave_chat(update.effective_chat.id)


def __user_info__(user_id):
    if user_id in [777000, 1087968824]:
        return """Groups count: <code>N/A</code>"""
    if user_id == dispatcher.bot.id:
        return """Groups count: <code>N/A</code>"""
    num_chats = sql.get_user_num_chats(user_id)
    return f"""Groups count: <code>{num_chats}</code>"""


def __stats__():
    return f"• {sql.num_users()} users, across {sql.num_chats()} chats"


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


__help__ = ""  # no help string

BROADCAST_HANDLER = CommandHandler(
    ["broadcastall", "broadcastusers", "broadcastgroups"], broadcast
)
USER_HANDLER = MessageHandler(
    filters.ALL & filters.ChatType.GROUPS & ~filters.User(777000), log_user
)
CHAT_CHECKER_HANDLER = MessageHandler(
    filters.ALL & filters.ChatType.GROUPS & ~filters.User(777000), chat_checker
)

dispatcher.add_handler(
    ChatMemberHandler(
        welcomeFilter, ChatMemberHandler.CHAT_MEMBER
    ),
    group=110,
)

dispatcher.add_handler(USER_HANDLER, USERS_GROUP)
dispatcher.add_handler(BROADCAST_HANDLER)
dispatcher.add_handler(CHAT_CHECKER_HANDLER, CHAT_GROUP)

__mod_name__ = "Users"
__handlers__ = [(USER_HANDLER, USERS_GROUP), BROADCAST_HANDLER]
