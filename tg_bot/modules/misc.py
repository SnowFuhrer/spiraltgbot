import contextlib
import html
import time
import git
import requests
from io import BytesIO
from subprocess import Popen, PIPE
import datetime
import platform
from platform import python_version
from telegram import Chat, Update, User, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
from telegram.ext import ContextTypes, filters as tg_filters
from telegram.helpers import mention_html, escape_markdown
from telegram.constants import ParseMode, MessageEntityType
from telegram import __version__ as ptbver
from psutil import cpu_percent, virtual_memory, disk_usage, boot_time

from tg_bot import (
    dispatcher,
    OWNER_ID,
    SUDO_USERS,
    SUPPORT_USERS,
    DEV_USERS,
    SARDEGNA_USERS,
    WHITELIST_USERS,
    INFOPIC,
    StartTime,
)
# Avoid circular import: fetch STATS/USER_INFO lazily when needed

from tg_bot.modules.sql import SESSION
from tg_bot.modules.helper_funcs.chat_status import user_admin, sudo_plus
from tg_bot.modules.helper_funcs.extraction import extract_user
import tg_bot.modules.sql.users_sql as sql
from sqlalchemy import text
from tg_bot.modules.users import __user_info__ as chat_count
from tg_bot.modules.language import gs
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigcallback, rate_limit


def _stats_modules():
    try:
        from tg_bot.__main__ import STATS
        return STATS
    except Exception:
        return []


def _user_info_modules():
    try:
        from tg_bot.__main__ import USER_INFO
        return USER_INFO
    except Exception:
        return []


MARKDOWN_HELP = """
Markdown is a very powerful formatting tool supported by telegram. {dispatcher.bot.first_name} has some enhancements, to make sure that \
saved messages are correctly parsed, and to allow you to create buttons.

- <code>_italic_</code>: wrapping text with '_' will produce italic text
- <code>*bold*</code>: wrapping text with '*' will produce bold text
- <code>`code`</code>: wrapping text with '`' will produce monospaced text, also known as 'code'
- <code>[sometext](someURL)</code>: this will create a link - the message will just show <code>sometext</code>, \
and tapping on it will open the page at <code>someURL</code>.
EG: <code>[test](example.com)</code>

- <code>[buttontext](buttonurl:someURL)</code>: this is a special enhancement to allow users to have telegram \
buttons in their markdown. <code>buttontext</code> will be what is displayed on the button, and <code>someurl</code> \
will be the url which is opened.
EG: <code>[This is a button](buttonurl:example.com)</code>

If you want multiple buttons on the same line, use :same, as such:
<code>[one](buttonurl://example.com)
[two](buttonurl://google.com:same)</code>
This will create two buttons on a single line, instead of one button per line.

Keep in mind that your message <b>MUST</b> contain some text other than just a button!
"""


@kigcmd(command='id')
@rate_limit(40, 60)
async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot, args = context.bot, context.args
    message = update.effective_message
    chat = update.effective_chat
    msg = update.effective_message

    user_id = await extract_user(msg, args)

    if user_id:
        # If replying to a forwarded message, show both the origin and the forwarder
        if msg.reply_to_message and getattr(msg.reply_to_message, "forward_origin", None):
            fwd = msg.reply_to_message
            fo = fwd.forward_origin

            # Forwarder (the sender in this chat)
            if fwd.from_user:
                forwarder_name = html.escape(fwd.from_user.first_name)
                forwarder_id = fwd.from_user.id
            elif fwd.sender_chat:
                forwarder_name = html.escape(fwd.sender_chat.title or fwd.sender_chat.username or "Unknown chat")
                forwarder_id = fwd.sender_chat.id
            else:
                forwarder_name = "Unknown"
                forwarder_id = "N/A"

            # Origin of the forwarded message (user/chat/channel)
            origin_name = "Hidden user"
            origin_id = "N/A"
            if getattr(fo, "sender_user", None):
                origin_name = html.escape(fo.sender_user.first_name)
                origin_id = fo.sender_user.id
            elif getattr(fo, "sender_chat", None):
                origin_name = html.escape(fo.sender_chat.title or fo.sender_chat.username or "Unknown chat")
                origin_id = fo.sender_chat.id
            elif getattr(fo, "chat", None):  # MessageOriginChannel
                origin_name = html.escape(fo.chat.title or fo.chat.username or "Unknown channel")
                origin_id = fo.chat.id
            # MessageOriginHiddenUser exposes only sender_user_name (no ID); keep N/A for ID

            await msg.reply_text(
                f"<b>Telegram ID:</b>\n"
                f"• {origin_name} - <code>{origin_id}</code>.\n"
                f"• {forwarder_name} - <code>{forwarder_id}</code>.",
                parse_mode=ParseMode.HTML,
            )
        else:
            user = await bot.get_chat(user_id)
            name = (
                html.escape(getattr(user, "first_name", None) or "")
                or html.escape(getattr(user, "title", None) or "")
                or (f"@{user.username}" if getattr(user, "username", None) else "User")
            )
            await msg.reply_text(
                f"{name}'s id is <code>{user.id}</code>.",
                parse_mode=ParseMode.HTML,
            )

    elif chat.type == "private":
        await msg.reply_text(
            f"Your id is <code>{chat.id}</code>.", parse_mode=ParseMode.HTML
        )
    else:
        await msg.reply_text(
            f"This group's id is <code>{chat.id}</code>.", parse_mode=ParseMode.HTML
        )

