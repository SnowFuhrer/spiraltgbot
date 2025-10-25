import contextlib
import html
import random
import re
import time
from io import BytesIO
from functools import partial
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from tg_bot.modules.helper_funcs.alternate import send_message, typing_action
from tg_bot.modules.helper_funcs.decorators import rate_limit, kigmsg
from tg_bot.modules.helper_funcs.filters import CustomFilters
import tg_bot.modules.sql.welcome_sql as sql
from tg_bot import (
    DEV_USERS,
    SYS_ADMIN,
    log,
    OWNER_ID,
    SUDO_USERS,
    SUPPORT_USERS,
    SARDEGNA_USERS,
    WHITELIST_USERS,
    dispatcher,  # assuming your core aliases Application to `dispatcher`
)
from tg_bot.modules.helper_funcs.chat_status import (
    is_user_ban_protected,
    user_admin as u_admin,
)
from tg_bot.modules.helper_funcs.misc import build_keyboard, revert_buttons
from tg_bot.modules.helper_funcs.msg_types import get_welcome_type
from tg_bot.modules.helper_funcs.string_handling import (
    escape_invalid_curly_brackets,
    markdown_parser,
)
from tg_bot.modules.log_channel import loggable
from tg_bot.modules.sql.antispam_sql import is_user_gbanned

from telegram import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    User,
)
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    CallbackContext,  # kept for your existing type annotations; use ContextTypes.DEFAULT_TYPE at runtime
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from telegram.helpers import escape_markdown, mention_html, mention_markdown
import tg_bot.modules.sql.log_channel_sql as logsql
from ..modules.helper_funcs.anonymous import user_admin, AdminPerms

from multicolorcaptcha import CaptchaGenerator
try:
    BAN_STATUS = ChatMemberStatus.BANNED
except AttributeError:
    # Older PTB/Bot API
    BAN_STATUS = ChatMemberStatus.KICKED

VALID_WELCOME_FORMATTERS = [
    "first",
    "last",
    "fullname",
    "username",
    "id",
    "count",
    "chatname",
    "mention",
]

VERIFIED_USER_WAITLIST = {}
CAPTCHA_ANS_DICT = {}

WHITELISTED = (
    [OWNER_ID, SYS_ADMIN] + DEV_USERS + SUDO_USERS + SUPPORT_USERS + WHITELIST_USERS
)
WHITELISTED = (
    [OWNER_ID, SYS_ADMIN] + DEV_USERS + SUDO_USERS + SUPPORT_USERS + WHITELIST_USERS
)


