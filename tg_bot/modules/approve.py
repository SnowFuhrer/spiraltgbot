import html

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import ContextTypes, filters
from telegram.helpers import mention_html

import tg_bot.modules.sql.approve_sql as sql
from tg_bot import SUDO_USERS
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigcallback, rate_limit
from tg_bot.modules.helper_funcs.extraction import extract_user
from tg_bot.modules.log_channel import loggable
from ..modules.helper_funcs.anonymous import user_admin, AdminPerms


@kigcmd(command='approve', filters=filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    chat_title = chat.title
    args = context.args or []
    user = update.effective_user

    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "I don't know who you're talking about, you're going to need to specify a user!"
        )
        return ""

    try:
        member = await chat.get_member(user_id)
    except BadRequest:
        return ""

    if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        await message.reply_text(
            "User is already admin - locks, blocklists, and antiflood already don't apply to them."
        )
        return ""

    if sql.is_approved(chat.id, user_id):
        await message.reply_text(
            f"{mention_html(member.user.id, member.user.first_name)} is already approved in {html.escape(chat_title)}",
            parse_mode=ParseMode.HTML,
        )
        return ""

    sql.approve(chat.id, user_id)
    await message.reply_text(
        f"{mention_html(member.user.id, member.user.first_name)} has been approved in {html.escape(chat_title)}! "
        f"They will now be ignored by automated admin actions like locks, blocklists, and antiflood.",
        parse_mode=ParseMode.HTML,
    )
    log_message = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#APPROVED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )
    return log_message


@kigcmd(command='unapprove', filters=filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def disapprove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    chat_title = chat.title
    args = context.args or []
    user = update.effective_user

    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "I don't know who you're talking about, you're going to need to specify a user!"
        )
        return ""

    try:
        member = await chat.get_member(user_id)
    except BadRequest:
        return ""

    if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        await message.reply_text("This user is an admin, they can't be unapproved.")
        return ""

    if not sql.is_approved(chat.id, user_id):
        await message.reply_text(f"{member.user.first_name} isn't approved yet!")
        return ""

    sql.disapprove(chat.id, user_id)
    await message.reply_text(f"{member.user.first_name} is no longer approved in {chat_title}.")
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNAPPROVED\n<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )


@kigcmd(command='approved', filters=filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def approved(update: Update, _: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    chat_title = chat.title

    approved_users = sql.list_approved(chat.id)

    if not approved_users:
        await message.reply_text(f"No users are approved in {chat_title}.")
        return ""

    msg_lines = ["The following users are approved."]
    for i in approved_users:
        member = await chat.get_member(int(i.user_id))
        msg_lines.append(
            f"- <code>{i.user_id}</code>: {mention_html(member.user.id, member.user.first_name)}"
        )

    await message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.HTML)
    return ""


@kigcmd(command='approval', filters=filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    args = context.args or []

    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "I don't know who you're talking about, you're going to need to specify a user!"
        )
        return ""

    member = await chat.get_member(int(user_id))

    if sql.is_approved(chat.id, user_id):
        await message.reply_text(
            f"{member.user.first_name} is an approved user. Locks, antiflood, and blocklists won't apply to them."
        )
    else:
        await message.reply_text(
            f"{member.user.first_name} is not an approved user. They are affected by normal commands."
        )


@kigcmd(command='unapproveall', filters=filters.ChatType.GROUPS)
@rate_limit(40, 60)
async def unapproveall(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    member = await chat.get_member(user.id)

    if member.status != ChatMemberStatus.OWNER and user.id not in SUDO_USERS:
        await update.effective_message.reply_text(
            "Only the chat owner can unapprove all users at once."
        )
    else:
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="Unapprove all users", callback_data="unapproveall_user")],
            [InlineKeyboardButton(text="Cancel", callback_data="unapproveall_cancel")],
        ])
        await update.effective_message.reply_text(
            f"Are you sure you would like to unapprove ALL users in {html.escape(chat.title)}? "
            f"This action cannot be undone.",
            reply_markup=buttons,
            parse_mode=ParseMode.HTML,
        )


@kigcallback(pattern=r"unapproveall_.*")
async def unapproveall_btn(update: Update, _: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    message = update.effective_message
    member = await chat.get_member(query.from_user.id)

    if query.data == "unapproveall_user":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in SUDO_USERS:
            approved_users = sql.list_approved(chat.id)
            users = [int(i.user_id) for i in approved_users]
            for user_id in users:
                sql.disapprove(chat.id, user_id)
            await message.edit_text("All approved users have been unapproved.")
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")
        elif member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")

    elif query.data == "unapproveall_cancel":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in SUDO_USERS:
            await message.edit_text("Removing of all approved users has been cancelled.")
            return ""
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")
        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")


from tg_bot.modules.language import gs


def get_help(chat):
    return gs(chat, "approve_help")


__mod_name__ = "Approvals"