@kigcmd(command='info')
@rate_limit(40, 60)
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    bot = context.bot
    args = context.args
    message = update.effective_message
    chat = update.effective_chat

    user_id = await extract_user(update.effective_message, args)  # <-- await here
    if user_id:
        user = await bot.get_chat(user_id)
    elif not message.reply_to_message and not args:
        user = message.sender_chat if message.sender_chat is not None else message.from_user
    elif not message.reply_to_message and (
        not args
        or (
            len(args) >= 1
            and not args[0].startswith("@")
            and not args[0].lstrip("-").isdigit()
            and not message.parse_entities(types=[MessageEntityType.TEXT_MENTION])
        )
    ):
        await message.reply_text("I can't extract a user from this.")
        return
    else:
        return

    if hasattr(user, 'type') and user.type != "private":
        text = get_chat_info(user)
        is_chat = True
    else:
        text = await get_user_info(chat, user)
        is_chat = False

    if INFOPIC:
        if is_chat:
            try:
                pic = user.photo.big_file_id
                _file = await bot.get_file(pic)
                pfp = BytesIO()
                await _file.download_to_memory(out=pfp)
                pfp.seek(0)

                await message.reply_document(
                    document=bio,
                    filename=f"{user.id}.jpg",
                    caption=text,
                    parse_mode=ParseMode.HTML,
                )
            except AttributeError:
                await message.reply_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        else:
            try:
                upp = await bot.get_user_profile_photos(user.id)
                profile = upp.photos[0][-1]
                _file = await bot.get_file(profile.file_id)
                bio = BytesIO()
                await _file.download_to_memory(out=bio)
                bio.seek(0)

                await message.reply_document(
                    document=bio,
                    filename=f"{user.id}.jpg",
                    caption=text,
                    parse_mode=ParseMode.HTML,
                )
            except IndexError:
                await message.reply_text(
                    text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
    else:
        await message.reply_text(
            text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )

async def get_user_info(chat: Chat, user: User) -> str:
    from telegram.constants import ChatMemberStatus

    bot = dispatcher.bot
    text = (
        f"<b>General:</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"First Name: {html.escape(user.first_name)}"
    )
    if user.last_name:
        text += f"\nLast Name: {html.escape(user.last_name)}"
    if user.username:
        text += f"\nUsername: @{html.escape(user.username)}"
    text += f"\nPermanent user link: {mention_html(user.id, 'link')}"
    Nation_level_present = False
    num_chats = sql.get_user_num_chats(user.id)
    text += f"\n<b>Chat count</b>: <code>{num_chats}</code>"
    with contextlib.suppress(BadRequest):
        result = await bot.get_chat_member(chat.id, user.id)
        if result.status == ChatMemberStatus.ADMINISTRATOR and result.custom_title:
            text += f"\nThis user holds the title <b>{result.custom_title}</b> here."
    if user.id == OWNER_ID:
        text += '\nThis person is my owner'
        Nation_level_present = True
    elif user.id in DEV_USERS:
        text += '\nThis Person is a developer'
        Nation_level_present = True
    elif user.id in SUDO_USERS:
        text += '\nThis person is a superuser'
        Nation_level_present = True
    elif user.id in SUPPORT_USERS:
        text += '\nThis person is a support user'
        Nation_level_present = True
    elif user.id in SARDEGNA_USERS:
        text += '\nThis person is a pro user'
        Nation_level_present = True
    elif user.id in WHITELIST_USERS:
        text += '\nThis person is whitelisted'
        Nation_level_present = True
    if Nation_level_present:
        text += f' [<a href="https://t.me/{bot.username}?start=nations">?</a>]'
    text += "\n"
    for mod in _user_info_modules():
        if mod.__mod_name__ == "Users":
            continue
        try:
            mod_info = mod.__user_info__(user.id)
        except TypeError:
            mod_info = mod.__user_info__(user.id, chat.id)
        if mod_info:
            text += "\n" + mod_info
    return text


def get_chat_info(user):
    text = (
        f"<b>Chat Info:</b>\n"
        f"<b>Title:</b> {user.title}"
    )
    if user.username:
        text += f"\n<b>Username:</b> @{html.escape(user.username)}"
    text += f"\n<b>Chat ID:</b> <code>{user.id}</code>"
    text += f"\n<b>Chat Type:</b> {user.type.capitalize()}"
    text += "\n" + chat_count(user.id)
    return text


@kigcmd(command='echo', filters=tg_filters.ChatType.GROUPS)
@user_admin
@rate_limit(40, 60)
async def echo(update: Update, _):
    args = update.effective_message.text.split(None, 1)
    message = update.effective_message

    if message.reply_to_message:
        await message.reply_to_message.reply_text(args[1])
    else:
        await message.reply_text(args[1], quote=False)

    await message.delete()


def shell(command):
    process = Popen(command, stdout=PIPE, shell=True, stderr=PIPE)
    stdout, stderr = process.communicate()
    return (stdout, stderr)


@kigcmd(command='markdownhelp', filters=tg_filters.ChatType.PRIVATE)
@rate_limit(40, 60)
async def markdown_help(update: Update, _):
    chat = update.effective_chat
    await update.effective_message.reply_text((gs(chat.id, "markdown_help_text")), parse_mode=ParseMode.HTML)
    await update.effective_message.reply_text(
        "Try forwarding the following message to me, and you'll see!"
    )
    await update.effective_message.reply_text(
        "/save test This is a markdown test. _italics_, *bold*, `code`, "
        "[URL](example.com) [button](buttonurl:github.com) "
        "[button2](buttonurl://google.com:same)"
    )


def get_readable_time(seconds: int) -> str:
    count = 0
    ping_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "days"]

    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)

    for x in range(len(time_list)):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        ping_time += f'{time_list.pop()}, '

    time_list.reverse()
    ping_time += ":".join(time_list)

    return ping_time


