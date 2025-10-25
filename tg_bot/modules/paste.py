from .helper_funcs.misc import upload_text
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes
# ParseMode not needed here, kept for reference:
# from telegram.constants import ParseMode
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit

@kigcmd(command='paste')
@rate_limit(40, 60)
async def paste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    message = update.effective_message

    if not message:
        return

    data = None

    if message.reply_to_message:
        data = message.reply_to_message.text or message.reply_to_message.caption
        if message.reply_to_message.document:
            file_info = await context.bot.get_file(message.reply_to_message.document.file_id)
            with BytesIO() as file:
                await file_info.download_to_memory(out=file)
                file.seek(0)
                data = file.read().decode(errors="ignore")

    elif args:
        data = message.text.split(None, 1)[1]

    if not data:
        await message.reply_text("What am I supposed to do with this?")
        return

    paste_url = upload_text(data)
    if not paste_url:
        txt = "Failed to paste data"
    else:
        txt = f"Successfully uploaded to Privatebin: {paste_url}"

    await message.reply_text(txt, disable_web_page_preview=True)
