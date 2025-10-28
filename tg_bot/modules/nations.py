import html
import json
import os
from typing import List, Optional

from telegram import Update, Bot
from telegram.constants import ParseMode, ChatType
from telegram.error import TelegramError
from telegram.helpers import mention_html
from telegram.ext import ContextTypes

from tg_bot import (
    dispatcher,  # kept import if used elsewhere in project
    WHITELIST_USERS,
    SARDEGNA_USERS,
    SUPPORT_USERS,
    SUDO_USERS,
    DEV_USERS,
    OWNER_ID,
)
from tg_bot.modules.helper_funcs.chat_status import whitelist_plus, dev_plus, sudo_plus
from tg_bot.modules.helper_funcs.extraction import extract_user
from tg_bot.modules.log_channel import gloggable
from tg_bot.modules.sql import nation_sql as sql
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit

def check_user_id(user_id: int, bot: Bot) -> Optional[str]:
    if not user_id:
        return "That...is a chat."

    elif user_id == bot.id:
        return "This does not work that way."

    else:
        return None

@kigcmd(command='addsudo')
@dev_plus
@gloggable
@rate_limit(40, 60)
async def addsudo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)
    rt = ""

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in SUDO_USERS:
        await message.reply_text("This member is already a sudo user")
        return ""

    if user_id in SUPPORT_USERS:
        rt += "Promoted a support user to sudo."
        SUPPORT_USERS.remove(user_id)

    if user_id in WHITELIST_USERS:
        rt += "Promoted a whitelisted user to sudo."
        WHITELIST_USERS.remove(user_id)

    # will add or update their role
    sql.set_royal_role(user_id, "sudos")
    SUDO_USERS.append(user_id)

    await update.effective_message.reply_text(
        rt
        + "\nSuccessfully promoted {} to Sudo!".format(
            user_member.first_name
        )
    )

    log_message = (
        f"#SUDO\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
        f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
    )

    if chat.type != ChatType.PRIVATE:
        log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

    return log_message


@kigcmd(command='addsupport')
@sudo_plus
@gloggable
@rate_limit(40, 60)
async def addsupport(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)
    rt = ""

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in SUDO_USERS:
        rt += "Requested to demote this Sudo to Support"
        SUDO_USERS.remove(user_id)

    if user_id in SUPPORT_USERS:
        await message.reply_text("This user is already a Support user.")
        return ""

    if user_id in WHITELIST_USERS:
        rt += "Requested to promote this Whitelist user to Support"
        WHITELIST_USERS.remove(user_id)

    sql.set_royal_role(user_id, "supports")
    SUPPORT_USERS.append(user_id)

    await update.effective_message.reply_text(
        rt + f"\n{user_member.first_name} was added as a Support user!"
    )

    log_message = (
        f"#SUPPORT\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
        f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
    )

    if chat.type != ChatType.PRIVATE:
        log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

    return log_message


@kigcmd(command='addwhitelist')
@sudo_plus
@gloggable
@rate_limit(40, 60)
async def addwhitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)
    rt = ""

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in SUDO_USERS:
        rt += "This member is a Sudo user, Demoting to Whitelisted user."
        SUDO_USERS.remove(user_id)

    if user_id in SUPPORT_USERS:
        rt += "This user is already a Support user, Demoting to Whitelisted user."
        SUPPORT_USERS.remove(user_id)

    if user_id in WHITELIST_USERS:
        await message.reply_text("This user is already a Whitelist user.")
        return ""

    sql.set_royal_role(user_id, "whitelists")
    WHITELIST_USERS.append(user_id)

    await update.effective_message.reply_text(
        rt + f"\nSuccessfully promoted {user_member.first_name} to a Whitelist user!"
    )

    log_message = (
        f"#WHITELIST\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))} \n"
        f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
    )

    if chat.type != ChatType.PRIVATE:
        log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

    return log_message


@kigcmd(command='addswhitelist')
@sudo_plus
@gloggable
@rate_limit(40, 60)
async def addsardegna(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)
    rt = ""

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in SUDO_USERS:
        rt += "This member is a Sudo user, Demoting to whitelisted."
        SUDO_USERS.remove(user_id)

    if user_id in SUPPORT_USERS:
        rt += "This user is already a Support user, Demoting to whitelisted."
        SUPPORT_USERS.remove(user_id)

    if user_id in WHITELIST_USERS:
        rt += "This user is already a pro user, Demoting to whitelisted."
        WHITELIST_USERS.remove(user_id)

    if user_id in SARDEGNA_USERS:
        await message.reply_text("This user is already a whitelisted user.")
        return ""

    sql.set_royal_role(user_id, "whitelist")
    SARDEGNA_USERS.append(user_id)

    await update.effective_message.reply_text(
        rt + f"\nSuccessfully promoted {user_member.first_name} to a whitelisted user!"
    )

    log_message = (
        f"#WHITELIST\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))} \n"
        f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
    )

    if chat.type != ChatType.PRIVATE:
        log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

    return log_message


@kigcmd(command='removesudo')
@dev_plus
@gloggable
@rate_limit(40, 60)
async def removesudo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in SUDO_USERS:
        await message.reply_text("Requested to demote this user to Civilian")
        SUDO_USERS.remove(user_id)
        sql.remove_royal(user_id)

        log_message = (
            f"#UNSUDO\n"
            f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
            f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
        )

        if chat.type != ChatType.PRIVATE:
            log_message = "<b>{}:</b>\n".format(html.escape(chat.title)) + log_message

        return log_message

    else:
        await message.reply_text("This user is not a Sudo user!")
        return ""


