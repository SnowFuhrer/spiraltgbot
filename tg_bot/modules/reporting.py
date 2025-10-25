import html

from tg_bot import log, SUDO_USERS, SARDEGNA_USERS, WHITELIST_USERS
from tg_bot.modules.helper_funcs.chat_status import user_not_admin
from tg_bot.modules.log_channel import loggable
from tg_bot.modules.sql import reporting_sql as sql
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    ContextTypes,
    filters,
)
import tg_bot.modules.sql.log_channel_sql as logsql
from telegram.helpers import mention_html
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, kigcallback, rate_limit

from ..modules.helper_funcs.anonymous import user_admin, AdminPerms

REPORT_GROUP = 12
REPORT_IMMUNE_USERS = SUDO_USERS + SARDEGNA_USERS + WHITELIST_USERS


@kigcmd(command='reports')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def report_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot, args = context.bot, context.args
    chat = update.effective_chat
    msg = update.effective_message

    if chat.type == chat.PRIVATE:
        if len(args) >= 1:
            if args[0] in ("yes", "on"):
                sql.set_user_setting(chat.id, True)
                await msg.reply_text(
                    "Turned on reporting! You'll be notified whenever anyone reports something."
                )

            elif args[0] in ("no", "off"):
                sql.set_user_setting(chat.id, False)
                await msg.reply_text("Turned off reporting! You wont get any reports.")
        else:
            await msg.reply_text(
                f"Your current report preference is: `{sql.user_should_report(chat.id)}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif len(args) >= 1:
        if args[0] in ("yes", "on"):
            sql.set_chat_setting(chat.id, True)
            await msg.reply_text(
                "Turned on reporting! Admins who have turned on reports will be notified when /report "
                "or @admin is called."
            )

        elif args[0] in ("no", "off"):
            sql.set_chat_setting(chat.id, False)
            await msg.reply_text(
                "Turned off reporting! No admins will be notified on /report or @admin."
            )
    else:
        await msg.reply_text(
            f"This group's current setting is: `{sql.chat_should_report(chat.id)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


@kigcmd(command='report', filters=filters.ChatType.GROUPS, group=REPORT_GROUP)
@kigmsg(filters.Regex(r"(?i)@admin(s)?"), group=REPORT_GROUP)
@user_not_admin
@rate_limit(40, 60)
@loggable
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    # sourcery no-metrics
    global reply_markup
    bot = context.bot
    args = context.args
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    log_setting = logsql.get_chat_setting(chat.id)
    if not log_setting:
        logsql.set_chat_setting(logsql.LogChannelSettings(chat.id, True, True, True, True, True))
        log_setting = logsql.get_chat_setting(chat.id)

    if message.sender_chat:
        admin_list = await bot.get_chat_administrators(chat.id)
        reported = "Reported to admins."
        for admin in admin_list:
            if admin.user.is_bot:  # AI didnt take over yet
                continue
            try:
                reported += f"<a href=\"tg://user?id={admin.user.id}\">\u2063</a>"
            except BadRequest:
                log.exception("Exception while reporting user")
        await message.reply_text(reported, parse_mode=ParseMode.HTML)

    if chat and message.reply_to_message and sql.chat_should_report(chat.id):
        reported_user = message.reply_to_message.from_user
        chat_name = chat.title or chat.username

        if not args:
            if message.text and message.text.lower().split()[0] in ["@admin", "@admins"]:
                if user.id == reported_user.id:
                    with contextlib.suppress(Exception):
                        await message.delete()
                    return ""
                if user.id == bot.id:
                    with contextlib.suppress(Exception):
                        await message.delete()
                    return ""
                if reported_user.id in REPORT_IMMUNE_USERS:
                    with contextlib.suppress(Exception):
                        await message.delete()
                    return ""
            else:
                with contextlib.suppress(Exception):
                    await message.delete()
                return ""

        if chat.username and chat.type == ChatType.SUPERGROUP:
            msg = f'{mention_html(user.id, user.first_name)} is calling for admins in "{html.escape(chat_name)}"!'
            link = ""
            should_forward = True

        admin_list = await bot.get_chat_administrators(chat.id)
        reported = "Reported to admins."
        msg = f'{mention_html(user.id, user.first_name)} is calling for admins in "{html.escape(chat_name)}"!'
        link = ""
        should_forward = True

        for admin in admin_list:
            if admin.user.is_bot:  # AI didnt take over yet
                continue
            try:
                reported += f"<a href=\"tg://user?id={admin.user.id}\">\u2063</a>"
            except BadRequest:
                log.exception("Exception while reporting user")

            if sql.user_should_report(admin.user.id):
                try:
                    if chat.type != ChatType.SUPERGROUP:
                        await bot.send_message(
                            admin.user.id, msg + link, parse_mode=ParseMode.HTML
                        )

                        if should_forward:
                            await message.reply_to_message.forward(admin.user.id)

                            if message.text and len(message.text.split()) > 1:
                                await message.forward(admin.user.id)

                    if not chat.username:
                        await bot.send_message(
                            admin.user.id, msg + link, parse_mode=ParseMode.HTML
                        )

                        if should_forward:
                            await message.reply_to_message.forward(admin.user.id)

                            if message.text and len(message.text.split()) > 1:
                                await message.forward(admin.user.id)

                    if chat.username and chat.type == ChatType.SUPERGROUP:
                        await bot.send_message(
                            admin.user.id,
                            msg + link,
                            parse_mode=ParseMode.HTML,
                            # reply_markup=reply_markup,
                        )

                        if should_forward:
                            await message.reply_to_message.forward(admin.user.id)

                            if message.text and len(message.text.split()) > 1:
                                await message.forward(admin.user.id)

                except (Unauthorized, Forbidden):
                    pass
                except BadRequest as excp:  # TODO: cleanup exceptions
                    log.exception("Exception while reporting user\n{}".format(excp))

        with contextlib.suppress(Exception):
            await message.delete()

        await message.reply_to_message.reply_text(
            reported,
            parse_mode=ParseMode.HTML,
        )
        if not log_setting.log_report:
            return ""
        return msg
    else:
        with contextlib.suppress(Exception):
            await message.delete()
        return ""


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, _):
    return f"This chat is setup to send user reports to admins, via /report and @admin: `{sql.chat_should_report(chat_id)}`"


def __user_settings__(user_id):
    if sql.user_should_report(user_id) is True:
        return "You will receive reports from chats you're admin."
    else:
        return "You will *not* receive reports from chats you're admin."


@kigcallback(pattern=r"report_")
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    query = update.callback_query
    splitter = query.data.replace("report_", "").split("=")
    if splitter[1] == "kick":
        try:
            await bot.ban_chat_member(splitter[0], splitter[2])
            await bot.unban_chat_member(splitter[0], splitter[2])
            await query.answer("✅ Successfully kicked")
            return ""
        except Exception as err:
            await query.answer("🛑 Failed to kick")
            await bot.send_message(
                text=f"Error: {err}",
                chat_id=query.message.chat.id,
                parse_mode=ParseMode.HTML,
            )
    elif splitter[1] == "banned":
        try:
            await bot.ban_chat_member(splitter[0], splitter[2])
            await query.answer("✅  Succesfully Banned")
            return ""
        except Exception as err:
            await bot.send_message(
                text=f"Error: {err}",
                chat_id=query.message.chat.id,
                parse_mode=ParseMode.HTML,
            )
            await query.answer("🛑 Failed to Ban")
    elif splitter[1] == "delete":
        try:
            await bot.delete_message(splitter[0], splitter[3])
            await query.answer("✅ Message Deleted")
            return ""
        except Exception as err:
            await bot.send_message(
                text=f"Error: {err}",
                chat_id=query.message.chat.id,
                parse_mode=ParseMode.HTML,
            )
            await query.answer("🛑 Failed to delete message!")


from tg_bot.modules.language import gs


def get_help(chat):
    return gs(chat, "reports_help")


__mod_name__ = "Reporting"