async def send(update: Update, context: ContextTypes.DEFAULT_TYPE, message, keyboard, backup_message):
    chat = update.effective_chat
    try:
        msg = await context.bot.send_message(
            chat.id,
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
            allow_sending_without_reply=True,
        )
    except BadRequest as excp:
        if excp.message == "Button_url_invalid":
            msg = await context.bot.send_message(
                chat.id,
                markdown_parser(
                    (
                        backup_message
                        + "\nNote: the current message has an invalid url in one of its buttons. Please update."
                    )
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif excp.message == "Have no rights to send a message":
            return
        elif excp.message == "Reply message not found":
            msg = await context.bot.send_message(
                chat.id,
                message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
                allow_sending_without_reply=True,
            )
        elif excp.message == "Unsupported url protocol":
            msg = await context.bot.send_message(
                chat.id,
                markdown_parser(
                    (
                        backup_message
                        + "\nNote: the current message has buttons which use url protocols that are unsupported by telegram. Please update."
                    )
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif excp.message == "Wrong url host":
            msg = await context.bot.send_message(
                chat.id,
                markdown_parser(
                    (backup_message + "\nNote: the current message has some bad urls. Please update.")
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            log.warning(message)
            log.warning(keyboard)
            log.exception("Could not parse! got invalid url host errors")
        else:
            msg = await context.bot.send_message(
                chat.id,
                markdown_parser(
                    (
                        backup_message
                        + "\nNote: An error occured when sending the custom message. Please update."
                    )
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            log.exception()
    return msg


def _escape_md(text: str) -> str:
    # PTB v20: escape_markdown default is v2; here we keep v1 to match ParseMode.MARKDOWN usage across this module
    return escape_markdown(text, version=1)


def _mention_md(user_id: int, name: str) -> str:
    return mention_markdown(user_id, _escape_md(name), version=1)


async def _send_media(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    msg_type,
    content,
    caption=None,
    keyboard=None,
    parse_mode=ParseMode.MARKDOWN,
):
    # msg_type is likely an IntEnum (sql.Types)
    if msg_type == sql.Types.STICKER:
        return await context.bot.send_sticker(chat_id, content, reply_markup=keyboard)
    if msg_type == sql.Types.DOCUMENT:
        return await context.bot.send_document(
            chat_id, content, caption=caption, reply_markup=keyboard, parse_mode=parse_mode
        )
    if msg_type == sql.Types.PHOTO:
        return await context.bot.send_photo(
            chat_id, content, caption=caption, reply_markup=keyboard, parse_mode=parse_mode
        )
    if msg_type == sql.Types.AUDIO:
        return await context.bot.send_audio(
            chat_id, content, caption=caption, reply_markup=keyboard, parse_mode=parse_mode
        )
    if msg_type == sql.Types.VOICE:
        return await context.bot.send_voice(
            chat_id, content, caption=caption, reply_markup=keyboard, parse_mode=parse_mode
        )
    if msg_type == sql.Types.VIDEO:
        return await context.bot.send_video(
            chat_id, content, caption=caption, reply_markup=keyboard, parse_mode=parse_mode
        )
    # Fallback to text
    return await context.bot.send_message(
        chat_id, caption or content, reply_markup=keyboard, parse_mode=parse_mode
    )


@rate_limit(40, 60)
async def welcomeFilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    if update.chat_member:
        nm = update.chat_member.new_chat_member
        om = update.chat_member.old_chat_member
        # Joins
        if nm.status == ChatMemberStatus.MEMBER and om.status in [BAN_STATUS, ChatMemberStatus.LEFT]:
            return await new_member(update, context)
        # Leaves
        if nm.status in [BAN_STATUS, ChatMemberStatus.LEFT] and om.status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ]:
            return await left_member(update, context)


@rate_limit(40, 60)
@loggable
async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    bot = context.bot
    job_queue = context.application.job_queue
    chat = update.effective_chat
    user = update.effective_user
    log_setting = logsql.get_chat_setting(chat.id)
    if not log_setting:
        logsql.set_chat_setting(
            logsql.LogChannelSettings(chat.id, True, True, True, True, True)
        )
        log_setting = logsql.get_chat_setting(chat.id)
    should_welc, cust_welcome, cust_content, welc_type = sql.get_welc_pref(chat.id)
    welc_mutes = sql.welcome_mutes(chat.id)
    human_checks = sql.get_human_checks(user.id, chat.id)
    raid, _, deftime = sql.getRaidStatus(str(chat.id))

    new_mem = update.chat_member.new_chat_member.user

    welcome_log = None
    res = None
    sent = None
    should_mute = True
    welcome_bool = True
    media_wel = False

    if raid and new_mem.id not in WHITELISTED:
        bantime = deftime
        with contextlib.suppress(BadRequest):
            await bot.ban_chat_member(chat.id, new_mem.id, until_date=bantime)
        return

    if should_welc:
        if new_mem.id == bot.id:
            return
        else:
            buttons = sql.get_welc_buttons(chat.id)
            keyb = build_keyboard(buttons)

            if welc_type not in (sql.Types.TEXT, sql.Types.BUTTON_TEXT):
                media_wel = True

            first_name = new_mem.first_name or "PersonWithNoName"

            if cust_welcome:
                if cust_welcome == sql.DEFAULT_WELCOME:
                    cust_welcome = random.choice(sql.DEFAULT_WELCOME_MESSAGES).format(
                        first=_escape_md(first_name)
                    )

                if new_mem.last_name:
                    fullname = _escape_md(f"{first_name} {new_mem.last_name}")
                else:
                    fullname = _escape_md(first_name)
                count = await chat.get_member_count()
                mention = _mention_md(new_mem.id, first_name)
                if new_mem.username:
                    username = "@" + _escape_md(new_mem.username)
                else:
                    username = mention

                valid_format = escape_invalid_curly_brackets(
                    cust_welcome, VALID_WELCOME_FORMATTERS
                )
                res = valid_format.format(
                    first=_escape_md(first_name),
                    last=_escape_md(new_mem.last_name or first_name),
                    fullname=_escape_md(fullname),
                    username=username,
                    mention=mention,
                    count=count,
                    chatname=_escape_md(chat.title),
                    id=new_mem.id,
                )
            else:
                res = random.choice(sql.DEFAULT_WELCOME_MESSAGES).format(
                    first=_escape_md(first_name)
                )
                keyb = []

            backup_message = random.choice(sql.DEFAULT_WELCOME_MESSAGES).format(
                first=_escape_md(first_name)
            )
            keyboard = InlineKeyboardMarkup(keyb)

    else:
        welcome_bool = False
        res = None
        keyboard = None
        backup_message = None

    # User exceptions from welcomemutes
    member_obj = await chat.get_member(new_mem.id)
    if await is_user_ban_protected(update, new_mem.id, member_obj) or human_checks:
        should_mute = False

    if new_mem.is_bot:
        should_mute = False

    if user.id == new_mem.id and should_mute:
        if welc_mutes == "soft":
            await bot.restrict_chat_member(
                chat.id,
                new_mem.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                    can_send_polls=False,
                    can_change_info=False,
                    can_add_web_page_previews=False,
                ),
                until_date=(int(time.time() + 24 * 60 * 60)),
            )
            sql.set_human_checks(user.id, chat.id)

        if welc_mutes == "strong":
            welcome_bool = False
            if not media_wel:
                VERIFIED_USER_WAITLIST.update(
                    {
                        (chat.id, new_mem.id): {
                            "should_welc": should_welc,
                            "media_wel": False,
                            "status": False,
                            "update": update,
                            "res": res,
                            "keyboard": keyboard,
                            "backup_message": backup_message,
                        }
                    }
                )
            else:
                VERIFIED_USER_WAITLIST.update(
                    {
                        (chat.id, new_mem.id): {
                            "should_welc": should_welc,
                            "chat_id": chat.id,
                            "status": False,
                            "media_wel": True,
                            "cust_content": cust_content,
                            "welc_type": welc_type,
                            "res": res,
                            "keyboard": keyboard,
                        }
                    }
                )
            new_join_mem = f"[{_escape_md(new_mem.first_name)}](tg://user?id={user.id})"
            message = await bot.send_message(
                chat.id,
                f"{new_join_mem}, click the button below to prove you're human.\nYou have 120 seconds.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text="Yes, I'm human.",
                                callback_data=f"user_join_({new_mem.id})",
                            )
                        ]
                    ]
                ),
                parse_mode=ParseMode.MARKDOWN,
                allow_sending_without_reply=True,
            )
            await bot.restrict_chat_member(
                chat.id,
                new_mem.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                    can_send_polls=False,
                    can_change_info=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                ),
            )
            context.application.job_queue.run_once(
                check_not_bot,
                when=120,
                data={"member_id": new_mem.id, "chat_id": chat.id, "message_id": message.message_id},
                name="welcomemute",
            )

        if welc_mutes == "captcha":
            btn = []
            CAPCTHA_SIZE_NUM = 2
            generator = CaptchaGenerator(CAPCTHA_SIZE_NUM)

            captcha = generator.gen_captcha_image(difficult_level=3)
            image = captcha["image"]
            characters = captcha["characters"]
            fileobj = BytesIO()
            fileobj.name = f"captcha_{new_mem.id}.png"
            image.save(fp=fileobj)
            fileobj.seek(0)
            CAPTCHA_ANS_DICT[(chat.id, new_mem.id)] = int(characters)
            welcome_bool = False
            if not media_wel:
                VERIFIED_USER_WAITLIST.update(
                    {
                        (chat.id, new_mem.id): {
                            "should_welc": should_welc,
                            "media_wel": False,
                            "status": False,
                            "update": update,
                            "res": res,
                            "keyboard": keyboard,
                            "backup_message": backup_message,
                            "captcha_correct": characters,
                        }
                    }
                )
            else:
                VERIFIED_USER_WAITLIST.update(
                    {
                        (chat.id, new_mem.id): {
                            "should_welc": should_welc,
                            "chat_id": chat.id,
                            "status": False,
                            "media_wel": True,
                            "cust_content": cust_content,
                            "welc_type": welc_type,
                            "res": res,
                            "keyboard": keyboard,
                            "captcha_correct": characters,
                        }
                    }
                )

            nums = [random.randint(1000, 9999) for _ in range(7)]
            nums.append(characters)
            random.shuffle(nums)
            to_append = []
            for a in nums:
                to_append.append(
                    InlineKeyboardButton(
                        text=str(a),
                        callback_data=f"user_captchajoin_({chat.id},{new_mem.id})_({a})",
                    )
                )
                if len(to_append) > 2:
                    btn.append(to_append)
                    to_append = []
            if to_append:
                btn.append(to_append)

            message = await bot.send_photo(
                chat.id,
                fileobj,
                caption=f"Welcome [{_escape_md(new_mem.first_name)}](tg://user?id={user.id}). Click the correct button to get unmuted!\nYou got 120 seconds for this.",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=ParseMode.MARKDOWN,
                allow_sending_without_reply=True,
            )
            await bot.restrict_chat_member(
                chat.id,
                new_mem.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                    can_send_polls=False,
                    can_change_info=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                ),
            )
            context.application.job_queue.run_once(
                check_not_bot,
                when=120,
                data={"member_id": new_mem.id, "chat_id": chat.id, "message_id": message.message_id},
                name="welcomemute",
            )

    if welcome_bool:
        if media_wel:
            sent = await _send_media(
                context,
                chat.id,
                welc_type,
                cust_content,
                caption=res if welc_type != sql.Types.STICKER else None,
                keyboard=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            sent = await send(update, context, res, keyboard, backup_message)

        prev_welc = sql.get_clean_pref(chat.id)
        if prev_welc:
            try:
                await bot.delete_message(chat.id, prev_welc)
            except BadRequest:
                log.error("cant delete")
            if sent:
                sql.set_clean_welcome(chat.id, sent.message_id)

        if not log_setting.log_joins:
            return ""
        if welcome_log:
            return welcome_log

    return ""


@kigmsg(filters.ChatType.GROUPS, group=110)
async def handleCleanService(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if sql.clean_service(chat.id):
        if msg.new_chat_members or msg.left_chat_member:
            try:
                await msg.delete()
            except BadRequest as e:
                log.error(f"Error deleting service message: {e}")
    return ""


async def check_not_bot(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    bot = context.bot
    chat_id = data.get("chat_id")
    member_id = data.get("member_id")
    message_id = data.get("message_id")

    if chat_id is None or member_id is None:
        return

    member_dict = VERIFIED_USER_WAITLIST.pop((chat_id, member_id), None)
    member_status = member_dict.get("status") if member_dict else False

    if not member_status:
        try:
            await bot.unban_chat_member(chat_id, member_id)
        except BadRequest:
            pass

        try:
            await bot.edit_message_text(
                "*kicks user*\nThey can always rejoin and try.",
                chat_id=chat_id,
                message_id=message_id,
            )
        except TelegramError:
            with contextlib.suppress(TelegramError):
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            chat_member = await bot.get_chat_member(chat_id, member_id)
            user_name = chat_member.user.first_name if chat_member and chat_member.user else "User"
            await bot.send_message(
                chat_id=chat_id,
                text="{} was kicked as they failed to verify themselves".format(
                    mention_html(member_id, user_name)
                ),
                parse_mode=ParseMode.HTML,
            )


@rate_limit(40, 60)
async def left_member(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    bot = context.bot
    chat = update.effective_chat
    user = update.effective_user
    should_goodbye, cust_goodbye, goodbye_type = sql.get_gdbye_pref(chat.id)

    if user.id == bot.id:
        return

    if should_goodbye:
        left_mem = update.chat_member.new_chat_member.user
        if left_mem:
            if is_user_gbanned(left_mem.id):
                return
            if left_mem.id == bot.id:
                return
            if left_mem.id == OWNER_ID:
                return
            if left_mem.id in DEV_USERS:
                return

            if goodbye_type not in [sql.Types.TEXT, sql.Types.BUTTON_TEXT]:
                await _send_media(context, chat.id, goodbye_type, cust_goodbye)
                return

            first_name = left_mem.first_name or "PersonWithNoName"
            if cust_goodbye:
                if cust_goodbye == sql.DEFAULT_GOODBYE:
                    cust_goodbye = random.choice(sql.DEFAULT_GOODBYE_MESSAGES).format(
                        first=_escape_md(first_name)
                    )
                if left_mem.last_name:
                    fullname = _escape_md(f"{first_name} {left_mem.last_name}")
                else:
                    fullname = _escape_md(first_name)
                count = await chat.get_member_count()
                mention = mention_markdown(left_mem.id, first_name, version=1)
                if left_mem.username:
                    username = "@" + _escape_md(left_mem.username)
                else:
                    username = mention

                valid_format = escape_invalid_curly_brackets(
                    cust_goodbye, VALID_WELCOME_FORMATTERS
                )
                res = valid_format.format(
                    first=_escape_md(first_name),
                    last=_escape_md(left_mem.last_name or first_name),
                    fullname=_escape_md(fullname),
                    username=username,
                    mention=mention,
                    count=count,
                    chatname=_escape_md(chat.title),
                    id=left_mem.id,
                )
                buttons = sql.get_gdbye_buttons(chat.id)
                keyb = build_keyboard(buttons)
            else:
                res = random.choice(sql.DEFAULT_GOODBYE_MESSAGES).format(first=first_name)
                keyb = []

            keyboard = InlineKeyboardMarkup(keyb)

            await send(
                update,
                context,
                res,
                keyboard,
                random.choice(sql.DEFAULT_GOODBYE_MESSAGES).format(first=first_name),
            )


@u_admin
@rate_limit(40, 60)
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    chat = update.effective_chat
    if not args or args[0].lower() == "noformat":
        noformat = True
        pref, welcome_m, cust_content, welcome_type = sql.get_welc_pref(chat.id)
        await update.effective_message.reply_text(
            f"This chat has it's welcome setting set to: `{pref}`.\n"
            f"*The welcome message (not filling the {{}}) is:*",
            parse_mode=ParseMode.MARKDOWN,
        )

        if welcome_type in [sql.Types.BUTTON_TEXT, sql.Types.TEXT]:
            buttons = sql.get_welc_buttons(chat.id)
            if noformat:
                welcome_m += revert_buttons(buttons)
                await update.effective_message.reply_text(welcome_m)
            else:
                keyb = build_keyboard(buttons)
                keyboard = InlineKeyboardMarkup(keyb)
                await send(update, context, welcome_m, keyboard, sql.DEFAULT_WELCOME)
        else:
            buttons = sql.get_welc_buttons(chat.id)
            if noformat:
                welcome_m += revert_buttons(buttons)
                await _send_media(context, chat.id, welcome_type, cust_content, caption=welcome_m)
            else:
                keyb = build_keyboard(buttons)
                keyboard = InlineKeyboardMarkup(keyb)
                await _send_media(
                    context,
                    chat.id,
                    welcome_type,
                    cust_content,
                    caption=welcome_m,
                    keyboard=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
    elif len(args) >= 1:
        if args[0].lower() in ("on", "yes"):
            sql.set_welc_preference(str(chat.id), True)
            await update.effective_message.reply_text("Okay! I'll greet members when they join.")
        elif args[0].lower() in ("off", "no"):
            sql.set_welc_preference(str(chat.id), False)
            await update.effective_message.reply_text("I'll not welcome anyone.")
        else:
            await update.effective_message.reply_text("I understand 'on/yes' or 'off/no' only!")


@u_admin
@rate_limit(40, 60)
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    chat = update.effective_chat

    if not args or args[0] == "noformat":
        noformat = True
        pref, goodbye_m, goodbye_type = sql.get_gdbye_pref(chat.id)
        await update.effective_message.reply_text(
            f"This chat has it's goodbye setting set to: `{pref}`.\n"
            f"*The goodbye  message (not filling the {{}}) is:*",
            parse_mode=ParseMode.MARKDOWN,
        )

        if goodbye_type == sql.Types.BUTTON_TEXT:
            buttons = sql.get_gdbye_buttons(chat.id)
            if noformat:
                goodbye_m += revert_buttons(buttons)
                await update.effective_message.reply_text(goodbye_m)
            else:
                keyb = build_keyboard(buttons)
                keyboard = InlineKeyboardMarkup(keyb)
                await send(update, context, goodbye_m, keyboard, sql.DEFAULT_GOODBYE)
        elif noformat:
            await _send_media(context, chat.id, goodbye_type, goodbye_m)
        else:
            await _send_media(context, chat.id, goodbye_type, goodbye_m, parse_mode=ParseMode.MARKDOWN)

    elif len(args) >= 1:
        if args[0].lower() in ("on", "yes"):
            sql.set_gdbye_preference(str(chat.id), True)
            await update.effective_message.reply_text("Ok!")
        elif args[0].lower() in ("off", "no"):
            sql.set_gdbye_preference(str(chat.id), False)
            await update.effective_message.reply_text("Ok!")
        else:
            await update.effective_message.reply_text("I understand 'on/yes' or 'off/no' only!")


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    text, data_type, content, buttons = get_welcome_type(msg)

    if data_type is None:
        await msg.reply_text("You didn't specify what to reply with!")
        return ""

    sql.set_custom_welcome(chat.id, content, text, data_type, buttons)
    await msg.reply_text("Successfully set custom welcome message!")

    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#SET_WELCOME\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set the welcome message."
    )


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def reset_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    chat = update.effective_chat
    user = update.effective_user

    sql.set_custom_welcome(chat.id, None, sql.DEFAULT_WELCOME, sql.Types.TEXT)
    await update.effective_message.reply_text("Successfully reset welcome message to default!")

    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#RESET_WELCOME\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Reset the welcome message to default."
    )


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    text, data_type, content, buttons = get_welcome_type(msg)

    if data_type is None:
        await msg.reply_text("You didn't specify what to reply with!")
        return ""

    sql.set_custom_gdbye(chat.id, content or text, data_type, buttons)
    await msg.reply_text("Successfully set custom goodbye message!")
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#SET_GOODBYE\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set the goodbye message."
    )


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def reset_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    chat = update.effective_chat
    user = update.effective_user

    sql.set_custom_gdbye(chat.id, sql.DEFAULT_GOODBYE, sql.Types.TEXT)
    await update.effective_message.reply_text("Successfully reset goodbye message to default!")

    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#RESET_GOODBYE\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Reset the goodbye message."
    )


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def welcomemute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if len(args) >= 1:
        if args[0].lower() in ("off", "no"):
            sql.set_welcome_mutes(chat.id, False)
            await msg.reply_text("I will no longer mute people on joining!")
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"#WELCOME_MUTE\n"
                f"<b>• Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has toggled welcome mute to <b>OFF</b>."
            )
        elif args[0].lower() in ["soft"]:
            sql.set_welcome_mutes(chat.id, "soft")
            await msg.reply_text("I will restrict users' permission to send media for 24 hours.")
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"#WELCOME_MUTE\n"
                f"<b>• Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has toggled welcome mute to <b>SOFT</b>."
            )
        elif args[0].lower() in ["strong"]:
            sql.set_welcome_mutes(chat.id, "strong")
            await msg.reply_text(
                "I will now mute people when they join until they prove they're not a bot.\nThey will have 120seconds before they get kicked. "
            )
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"#WELCOME_MUTE\n"
                f"<b>• Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has toggled welcome mute to <b>STRONG</b>."
            )
        elif args[0].lower() in ["captcha"]:
            sql.set_welcome_mutes(chat.id, "captcha")
            await msg.reply_text(
                "I will now mute people when they join until they prove they're not a bot.\nThey have to solve a captcha to get unmuted. "
            )
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"#WELCOME_MUTE\n"
                f"<b>• Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has toggled welcome mute to <b>CAPTCHA</b>."
            )
        else:
            await msg.reply_text(
                "Please enter `off`/`no`/`soft`/`strong`/`captcha`!",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ""
    else:
        curr_setting = sql.welcome_mutes(chat.id)
        reply = (
            f"\n Give me a setting!\nChoose one out of: `off`/`no` or `soft`, `strong` or `captcha` only! \n"
            f"Current setting: `{curr_setting}`"
        )
        await msg.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
        return ""


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
@loggable
async def clean_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args = context.args
    chat = update.effective_chat
    user = update.effective_user

    if not args:
        clean_pref = sql.get_clean_pref(chat.id)
        if clean_pref:
            await update.effective_message.reply_text(
                "I should be deleting welcome messages up to two days old."
            )
        else:
            await update.effective_message.reply_text(
                "I'm currently not deleting old welcome messages!"
            )
        return ""

    if args[0].lower() in ("on", "yes"):
        sql.set_clean_welcome(str(chat.id), True)
        await update.effective_message.reply_text("I'll try to delete old welcome messages!")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#CLEAN_WELCOME\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Has toggled clean welcomes to <code>ON</code>."
        )
    elif args[0].lower() in ("off", "no"):
        sql.set_clean_welcome(str(chat.id), False)
        await update.effective_message.reply_text("I won't delete old welcome messages.")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#CLEAN_WELCOME\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Has toggled clean welcomes to <code>OFF</code>."
        )
    else:
        await update.effective_message.reply_text("I understand 'on/yes' or 'off/no' only!")
        return ""


