import requests
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit
from tg_bot.modules.helper_funcs.chat_status import bot_admin


@kigcmd(command=["ud", "urban"])
@bot_admin
@rate_limit(40, 60)
async def ud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    text = " ".join(context.args).strip() if context.args else ""

    if not text:
        await message.reply_text("Please provide a term to search, e.g. /ud yeet")
        return

    try:
        results = requests.get(
            "https://api.urbandictionary.com/v0/define", params={"term": text}
        ).json()
        first = results["list"][0]
        reply_text = f'*{text}*\n\n{first["definition"]}\n\n__{first["example"]}__'
    except Exception:
        reply_text = "No results found."

    await message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
