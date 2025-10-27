from datetime import datetime, timezone
from functools import wraps

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest, Forbidden
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from tg_bot.modules.helper_funcs.decorators import kigcmd, kigcallback, rate_limit
from tg_bot.modules.helper_funcs.misc import is_module_loaded
from tg_bot.modules.language import gs

from ..modules.helper_funcs.anonymous import user_admin, AdminPerms


def get_help(chat):
    return gs(chat, "log_help")


FILENAME = __name__.rsplit(".", 1)[-1]

if is_module_loaded(FILENAME):
    from tg_bot import GBAN_LOGS, log, application  # application for PTB 20+
    from tg_bot.modules.helper_funcs.chat_status import user_admin as u_admin, is_user_admin
    from tg_bot.modules.sql import log_channel_sql as sql

    def loggable(func):
        @wraps(func)
        async def log_action(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            result = await func(update, context, *args, **kwargs)
            chat = update.effective_chat
            message = update.effective_message

            if result:
                datetime_fmt = "%H:%M - %d-%m-%Y"
                result = str(result)
                result += f"\n<b>Event Stamp</b>: <code>{datetime.now(timezone.utc).strftime(datetime_fmt)}</code>"
                try:
                    if message.chat.type == ChatType.SUPERGROUP:
                        if message.chat.username:
                            result += f'\n<b>Link:</b> <a href="https://t.me/{chat.username}/{message.message_id}">click here</a>'
                        else:
                            cid = str(chat.id).replace("-100", "")
                            result += f'\n<b>Link:</b> <a href="https://t.me/c/{cid}/{message.message_id}">click here</a>'
                except AttributeError:
                    result += '\n<b>Link:</b> No link for manual actions.'  # or just without the whole line
                log_chat = sql.get_chat_log_channel(chat.id)
                if log_chat:
                    await send_log(context, log_chat, chat.id, result)

            return result

        return log_action

    def gloggable(func):
        @wraps(func)
        async def glog_action(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            result = await func(update, context, *args, **kwargs)
            chat = update.effective_chat
            message = update.effective_message

            if result:
                datetime_fmt = "%H:%M - %d-%m-%Y"
                result += "\n<b>Event Stamp</b>: <code>{}</code>".format(
                    datetime.now(timezone.utc).strftime(datetime_fmt)
                )

                if message.chat.type == ChatType.SUPERGROUP and message.chat.username:
                    result += f'\n<b>Link:</b> <a href="https://t.me/{chat.username}/{message.message_id}">click here</a>'
                log_chat = str(GBAN_LOGS)
                if log_chat:
                    await send_log(context, log_chat, chat.id, result)

            return result

        return glog_action

    async def send_log(
        context: ContextTypes.DEFAULT_TYPE, log_chat_id: str, orig_chat_id: str, result: str
    ):
        bot = context.bot
        try:
            await bot.send_message(
                log_chat_id,
                result,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except BadRequest as excp:
            if excp.message == "Chat not found":
                await bot.send_message(orig_chat_id, "This log channel has been deleted - unsetting.")
                sql.stop_chat_logging(orig_chat_id)
            else:
                log.warning(excp.message)
                log.warning(result)
                log.exception("Could not parse")

                await bot.send_message(
                    log_chat_id,
                    result + "\n\nFormatting has been disabled due to an unexpected error.",
                )

    @kigcmd(command='logchannel')
    @u_admin
    @rate_limit(40, 60)
    async def logging(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat = update.effective_chat

        log_channel = sql.get_chat_log_channel(chat.id)
        if log_channel:
            log_channel_info = await bot.get_chat(log_channel)
            await message.reply_text(
                f"This group has all it's logs sent to: {escape_markdown(log_channel_info.title, version=2)} (`{log_channel}`)",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        else:
            await message.reply_text("No log channel has been set for this group!")

@kigcmd(command='setlog')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def setlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    message = update.effective_message
    chat = update.effective_chat

    # If run inside the channel itself, instruct to forward to the target group
    if chat.type == ChatType.CHANNEL:
        await message.reply_text(
            "Now, forward the /setlog to the group you want to tie this channel to!"
        )
        return

    # Expect a forwarded /setlog message from the desired channel
    fo = getattr(message, "forward_origin", None)
    sender_chat = getattr(fo, "sender_chat", None) if fo else None

    if sender_chat and sender_chat.type == ChatType.CHANNEL:
        sql.set_chat_log_channel(chat.id, sender_chat.id)

        # Try to delete the setup message in the group (optional)
        try:
            await message.delete()
        except BadRequest as excp:
            if excp.message != "Message to delete not found":
                log.exception(
                    "Error deleting message in log channel. Should work anyway though."
                )

        # Notify the channel (if the bot is a member) and the group
        try:
            await bot.send_message(
                sender_chat.id,
                f"This channel has been set as the log channel for {chat.title or chat.first_name}.",
            )
        except Forbidden as excp:
            # Bot not in channel: still confirm in the group
            if "bot is not a member" in (excp.message or "").lower():
                await bot.send_message(chat.id, "Successfully set log channel!")
            else:
                log.exception("ERROR in setting the log channel.")
        else:
            await bot.send_message(chat.id, "Successfully set log channel!")

        return

    # Fallback: wrong or missing forward
    await message.reply_text(
        "The steps to set a log channel are:\n"
        " - add bot to the desired channel\n"
        " - send /setlog to the channel\n"
        " - forward the /setlog to the group\n"
    )

    @kigcmd(command='unsetlog')
    @user_admin(AdminPerms.CAN_CHANGE_INFO)
    @rate_limit(40, 60)
    async def unsetlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat = update.effective_chat

        log_channel = sql.stop_chat_logging(chat.id)
        if log_channel:
            await bot.send_message(
                log_channel, f"Channel has been unlinked from {chat.title}"
            )
            await message.reply_text("Log channel has been un-set.")

        else:
            await message.reply_text("No log channel has been set yet!")

    def __stats__():
        return f"• {sql.num_logchannels()} log channels set."

    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)

    def __chat_settings__(chat_id, user_id):
        log_channel = sql.get_chat_log_channel(chat_id)
        if log_channel:
            # PTB 20+ would need async get_chat. Keep it simple here.
            return f"This group has all it's logs sent to: (`{log_channel}`)"
        return "No log channel is set for this group!"

    __help__ = """
*Admins only:*
• `/logchannel`*:* get log channel info
• `/setlog`*:* set the log channel.
• `/unsetlog`*:* unset the log channel.

Setting the log channel is done by:
• adding the bot to the desired channel (as an admin!)
• sending `/setlog` in the channel
• forwarding the `/setlog` to the group
"""

    __mod_name__ = "Logger"

else:
    # run anyway if module not loaded
    def loggable(func):
        return func

    def gloggable(func):
        return func


@kigcmd("logsettings")
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def log_settings(update: Update, _: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton  # ensure available

    chat = update.effective_chat
    chat_set = sql.get_chat_setting(chat_id=chat.id)
    if not chat_set:
        sql.set_chat_setting(setting=sql.LogChannelSettings(chat.id, True, True, True, True, True))
    btn = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text="Warn", callback_data="log_tog_warn"),
                InlineKeyboardButton(text="Action", callback_data="log_tog_act")
            ],
            [
                InlineKeyboardButton(text="Join", callback_data="log_tog_join"),
                InlineKeyboardButton(text="Leave", callback_data="log_tog_leave")
            ],
            [
                InlineKeyboardButton(text="Report", callback_data="log_tog_rep")
            ]
        ]
    )
    msg = update.effective_message
    await msg.reply_text("Toggle channel log settings", reply_markup=btn)


from tg_bot.modules.sql import log_channel_sql as sql
from tg_bot.modules.helper_funcs.chat_status import is_user_admin


@kigcallback(pattern=r"log_tog_.*")
@rate_limit(40, 60)
async def log_setting_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cb = update.callback_query
    user = cb.from_user
    chat = cb.message.chat
    if not await is_user_admin(update, user.id):
        await cb.answer("You aren't admin", show_alert=True)
        return
    setting = cb.data.replace("log_tog_", "")
    chat_set = sql.get_chat_setting(chat_id=chat.id)
    if not chat_set:
        sql.set_chat_setting(setting=sql.LogChannelSettings(chat.id, True, True, True, True, True))

    t = sql.get_chat_setting(chat.id)
    if setting == "warn":
        r = t.toggle_warn()
        await cb.answer(f"Warning log set to {r}")
        return
    if setting == "act":
        r = t.toggle_action()
        await cb.answer(f"Action log set to {r}")
        return
    if setting == "join":
        r = t.toggle_joins()
        await cb.answer(f"Join log set to {r}")
        return
    if setting == "leave":
        r = t.toggle_leave()
        await cb.answer(f"Leave log set to {r}")
        return
    if setting == "rep":
        r = t.toggle_report()
        await cb.answer(f"Report log set to {r}")
        return

    await cb.answer("Idk what to do")
