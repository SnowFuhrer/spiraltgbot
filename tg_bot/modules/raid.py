import html
from typing import Optional
from datetime import timedelta

from pytimeparse.timeparse import timeparse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

from .log_channel import loggable
from .helper_funcs.anonymous import user_admin, AdminPerms
from .helper_funcs.chat_status import bot_admin, connection_status, user_admin_no_reply
from .helper_funcs.decorators import kigcmd, kigcallback, rate_limit
from .. import log, application as app

import tg_bot.modules.sql.welcome_sql as sql

j = app.job_queue

# store job in a dict to be able to cancel them later
# {chat_id: job, ...}
RUNNING_RAIDS = {}


def get_time(time: str) -> int:
    try:
        return timeparse(time)
    except BaseException:
        return 0


def get_readable_time(time: int) -> str:
    t = f"{timedelta(seconds=time)}".split(":")
    if time == 86400:
        return "1 day"
    return "{} hour(s)".format(t[0]) if time >= 3600 else "{} minutes".format(t[1])


@kigcmd(command="raid", pass_args=True)
@bot_admin
@connection_status
@rate_limit(40, 60)
@loggable
@user_admin(AdminPerms.CAN_CHANGE_INFO)
async def setRaid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    args = context.args
    chat = update.effective_chat
    msg = update.effective_message
    user = update.effective_user
    if chat.type == "private":
        await context.bot.send_message(chat.id, "This command is not available in PMs.")
        return
    stat, time_val, acttime = sql.getRaidStatus(chat.id)
    readable_time = get_readable_time(time_val)
    if len(args) == 0:
        if stat:
            text = 'Raid mode is currently <code>Enabled</code>\nWould you like to <code>Disable</code> raid?'
            keyboard = [[
                InlineKeyboardButton("Disable Raid Mode", callback_data=f"disable_raid={chat.id}={time_val}"),
                InlineKeyboardButton("Cancel Action", callback_data="cancel_raid=1"),
            ]]
        else:
            text = f"Raid mode is currently <code>Disabled</code>\nWould you like to <code>Enable</code> raid for {readable_time}?"
            keyboard = [[
                InlineKeyboardButton("Enable Raid Mode", callback_data=f"enable_raid={chat.id}={time_val}"),
                InlineKeyboardButton("Cancel Action", callback_data="cancel_raid=0"),
            ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    elif args[0] == "off":
        if stat:
            sql.setRaidStatus(chat.id, False, time_val, acttime)
            job = RUNNING_RAIDS.pop(chat.id, None)
            if job:
                job.schedule_removal()
            text = "Raid mode has been <code>Disabled</code>, members that join will no longer be kicked."
            await msg.reply_text(text, parse_mode=ParseMode.HTML)
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"#RAID\n"
                f"Disabled\n"
                f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n")

    else:
        args_time = args[0].lower()
        if time := get_time(args_time):
            readable_time = get_readable_time(time)
            if 300 <= time < 86400:
                text = f"Raid mode is currently <code>Disabled</code>\nWould you like to <code>Enable</code> raid for {readable_time}? "
                keyboard = [[
                    InlineKeyboardButton("Enable Raid", callback_data=f"enable_raid={chat.id}={time}"),
                    InlineKeyboardButton("Cancel Action", callback_data="cancel_raid=0"),
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            else:
                await msg.reply_text("You can only set time between 5 minutes and 1 day", parse_mode=ParseMode.HTML)

        else:
            await msg.reply_text("Unknown time given, give me something like 5m or 1h", parse_mode=ParseMode.HTML)


@kigcallback(pattern="enable_raid=")
@rate_limit(40, 60)
@connection_status
@user_admin_no_reply
@loggable
async def enable_raid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    args = update.callback_query.data.replace("enable_raid=", "").split("=")
    chat = update.effective_chat
    user = update.effective_user
    chat_id = int(args[0])
    time_val = int(args[1])
    readable_time = get_readable_time(time_val)
    _, t, acttime = sql.getRaidStatus(chat_id)
    sql.setRaidStatus(chat_id, True, time_val, acttime)
    await update.effective_message.edit_text(f"Raid mode has been <code>Enabled</code> for {readable_time}.",
                                             parse_mode=ParseMode.HTML)
    log.info("enabled raid mode in %s for %s", chat_id, readable_time)

    old = RUNNING_RAIDS.pop(chat_id, None)
    if old:
        old.schedule_removal()

    async def disable_raid(job_context: ContextTypes.DEFAULT_TYPE):
        sql.setRaidStatus(chat_id, False, t, acttime)
        log.info("disabled raid mode in %s", chat_id)
        await job_context.bot.send_message(chat_id, "Raid mode has been automatically disabled!")

    raid_job = j.run_once(disable_raid, time_val)
    RUNNING_RAIDS[chat_id] = raid_job
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#RAID\n"
        f"Enabled for {readable_time}\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
    )


@kigcallback(pattern="disable_raid=")
@connection_status
@user_admin_no_reply
@rate_limit(40, 60)
@loggable
async def disable_raid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    args = update.callback_query.data.replace("disable_raid=", "").split("=")
    chat = update.effective_chat
    user = update.effective_user
    chat_id = int(args[0])
    time_val = int(args[1])
    _, _, acttime = sql.getRaidStatus(chat_id)
    sql.setRaidStatus(chat_id, False, time_val, acttime)
    job = RUNNING_RAIDS.pop(chat_id, None)
    if job:
        job.schedule_removal()
    await update.effective_message.edit_text(
        'Raid mode has been <code>Disabled</code>, newly joining members will no longer be kicked.',
        parse_mode=ParseMode.HTML,
    )
    logmsg = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#RAID\n"
        f"Disabled\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
    )
    return logmsg


@kigcallback(pattern="cancel_raid=")
@connection_status
@user_admin_no_reply
@rate_limit(40, 60)
async def cancel_raid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.callback_query.data.split("=")
    # args looks like ["cancel_raid", "<0|1>"]
    state = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
    await update.effective_message.edit_text(
        f"Action cancelled, Raid mode will stay <code>{'Enabled' if state == 1 else 'Disabled'}</code>.",
        parse_mode=ParseMode.HTML
    )


@kigcmd(command="raidtime")
@connection_status
@loggable
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def raidtime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    what, time_val, acttime = sql.getRaidStatus(update.effective_chat.id)
    args = context.args
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not args:
        await msg.reply_text(
            f"Raid mode is currently set to {get_readable_time(time_val)}\nWhen toggled, the raid mode will last "
            f"for {get_readable_time(time_val)} then turn off automatically",
            parse_mode=ParseMode.HTML)
        return
    args_time = args[0].lower()
    if t := get_time(args_time):
        readable_time = get_readable_time(t)
        if 300 <= t < 86400:
            text = f"Raid mode is currently set to {readable_time}\nWhen toggled, the raid mode will last for " \
                   f"{readable_time} then turn off automatically"
            await msg.reply_text(text, parse_mode=ParseMode.HTML)
            sql.setRaidStatus(chat.id, what, t, acttime)
            return (f"<b>{html.escape(chat.title)}:</b>\n"
                    f"#RAID\n"
                    f"Set Raid mode time to {readable_time}\n"
                    f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n")
        else:
            await msg.reply_text("You can only set time between 5 minutes and 1 day", parse_mode=ParseMode.HTML)
    else:
        await msg.reply_text("Unknown time given, give me something like 5m or 1h", parse_mode=ParseMode.HTML)


@kigcmd(command="raidactiontime", pass_args=True)
@connection_status
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def raidactiontime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    what, t, time_val = sql.getRaidStatus(update.effective_chat.id)
    args = context.args
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not args:
        await msg.reply_text(
            f"Raid action time is currently set to {get_readable_time(time_val)}\nWhen toggled, the members that "
            f"join will be temp banned for {get_readable_time(time_val)}",
            parse_mode=ParseMode.HTML)
        return
    args_time = args[0].lower()
    if new_t := get_time(args_time):
        readable_time = get_readable_time(new_t)
        if 300 <= new_t < 86400:
            text = f"Raid action time is currently set to {get_readable_time(new_t)}\nWhen toggled, the members that join will be temp banned for {readable_time}"
            await msg.reply_text(text, parse_mode=ParseMode.HTML)
            sql.setRaidStatus(chat.id, what, t, new_t)
            return (f"<b>{html.escape(chat.title)}:</b>\n"
                    f"#RAID\n"
                    f"Set Raid mode action time to {readable_time}\n"
                    f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n")
        else:
            await msg.reply_text("You can only set time between 5 minutes and 1 day", parse_mode=ParseMode.HTML)
    else:
        await msg.reply_text("Unknown time given, give me something like 5m or 1h", parse_mode=ParseMode.HTML)


from .language import gs


def get_help(chat):
    return gs(chat, "raid_help")


__mod_name__ = "AntiRaid"
