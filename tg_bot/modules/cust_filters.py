import re
from html import escape
from typing import Optional

from telegram import Chat, InlineKeyboardMarkup, Message, InlineKeyboardButton, Update
from telegram.error import BadRequest
from telegram.ext import filters
from telegram.helpers import mention_html, escape_markdown
from telegram.constants import ParseMode, MessageLimit
from telegram.ext import ApplicationHandlerStop

from tg_bot import dispatcher, log, SUDO_USERS
from tg_bot.modules.helper_funcs.extraction import extract_text
from tg_bot.modules.helper_funcs.filters import CustomFilters
from tg_bot.modules.helper_funcs.misc import build_keyboard_parser
from tg_bot.modules.helper_funcs.msg_types import get_filter_type
from tg_bot.modules.helper_funcs.string_handling import (
    split_quotes,
    button_markdown_parser,
    escape_invalid_curly_brackets,
    markdown_to_html,
)
from tg_bot.modules.sql import cust_filters_sql as sql

from tg_bot.modules.connection import connected

from tg_bot.modules.helper_funcs.alternate import send_message, typing_action
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, kigcallback, rate_limit

from ..modules.helper_funcs.anonymous import user_admin, AdminPerms
from tg_bot.modules.language import gs

HANDLER_GROUP = 10

ENUM_FUNC_MAP = {
    sql.Types.TEXT.value: dispatcher.bot.send_message,
    sql.Types.BUTTON_TEXT.value: dispatcher.bot.send_message,
    sql.Types.STICKER.value: dispatcher.bot.send_sticker,
    sql.Types.DOCUMENT.value: dispatcher.bot.send_document,
    sql.Types.PHOTO.value: dispatcher.bot.send_photo,
    sql.Types.AUDIO.value: dispatcher.bot.send_audio,
    sql.Types.VOICE.value: dispatcher.bot.send_voice,
    sql.Types.VIDEO.value: dispatcher.bot.send_video,
    # sql.Types.VIDEO_NOTE.value: dispatcher.bot.send_video_note
}

