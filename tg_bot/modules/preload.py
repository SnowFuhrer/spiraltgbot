
import contextlib
import html
import time
import git
import requests
from io import BytesIO

from telegram import Chat, Update, MessageEntity, User
from telegram.error import BadRequest
from telegram.ext import ContextTypes, filters
from telegram.helpers import mention_html, escape_markdown
from subprocess import Popen, PIPE
import tg_bot.modules.sql.welcome_sql as wsql

from tg_bot import (
    dispatcher,  # keep if still used elsewhere in your project
    OWNER_ID,
    SUDO_USERS,
    SUPPORT_USERS,
    DEV_USERS,
    SARDEGNA_USERS,
    WHITELIST_USERS,
    INFOPIC,
    StartTime,
)
# Removed to avoid circular import; also not used in this module
# from tg_bot.__main__ import STATS, USER_INFO, TOKEN
from tg_bot.modules.sql import SESSION
from tg_bot.modules.helper_funcs.chat_status import user_admin, sudo_plus
from tg_bot.modules.helper_funcs.extraction import extract_user
import tg_bot.modules.sql.users_sql as sql
from tg_bot.modules.users import __user_info__ as chat_count
from tg_bot.modules.language import gs
from telegram import __version__ as ptbver, InlineKeyboardMarkup, InlineKeyboardButton
from psutil import cpu_percent, virtual_memory, disk_usage, boot_time
import datetime
import platform
from platform import python_version
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigcallback, rate_limit


@kigcmd(command='writedb', can_disable=False)
@sudo_plus
@rate_limit(40, 60)
async def writedb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    pr = ''
    if chat.type != "private":
        return ""
    wsql.set_gdbye_preference(str(pr), False)
    await msg.reply_text(f"goodbye turned off for {pr}")
    wsql.set_welc_preference(str(pr), False)
    await msg.reply_text(f"welcome turned off for {pr}")
    wsql.set_clean_service(pr, True)
    await msg.reply_text(f"cleanservice turned on for {pr}")
    return ""


def get_help(chat):
    return gs(chat, "preload_help")


__mod_name__ = "preload"
