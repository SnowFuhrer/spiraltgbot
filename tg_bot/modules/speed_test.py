import asyncio
import speedtest

from tg_bot import DEV_USERS, dispatcher
from tg_bot.modules.helper_funcs.chat_status import dev_plus
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigcallback, rate_limit


def convert(speed):
    return round(int(speed) / 1048576, 2)


@kigcmd(command='speedtest')
@dev_plus
@rate_limit(40, 60)
async def speedtestxyz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [
            InlineKeyboardButton("Image", callback_data="speedtest_image"),
            InlineKeyboardButton("Text", callback_data="speedtest_text"),
        ]
    ]
    await update.effective_message.reply_text(
        "Select SpeedTest Mode", reply_markup=InlineKeyboardMarkup(buttons)
    )


@kigcallback(pattern="speedtest_.*")
@rate_limit(40, 60)
async def speedtestxyz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id in DEV_USERS:
        msg = await update.effective_message.edit_text("Running a speedtest....")

        if query.data == "speedtest_image":
            def run_image():
                s = speedtest.Speedtest()
                s.get_best_server()
                s.download()
                s.upload()
                return s.results.share()

            speedtest_image = await asyncio.to_thread(run_image)
            await update.effective_message.reply_photo(
                photo=speedtest_image, caption="SpeedTest Results:"
            )
            await msg.delete()

        elif query.data == "speedtest_text":
            def run_text():
                s = speedtest.Speedtest()
                s.get_best_server()
                s.download()
                s.upload()
                return s.results.dict()

            result = await asyncio.to_thread(run_text)
            replymsg = (
                "SpeedTest Results:"
                f"\nDownload: `{convert(result['download'])}Mb/s`"
                f"\nUpload: `{convert(result['upload'])}Mb/s`"
                f"\nPing: `{result['ping']}`"
            )
            await update.effective_message.edit_text(replymsg, parse_mode=ParseMode.MARKDOWN)
    else:
        await query.answer("You are not a part of Eagle Union.")
        

__mod_name__ = "SpeedTest"