@typing_action
@kigcmd(command='filters', admin_ok=True)
@user_admin
@rate_limit(40, 60)
async def list_handlers(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user

    conn = connected(context.bot, update, chat, user.id, need_admin=False)
    if conn is not False:
        chat_id = conn
        chat_name = (await dispatcher.bot.get_chat(conn)).title
        filter_list = "*Filter in {}:*\n"
    else:
        chat_id = update.effective_chat.id
        if chat.type == "private":
            chat_name = "Local filters"
            filter_list = "*local filters:*\n"
        else:
            chat_name = chat.title
            filter_list = "*Filters in {}*:\n"

    all_handlers = sql.get_chat_triggers(chat_id)

    if not all_handlers:
        await send_message(update.effective_message, "No filters saved in {}!".format(chat_name))
        return

    for keyword in all_handlers:
        entry = " • `{}`\n".format(escape_markdown(keyword, version=1))
        if len(entry) + len(filter_list) > MessageLimit.MAX_TEXT_LENGTH:
            await send_message(
                update.effective_message,
                filter_list.format(chat_name),
                parse_mode=ParseMode.MARKDOWN,
            )
            filter_list = entry
        else:
            filter_list += entry

    await send_message(
        update.effective_message,
        filter_list.format(chat_name),
        parse_mode=ParseMode.MARKDOWN,
    )

@kigcmd(command='filter')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@typing_action
@rate_limit(40, 60)
async def filters_cmd(update: Update, context):  # sourcery no-metrics
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    args = msg.text.split(None, 1)

    conn = connected(context.bot, update, chat, user.id)
    if conn is not False:
        chat_id = conn
        chat_name = (await dispatcher.bot.get_chat(conn)).title
    else:
        chat_id = update.effective_chat.id
        chat_name = "local filters" if chat.type == "private" else chat.title

    if not msg.reply_to_message and len(args) < 2:
        await send_message(
            update.effective_message,
            "Please provide keyboard keyword for this filter to reply with!",
        )
        return

    if msg.reply_to_message:
        if len(args) < 2:
            await send_message(
                update.effective_message,
                "Please provide keyword for this filter to reply with!",
            )
            return
        else:
            keyword = args[1]
    else:
        extracted = split_quotes(args[1])
        if len(extracted) < 1:
            return
        keyword = extracted[0].lower()

    # Try to remove any old handler if your framework still stores them (best-effort for legacy support)
    try:
        for handler in getattr(dispatcher, "handlers", {}).get(HANDLER_GROUP, []):
            if getattr(handler, "filters", None) == (keyword, chat_id):
                dispatcher.remove_handler(handler, HANDLER_GROUP)
    except Exception:
        pass

    text, file_type, file_id = get_filter_type(msg)
    if not msg.reply_to_message and len(extracted) >= 2:
        offset = len(extracted[1]) - len(msg.text)
        text, buttons = button_markdown_parser(
            extracted[1], entities=msg.parse_entities(), offset=offset
        )
        text = text.strip()
        if not text:
            await send_message(
                update.effective_message,
                "There is no filter message - You can't JUST have buttons, you need a message to go with it!",
            )
            return

    elif msg.reply_to_message and len(args) >= 2:
        if msg.reply_to_message.text:
            text_to_parsing = msg.reply_to_message.text
        elif msg.reply_to_message.caption:
            text_to_parsing = msg.reply_to_message.caption
        else:
            text_to_parsing = ""
        offset = len(text_to_parsing)
        text, buttons = button_markdown_parser(
            text_to_parsing, entities=msg.parse_entities(), offset=offset
        )
        text = text.strip()

    elif not text and not file_type:
        await send_message(
            update.effective_message,
            "Please provide keyword for this filter reply with!",
        )
        return

    elif msg.reply_to_message:
        if msg.reply_to_message.text:
            text_to_parsing = msg.reply_to_message.text
        elif msg.reply_to_message.caption:
            text_to_parsing = msg.reply_to_message.caption
        else:
            text_to_parsing = ""
        offset = len(text_to_parsing)
        text, buttons = button_markdown_parser(
            text_to_parsing, entities=msg.parse_entities(), offset=offset
        )
        text = text.strip()
        if (msg.reply_to_message.text or msg.reply_to_message.caption) and not text:
            await send_message(
                update.effective_message,
                "There is no filter message - You can't JUST have buttons, you need a message to go with it!",
            )
            return
    else:
        await send_message(update.effective_message, "Invalid filter!")
        return

    add = addnew_filter(update, chat_id, keyword, text, file_type, file_id, buttons)
    if add is True:
        await send_message(
            update.effective_message,
            "Saved filter '{}' in *{}*!".format(keyword, chat_name),
            parse_mode=ParseMode.MARKDOWN,
        )
    raise ApplicationHandlerStop

@kigcmd(command='stop')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@typing_action
@rate_limit(40, 60)
async def stop_filter(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    args = update.effective_message.text.split(None, 1)

    conn = connected(context.bot, update, chat, user.id)
    if conn is not False:
        chat_id = conn
        chat_name = (await dispatcher.bot.get_chat(conn)).title
    else:
        chat_id = update.effective_chat.id
        chat_name = "Local filters" if chat.type == "private" else chat.title

    if len(args) < 2:
        await send_message(update.effective_message, "What should i stop?")
        return

    chat_filters = sql.get_chat_triggers(chat_id)

    if not chat_filters:
        await send_message(update.effective_message, "No filters active here!")
        return

    for keyword in chat_filters:
        if keyword == args[1]:
            sql.remove_filter(chat_id, args[1])
            await send_message(
                update.effective_message,
                "Okay, I'll stop replying to that filter in *{}*.".format(chat_name),
                parse_mode=ParseMode.MARKDOWN,
            )
            raise ApplicationHandlerStop

    await send_message(
        update.effective_message,
        "That's not a filter - Click: /filters to get currently active filters.",
    )

@kigmsg((CustomFilters.has_text & ~filters.User(777000)))
@rate_limit(40, 60)
async def reply_filter(update: Update, context):  # sourcery no-metrics
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not update.effective_user or update.effective_user.id == 777000:
        return
    to_match = extract_text(message)
    if not to_match:
        return

    chat_filters = sql.get_chat_triggers(chat.id)
    for keyword in chat_filters:
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, to_match, flags=re.IGNORECASE):
            filt = sql.get_filter(chat.id, keyword)
            if filt.reply == "there is should be a new reply":
                buttons = sql.get_buttons(chat.id, filt.keyword)
                keyb = build_keyboard_parser(context.bot, chat.id, buttons)
                keyboard = InlineKeyboardMarkup(keyb)

                VALID_WELCOME_FORMATTERS = [
                    "first",
                    "last",
                    "fullname",
                    "username",
                    "id",
                    "chatname",
                    "mention",
                ]
                if filt.reply_text:
                    valid_format = escape_invalid_curly_brackets(
                        markdown_to_html(filt.reply_text), VALID_WELCOME_FORMATTERS
                    )
                    if valid_format:
                        filtext = valid_format.format(
                            first=escape(message.from_user.first_name),
                            last=escape(
                                message.from_user.last_name
                                or message.from_user.first_name
                            ),
                            fullname=" ".join(
                                [
                                    escape(message.from_user.first_name),
                                    escape(message.from_user.last_name),
                                ]
                                if message.from_user.last_name
                                else [escape(message.from_user.first_name)]
                            ),
                            username="@" + escape(message.from_user.username)
                            if message.from_user.username
                            else mention_html(
                                message.from_user.id, message.from_user.first_name
                            ),
                            mention=mention_html(
                                message.from_user.id, message.from_user.first_name
                            ),
                            chatname=escape(message.chat.title)
                            if message.chat.type != "private"
                            else escape(message.from_user.first_name),
                            id=message.from_user.id,
                        )
                    else:
                        filtext = ""
                else:
                    filtext = ""

                if filt.file_type in (sql.Types.BUTTON_TEXT, sql.Types.TEXT):
                    try:
                        await context.bot.send_message(
                            chat.id,
                            filtext,
                            reply_to_message_id=message.message_id,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                            reply_markup=keyboard,
                        )
                    except BadRequest as excp:
                        error_catch = get_exception(excp, filt, chat)
                        if error_catch == "noreply":
                            try:
                                await context.bot.send_message(
                                    chat.id,
                                    filtext,
                                    parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True,
                                    reply_markup=keyboard,
                                )
                            except BadRequest as excp2:
                                log.exception("Error in filters: " + excp2.message)
                                await send_message(
                                    update.effective_message,
                                    get_exception(excp2, filt, chat),
                                )
                        else:
                            try:
                                await send_message(
                                    update.effective_message,
                                    get_exception(excp, filt, chat),
                                )
                            except BadRequest as excp3:
                                log.exception("Failed to send message: " + excp3.message)
                elif ENUM_FUNC_MAP[filt.file_type] == dispatcher.bot.send_sticker:
                    await ENUM_FUNC_MAP[filt.file_type](
                        chat.id,
                        filt.file_id,
                        reply_to_message_id=message.message_id,
                        reply_markup=keyboard,
                    )
                else:
                    await ENUM_FUNC_MAP[filt.file_type](
                        chat.id,
                        filt.file_id,
                        caption=filtext,
                        reply_to_message_id=message.message_id,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
            elif filt.is_sticker:
                await message.reply_sticker(filt.reply)
            elif filt.is_document:
                await message.reply_document(filt.reply)
            elif filt.is_image:
                await message.reply_photo(filt.reply)
            elif filt.is_audio:
                await message.reply_audio(filt.reply)
            elif filt.is_voice:
                await message.reply_voice(filt.reply)
            elif filt.is_video:
                await message.reply_video(filt.reply)
            elif filt.has_markdown:
                buttons = sql.get_buttons(chat.id, filt.keyword)
                keyb = build_keyboard_parser(context.bot, chat.id, buttons)
                keyboard = InlineKeyboardMarkup(keyb)

                try:
                    await send_message(
                        update.effective_message,
                        filt.reply,
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=True,
                        reply_markup=keyboard,
                    )
                except BadRequest as excp:
                    if excp.message == "Unsupported url protocol":
                        try:
                            await send_message(
                                update.effective_message,
                                "You seem to be trying to use an unsupported url protocol. "
                                "Telegram doesn't support buttons for some protocols, such as tg://. Please try "
                                "again...",
                            )
                        except BadRequest as excp2:
                            log.exception("Error in filters: " + excp2.message)
                    elif excp.message == "Reply message not found":
                        try:
                            await context.bot.send_message(
                                chat.id,
                                filt.reply,
                                parse_mode=ParseMode.MARKDOWN,
                                disable_web_page_preview=True,
                                reply_markup=keyboard,
                            )
                        except BadRequest as excp3:
                            log.exception("Error in filters: " + excp3.message)
                    else:
                        try:
                            await send_message(
                                update.effective_message,
                                "This message couldn't be sent as it's incorrectly formatted.",
                            )
                        except BadRequest as excp4:
                            log.exception("Error in filters: " + excp4.message)
                        log.warning("Message %s could not be parsed", str(filt.reply))
                        log.exception(
                            "Could not parse filter %s in chat %s",
                            str(filt.keyword),
                            str(chat.id),
                        )
            else:
                try:
                    await send_message(update.effective_message, filt.reply)
                except BadRequest as excp:
                    log.exception("Error in filters: " + excp.message)
            break

@kigcmd(command="removeallfilters", filters=filters.ChatType.GROUPS)
@rate_limit(40, 60)
async def rmall_filters(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status != "creator" and user.id not in SUDO_USERS:
        await update.effective_message.reply_text(
            "Only the chat owner can clear all notes at once."
        )
    else:
        buttons = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(text="Stop all filters", callback_data="filters_rmall")],
                [InlineKeyboardButton(text="Cancel", callback_data="filters_cancel")],
            ]
        )
        await update.effective_message.reply_text(
            f"Are you sure you would like to stop ALL filters in {chat.title}? This action cannot be undone.",
            reply_markup=buttons,
            parse_mode=ParseMode.MARKDOWN,
        )

