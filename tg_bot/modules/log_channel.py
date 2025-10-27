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
from tg_bot.modules.helper_funcs.anonymous import user_admin, AdminPerms
from tg_bot.modules.helper_funcs.chat_status import user_admin as u_admin, is_user_admin
from tg_bot.modules.sql import log_channel_sql as sql
from tg_bot import GBAN_LOGS, log


def get_help(chat_id):
    return gs(chat_id, "log_help")


FILENAME = __name__.rsplit(".", 1)[-1]


# -------- logging decorators --------
if is_module_loaded(FILENAME):
    def loggable(func):
        @wraps(func)
        async def log_action(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            result = await func(update, context, *args, **kwargs)
            if not result:
                return result

            chat = update.effective_chat
            message = update.effective_message

            # Compose log entry
            dt_fmt = "%H:%M - %d-%m-%Y"
            text = str(result)
            text += f"\n<b>Event Stamp</b>: <code>{datetime.now(timezone.utc).strftime(dt_fmt)}</code>"

            # Attempt to attach a message link for supergroups
            try:
                if message.chat.type == ChatType.SUPERGROUP:
                    if chat.username:
                        text += f'\n<b>Link:</b> <a href="https://t.me/{chat.username}/{message.message_id}">click here</a>'
                    else:
                        cid = str(chat.id).replace("-100", "")
                        text += f'\n<b>Link:</b> <a href="https://t.me/c/{cid}/{message.message_id}">click here</a>'
            except AttributeError:
                text += "\n<b>Link:</b> No link for manual actions."

            log_chat = sql.get_chat_log_channel(chat.id)
            if log_chat:
                await send_log(context, log_chat, chat.id, text)

            return result

        return log_action

    def gloggable(func):
        @wraps(func)
        async def glog_action(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            result = await func(update, context, *args, **kwargs)
            if not result:
                return result

            chat = update.effective_chat
            message = update.effective_message

            dt_fmt = "%H:%M - %d-%m-%Y"
            text = str(result) + "\n<b>Event Stamp</b>: <code>{}</code>".format(
                datetime.now(timezone.utc).strftime(dt_fmt)
            )

            if message.chat.type == ChatType.SUPERGROUP and chat.username:
                text += f'\n<b>Link:</b> <a href="https://t.me/{chat.username}/{message.message_id}">click here</a>'

            log_chat = str(GBAN_LOGS)
            if log_chat:
                await send_log(context, log_chat, chat.id, text)

            return result

        return glog_action
else:
    # no-op wrappers if module disabled
    def loggable(func):
        return func

    def gloggable(func):
        return func


async def send_log(
    context: ContextTypes.DEFAULT_TYPE,
    log_chat_id: int | str,
    orig_chat_id: int | str,
    result: str,
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
        msg = (excp.message or "").lower()
        if "chat not found" in msg:
            # Inform original chat and unset
            await bot.send_message(orig_chat_id, "This log channel has been deleted - unsetting.")
            sql.stop_chat_logging(int(orig_chat_id))
        else:
            log.warning("send_log BadRequest: %s", excp.message)
            log.warning("Offending log text: %s", result)
            log.exception("Could not parse HTML in send_log")
            # Retry without formatting if HTML parsing failed
            try:
                await bot.send_message(
                    log_chat_id,
                    result + "\n\nFormatting has been disabled due to an unexpected error.",
                    disable_web_page_preview=True,
                )
            except Exception:
                pass


# -------- commands --------

if is_module_loaded(FILENAME):
    @kigcmd(command="logchannel")
    @u_admin
    @rate_limit(40, 60)
    async def logging(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat = update.effective_chat

        log_channel = sql.get_chat_log_channel(chat.id)
        if not log_channel:
            await message.reply_text("No log channel has been set for this group!")
            return

        info = await bot.get_chat(log_channel)
        await message.reply_text(
            f"This group has all its logs sent to: {escape_markdown(info.title, version=2)} (`{log_channel}`)",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


@kigcmd(command="setlog")
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

    # Expect a forwarded /setlog message from the desired channel (Bot API 7.5+)
    fo = getattr(message, "forward_origin", None)
    sender_chat = getattr(fo, "sender_chat", None) if fo else None

    if sender_chat and sender_chat.type == ChatType.CHANNEL:
        sql.set_chat_log_channel(chat.id, sender_chat.id)

        # Try to delete the forwarded setup message in the group (optional)
        try:
            await message.delete()
        except BadRequest as excp:
            if (excp.message or "") != "Message to delete not found":
                log.exception("Error deleting /setlog forward in group")

        # Notify the channel (if the bot is a member) and the group
        try:
            await bot.send_message(
                sender_chat.id,
                f"This channel has been set as the log channel for {chat.title or chat.first_name}.",
            )
        except Forbidden as excp:
            if "bot is not a member" in (excp.message or "").lower():
                await bot.send_message(chat.id, "Successfully set log channel!")
            else:
                log.exception("ERROR sending confirmation to channel on setlog: %s", excp)
        else:
            await bot.send_message(chat.id, "Successfully set log channel!")
        return

    # Fallback: wrong or missing forward
    await message.reply_text(
        "The steps to set a log channel are:\n"
        " - add the bot to the desired channel (as an admin)\n"
        " - send /setlog to the channel\n"
        " - forward that /setlog to the group\n"
    )


@kigcmd(command="unsetlog")
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def unsetlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    message = update.effective_message
    chat = update.effective_chat

    log_channel = sql.stop_chat_logging(chat.id)
    if not log_channel:
        await message.reply_text("No log channel has been set yet!")
        return

    # Best-effort notify the channel that it was unlinked
    try:
        await bot.send_message(
            log_channel, f"Channel has been unlinked from {chat.title or chat.first_name}."
        )
    except Forbidden as excp:
        if "bot is not a member" not in (excp.message or "").lower():
            log.exception("unsetlog: Forbidden sending to %s: %s", log_channel, excp)
    except BadRequest as excp:
        if "chat not found" not in (excp.message or "").lower():
            log.exception("unsetlog: BadRequest sending to %s: %s", log_channel, excp)

    await message.reply_text("Log channel has been un-set.")


@kigcmd(command="logsettings")
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def log_settings(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    chat_set = sql.get_chat_setting(chat_id=chat.id)
    if not chat_set:
        sql.set_chat_setting(setting=sql.LogChannelSettings(chat.id, True, True, True, True, True))

    btn = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text="Warn", callback_data="log_tog_warn"),
                InlineKeyboardButton(text="Action", callback_data="log_tog_act"),
            ],
            [
                InlineKeyboardButton(text="Join", callback_data="log_tog_join"),
                InlineKeyboardButton(text="Leave", callback_data="log_tog_leave"),
            ],
            [InlineKeyboardButton(text="Report", callback_data="log_tog_rep")],
        ]
    )
    await update.effective_message.reply_text("Toggle channel log settings", reply_markup=btn)


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


# -------- module metadata --------

def __stats__():
    return f"• {sql.num_logchannels()} log channels set."


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    log_channel = sql.get_chat_log_channel(chat_id)
    if log_channel:
        return f"This group has all its logs sent to: (`{log_channel}`)"
    return "No log channel is set for this group!"


__help__ = """
*Admins only:*
• `/logchannel`*:* get log channel info
• `/setlog`*:* set the log channel
• `/unsetlog`*:* unset the log channel

Setting the log channel is done by:
• adding the bot to the desired channel (as an admin)
• sending `/setlog` in the channel
• forwarding that `/setlog` to the group
"""

__mod_name__ = "Logger"
