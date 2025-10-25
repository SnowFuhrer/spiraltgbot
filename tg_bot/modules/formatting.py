from tg_bot.modules.helper_funcs.decorators import kigcallback, rate_limit
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from tg_bot.modules.language import gs


@rate_limit(40, 60)
async def fmt_md_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        gs(update.effective_chat.id, "md_help"),
        parse_mode=ParseMode.HTML,
    )


@rate_limit(40, 60)
async def fmt_filling_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        gs(update.effective_chat.id, "filling_help"),
        parse_mode=ParseMode.HTML,
    )


@kigcallback(pattern=r"fmt_help_")
@rate_limit(40, 60)
async def fmt_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    help_info = query.data.split("fmt_help_")[1]

    if help_info == "md":
        help_text = gs(update.effective_chat.id, "md_help")
    elif help_info == "filling":
        help_text = gs(update.effective_chat.id, "filling_help")
    else:
        help_text = gs(update.effective_chat.id, "md_help")

    await query.message.edit_text(
        text=help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Back",
                        callback_data=f"help_module({__mod_name__.lower()})",
                    ),
                    InlineKeyboardButton(
                        text="Report Error",
                        url="https://t.me/YorkTownEagleUnion",
                    ),
                ]
            ]
        ),
    )
    await query.answer()


__mod_name__ = "Formatting"


def get_help(chat):
    return [
        gs(chat, "formt_help_bse"),
        [
            InlineKeyboardButton(text="Markdown", callback_data="fmt_help_md"),
            InlineKeyboardButton(text="Filling", callback_data="fmt_help_filling"),
        ],
    ]