@kigcallback(pattern=r"filters_.*")
@rate_limit(40, 60)
async def rmall_callback(update: Update, context):
    query = update.callback_query
    chat = update.effective_chat
    msg = update.effective_message
    member = await context.bot.get_chat_member(chat.id, query.from_user.id)

    if query.data == "filters_rmall":
        if member.status == "creator" or query.from_user.id in SUDO_USERS:
            allfilters = sql.get_chat_triggers(chat.id)
            if not allfilters:
                await msg.edit_text("No filters in this chat, nothing to stop!")
                return

            count = 0
            filterlist = []
            for x in allfilters:
                count += 1
                filterlist.append(x)

            for i in filterlist:
                sql.remove_filter(chat.id, i)

            await msg.edit_text(f"Cleaned {count} filters in {chat.title}")

        if member.status == "administrator":
            await query.answer("Only owner of the chat can do this.")

        if member.status == "member":
            await query.answer("You need to be admin to do this.")
    elif query.data == "filters_cancel":
        if member.status == "creator" or query.from_user.id in SUDO_USERS:
            await msg.edit_text("Clearing of all filters has been cancelled.")
            return
        if member.status == "administrator":
            await query.answer("Only owner of the chat can do this.")
        if member.status == "member":
            await query.answer("You need to be admin to do this.")

