from typing import Optional

import tg_bot.modules.sql.rules_sql as sql
from tg_bot import dispatcher
from tg_bot.modules.helper_funcs.string_handling import markdown_parser
from telegram.constants import ParseMode
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from telegram.error import BadRequest
from telegram.ext import ContextTypes, filters as tg_filters
from telegram.helpers import escape_markdown
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit

from ..modules.helper_funcs.anonymous import user_admin, AdminPerms


@kigcmd(command='rules', filters=tg_filters.ChatType.GROUPS)
@rate_limit(40, 60)
async def get_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await send_rules(update, chat_id)


# Async helper (may also be called from other modules)
async def send_rules(update: Update, chat_id: int, from_pm: bool = False):
    bot = dispatcher.bot
    user: Optional[User] = update.effective_user
    message = update.effective_message
    try:
        chat = await bot.get_chat(chat_id)
    except BadRequest as excp:
        if excp.message != "Chat not found" or not from_pm:
            raise

        if user:
            await bot.send_message(
                user.id,
                "The rules shortcut for this chat hasn't been set properly! Ask admins to "
                "fix this.\nMaybe they forgot the hyphen in ID",
            )
        return

    rules = sql.get_rules(chat_id)
    text = f"The rules for *{escape_markdown(chat.title)}* are:\n\n{rules}"

    if from_pm and rules:
        if user:
            await bot.send_message(
                user.id, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
            )
    elif from_pm:
        if user:
            await bot.send_message(
                user.id,
                "The group admins haven't set any rules for this chat yet. "
                "This probably doesn't mean it's lawless though...!",
            )
    elif rules:
        btn = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Rules", url=f"t.me/{bot.username}?start={chat_id}"
                    )
                ]
            ]
        )
        txt = "Please click the button below to see the rules."
        if not message.reply_to_message:
            await message.reply_text(txt, reply_markup=btn)

        if message.reply_to_message:
            await message.reply_to_message.reply_text(txt, reply_markup=btn)
    else:
        await update.effective_message.reply_text(
            "The group admins haven't set any rules for this chat yet. "
            "This probably doesn't mean it's lawless though...!"
        )


@kigcmd(command='setrules', filters=tg_filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg: Optional[Message] = update.effective_message
    raw_text = msg.text if msg and msg.text else ""
    args = raw_text.split(None, 1)  # use python's maxsplit to separate cmd and args
    if len(args) == 2:
        txt = args[1]
        offset = len(raw_text) - len(txt)  # set correct offset relative to command
        markdown_rules = markdown_parser(
            txt, entities=msg.parse_entities() if msg else None, offset=offset
        )

        sql.set_rules(chat_id, markdown_rules)
        await update.effective_message.reply_text("Successfully set rules for this group.")


@kigcmd(command='clearrules', filters=tg_filters.ChatType.GROUPS)
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def clear_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sql.set_rules(chat_id, "")
    await update.effective_message.reply_text("Successfully cleared rules!")


def __stats__():
    return f"• {sql.num_chats()} chats have rules set."


def __import_data__(chat_id, data):
    # set chat rules
    rules = data.get("info", {}).get("rules", "")
    sql.set_rules(chat_id, rules)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    return f"This chat has had it's rules set: `{bool(sql.get_rules(chat_id))}`"


from tg_bot.modules.language import gs


def get_help(chat):
    return gs(chat, "rules_help")


__mod_name__ = "Rules"
