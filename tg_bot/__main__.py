import importlib
import logging
import re
from typing import Optional, List, Dict, Any
import asyncio
import signal
from contextlib import suppress
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode, ChatType
from telegram.error import (
    TelegramError,
    BadRequest,
    TimedOut,
    NetworkError,
    Forbidden,
)
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ApplicationHandlerStop,
    filters,
)
from telegram.helpers import escape_markdown

from tg_bot import (
    KInit,
    dispatcher,  # Application instance (compat alias)
    application,  # Application instance
    WEBHOOK,
    OWNER_ID,
    CERT_PATH,
    PORT,
    URL,
    KigyoINIT,
)

# NEW: ensure we insert the bot into DB after init
from tg_bot.modules.sql.users_sql import ensure_bot_in_db_app

# needed to dynamically load modules
# NOTE: Module order is not guaranteed, specify that in the config file!
from tg_bot.modules import ALL_MODULES
from tg_bot.modules.helper_funcs.chat_status import is_user_admin
from tg_bot.modules.helper_funcs.misc import paginate_modules
from tg_bot.modules.language import gs

IMPORTED: Dict[str, Any] = {}
MIGRATEABLE: List[Any] = []
HELPABLE: Dict[str, Any] = {}
STATS: List[Any] = []
USER_INFO: List[Any] = []
DATA_IMPORT: List[Any] = []
DATA_EXPORT: List[Any] = []

CHAT_SETTINGS: Dict[str, Any] = {}
USER_SETTINGS: Dict[str, Any] = {}

for module_name in ALL_MODULES:
    imported_module = importlib.import_module("tg_bot.modules." + module_name)
    if not hasattr(imported_module, "__mod_name__"):
        imported_module.__mod_name__ = imported_module.__name__

    if imported_module.__mod_name__.lower() not in IMPORTED:
        IMPORTED[imported_module.__mod_name__.lower()] = imported_module
    else:
        raise Exception("Can't have two modules with the same name! Please change one")

    if hasattr(imported_module, "get_help") and imported_module.get_help:
        HELPABLE[imported_module.__mod_name__.lower()] = imported_module

    # Chats to migrate on chat_migrated events
    if hasattr(imported_module, "__migrate__"):
        MIGRATEABLE.append(imported_module)

    if hasattr(imported_module, "__stats__"):
        STATS.append(imported_module)

    if hasattr(imported_module, "__user_info__"):
        USER_INFO.append(imported_module)

    if hasattr(imported_module, "__import_data__"):
        DATA_IMPORT.append(imported_module)

    if hasattr(imported_module, "__export_data__"):
        DATA_EXPORT.append(imported_module)

    if hasattr(imported_module, "__chat_settings__"):
        CHAT_SETTINGS[imported_module.__mod_name__.lower()] = imported_module

    if hasattr(imported_module, "__user_settings__"):
        USER_SETTINGS[imported_module.__mod_name__.lower()] = imported_module