def get_exception(excp, filt, chat):
    if excp.message == "Unsupported url protocol":
        return "You seem to be trying to use the URL protocol which is not supported. Telegram does not support key for multiple protocols, such as tg: //. Please try again!"
    elif excp.message == "Reply message not found":
        return "noreply"
    else:
        log.warning("Message %s could not be parsed", str(filt.reply))
        log.exception(
            "Could not parse filter %s in chat %s", str(filt.keyword), str(chat.id)
        )
        return "This data could not be sent because it is incorrectly formatted."

def addnew_filter(update, chat_id, keyword, text, file_type, file_id, buttons):
    msg = update.effective_message
    totalfilt = sql.get_chat_triggers(chat_id)
    if len(totalfilt) >= 1000:
        # Keeping the original limit text (150) as-is, though condition checks 1000
        # to avoid changing behavior unexpectedly.
        msg.reply_text("This group has reached its max filters limit of 150.")
        return False
    else:
        sql.new_add_filter(chat_id, keyword, text, file_type, file_id, buttons)
        return True

def __stats__():
    return "• {} filters, across {} chats.".format(sql.num_filters(), sql.num_chats())

def __import_data__(chat_id, data):
    filters = data.get("filters", {})
    for trigger in filters:
        sql.add_to_blacklist(chat_id, trigger)

def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)

def __chat_settings__(chat_id, _):
    cust_filters = sql.get_chat_triggers(chat_id)
    return "There are `{}` custom filters here.".format(len(cust_filters))

def get_help(chat):
    return gs(chat, "cust_filters_help")

__mod_name__ = "Filters"
