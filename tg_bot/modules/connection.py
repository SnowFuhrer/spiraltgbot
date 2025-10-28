import time
import re
import html

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update, Bot
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest, Forbidden
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

import tg_bot.modules.sql.connection_sql as sql
from tg_bot import application, SUDO_USERS, DEV_USERS
from tg_bot.modules.helper_funcs import chat_status
from tg_bot.modules.helper_funcs.alternate import send_message, typing_action
from tg_bot.modules.language import gs

user_admin = chat_status.user_admin


def _status_val(status) -> str:
    return status.value if hasattr(status, "value") else status


@user_admin
@typing_action
async def allow_connections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    chat = update.effective_chat
    args = context.args

    if chat.type != ChatType.PRIVATE:
        if args and len(args) >= 1:
            var = args[0].lower()
            if var == "no":
                sql.set_allow_connect_to_chat(chat.id, False)
                await send_message(update.effective_message, "Connection has been disabled for this chat")
            elif var == "yes":
                sql.set_allow_connect_to_chat(chat.id, True)
                await send_message(update.effective_message, "Connection has been enabled for this chat")
            else:
                await send_message(
                    update.effective_message,
                    "Please enter <code>yes</code> or <code>no</code>!",
                    parse_mode=ParseMode.HTML,
                )
        else:
            get_settings = sql.allow_connect_to_chat(chat.id)
            if get_settings:
                await send_message(
                    update.effective_message,
                    "Connections to this group are <b>Allowed</b> for members!",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await send_message(
                    update.effective_message,
                    "Connections to this group are <b>Not Allowed</b> for members!",
                    parse_mode=ParseMode.HTML,
                )
    else:
        await send_message(update.effective_message, "This command is for group only. Not in PM!")


@typing_action
async def connection_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    conn = await connected(context.bot, update, chat, user.id, need_admin=True)

    if conn:
        conn_chat = await context.bot.get_chat(conn)
        chat_name = conn_chat.title
    else:
        if chat.type != ChatType.PRIVATE:
            return
        chat_name = chat.title

    if conn:
        message = f"You are currently connected to <b>{html.escape(chat_name)}</b>.\n"
    else:
        message = "You are currently not connected in any group.\n"
    await send_message(update.effective_message, message, parse_mode=ParseMode.HTML)


@typing_action
async def connect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.type == ChatType.PRIVATE:
        if args and len(args) >= 1:
            try:
                connect_chat_id = int(args[0])
                getstatusadmin = await context.bot.get_chat_member(
                    connect_chat_id, update.effective_message.from_user.id
                )
            except ValueError:
                try:
                    connect_ref = str(args[0])
                    get_chat = await context.bot.get_chat(connect_ref)
                    connect_chat_id = get_chat.id
                    getstatusadmin = await context.bot.get_chat_member(
                        connect_chat_id, update.effective_message.from_user.id
                    )
                except BadRequest:
                    await send_message(update.effective_message, "Invalid Chat ID!")
                    return
            except BadRequest:
                await send_message(update.effective_message, "Invalid Chat ID!")
                return

            status_val = _status_val(getstatusadmin.status)
            isadmin = status_val in ("administrator", "creator")
            ismember = status_val == "member"
            isallow = sql.allow_connect_to_chat(connect_chat_id)

            if isadmin or (isallow and ismember) or (user.id in SUDO_USERS):
                connection_status = sql.connect(update.effective_message.from_user.id, connect_chat_id)
                if connection_status:
                    conn_id = await connected(context.bot, update, chat, user.id, need_admin=False)
                    if conn_id:
                        conn_chat = await context.bot.get_chat(conn_id)
                        chat_name = conn_chat.title
                    else:
                        chat_name = str(connect_chat_id)
                    await send_message(
                        update.effective_message,
                        f"Successfully connected to <b>{html.escape(chat_name)}</b>.\nUse <code>/helpconnect</code> to check available commands.",
                        parse_mode=ParseMode.HTML,
                    )
                    sql.add_history_conn(user.id, str(connect_chat_id), chat_name)
                else:
                    await send_message(update.effective_message, "Connection failed!")
            else:
                await send_message(update.effective_message, "Connection to this chat is not allowed!")
        else:
            gethistory = sql.get_history_conn(user.id)
            if gethistory:
                buttons = [
                    InlineKeyboardButton(text="❎ Close button", callback_data="connect_close"),
                    InlineKeyboardButton(text="🧹 Clear history", callback_data="connect_clear"),
                ]
            else:
                buttons = []
            conn = await connected(context.bot, update, chat, user.id, need_admin=False)
            if conn:
                connectedchat = await context.bot.get_chat(conn)
                text = f"You are currently connected to <b>{html.escape(connectedchat.title)}</b> (<code>{conn}</code>)"
                buttons.append(InlineKeyboardButton(text="🔌 Disconnect", callback_data="connect_disconnect"))
            else:
                text = "Write the chat ID or tag to connect!"
            if gethistory:
                text += "\n\n<b>Connection history:</b>\n"
                text += "╒═══「 <b>Info</b> 」\n"
                text += "│  Sorted: <code>Newest</code>\n"
                text += "│\n"
                buttons = [buttons]
                for x in sorted(gethistory.keys(), reverse=True):
                    htime = time.strftime("%d/%m/%Y", time.localtime(x))
                    text += "╞═「 <b>{}</b> 」\n│   <code>{}</code>\n│   <code>{}</code>\n".format(
                        html.escape(gethistory[x]["chat_name"]), gethistory[x]["chat_id"], htime
                    )
                    text += "│\n"
                    buttons.append(
                        [
                            InlineKeyboardButton(
                                text=gethistory[x]["chat_name"],
                                callback_data="connect({})".format(gethistory[x]["chat_id"]),
                            )
                        ]
                    )
                text += "╘══「 Total {} Chats 」".format(
                    str(len(gethistory)) + " (max)" if len(gethistory) == 5 else str(len(gethistory))
                )
                conn_hist = InlineKeyboardMarkup(buttons)
            elif buttons:
                conn_hist = InlineKeyboardMarkup([buttons])
            else:
                conn_hist = None
            await send_message(update.effective_message, text, parse_mode=ParseMode.HTML, reply_markup=conn_hist)

    else:
        getstatusadmin = await context.bot.get_chat_member(chat.id, update.effective_message.from_user.id)
        status_val = _status_val(getstatusadmin.status)
        isadmin = status_val in ("administrator", "creator")
        ismember = status_val == "member"
        isallow = sql.allow_connect_to_chat(chat.id)
        if isadmin or (isallow and ismember) or (user.id in SUDO_USERS):
            connection_status = sql.connect(update.effective_message.from_user.id, chat.id)
            if connection_status:
                chat_name = (await context.bot.get_chat(chat.id)).title
                safe_name = html.escape(chat_name)
                await send_message(
                    update.effective_message,
                    f"Successfully connected to <b>{safe_name}</b>.",
                    parse_mode=ParseMode.HTML,
                )
                try:
                    sql.add_history_conn(user.id, str(chat.id), chat_name)
                    await context.bot.send_message(
                        update.effective_message.from_user.id,
                        f"You are connected to <b>{safe_name}</b>.\nUse <code>/helpconnect</code> to check available commands.",
                        parse_mode=ParseMode.HTML,
                    )
                except BadRequest:
                    pass
                except Forbidden:
                    pass
            else:
                await send_message(update.effective_message, "Connection failed!")
        else:
            await send_message(update.effective_message, "Connection to this chat is not allowed!")


async def disconnect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        disconnection_status = sql.disconnect(update.effective_message.from_user.id)
        if disconnection_status:
            sql.disconnected_chat = await send_message(update.effective_message, "Disconnected from chat!")
        else:
            await send_message(update.effective_message, "You're not connected!")
    else:
        await send_message(update.effective_message, "This command is only available in PM.")


async def connected(bot: Bot, update: Update, chat, user_id, need_admin=True):
    user = update.effective_user

    if chat.type == ChatType.PRIVATE and sql.get_connected_chat(user_id):
        conn_id = sql.get_connected_chat(user_id).chat_id
        getstatusadmin = await bot.get_chat_member(conn_id, update.effective_message.from_user.id)
        status_val = _status_val(getstatusadmin.status)
        isadmin = status_val in ("administrator", "creator")
        ismember = status_val == "member"
        isallow = sql.allow_connect_to_chat(conn_id)

        if isadmin or (isallow and ismember) or (user.id in SUDO_USERS) or (user.id in DEV_USERS):
            if not need_admin:
                return conn_id
            if isadmin or user_id in SUDO_USERS or user.id in DEV_USERS:
                return conn_id
            else:
                await send_message(update.effective_message, "You must be an admin in the connected group!")
        else:
            await send_message(
                update.effective_message,
                "The group changed the connection rights or you are no longer an admin.\nI've disconnected you.",
            )
            # Directly disconnect without calling another handler to avoid context issues here
            sql.disconnect(update.effective_message.from_user.id)
    else:
        return False


CONN_HELP = (
    "Actions are available with connected groups:\n"
    " • View and edit Notes.\n"
    " • View and edit Filters.\n"
    " • Get invite link of chat.\n"
    " • Set and control AntiFlood settings.\n"
    " • Set and control Blacklist settings.\n"
    " • Set Locks and Unlocks in chat.\n"
    " • Enable and Disable commands in chat.\n"
    " • Export and Imports of chat backup.\n"
    " • More in future!"
)


async def help_connect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message.chat.type != ChatType.PRIVATE:
        await send_message(update.effective_message, "PM me with that command to get help.")
        return
    else:
        await send_message(update.effective_message, CONN_HELP, parse_mode=ParseMode.HTML)


async def connect_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user

    connect_match = re.match(r"connect\((.+?)\)", query.data or "")
    disconnect_match = (query.data == "connect_disconnect")
    clear_match = (query.data == "connect_clear")
    connect_close = (query.data == "connect_close")

    if connect_match:
        target_chat = connect_match.group(1)
        getstatusadmin = await context.bot.get_chat_member(target_chat, query.from_user.id)
        status_val = _status_val(getstatusadmin.status)
        isadmin = status_val in ("administrator", "creator")
        ismember = status_val == "member"
        isallow = sql.allow_connect_to_chat(target_chat)

        if isadmin or (isallow and ismember) or (user.id in SUDO_USERS):
            connection_status = sql.connect(query.from_user.id, target_chat)

            if connection_status:
                conn = await connected(context.bot, update, chat, user.id, need_admin=False)
                if conn:
                    conn_chat = await context.bot.get_chat(conn)
                    chat_name = conn_chat.title
                else:
                    chat_name = str(target_chat)
                await query.message.edit_text(
                    f"Successfully connected to <b>{html.escape(chat_name)}</b>.\nUse <code>/helpconnect</code> to check available commands.",
                    parse_mode=ParseMode.HTML,
                )
                sql.add_history_conn(user.id, str(conn if conn else target_chat), chat_name)
            else:
                await query.message.edit_text("Connection failed!")
        else:
            await context.bot.answer_callback_query(
                query.id, "Connection to this chat is not allowed!", show_alert=True
            )
    elif disconnect_match:
        disconnection_status = sql.disconnect(query.from_user.id)
        if disconnection_status:
            sql.disconnected_chat = await query.message.edit_text("Disconnected from chat!")
        else:
            await context.bot.answer_callback_query(query.id, "You're not connected!", show_alert=True)
    elif clear_match:
        sql.clear_history_conn(query.from_user.id)
        await query.message.edit_text("History connected has been cleared!")
    elif connect_close:
        await query.message.edit_text("Closed.\nTo open again, type /connect")
    else:
        await connect_chat(update, context)


def get_help(chat):
    return gs(chat, "connections_help")


CONNECT_CHAT_HANDLER = CommandHandler("connect", connect_chat)
CONNECTION_CHAT_HANDLER = CommandHandler("connection", connection_chat)
DISCONNECT_CHAT_HANDLER = CommandHandler("disconnect", disconnect_chat)
ALLOW_CONNECTIONS_HANDLER = CommandHandler("allowconnect", allow_connections)
HELP_CONNECT_CHAT_HANDLER = CommandHandler("helpconnect", help_connect_chat)
CONNECT_BTN_HANDLER = CallbackQueryHandler(connect_button, pattern=r"^connect")

# Register handlers on PTB 22+ Application (no legacy fallback)
application.add_handler(CONNECT_CHAT_HANDLER)
application.add_handler(CONNECTION_CHAT_HANDLER)
application.add_handler(DISCONNECT_CHAT_HANDLER)
application.add_handler(ALLOW_CONNECTIONS_HANDLER)
application.add_handler(HELP_CONNECT_CHAT_HANDLER)
application.add_handler(CONNECT_BTN_HANDLER)

__mod_name__ = "Connection"
__handlers__ = [
    CONNECT_CHAT_HANDLER,
    CONNECTION_CHAT_HANDLER,
    DISCONNECT_CHAT_HANDLER,
    ALLOW_CONNECTIONS_HANDLER,
    HELP_CONNECT_CHAT_HANDLER,
    CONNECT_BTN_HANDLER,
]