async def send_help(chat_id: int, text: str, keyboard: InlineKeyboardMarkup | None = None):
    if not keyboard:
        kb = paginate_modules(0, HELPABLE, "help")
        keyboard = InlineKeyboardMarkup(kb)
    await dispatcher.bot.send_message(
        chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Minimal test command
    await update.effective_message.reply_text("This person edited a message")
    print(update.effective_message)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    args = context.args

    if update.callback_query:
        query = update.callback_query
        first_name = update.effective_user.first_name
        await update.effective_message.edit_text(
            text=gs(chat.id, "pm_start_text").format(
                escape_markdown(first_name),
                escape_markdown(context.bot.first_name),
                OWNER_ID,
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text=gs(chat.id, "support_chat_link_btn"),
                            url="https://t.me/spiralsupport",
                        ),
                        InlineKeyboardButton(
                            text=gs(chat.id, "src_btn"),
                            url="https://github.com/SnowFuhrer/spiraltgbot",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="Try inline",
                            switch_inline_query_current_chat="",
                        ),
                        InlineKeyboardButton(
                            text="Help",
                            callback_data="help_back",
                        ),
                        InlineKeyboardButton(
                            text=gs(chat.id, "add_bot_to_group_btn"),
                            url=f"t.me/{context.bot.username}?startgroup=true",
                        ),
                    ],
                ]
            ),
        )
        await context.bot.answer_callback_query(query.id)
        return

    if chat.type == ChatType.PRIVATE:
        if args and len(args) >= 1:
            arg = args[0].lower()
            if arg == "help":
                await send_help(chat.id, gs(chat.id, "pm_help_text"))
            elif arg.startswith("ghelp_"):
                mod = arg.split("_", 1)[1]
                if not HELPABLE.get(mod, False):
                    return
                help_list = HELPABLE[mod].get_help(chat.id)
                if isinstance(help_list, list):
                    help_text = help_list[0]
                    help_buttons = help_list[1:]
                else:
                    help_text = str(help_list)
                    help_buttons = []
                text = "Here is the help for the *{}* module:\n".format(
                    HELPABLE[mod].__mod_name__
                ) + help_text
                help_buttons.append(
                    [
                        InlineKeyboardButton(text="Back", callback_data="help_back"),
                        InlineKeyboardButton(
                            text="Support", url="https://t.me/spiralsupport"
                        ),
                    ]
                )
                await send_help(
                    chat.id,
                    text,
                    InlineKeyboardMarkup(help_buttons),
                )
            elif arg == "markdownhelp" and "extras" in IMPORTED:
                IMPORTED["extras"].markdown_help_sender(update)
            elif arg == "nations" and "nations" in IMPORTED:
                IMPORTED["nations"].send_nations(update)
            elif arg.startswith("stngs_"):
                match = re.match(r"stngs_(.*)", arg)
                if not match:
                    return
                chat_obj = await dispatcher.bot.get_chat(match.group(1))
                if await is_user_admin(update, update.effective_user.id):
                    await send_settings(chat_obj.id, update.effective_user.id, False)
                else:
                    await send_settings(chat_obj.id, update.effective_user.id, True)
            elif arg == "settings":
                await send_settings(update.effective_chat.id, update.effective_user.id, True)
            elif arg[1:].isdigit() and "rules" in IMPORTED:
                IMPORTED["rules"].send_rules(update, arg, from_pm=True)
        else:
            first_name = update.effective_user.first_name
            await update.effective_message.reply_text(
                text=gs(chat.id, "pm_start_text").format(
                    escape_markdown(first_name),
                    escape_markdown(context.bot.first_name),
                    OWNER_ID,
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text=gs(chat.id, "support_chat_link_btn"),
                                url="https://t.me/spiralsupport",
                            ),
                            InlineKeyboardButton(
                                text=gs(chat.id, "src_btn"),
                                url="https://github.com/SnowFuhrer/spiraltgbot",
                            ),
                        ],
                        [
                            InlineKeyboardButton(
                                text="Try inline",
                                switch_inline_query_current_chat="",
                            ),
                            InlineKeyboardButton(
                                text="Help",
                                callback_data="help_back",
                            ),
                            InlineKeyboardButton(
                                text=gs(chat.id, "add_bot_to_group_btn"),
                                url=f"t.me/{context.bot.username}?startgroup=true",
                            ),
                        ],
                    ]
                ),
            )
    else:
        await update.effective_message.reply_text(gs(chat.id, "grp_start_text"))


async def error_callback(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        raise context.error
    except (Forbidden, BadRequest, TimedOut, NetworkError, TelegramError):
        pass
    except Exception:
        logging.exception("Unhandled exception", exc_info=context.error)


async def help_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    mod_match = re.match(r"help_module\((.+?)\)", query.data)
    prev_match = re.match(r"help_prev\((.+?)\)", query.data)
    next_match = re.match(r"help_next\((.+?)\)", query.data)
    back_match = re.match(r"help_back", query.data)
    chat = update.effective_chat

    try:
        if mod_match:
            module = mod_match.group(1).replace("_", " ")
            help_list = HELPABLE[module].get_help(chat.id)
            if isinstance(help_list, list):
                help_text = help_list[0]
                help_buttons = help_list[1:]
            else:
                help_text = str(help_list)
                help_buttons = []
            text = "Here is the help for the *{}* module:\n".format(
                HELPABLE[module].__mod_name__
            ) + help_text
            help_buttons.append(
                [
                    InlineKeyboardButton(text="Back", callback_data="help_back"),
                    InlineKeyboardButton(
                        text="Support", url="https://t.me/spiralsupport"
                    ),
                ]
            )
            await query.message.edit_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(help_buttons),
            )

        elif prev_match:
            curr_page = int(prev_match.group(1))
            kb = paginate_modules(curr_page - 1, HELPABLE, "help")
            await query.message.edit_text(
                text=gs(chat.id, "pm_help_text"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb),
            )

        elif next_match:
            next_page = int(next_match.group(1))
            kb = paginate_modules(next_page + 1, HELPABLE, "help")
            await query.message.edit_text(
                text=gs(chat.id, "pm_help_text"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb),
            )

        elif back_match:
            kb = paginate_modules(0, HELPABLE, "help")
            await query.message.edit_text(
                text=gs(chat.id, "pm_help_text"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb),
            )

        await context.bot.answer_callback_query(query.id)

    except BadRequest:
        pass


