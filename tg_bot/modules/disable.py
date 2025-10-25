from typing import Union, Optional
import inspect

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, MessageHandler, ContextTypes
try:
    # PTB v20+
    from telegram.helpers import escape_markdown
except ImportError:
    # PTB v13.x
    from telegram.utils.helpers import escape_markdown

from tg_bot import application
from tg_bot.modules.helper_funcs.handlers import CMD_STARTERS
from tg_bot.modules.helper_funcs.misc import is_module_loaded
from tg_bot.modules.connection import connected

CMD_STARTERS = tuple(CMD_STARTERS)

FILENAME = __name__.rsplit(".", 1)[-1]

# If module is due to be loaded, then setup all the magical handlers
if is_module_loaded(FILENAME):
    from tg_bot.modules.helper_funcs.chat_status import (
        user_admin,
        is_user_admin,
    )

    from tg_bot.modules.sql import disable_sql as sql

    DISABLE_CMDS = []
    DISABLE_OTHER = []
    ADMIN_CMDS = []

    class DisableAbleCommandHandler(CommandHandler):
        def __init__(self, command, callback, admin_ok: bool = False, **kwargs):
            super().__init__(command, callback, **kwargs)
            self.admin_ok = admin_ok
            if isinstance(command, str):
                DISABLE_CMDS.append(command)
                if admin_ok:
                    ADMIN_CMDS.append(command)
            else:
                DISABLE_CMDS.extend(command)
                if admin_ok:
                    ADMIN_CMDS.extend(command)

        # Keep base matching; do NOT try async checks here
        def check_update(self, update: object) -> Optional[object]:
            return super().check_update(update)

        async def handle_update(self, update, application, check_result, context) -> Optional[bool]:
            # Block disabled commands for non-admins; allow for admins if admin_ok
            try:
                if isinstance(update, Update) and update.effective_message and update.effective_chat:
                    text = update.effective_message.text or ""
                    if text and len(text) > 1:
                        fst_word = text.split(None, 1)[0]
                        if any(fst_word.startswith(s) for s in CMD_STARTERS):
                            cmd_name = fst_word[1:].split("@")[0].lower()
                            if sql.is_command_disabled(update.effective_chat.id, cmd_name):
                                if self.admin_ok:
                                    is_admin = await is_user_admin(update, update.effective_user.id)
                                    if not is_admin:
                                        return False
                                else:
                                    return False
            except Exception:
                # Never block handler execution due to our own errors
                pass
            return await super().handle_update(update, application, check_result, context)

    class DisableAbleMessageHandler(MessageHandler):
        def __init__(self, pattern, callback, friendly: str = "", **kwargs):
            super().__init__(pattern, callback, **kwargs)
            self.friendly = friendly or str(pattern)
            DISABLE_OTHER.append(self.friendly)

        # Keep base matching
        def check_update(self, update: object) -> Optional[object]:
            return super().check_update(update)

        async def handle_update(self, update, application, check_result, context) -> Optional[bool]:
            try:
                if isinstance(update, Update) and update.effective_chat:
                    if sql.is_command_disabled(update.effective_chat.id, self.friendly):
                        return False
            except Exception:
                pass
            return await super().handle_update(update, application, check_result, context)

    @user_admin
    async def disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        conn = connected(context.bot, update, chat, user.id, need_admin=True)
        if inspect.isawaitable(conn):
            conn = await conn
        if conn:
            chat = await context.bot.get_chat(conn)
            chat_name = chat.title or str(conn)
        else:
            if update.effective_message.chat.type == "private":
                await update.effective_message.reply_text(
                    "This command meant to be used in group not in PM",
                )
                return ""
            chat = update.effective_chat
            chat_name = update.effective_message.chat.title

        if len(args) >= 1:
            disable_cmd = args[0]
            if disable_cmd.startswith(CMD_STARTERS):
                disable_cmd = disable_cmd[1:]

            if disable_cmd in set(DISABLE_CMDS + DISABLE_OTHER):
                sql.disable_command(chat.id, disable_cmd)
                if conn:
                    text = f"Disabled the use of `{disable_cmd}` command in *{chat_name}*!"
                else:
                    text = f"Disabled the use of `{disable_cmd}` command!"
                await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.effective_message.reply_text("This command can't be disabled")

        else:
            await update.effective_message.reply_text("What should I disable?")

    @user_admin
    async def enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        conn = connected(context.bot, update, chat, user.id, need_admin=True)
        if inspect.isawaitable(conn):
            conn = await conn
        if conn:
            chat = await context.bot.get_chat(conn)
            chat_name = chat.title or str(conn)
        else:
            if update.effective_message.chat.type == "private":
                await update.effective_message.reply_text(
                    "This command is meant to be used in group not in PM",
                )
                return ""
            chat = update.effective_chat
            chat_name = update.effective_message.chat.title

        if len(args) >= 1:
            enable_cmd = args[0]
            if enable_cmd.startswith(CMD_STARTERS):
                enable_cmd = enable_cmd[1:]

            if sql.enable_command(chat.id, enable_cmd):
                if conn:
                    text = f"Enabled the use of `{enable_cmd}` command in *{chat_name}*!"
                else:
                    text = f"Enabled the use of `{enable_cmd}` command!"
                await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.effective_message.reply_text("Is that even disabled?")

        else:
            await update.effective_message.reply_text("What should I enable?")

    @user_admin
    async def list_cmds(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if DISABLE_CMDS + DISABLE_OTHER:
            result = "".join(
                f" - `{escape_markdown(str(cmd))}`\n"
                for cmd in set(DISABLE_CMDS + DISABLE_OTHER)
            )

            await update.effective_message.reply_text(
                f"The following commands are toggleable:\n{result}",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.effective_message.reply_text("No commands can be disabled.")

    # do not async
    def build_curr_disabled(chat_id: Union[str, int]) -> str:
        disabled = sql.get_all_disabled(chat_id)
        if not disabled:
            return "No commands are disabled!"

        result = "".join(f" - `{escape_markdown(cmd)}`\n" for cmd in disabled)
        return f"The following commands are currently restricted:\n{result}"

    async def commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user
        conn = connected(context.bot, update, chat, user.id, need_admin=True)
        if inspect.isawaitable(conn):
            conn = await conn
        if conn:
            chat = await context.bot.get_chat(conn)

        text = build_curr_disabled(chat.id)
        await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    def __import_data__(chat_id, data):
        disabled = data.get("disabled", {})
        for disable_cmd in disabled:
            sql.disable_command(chat_id, disable_cmd)

    def __stats__():
        return "• {} disabled items, across {} chats.".format(
            sql.num_disabled(), sql.num_chats()
        )

    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)

    def __chat_settings__(chat_id, user_id):
        return build_curr_disabled(chat_id)

    __mod_name__ = "Disabling"

    __help__ = """
Not everyone wants every feature that the bot offers. Some commands are best left unused; to avoid spam and abuse.

This allows you to disable some commonly used commands, so noone can use them. It'll also allow you to autodelete them, stopping people from bluetexting.

 • /cmds: Check the current status of disabled commands

Admin only:
 • /enable <cmd name>: Enable that command
 • /disable <cmd name>: Disable that command
 • /listcmds: List all possible disablable commands
    """

    DISABLE_HANDLER = CommandHandler("disable", disable)
    ENABLE_HANDLER = CommandHandler("enable", enable)
    COMMANDS_HANDLER = CommandHandler(["cmds", "disabled"], commands)
    TOGGLE_HANDLER = CommandHandler("listcmds", list_cmds)

    application.add_handler(DISABLE_HANDLER)
    application.add_handler(ENABLE_HANDLER)
    application.add_handler(COMMANDS_HANDLER)
    application.add_handler(TOGGLE_HANDLER)

else:
    DisableAbleCommandHandler = CommandHandler
    DisableAbleMessageHandler = MessageHandler

from tg_bot.modules.language import gs

def get_help(chat):
    return gs(chat, "disable_help")