stats_str = '''
'''


@kigcmd(command='stats', can_disable=False)
@sudo_plus
@rate_limit(40, 60)
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_size = SESSION.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar_one_or_none()
    uptime = datetime.datetime.fromtimestamp(boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    botuptime = get_readable_time((time.time() - StartTime))
    status = "*╒═══「 System statistics: 」*\n\n"
    status += f"*• System Start time:* {str(uptime)}\n"
    uname = platform.uname()
    status += f"*• System:* {str(uname.system)}\n"
    status += f"*• Node name:* {escape_markdown(str(uname.node), version=1)}\n"
    status += f"*• Release:* {escape_markdown(str(uname.release), version=1)}\n"
    status += f"*• Machine:* {escape_markdown(str(uname.machine), version=1)}\n"

    mem = virtual_memory()
    cpu = cpu_percent()
    disk = disk_usage("/")
    status += f"*• CPU:* {str(cpu)} %\n"
    status += f"*• RAM:* {str(mem[2])} %\n"
    status += f"*• Storage:* {str(disk[3])} %\n\n"
    status += f"*• Python version:* {python_version()}\n"
    status += f"*• python-telegram-bot:* {str(ptbver)}\n"
    status += f"*• Uptime:* {str(botuptime)}\n"
    status += f"*• Database size:* {str(db_size)}\n"
    kb = [[InlineKeyboardButton('Ping', callback_data='pingCB')]]

    try:
        repo = git.Repo(search_parent_directories=True)
        sha = repo.head.object.hexsha
        status += f"*• Commit*: `{sha[:9]}`\n"
    except Exception as e:
        status += f"*• Commit*: `{str(e)}`\n"

    try:
        await update.effective_message.reply_text(
            status +
            "\n*Bot statistics*:\n"
            + "\n".join([mod.__stats__() for mod in _stats_modules()]) +
            "\n\n[⍙ GitHub](https://t.me/enrapturedoverwatch_bot) \n" +
            "╘══「 by [SnowFuhrer](github.com/SnowFuhrer) 」\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb),
            disable_web_page_preview=True
        )
    except BaseException:
        await update.effective_message.reply_text(
            (
                "\n*Bot statistics*:\n"
                + "\n".join(mod.__stats__() for mod in _stats_modules())
                + "\n\n⍙ [GitHub](https://t.me/enrapturedoverwatch_bot)\n"
                + "╘══「 by [SnowFuhrer](github.com/SnowFuhrer) 」\n"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb),
            disable_web_page_preview=True,
        )


@kigcmd(command='ping')
@rate_limit(40, 60)
async def ping(update: Update, _):
    msg = update.effective_message
    start_time = time.time()
    message = await msg.reply_text("Pinging...")
    end_time = time.time()
    ping_time = round((end_time - start_time) * 1000, 3)
    await message.edit_text(
        "*Pong!!!*\n`{}ms`".format(ping_time), parse_mode=ParseMode.MARKDOWN
    )


@kigcallback(pattern=r'^pingCB')
@rate_limit(40, 60)
async def pingCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    start_time = time.time()
    requests.get('https://api.telegram.org')
    end_time = time.time()
    ping_time = round((end_time - start_time) * 1000, 3)
    await query.answer(f'Pong! {ping_time}ms')


def get_help(chat):
    return gs(chat, "misc_help")


__mod_name__ = "Misc"
