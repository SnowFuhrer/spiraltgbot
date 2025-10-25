import traceback
import html
import random
from .helper_funcs.misc import upload_text
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode
from tg_bot import KInit, application, DEV_USERS, OWNER_ID, log


class ErrorsDict(dict):
    "A custom dict to store errors and their count"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __contains__(self, error):
        error.identifier = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5))
        for e in self:
            if type(e) is type(error) and e.args == error.args:
                self[e] += 1
                return True
        self[error] = 0
        return False


errors = ErrorsDict()


async def error_callback(update: object, context: ContextTypes.DEFAULT_TYPE):
    upd = update if isinstance(update, Update) else None
    if not upd:
        # No update to show user-facing error; still continue to log/notify owner below
        pass

    e = html.escape(f"{context.error}")
    try:
        if e.find(KInit.TOKEN) != -1:
            e = e.replace(KInit.TOKEN, "TOKEN")
    except Exception:
        pass

    if upd and upd.effective_chat and upd.effective_chat.type != "channel" and getattr(KInit, "DEBUG", False):
        try:
            await context.bot.send_message(
                upd.effective_chat.id,
                text=(
                    "<b>Sorry I ran into an error!</b>\n"
                    f"<b>Error</b>: <code>{e}</code>\n"
                    "<i>This incident has been logged. No further action is required.</i>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except BaseException as ex:
            log.exception(ex)

    # Deduplicate identical errors (and assign identifier)
    if context.error in errors:
        return

    try:
        tb = "".join(
            traceback.format_exception(
                context.error.__class__, context.error, context.error.__traceback__
            )
        )
    except Exception:
        tb = f"{context.error}"

    user_str = (
        str(upd.effective_user.id)
        if upd and upd.effective_user
        else str(upd.effective_message.sender_chat.id)
        if upd and upd.effective_message and upd.effective_message.sender_chat
        else "Unknown"
    )
    chat_title = upd.effective_chat.title if upd and upd.effective_chat else ""
    chat_id = upd.effective_chat.id if upd and upd.effective_chat else ""
    cb_data = upd.callback_query.data if upd and upd.callback_query else "None"
    msg_text = upd.effective_message.text if upd and upd.effective_message else "No message"

    pretty_message = (
        "An exception was raised while handling an update\n"
        f"User: {user_str}\n"
        f"Chat: {chat_title} {chat_id}\n"
        f"Callback data: {cb_data}\n"
        f"Message: {msg_text}\n\n"
        f"Full Traceback: {tb}"
    )
    paste_url = upload_text(pretty_message)

    if not paste_url:
        with open("error.txt", "w+", encoding="utf-8") as f:
            f.write(pretty_message)
        try:
            with open("error.txt", "rb") as fbin:
                await context.bot.send_document(
                    OWNER_ID,
                    fbin,
                    caption=f"#{context.error.identifier}\n<b>Unhandled exception caught:</b>\n<code>{e}</code>",
                    parse_mode=ParseMode.HTML,
                )
        except BaseException as ex:
            log.exception(ex)
        return

    await context.bot.send_message(
        OWNER_ID,
        text=f"#{context.error.identifier}\n<b>Unhandled exception caught:</b>\n<code>{e}</code>",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("PrivateBin", url=paste_url)]]
        ),
        parse_mode=ParseMode.HTML,
    )


async def list_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id not in DEV_USERS:
        return
    e = dict(sorted(errors.items(), key=lambda item: item[1], reverse=True))
    msg = "<b>Errors List:</b>\n"
    for x, value in e.items():
        msg += f"• <code>{x}:</code> <b>{value}</b> #{x.identifier}\n"

    msg += f"{len(errors)} have occurred since startup."
    if len(msg) > 4096:
        short = "".join(f"• {x}: {value_} #{x.identifier}\n" for x, value_ in e.items())
        with open("errors_msg.txt", "w+", encoding="utf-8") as f:
            f.write(short)
        with open("errors_msg.txt", "rb") as fbin:
            await context.bot.send_document(
                update.effective_chat.id,
                fbin,
                caption="Too many errors have occurred..",
                parse_mode=ParseMode.HTML,
            )
        return
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


application.add_error_handler(error_callback)
application.add_handler(CommandHandler("errors", list_errors))