@kigcmd(command='removesupport')
@sudo_plus
@gloggable
@rate_limit(40, 60)
async def removesupport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in SUPPORT_USERS:
        await message.reply_text("Requested Eagle Union to demote this user to Civilian")
        SUPPORT_USERS.remove(user_id)
        sql.remove_royal(user_id)

        log_message = (
            f"#UNSUPPORT\n"
            f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
            f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
        )

        if chat.type != ChatType.PRIVATE:
            log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

        return log_message

    else:
        await message.reply_text("This user is not a Support user!")
        return ""


@kigcmd(command='unpro')
@sudo_plus
@gloggable
@rate_limit(40, 60)
async def removewhitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in WHITELIST_USERS:
        await message.reply_text("Demoting to normal user")
        WHITELIST_USERS.remove(user_id)
        sql.remove_royal(user_id)

        log_message = (
            f"#UNWHITELIST\n"
            f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
            f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
        )

        if chat.type != ChatType.PRIVATE:
            log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

        return log_message
    else:
        await message.reply_text("This user is not a pro user!")
        return ""


@kigcmd(command='unwhitelist')
@sudo_plus
@gloggable
@rate_limit(40, 60)
async def removesardegna(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    bot, args = context.bot, context.args
    user_id = await extract_user(message, args)
    user_member = await bot.get_chat(user_id)

    reply = check_user_id(user_id, bot)
    if reply:
        await message.reply_text(reply)
        return ""

    if user_id in SARDEGNA_USERS:
        await message.reply_text("Demoting to normal user")
        SARDEGNA_USERS.remove(user_id)
        sql.remove_royal(user_id)

        log_message = (
            f"#UNSARDEGNA\n"
            f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}\n"
            f"<b>User:</b> {mention_html(user_member.id, html.escape(user_member.first_name))}"
        )

        if chat.type != ChatType.PRIVATE:
            log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

        return log_message
    else:
        await message.reply_text("This user is not a whitelisted user!")
        return ""

# I added extra new lines
nations = """ Spiral has bot access levels we call as *"Nation Levels"*
\n*Devs* - Devs who can access the bots server and can execute, edit, modify bot code. Can also manage other Nations
\n*Owner* - Only one exists, bot owner.
Owner has complete bot access, including bot adminship in chats Spiral is at.
\n*Sudo* - Have super user access, can gban, manage admins lower than them and are admins in Spiral.
\n*Support* - Have access to globally ban users across Spiral.
\n*Pro* - Same as whitelisted users but can unban themselves if banned.
\n*Whitelisted* - Cannot be banned, muted flood kicked but can be manually banned by admins.
\n*Disclaimer*: The Nation levels in Kigyō are there for troubleshooting, support, banning potential scammers.
Report abuse or ask us more on these at [Spiral Support](https://t.me/enrapturedoverwatch_bot).
"""


async def send_nations(update):
    await update.effective_message.reply_text(
        nations, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
    )

@kigcmd(command='whitelists')  # fixed wrong command name
@whitelist_plus
@rate_limit(40, 60)
async def whitelistlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    reply = "<b>Known whitelisted users :</b>\n"
    for each_user in WHITELIST_USERS:
        user_id = int(each_user)
        try:
            user = await bot.get_chat(user_id)

            reply += f"• {mention_html(user_id, user.first_name)}\n"
        except TelegramError:
            pass
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.HTML)

@kigcmd(command='pro')
@whitelist_plus
@rate_limit(40, 60)
async def Sardegnalist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    reply = "<b>Known pro users :</b>\n"
    for each_user in SARDEGNA_USERS:
        user_id = int(each_user)
        try:
            user = await bot.get_chat(user_id)
            reply += f"• {mention_html(user_id, user.first_name)}\n"
        except TelegramError:
            pass
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.HTML)

@kigcmd(command=["supportlist", "sakuras"])
@whitelist_plus
@rate_limit(40, 60)
async def supportlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    reply = "<b>Known support users :</b>\n"
    for each_user in SUPPORT_USERS:
        user_id = int(each_user)
        try:
            user = await bot.get_chat(user_id)
            reply += f"• {mention_html(user_id, user.first_name)}\n"
        except TelegramError:
            pass
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.HTML)

@kigcmd(command=["sudolist", "royals"])
@whitelist_plus
@rate_limit(40, 60)
async def sudolist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    true_sudo = list(set(SUDO_USERS) - set(DEV_USERS))
    reply = "<b>Known sudo users :</b>\n"
    for each_user in true_sudo:
        user_id = int(each_user)
        try:
            user = await bot.get_chat(user_id)
            reply += f"• {mention_html(user_id, user.first_name)}\n"
        except TelegramError:
            pass
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.HTML)

@kigcmd(command=["devlist"])
@whitelist_plus
@rate_limit(40, 60)
async def devlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    true_dev = list(set(DEV_USERS) - {OWNER_ID})
    reply = "<b>Spiral developers :</b>\n"
    for each_user in true_dev:
        user_id = int(each_user)
        try:
            user = await bot.get_chat(user_id)
            reply += f"• {mention_html(user_id, user.first_name)}\n"
        except TelegramError:
            pass
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.HTML)


from tg_bot.modules.language import gs

def get_help(chat):
    return gs(chat, "nation_help")


__mod_name__ = "Nations"