async def get_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    args = (update.effective_message.text or "").split(None, 1)

    # ONLY send help in PM
    if chat.type != ChatType.PRIVATE:
        if len(args) >= 2:
            if any(args[1].lower() == x for x in HELPABLE):
                module = args[1].lower()
                await update.effective_message.reply_text(
                    f"Contact me in PM to get help of {module.capitalize()}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    text="Help",
                                    url=f"t.me/{context.bot.username}?start=ghelp_{module}",
                                )
                            ]
                        ]
                    ),
                )
            else:
                await update.effective_message.reply_text(
                    f"<code>{args[1].lower()}</code> is not a module",
                    parse_mode=ParseMode.HTML,
                )
            return

        await update.effective_message.reply_text(
            "Contact me in PM to get the list of possible commands.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="Help", url=f"t.me/{context.bot.username}?start=help")]]
            ),
        )
        return

    if len(args) >= 2:
        if any(args[1].lower() == x for x in HELPABLE):
            module = args[1].lower()
            help_list = HELPABLE[module].get_help(chat.id)
            if isinstance(help_list, list):
                help_text = help_list[0]
                help_buttons = help_list[1:]
            else:
                help_text = str(help_list)
                help_buttons = []
            text = "Here is the available help for the *{}* module:\n".format(
                HELPABLE[module].__mod_name__
            ) + help_text
            help_buttons.append(
                [
                    InlineKeyboardButton(text="Back", callback_data="help_back"),
                    InlineKeyboardButton(
                        text="Support", url="https://t.me/spiralsupport"
                    ),
                ]
            )
            await send_help(
                chat.id,
                text,
                InlineKeyboardMarkup(help_buttons),
            )
        else:
            await update.effective_message.reply_text(
                f"<code>{args[1].lower()}</code> is not a module",
                parse_mode=ParseMode.HTML,
            )
    else:
        await send_help(chat.id, gs(chat.id, "pm_help_text"))


async def send_settings(chat_id: int, user_id: int, user: bool = False):
    if user:
        if USER_SETTINGS:
            settings = "\n\n".join(
                "*{}*:\n{}".format(mod.__mod_name__, mod.__user_settings__(user_id))
                for mod in USER_SETTINGS.values()
            )
            await dispatcher.bot.send_message(
                user_id,
                "These are your current settings:\n\n" + settings,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await dispatcher.bot.send_message(
                user_id,
                "Seems like there aren't any user specific settings available :'(",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif CHAT_SETTINGS:
        chat_obj = await dispatcher.bot.get_chat(chat_id)
        await dispatcher.bot.send_message(
            user_id,
            text="Which module would you like to check {}'s settings for?".format(
                chat_obj.title
            ),
            reply_markup=InlineKeyboardMarkup(
                paginate_modules(0, CHAT_SETTINGS, "stngs", chat=chat_id)
            ),
        )
    else:
        await dispatcher.bot.send_message(
            user_id,
            "Seems like there aren't any chat settings available :'(\nSend this "
            "in a group chat you're admin in to find its current settings!",
            parse_mode=ParseMode.MARKDOWN,
        )


async def settings_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    user = update.effective_user
    bot = context.bot

    mod_match = re.match(r"stngs_module\((.+?),(.+?)\)", query.data)
    prev_match = re.match(r"stngs_prev\((.+?),(.+?)\)", query.data)
    next_match = re.match(r"stngs_next\((.+?),(.+?)\)", query.data)
    back_match = re.match(r"stngs_back\((.+?)\)", query.data)
    try:
        if mod_match:
            chat_id = mod_match.group(1)
            module = mod_match.group(2)
            chat = await bot.get_chat(chat_id)
            text = "*{}* has the following settings for the *{}* module:\n\n".format(
                escape_markdown(chat.title), CHAT_SETTINGS[module].__mod_name__
            ) + CHAT_SETTINGS[module].__chat_settings__(chat_id, user.id)
            await query.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text="Back",
                                callback_data=f"stngs_back({chat_id})",
                            )
                        ]
                    ]
                ),
            )

        elif prev_match:
            chat_id = prev_match.group(1)
            curr_page = int(prev_match.group(2))
            chat = await bot.get_chat(chat_id)
            await query.message.reply_text(
                f"Hi there! There are quite a few settings for {chat.title} - go ahead and pick what you're interested in.",
                reply_markup=InlineKeyboardMarkup(
                    paginate_modules(curr_page - 1, CHAT_SETTINGS, "stngs", chat=chat_id)
                ),
            )

        elif next_match:
            chat_id = next_match.group(1)
            next_page = int(next_match.group(2))
            chat = await bot.get_chat(chat_id)
            await query.message.reply_text(
                f"Hi there! There are quite a few settings for {chat.title} - go ahead and pick what you're interested in.",
                reply_markup=InlineKeyboardMarkup(
                    paginate_modules(next_page + 1, CHAT_SETTINGS, "stngs", chat=chat_id)
                ),
            )

        elif back_match:
            chat_id = back_match.group(1)
            chat = await bot.get_chat(chat_id)
            await query.message.reply_text(
                text="Hi there! There are quite a few settings for {} - go ahead and pick what you're interested in.".format(
                    escape_markdown(chat.title)
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    paginate_modules(0, CHAT_SETTINGS, "stngs", chat=chat_id)
                ),
            )

        await bot.answer_callback_query(query.id)
        await query.message.delete()
    except BadRequest as excp:
        if excp.message not in [
            "Message is not modified",
            "Query_id_invalid",
            "Message can't be deleted",
        ]:
            logging.exception("Exception in settings buttons. %s", str(query.data))


