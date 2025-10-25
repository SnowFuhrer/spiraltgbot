import html

from tg_bot import ALLOW_EXCL, dispatcher
from tg_bot.modules.disable import DisableAbleCommandHandler  # optional; may be unused
from tg_bot.modules.helper_funcs.chat_status import (
    bot_can_delete,
    connection_status,
    dev_plus,
)
from tg_bot.modules.helper_funcs.decorators import rate_limit
from tg_bot.modules.sql import cleaner_sql as sql
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters as tg_filters,
)

from ..modules.helper_funcs.anonymous import user_admin, AdminPerms

CMD_STARTERS = ("/", "!") if ALLOW_EXCL else "/"
BLUE_TEXT_CLEAN_GROUP = 13

# Base commands to always keep (fixed a missing comma bug and typos)
BASE_COMMANDS = {
    "cleanblue",
    "ignoreblue",
    "unignoreblue",
    "listblue",
    "ungignoreblue",
    "gignoreblue",
    "start",
    "help",
    "settings",
    "donate",
    "stalk",
    "aka",
    "leaderboard",
}

# Which handler classes to scan for commands
_HANDLER_CLASSES = [CommandHandler]
try:
    if DisableAbleCommandHandler:
        _HANDLER_CLASSES.append(DisableAbleCommandHandler)
except Exception:
    pass


def _collect_registered_commands():
    """
    Try to collect command names from already-registered handlers.
    Works with PTB 13/20-style dispatchers if dispatcher.handlers exists.
    Falls back to BASE_COMMANDS.
    """
    commands = set(BASE_COMMANDS)
    try:
        handlers_map = getattr(dispatcher, "handlers", None)
        if isinstance(handlers_map, dict):
            for _, group_handlers in handlers_map.items():
                for h in group_handlers:
                    if any(isinstance(h, cls) for cls in _HANDLER_CLASSES):
                        try:
                            # h.command can be set/list
                            commands.update(list(h.command))
                        except Exception:
                            pass
    except Exception:
        pass
    return commands


async def clean_blue_text_must_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    chat = update.effective_chat
    message = update.effective_message
    if not message or not message.text:
        return

    try:
        member = await chat.get_member(bot.id)
        can_delete = bool(getattr(member, "can_delete_messages", False))
    except Exception:
        can_delete = False

    if can_delete and sql.is_enabled(chat.id):
        fst_word = message.text.strip().split(None, 1)[0]

        if len(fst_word) > 1 and any(
            fst_word.startswith(start) for start in CMD_STARTERS
        ):
            command = fst_word[1:].split("@")
            # If command has @bot, only keep the part before @
            cmd_name = command[0].lower()

            # Is command ignored explicitly?
            if sql.is_command_ignored(chat.id, cmd_name):
                return

            # Avoid deleting commands our bot actually handles
            known_commands = _collect_registered_commands()
            if cmd_name not in known_commands:
                try:
                    await message.delete()
                except Exception:
                    pass


@connection_status
@bot_can_delete
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def set_blue_text_must_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    args = context.args

    if len(args) >= 1:
        val = args[0].lower()
        if val in ("off", "no"):
            sql.set_cleanbt(chat.id, False)
            reply = "Bluetext cleaning has been disabled for <b>{}</b>".format(
                html.escape(chat.title)
            )
            await message.reply_text(reply, parse_mode=ParseMode.HTML)

        elif val in ("yes", "on"):
            sql.set_cleanbt(chat.id, True)
            reply = "Bluetext cleaning has been enabled for <b>{}</b>".format(
                html.escape(chat.title)
            )
            await message.reply_text(reply, parse_mode=ParseMode.HTML)

        else:
            reply = "Invalid argument. Accepted values are 'yes', 'on', 'no', 'off'"
            await message.reply_text(reply)
    else:
        clean_status = sql.is_enabled(chat.id)
        clean_status = "Enabled" if clean_status else "Disabled"
        reply = "Bluetext cleaning for <b>{}</b> : <b>{}</b>".format(
            html.escape(chat.title), clean_status
        )
        await message.reply_text(reply, parse_mode=ParseMode.HTML)


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def add_bluetext_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    args = context.args
    if len(args) >= 1:
        val = args[0].lower()
        added = sql.chat_ignore_command(chat.id, val)
        if added:
            reply = "<b>{}</b> has been added to bluetext cleaner ignore list.".format(
                html.escape(args[0])
            )
        else:
            reply = "Command is already ignored."
        await message.reply_text(reply, parse_mode=ParseMode.HTML)
    else:
        reply = "No command supplied to be ignored."
        await message.reply_text(reply)


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def remove_bluetext_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    args = context.args
    if len(args) >= 1:
        val = args[0].lower()
        removed = sql.chat_unignore_command(chat.id, val)
        if removed:
            reply = (
                "<b>{}</b> has been removed from bluetext cleaner ignore list.".format(
                    html.escape(args[0])
                )
            )
        else:
            reply = "Command isn't ignored currently."
        await message.reply_text(reply, parse_mode=ParseMode.HTML)
    else:
        reply = "No command supplied to be unignored."
        await message.reply_text(reply)


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def add_bluetext_ignore_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    args = context.args
    if len(args) >= 1:
        val = args[0].lower()
        added = sql.global_ignore_command(val)
        if added:
            reply = "<b>{}</b> has been added to global bluetext cleaner ignore list.".format(
                html.escape(args[0])
            )
        else:
            reply = "Command is already ignored."
        await message.reply_text(reply, parse_mode=ParseMode.HTML)
    else:
        reply = "No command supplied to be ignored."
        await message.reply_text(reply)


