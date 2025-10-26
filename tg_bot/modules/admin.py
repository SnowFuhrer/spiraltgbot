import html
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

from tg_bot.modules.helper_funcs.chat_status import (
    bot_admin,
    can_pin,
    can_promote,
    connection_status,
)
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit
from tg_bot.modules.helper_funcs.extraction import extract_user, extract_user_and_text
from tg_bot.modules.language import gs
from tg_bot.modules.log_channel import loggable
from ..modules.helper_funcs.anonymous import user_admin, AdminPerms


@kigcmd(command="promote", can_disable=False)
@connection_status
@bot_admin
@can_promote
@user_admin(AdminPerms.CAN_PROMOTE_MEMBERS)
@rate_limit(40, 60)
@loggable
async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    bot = context.bot
    args = context.args

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "You don't seem to be referring to a user or the ID specified is incorrect.."
        )
        return

    try:
        user_member = await chat.get_member(user_id)
    except Exception:
        return

    if user_member.status in ("administrator", "creator"):
        await message.reply_text("How am I meant to promote someone that's already an admin?")
        return

    if user_id == bot.id:
        await message.reply_text("I can't promote myself! Get an admin to do it for me.")
        return

    # set same perms as bot - bot can't assign higher perms than itself!
    bot_member = await chat.get_member(bot.id)

    try:
        await bot.promote_chat_member(
            chat.id,
            user_id,
            can_change_info=getattr(bot_member, "can_change_info", None),
            can_post_messages=getattr(bot_member, "can_post_messages", None),
            can_edit_messages=getattr(bot_member, "can_edit_messages", None),
            can_delete_messages=getattr(bot_member, "can_delete_messages", None),
            can_invite_users=getattr(bot_member, "can_invite_users", None),
            # can_promote_members=getattr(bot_member, "can_promote_members", None),
            can_restrict_members=getattr(bot_member, "can_restrict_members", None),
            can_pin_messages=getattr(bot_member, "can_pin_messages", None),
            can_manage_video_chats=getattr(
                bot_member, "can_manage_video_chats", getattr(bot_member, "can_manage_voice_chats", None)
            ),
        )
    except BadRequest as err:
        if err.message == "User_not_mutual_contact":
            await message.reply_text("I can't promote someone who isn't in the group.")
        else:
            await message.reply_text("An error occured while promoting.")
        return

    await bot.send_message(
        chat.id,
        f"<b>{html.escape(user_member.user.first_name) if user_member.user.first_name else user_id}</b> was promoted by "
        f"<b>{html.escape(message.from_user.first_name) if message.from_user.first_name else ''}</b> in "
        f"<b>{html.escape(chat.title) if chat.title else ''}</b>",
        parse_mode=ParseMode.HTML,
    )

    log_message = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#PROMOTED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(user_member.user.id, user_member.user.first_name)}"
    )

    return log_message


@kigcmd(command="demote", can_disable=False)
@connection_status
@bot_admin
@can_promote
@user_admin(AdminPerms.CAN_PROMOTE_MEMBERS)
@rate_limit(40, 60)
@loggable
async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    bot = context.bot
    args = context.args

    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user

    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "You don't seem to be referring to a user or the ID specified is incorrect.."
        )
        return

    try:
        user_member = await chat.get_member(user_id)
    except Exception:
        return

    if user_member.status == "creator":
        await message.reply_text("This person CREATED the chat, how would I demote them?")
        return

    if user_member.status != "administrator":
        await message.reply_text("Can't demote what wasn't promoted!")
        return

    if user_id == bot.id:
        await message.reply_text("I can't demote myself! Get an admin to do it for me.")
        return

    try:
        await bot.promote_chat_member(
            chat.id,
            user_id,
            can_change_info=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False,
        )

        await bot.send_message(
            chat.id,
            f"<b>{html.escape(user_member.user.first_name) if user_member.user.first_name else user_id}</b> was demoted by "
            f"<b>{html.escape(message.from_user.first_name) if message.from_user.first_name else ''}</b> in "
            f"<b>{html.escape(chat.title) if chat.title else ''}</b>",
            parse_mode=ParseMode.HTML,
        )

        log_message = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#DEMOTED\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"<b>User:</b> {mention_html(user_member.user.id, user_member.user.first_name)}"
        )

        return log_message
    except BadRequest:
        await message.reply_text(
            "Could not demote. I might not be admin, or the admin status was appointed by another "
            "user, so I can't act upon them!"
        )
        return