@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def cleanservice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args = context.args
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        curr = sql.clean_service(chat.id)
        if curr:
            await update.effective_message.reply_text(
                "Welcome clean service is : on", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.effective_message.reply_text(
                "Welcome clean service is : off", parse_mode=ParseMode.MARKDOWN
            )
    elif len(args) >= 1:
        var = args[0]
        if var in ("no", "off"):
            sql.set_clean_service(chat.id, False)
            await update.effective_message.reply_text("Welcome clean service is : off")
        elif var in ("yes", "on"):
            sql.set_clean_service(chat.id, True)
            await update.effective_message.reply_text("Welcome clean service is : on")
        else:
            await update.effective_message.reply_text(
                "Invalid option", parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.effective_message.reply_text(
            "Usage is on/yes or off/no", parse_mode=ParseMode.MARKDOWN
        )


@rate_limit(40, 60)
async def user_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    query = update.callback_query
    bot = context.bot
    match = re.match(r"user_join_\((.+?)\)", query.data)
    message = update.effective_message
    join_user = int(match.group(1)) if match else None

    if join_user == user.id:
        sql.set_human_checks(user.id, chat.id)
        member_dict = VERIFIED_USER_WAITLIST.get((chat.id, user.id))
        if member_dict:
            member_dict["status"] = True
        await query.answer(text="Yeet! You're a human, unmuted!")
        await bot.restrict_chat_member(
            chat.id,
            user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_invite_users=True,
                can_pin_messages=True,
                can_send_polls=True,
                can_change_info=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        with contextlib.suppress(Exception):
            await bot.delete_message(chat.id, message.message_id)

        if member_dict and member_dict.get("should_welc"):
            if member_dict.get("media_wel"):
                sent = await _send_media(
                    context,
                    member_dict["chat_id"],
                    member_dict["welc_type"],
                    member_dict["cust_content"],
                    caption=member_dict["res"],
                    keyboard=member_dict["keyboard"],
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                sent = await send(
                    member_dict["update"], context, member_dict["res"], member_dict["keyboard"], member_dict["backup_message"]
                )

            prev_welc = sql.get_clean_pref(chat.id)
            if prev_welc:
                with contextlib.suppress(BadRequest):
                    await bot.delete_message(chat.id, prev_welc)
                if sent:
                    sql.set_clean_welcome(chat.id, sent.message_id)
    else:
        await query.answer(text="You're not allowed to do this!")


@rate_limit(40, 60)
async def user_captcha_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    query = update.callback_query
    bot = context.bot

    match = re.match(r"user_captchajoin_\(([\d\-]+),(\d+)\)_\((\d{4})\)", query.data)
    message = update.effective_message
    if not match:
        return
    join_chat = int(match.group(1))
    join_user = int(match.group(2))
    captcha_ans = int(match.group(3))
    join_usr_data = await bot.get_chat(join_user)

    if join_user == user.id:
        c_captcha_ans = CAPTCHA_ANS_DICT.pop((join_chat, join_user), None)
        if c_captcha_ans == captcha_ans:
            sql.set_human_checks(user.id, chat.id)
            member_dict = VERIFIED_USER_WAITLIST.get((chat.id, user.id))
            if member_dict:
                member_dict["status"] = True
            await query.answer(text="Yeet! You're a human, unmuted!")
            await bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_invite_users=True,
                    can_pin_messages=True,
                    can_send_polls=True,
                    can_change_info=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
            with contextlib.suppress(Exception):
                await bot.delete_message(chat.id, message.message_id)

            if member_dict and member_dict.get("should_welc"):
                if member_dict.get("media_wel"):
                    sent = await _send_media(
                        context,
                        member_dict["chat_id"],
                        member_dict["welc_type"],
                        member_dict["cust_content"],
                        caption=member_dict["res"],
                        keyboard=member_dict["keyboard"],
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    sent = await send(
                        member_dict["update"],
                        context,
                        member_dict["res"],
                        member_dict["keyboard"],
                        member_dict["backup_message"],
                    )

                prev_welc = sql.get_clean_pref(chat.id)
                if prev_welc:
                    with contextlib.suppress(BadRequest):
                        await bot.delete_message(chat.id, prev_welc)
                    if sent:
                        sql.set_clean_welcome(chat.id, sent.message_id)
        else:
            with contextlib.suppress(Exception):
                await bot.delete_message(chat.id, message.message_id)
            kicked_msg = f"❌ [{_escape_md(join_usr_data.first_name)}](tg://user?id={join_user}) failed the captcha and was kicked."
            await query.answer(text="Wrong answer")
            res = await bot.unban_chat_member(chat.id, join_user)
            if res:
                await bot.send_message(
                    chat_id=chat.id, text=kicked_msg, parse_mode=ParseMode.MARKDOWN
                )
    else:
        await query.answer(text="You're not allowed to do this!")


def _welcome_help_text(bot_username: str) -> str:
    return (
        "Your group's welcome/goodbye messages can be personalised in multiple ways. If you want the messages"
        " to be individually generated, like the default welcome message is, you can use *these* variables:\n"
        " • `{first}`*:* this represents the user's *first* name\n"
        " • `{last}`*:* this represents the user's *last* name. Defaults to *first name* if user has no last name.\n"
        " • `{fullname}`*:* this represents the user's *full* name. Defaults to *first name* if user has no last name.\n"
        " • `{username}`*:* this represents the user's *username*. Defaults to a *mention* of the user's first name if has no username.\n"
        " • `{mention}`*:* this simply *mentions* a user - tagging them with their first name.\n"
        " • `{id}`*:* this represents the user's *id*\n"
        " • `{count}`*:* this represents the user's *member number*.\n"
        " • `{chatname}`*:* this represents the *current chat name*.\n"
        "\nEach variable MUST be surrounded by `{}` to be replaced.\n"
        "Welcome messages also support markdown, so you can make any elements bold/italic/code/links. "
        "Buttons are also supported, so you can make your welcomes look awesome with some nice intro buttons.\n"
        f"To create a button linking to your rules, use this: `[Rules](buttonurl://t.me/{bot_username}?start=group_id)`. "
        "Simply replace `group_id` with your group's id, which can be obtained via /id, and you're good to go. Note that group ids are usually preceded by a `-` sign; this is required, so please don't remove it.\n"
        "You can even set images/gifs/videos/voice messages as the welcome message by replying to the desired media, and calling `/setwelcome`."
    )


WELC_MUTE_HELP_TXT = (
    "You can get the bot to mute new people who join your group and hence prevent spambots from flooding your group. "
    "The following options are possible:\n"
    "• `/welcomemute soft`*:* restricts new members from sending media for 24 hours.\n"
    "• `/welcomemute strong`*:* mutes new members till they tap on a button thereby verifying they're human.\n"
    "• `/welcomemute captcha`*:*  mutes new members till they solve a button captcha thereby verifying they're human.\n"
    "• `/welcomemute off`*:* turns off welcomemute.\n"
    "*Note:* Strong mode kicks a user from the chat if they dont verify in 120seconds. They can always rejoin though"
)


@u_admin
@rate_limit(40, 60)
async def welcome_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        _welcome_help_text(context.bot.username), parse_mode=ParseMode.MARKDOWN
    )


@u_admin
@rate_limit(40, 60)
async def welcome_mute_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(WELC_MUTE_HELP_TXT, parse_mode=ParseMode.MARKDOWN)


# def __import_data__(chat_id, data):
#     ...

def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    welcome_pref = sql.get_welc_pref(chat_id)[0]
    goodbye_pref = sql.get_gdbye_pref(chat_id)[0]
    return (
        "This chat has it's welcome preference set to `{}`.\n"
        "It's goodbye preference is `{}`.".format(welcome_pref, goodbye_pref)
    )


from tg_bot.modules.language import gs


def get_help(chat):
    return gs(chat, "greetings_help")


# Handlers (PTB v20+)
WELC_PREF_HANDLER = CommandHandler("welcome", welcome, filters=filters.ChatType.GROUPS)
GOODBYE_PREF_HANDLER = CommandHandler("goodbye", goodbye, filters=filters.ChatType.GROUPS)
SET_WELCOME = CommandHandler("setwelcome", set_welcome, filters=filters.ChatType.GROUPS)
SET_GOODBYE = CommandHandler("setgoodbye", set_goodbye, filters=filters.ChatType.GROUPS)
RESET_WELCOME = CommandHandler("resetwelcome", reset_welcome, filters=filters.ChatType.GROUPS)
RESET_GOODBYE = CommandHandler("resetgoodbye", reset_goodbye, filters=filters.ChatType.GROUPS)
WELCOMEMUTE_HANDLER = CommandHandler("welcomemute", welcomemute, filters=filters.ChatType.GROUPS)
CLEAN_SERVICE_HANDLER = CommandHandler("cleanservice", cleanservice, filters=filters.ChatType.GROUPS)
CLEAN_WELCOME = CommandHandler("cleanwelcome", clean_welcome, filters=filters.ChatType.GROUPS)
WELCOME_HELP = CommandHandler("welcomehelp", welcome_help)
WELCOME_MUTE_HELP = CommandHandler("welcomemutehelp", welcome_mute_help)
BUTTON_VERIFY_HANDLER = CallbackQueryHandler(user_button, pattern=r"^user_join_")
CAPTCHA_BUTTON_VERIFY_HANDLER = CallbackQueryHandler(
    user_captcha_button, pattern=r"^user_captchajoin_\([\d\-]+,\d+\)_\(\d{4}\)$"
)
CHAT_MEMBER_HANDLER = ChatMemberHandler(welcomeFilter, ChatMemberHandler.CHAT_MEMBER)

# Optional: auto-clean service messages (if you're not relying on @kigmsg to register it)
SERVICE_MSG_HANDLER = MessageHandler(
    filters.ChatType.GROUPS
    & (filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER),
    handleCleanService,
)

# If your core still adds handlers here, keep these;
# otherwise, rely on your loader that uses __handlers__.
dispatcher.add_handler(WELC_PREF_HANDLER)
dispatcher.add_handler(GOODBYE_PREF_HANDLER)
dispatcher.add_handler(SET_WELCOME)
dispatcher.add_handler(SET_GOODBYE)
dispatcher.add_handler(RESET_WELCOME)
dispatcher.add_handler(RESET_GOODBYE)
dispatcher.add_handler(CLEAN_WELCOME)
dispatcher.add_handler(WELCOME_HELP)
dispatcher.add_handler(WELCOMEMUTE_HANDLER)
dispatcher.add_handler(CLEAN_SERVICE_HANDLER)
dispatcher.add_handler(BUTTON_VERIFY_HANDLER)
dispatcher.add_handler(CAPTCHA_BUTTON_VERIFY_HANDLER)
dispatcher.add_handler(WELCOME_MUTE_HELP)
dispatcher.add_handler(CHAT_MEMBER_HANDLER)
dispatcher.add_handler(SERVICE_MSG_HANDLER)

__mod_name__ = "Greetings"
__command_list__ = []
__handlers__ = [
    WELC_PREF_HANDLER,
    GOODBYE_PREF_HANDLER,
    SET_WELCOME,
    SET_GOODBYE,
    RESET_WELCOME,
    RESET_GOODBYE,
    CLEAN_WELCOME,
    WELCOME_HELP,
    WELCOMEMUTE_HANDLER,
    CLEAN_SERVICE_HANDLER,
    BUTTON_VERIFY_HANDLER,
    CAPTCHA_BUTTON_VERIFY_HANDLER,
    WELCOME_MUTE_HELP,
    CHAT_MEMBER_HANDLER,
    SERVICE_MSG_HANDLER,
]