@dev_plus
@rate_limit(40, 60)
async def remove_bluetext_ignore_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    args = context.args
    if len(args) >= 1:
        val = args[0].lower()
        removed = sql.global_unignore_command(val)
        if removed:
            reply = "<b>{}</b> has been removed from global bluetext cleaner ignore list.".format(
                html.escape(args[0])
            )
        else:
            reply = "Command isn't ignored currently."
        await message.reply_text(reply, parse_mode=ParseMode.HTML)
    else:
        reply = "No command supplied to be unignored."
        await message.reply_text(reply)


@dev_plus
@rate_limit(40, 60)
async def bluetext_ignore_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    global_ignored_list, local_ignore_list = sql.get_all_ignored(chat.id)
    text = ""

    if global_ignored_list:
        text = "The following commands are currently ignored globally from bluetext cleaning:\n"
        for x in global_ignored_list:
            text += f" - <code>{html.escape(x)}</code>\n"

    if local_ignore_list:
        text += "\nThe following commands are currently ignored locally from bluetext cleaning:\n"
        for x in local_ignore_list:
            text += f" - <code>{html.escape(x)}</code>\n"

    if text == "":
        text = "No commands are currently ignored from bluetext cleaning."
        await message.reply_text(text)
        return

    await message.reply_text(text, parse_mode=ParseMode.HTML)
    return


from tg_bot.modules.language import gs

def get_help(chat):
    return gs(chat, "cleaner_help")


SET_CLEAN_BLUE_TEXT_HANDLER = CommandHandler("cleanbluetext", set_blue_text_must_click)
ADD_CLEAN_BLUE_TEXT_HANDLER = CommandHandler("ignorecleanbluetext", add_bluetext_ignore)
REMOVE_CLEAN_BLUE_TEXT_HANDLER = CommandHandler("unignorecleanbluetext", remove_bluetext_ignore)
ADD_CLEAN_BLUE_TEXT_GLOBAL_HANDLER = CommandHandler("ignoreglobalcleanbluetext", add_bluetext_ignore_global)
REMOVE_CLEAN_BLUE_TEXT_GLOBAL_HANDLER = CommandHandler("unignoreglobalcleanbluetext", remove_bluetext_ignore_global)
LIST_CLEAN_BLUE_TEXT_HANDLER = CommandHandler("listcleanbluetext", bluetext_ignore_list)

CLEAN_BLUE_TEXT_HANDLER = MessageHandler(
    tg_filters.COMMAND & tg_filters.ChatType.GROUPS,
    clean_blue_text_must_click,
)

dispatcher.add_handler(SET_CLEAN_BLUE_TEXT_HANDLER)
dispatcher.add_handler(ADD_CLEAN_BLUE_TEXT_HANDLER)
dispatcher.add_handler(REMOVE_CLEAN_BLUE_TEXT_HANDLER)
dispatcher.add_handler(ADD_CLEAN_BLUE_TEXT_GLOBAL_HANDLER)
dispatcher.add_handler(REMOVE_CLEAN_BLUE_TEXT_GLOBAL_HANDLER)
dispatcher.add_handler(LIST_CLEAN_BLUE_TEXT_HANDLER)
dispatcher.add_handler(CLEAN_BLUE_TEXT_HANDLER, BLUE_TEXT_CLEAN_GROUP)

__mod_name__ = "Cleaner"
__handlers__ = [
    SET_CLEAN_BLUE_TEXT_HANDLER,
    ADD_CLEAN_BLUE_TEXT_HANDLER,
    REMOVE_CLEAN_BLUE_TEXT_HANDLER,
    ADD_CLEAN_BLUE_TEXT_GLOBAL_HANDLER,
    REMOVE_CLEAN_BLUE_TEXT_GLOBAL_HANDLER,
    LIST_CLEAN_BLUE_TEXT_HANDLER,
    (CLEAN_BLUE_TEXT_HANDLER, BLUE_TEXT_CLEAN_GROUP),
]
