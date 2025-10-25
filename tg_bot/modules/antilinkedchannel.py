import html

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, filters
from tg_bot.modules.helper_funcs.chat_status import bot_admin, bot_can_delete

from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, rate_limit
from ..modules.helper_funcs.anonymous import user_admin, AdminPerms
import tg_bot.modules.sql.antilinkedchannel_sql as sql


@kigcmd(command="antilinkedchan", group=112)
@bot_can_delete
@user_admin(AdminPerms.CAN_RESTRICT_MEMBERS)
@rate_limit(40, 60)
async def set_antilinkedchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    args = context.args or []
    if args:
        s = args[0].lower()
        if s in ["yes", "on"]:
            if sql.status_pin(chat.id):
                # Disable anti channel pin and enable linked-channel deletion
                sql.disable_pin(chat.id)
                sql.enable_linked(chat.id)
                await message.reply_html(
                    "Enabled Linked channel deletion and Disabled anti channel pin in {}".format(
                        html.escape(chat.title)
                    )
                )
            else:
                sql.enable_linked(chat.id)
                await message.reply_html(
                    "Enabled anti linked channel in {}".format(html.escape(chat.title))
                )
        elif s in ["off", "no"]:
            sql.disable_linked(chat.id)
            await message.reply_html(
                "Disabled anti linked channel in {}".format(html.escape(chat.title))
            )
        else:
            await message.reply_text(f"Unrecognized arguments {s}")
        return
    await message.reply_html(
        "Linked channel deletion is currently {} in {}".format(
            sql.status_linked(chat.id), html.escape(chat.title)
        )
    )


@kigmsg(filters.IS_AUTOMATIC_FORWARD, group=111)
async def eliminate_linked_channel_msg(update: Update, _: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    if not sql.status_linked(chat.id):
        return
    try:
        await message.delete()
    except TelegramError:
        return


@kigcmd(command="antichannelpin", group=114)
@bot_admin
@user_admin(AdminPerms.CAN_RESTRICT_MEMBERS)
@rate_limit(40, 60)
async def set_antipinchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    args = context.args or []
    if args:
        s = args[0].lower()
        if s in ["yes", "on"]:
            if sql.status_linked(chat.id):
                sql.disable_linked(chat.id)
                sql.enable_pin(chat.id)
                await message.reply_html(
                    "Disabled Linked channel deletion and Enabled anti channel pin in {}".format(
                        html.escape(chat.title)
                    )
                )
            else:
                sql.enable_pin(chat.id)
                await message.reply_html(
                    "Enabled anti channel pin in {}".format(html.escape(chat.title))
                )
        elif s in ["off", "no"]:
            sql.disable_pin(chat.id)
            await message.reply_html(
                "Disabled anti channel pin in {}".format(html.escape(chat.title))
            )
        else:
            await message.reply_text(f"Unrecognized arguments {s}")
        return
    await message.reply_html(
        "Linked channel message unpin is currently {} in {}".format(
            sql.status_pin(chat.id), html.escape(chat.title)
        )
    )


@kigmsg(filters.IS_AUTOMATIC_FORWARD | filters.StatusUpdate.PINNED_MESSAGE, group=113)
async def eliminate_linked_channel_pin(update: Update, _: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    if not sql.status_pin(chat.id):
        return
    try:
        await message.unpin()
    except TelegramError:
        return