async def get_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    # ONLY send settings in PM
    if chat.type == ChatType.PRIVATE:
        await send_settings(chat.id, user.id, True)

    elif await is_user_admin(update, user.id):
        text = "Click here to get this chat's settings, as well as yours."
        await msg.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="Settings",
                            url=f"t.me/{context.bot.username}?start=stngs_{chat.id}",
                        )
                    ]
                ]
            ),
        )
    else:
        text = "Click here to check your settings."
        await msg.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="Settings",
                            url=f"t.me/{context.bot.username}?start=settings",
                        )
                    ]
                ]
            ),
        )


async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("I'm free for everyone! >_<")


async def migrate_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg.migrate_to_chat_id:
        old_chat = update.effective_chat.id
        new_chat = msg.migrate_to_chat_id
    elif msg.migrate_from_chat_id:
        old_chat = msg.migrate_from_chat_id
        new_chat = update.effective_chat.id
    else:
        return

    logging.info("Migrating from %s, to %s", str(old_chat), str(new_chat))
    for mod in MIGRATEABLE:
        mod.__migrate__(old_chat, new_chat)

    logging.info("Successfully migrated!")
    raise ApplicationHandlerStop


async def _post_init(app: Application):
    # Fill in bot identity after Application is ready
    me = await app.bot.get_me()
    KigyoINIT.bot_id = me.id
    KigyoINIT.bot_username = me.username
    KigyoINIT.bot_name = me.first_name

    # Ensure bot is present in DB (PTB 20+ safe place)
    await ensure_bot_in_db_app(app)

    logging.info(f"Spiral initialized. BOT: [@{me.username}]")

async def _graceful_shutdown():
    with suppress(Exception):
        await application.stop()
    with suppress(Exception):
        await application.shutdown()

def main():
    # Post-init hook
    application.post_init = _post_init

    # Error handler
    application.add_error_handler(error_callback)

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern=r"start_back"))

    application.add_handler(CallbackQueryHandler(help_button, pattern=r"help_"))
    application.add_handler(CommandHandler("help", get_help))

    application.add_handler(CallbackQueryHandler(settings_button, pattern=r"stngs_"))
    application.add_handler(CommandHandler("settings", get_settings))

    application.add_handler(CommandHandler("donate", donate))

    # Keep this as a small dev/test command
    application.add_handler(CommandHandler("test", test))

    # Migrations (supergroups) — PTB 20+: MIGRATION
    application.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, migrate_chats))

    # Map SIGTERM to KeyboardInterrupt so we run the same shutdown path
    def _raise_kbi(signum, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, _raise_kbi)
    except Exception:
        pass  # not available on some platforms (e.g., Windows)

    try:
        if WEBHOOK:
            logging.info("Using webhooks.")
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path=KInit.TOKEN,
                webhook_url=(URL or "") + KInit.TOKEN,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=KInit.DROP_UPDATES,
                stop_signals=None,  # we handle signals ourselves
            )
        else:
            logging.info("Using long polling.")
            application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=KInit.DROP_UPDATES,
                stop_signals=None,  # we handle signals ourselves
            )
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutdown requested (Ctrl+C / SIGTERM). Stopping application...")
    finally:
        # Ensure we always await a graceful stop/shutdown
        try:
            asyncio.run(_graceful_shutdown())
        except Exception:
            pass

if __name__ == "__main__":
    logging.info("[Spiral] Successfully loaded modules: %s", str(ALL_MODULES))
    main()