@kigcmd(command="title", can_disable=False)
@connection_status
@bot_admin
@can_promote
@user_admin(AdminPerms.CAN_PROMOTE_MEMBERS)
@rate_limit(40, 60)
async def set_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    args = context.args

    chat = update.effective_chat
    message = update.effective_message

    user_id, title = await extract_user_and_text(message, args)
    try:
        user_member = await chat.get_member(user_id)
    except Exception:
        return

    if not user_id:
        await message.reply_text(
            "You don't seem to be referring to a user or the ID specified is incorrect.."
        )
        return

    if user_member.status == "creator":
        await message.reply_text("This person CREATED the chat, how can i set custom title for him?")
        return

    if user_member.status != "administrator":
        await message.reply_text("Can't set title for non-admins!\nPromote them first to set custom title!")
        return

    if user_id == bot.id:
        await message.reply_text(
            "I can't set my own title myself! Get the one who made me admin to do it for me."
        )
        return

    if not title:
        await message.reply_text("Setting blank title doesn't do anything!")
        return

    if len(title) > 16:
        await message.reply_text(
            "The title length is longer than 16 characters.\nTruncating it to 16 characters."
        )

    try:
        await bot.set_chat_administrator_custom_title(chat.id, user_id, title[:16])
    except BadRequest:
        await message.reply_text("I can't set custom title for admins that I didn't promote!")
        return

    await bot.send_message(
        chat.id,
        f"Sucessfully set title for <code>{html.escape(user_member.user.first_name) if user_member.user.first_name else user_id}</code> "
        f"to <code>{html.escape(title[:16])}</code>!",
        parse_mode=ParseMode.HTML,
    )


@kigcmd(command="pin", can_disable=False)
@bot_admin
@can_pin
@user_admin(AdminPerms.CAN_PIN_MESSAGES)
@rate_limit(40, 60)
@loggable
async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    bot = context.bot
    args = context.args

    user = update.effective_user
    chat = update.effective_chat

    is_group = chat.type not in ("private", "channel")
    prev_message = update.effective_message.reply_to_message

    is_silent = True
    if len(args) >= 1:
        is_silent = args[0].lower() not in ("notify", "loud", "violent")

    if prev_message and is_group:
        try:
            await bot.pin_chat_message(
                chat.id, prev_message.message_id, disable_notification=is_silent
            )
        except BadRequest as excp:
            if excp.message == "Chat_not_modified":
                pass
            else:
                raise
        log_message = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#PINNED\n"
            f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}"
        )

        return log_message
    return None


@kigcmd(command="unpin", can_disable=False)
@bot_admin
@can_pin
@user_admin(AdminPerms.CAN_PIN_MESSAGES)
@rate_limit(40, 60)
@loggable
async def unpin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    bot = context.bot
    chat = update.effective_chat
    user = update.effective_user

    try:
        await bot.unpin_chat_message(chat.id)
    except BadRequest as excp:
        if excp.message == "Chat_not_modified":
            pass
        else:
            raise

    log_message = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNPINNED\n"
        f"<b>Admin:</b> {mention_html(user.id, html.escape(user.first_name))}"
    )

    return log_message


@kigcmd(command="invitelink", can_disable=False)
@bot_admin
@user_admin(AdminPerms.CAN_INVITE_USERS)
@connection_status
@rate_limit(40, 60)
async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    chat = update.effective_chat

    if chat.username:
        await update.effective_message.reply_text(f"https://t.me/{chat.username}")
    elif chat.type in (ChatType.SUPERGROUP, ChatType.CHANNEL):
        bot_member = await chat.get_member(bot.id)
        if getattr(bot_member, "can_invite_users", False):
            invitelink = await bot.export_chat_invite_link(chat.id)
            await update.effective_message.reply_text(invitelink)
        else:
            await update.effective_message.reply_text(
                "I don't have access to the invite link, try changing my permissions!"
            )
    else:
        await update.effective_message.reply_text(
            "I can only give you invite links for supergroups and channels, sorry!"
        )


@kigcmd(command=["admin", "admins"])
@bot_admin
@user_admin
@rate_limit(40, 60)
async def adminlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    administrators = await chat.get_administrators()

    text = f"Admins in <b>{html.escape(chat.title) if chat.title else 'this chat'}</b>:"
    for admin in administrators:
        if not admin.is_anonymous:
            user = admin.user
            name = mention_html(user.id, user.first_name or "User")
            custom_title = f" • <code>{html.escape(admin.custom_title)}</code>" if admin.custom_title else ""
            text += f"\n -> {name} • <code>{user.id}</code> • <code>{admin.status}</code>{custom_title}"

    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


def get_help(chat):
    return gs(chat, "admin_help")


__mod_name__ = "Admin"
