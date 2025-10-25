import html

from telegram import Update
from telegram.ext import ContextTypes, filters

from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, rate_limit
from ..modules.helper_funcs.anonymous import user_admin, AdminPerms
from ..modules.sql.antichannel_sql import (
    antichannel_status,
    disable_antichannel,
    enable_antichannel,
)


@kigcmd(command="antichannel", group=100)
@user_admin(AdminPerms.CAN_RESTRICT_MEMBERS)
@rate_limit(40, 60)
async def set_antichannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    args = context.args or []

    if args:
        s = args[0].lower()
        if s in ["yes", "on"]:
            enable_antichannel(chat.id)
            await message.reply_html(
                "Enabled antichannel in {}".format(html.escape(chat.title))
            )
        elif s in ["off", "no"]:
            disable_antichannel(chat.id)
            await message.reply_html(
                "Disabled antichannel in {}".format(html.escape(chat.title))
            )
        else:
            await message.reply_text(f"Unrecognized arguments {s}")
        return

    await message.reply_html(
        "Antichannel setting is currently {} in {}".format(
            antichannel_status(chat.id), html.escape(chat.title)
        )
    )


@kigmsg(filters.ChatType.GROUPS, group=110)
async def eliminate_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not antichannel_status(chat.id):
        return

    if message.sender_chat and message.sender_chat.type == "channel" and not message.is_automatic_forward:
        try:
            await message.delete()
        except Exception:
            pass
        sender_chat = message.sender_chat
        try:
            await context.bot.ban_chat_sender_chat(
                chat_id=chat.id, sender_chat_id=sender_chat.id
            )
        except Exception:
            pass
