import subprocess

from tg_bot import log as LOGGER, SYS_ADMIN
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, filters
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit
from telegram import InputFile


@kigcmd(command='sh', filters=filters.User(SYS_ADMIN))
@rate_limit(40, 60)
async def shell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    cmd_parts = message.text.split(" ", 1)
    if len(cmd_parts) == 1:
        await message.reply_text("No command to execute was given.")
        return

    cmd = cmd_parts[1]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True,
    )
    stdout, stderr = process.communicate()
    stderr = stderr.decode()
    stdout = stdout.decode()

    reply = ""
    if stdout:
        reply += f"*Stdout*\n`{stdout}`\n"
        LOGGER.info(f"Shell - {cmd} - {stdout}")
    if stderr:
        reply += f"*Stderr*\n`{stderr}`\n"
        LOGGER.error(f"Shell - {cmd} - {stderr}")

    if len(reply) > 3000:
        path = "shell_output.txt"
        with open(path, "w") as file:
            file.write(reply)
        await context.bot.send_document(
            chat_id=message.chat_id,
            document=FSInputFile(path),
            reply_to_message_id=message.message_id,
        )
    else:
        await message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)


__mod_name__ = "Shell"
