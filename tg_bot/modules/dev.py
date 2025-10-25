import html
import os
import re
import subprocess
import sys
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from tg_bot import DEV_USERS, application
from tg_bot.modules.helper_funcs.chat_status import dev_plus


@dev_plus
async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    args = context.args
    if args:
        chat_id = str(args[0])
        leave_msg = " ".join(args[1:]) if len(args) > 1 else None
        try:
            if leave_msg:
                await bot.send_message(chat_id, leave_msg)
            await bot.leave_chat(int(chat_id))
            await update.effective_message.reply_text("Left chat.")
        except TelegramError:
            await update.effective_message.reply_text("Failed to leave chat for some reason.")
    else:
        chat = update.effective_chat
        kb = [[
            InlineKeyboardButton(text="I am sure of this action.", callback_data=f"leavechat_cb_({chat.id})")
        ]]
        await update.effective_message.reply_text(
            f"I'm going to leave {chat.title}, press the button below to confirm",
            reply_markup=InlineKeyboardMarkup(kb),
        )


async def leave_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    callback = update.callback_query
    if callback.from_user.id not in DEV_USERS:
        await callback.answer(text="This isn't for you", show_alert=True)
        return

    match = re.match(r"leavechat_cb_\((.+?)\)", callback.data)
    if not match:
        await callback.answer()
        return
    chat = int(match.group(1))
    try:
        await bot.leave_chat(chat_id=chat)
        await callback.answer(text="Left chat")
    except TelegramError as e:
        await callback.answer(text=f"Failed: {e}", show_alert=True)


@dev_plus
async def gitpull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sent_msg = await update.effective_message.reply_text(
        "Pulling all changes from remote and then attempting to restart."
    )
    # Run git pull in a subprocess
    subprocess.Popen("git pull", stdout=subprocess.PIPE, shell=True)

    sent_msg_text = sent_msg.text + "\n\nChanges pulled...I guess.. Restarting in "

    for i in reversed(range(5)):
        await sent_msg.edit_text(sent_msg_text + str(i + 1))
        await asyncio.sleep(1)

    await sent_msg.edit_text("Restarted.")

    os.system("restart.bat")
    os.execv("start.bat", sys.argv)


@dev_plus
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Starting a new instance and shutting down this one"
    )

    os.system("restart.bat")
    os.execv("start.bat", sys.argv)


@dev_plus
async def pip_install(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    args = context.args
    if not args:
        await message.reply_text("Enter a package name.")
        return
    cmd = f"py -m pip install {' '.join(args)}"
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True,
    )
    stdout, stderr = process.communicate()
    reply = ""
    stderr_s = stderr.decode(errors="ignore")
    stdout_s = stdout.decode(errors="ignore")
    if stdout_s:
        reply += f"*Stdout*\n`{stdout_s}`\n"
    if stderr_s:
        reply += f"*Stderr*\n`{stderr_s}`\n"

    await message.reply_text(text=reply or "No output.", parse_mode=ParseMode.MARKDOWN)


@dev_plus
async def get_chat_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    args = context.args
    if not args:
        await msg.reply_text("<i>Chat ID required</i>", parse_mode=ParseMode.HTML)
        return
    data = await context.bot.get_chat(args[0])
    m = "<b>Found chat, below are the details.</b>\n\n"
    if data.title:
        m += f"<b>Title</b>: {html.escape(data.title)}\n"
    try:
        members = await context.bot.get_chat_member_count(data.id)
        m += f"<b>Members</b>: {members}\n\n"
    except TelegramError:
        pass
    if getattr(data, "description", None):
        m += f"<i>{html.escape(data.description)}</i>\n\n"
    if getattr(data, "linked_chat_id", None):
        m += f"<b>Linked chat</b>: {data.linked_chat_id}\n"

    m += f"<b>Type</b>: {data.type}\n"
    if getattr(data, "username", None):
        m += f"<b>Username</b>: {html.escape(data.username)}\n"
    m += f"<b>ID</b>: {data.id}\n"
    if getattr(data, "permissions", None):
        m += f"\n<b>Permissions</b>:\n <code>{data.permissions}</code>\n"

    await msg.reply_text(text=m, parse_mode=ParseMode.HTML)


PIP_INSTALL_HANDLER = CommandHandler("install", pip_install)
LEAVE_HANDLER = CommandHandler("leave", leave)
GITPULL_HANDLER = CommandHandler("gitpull", gitpull)
RESTART_HANDLER = CommandHandler("reboot", restart)
GET_CHAT_HANDLER = CommandHandler("getchat", get_chat_by_id)
LEAVE_CALLBACK = CallbackQueryHandler(leave_cb, pattern=r"^leavechat_cb_")

application.add_handler(LEAVE_HANDLER)
application.add_handler(GITPULL_HANDLER)
application.add_handler(RESTART_HANDLER)
application.add_handler(PIP_INSTALL_HANDLER)
application.add_handler(GET_CHAT_HANDLER)
application.add_handler(LEAVE_CALLBACK)

__mod_name__ = "Dev"
__handlers__ = [LEAVE_HANDLER, GITPULL_HANDLER, RESTART_HANDLER, PIP_INSTALL_HANDLER, GET_CHAT_HANDLER, LEAVE_CALLBACK]
