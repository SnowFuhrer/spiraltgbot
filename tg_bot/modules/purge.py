import asyncio
import contextlib
import logging
from typing import List

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from tg_bot.modules.helper_funcs.anonymous import AdminPerms, user_admin
from tg_bot.modules.helper_funcs.chat_status import bot_admin
from tg_bot.modules.helper_funcs.decorators import rate_limit, kigcmd
from tg_bot.modules.log_channel import loggable

AUTO_DELETE_AFTER = 3  # seconds to keep the "Purge completed." message


def _chunked(lst: List[int], n: int) -> List[List[int]]:
    return [lst[i:i + n] for i in range(0, len(lst), n)]


async def _delete_message_later(bot, chat_id: int, message_id: int, delay: int = AUTO_DELETE_AFTER):
    await asyncio.sleep(delay)
    with contextlib.suppress(BadRequest):
        await bot.delete_message(chat_id=chat_id, message_id=message_id)


@kigcmd(command='purge')
@bot_admin
@user_admin(AdminPerms.CAN_DELETE_MESSAGES)
@rate_limit(40, 60)
@loggable
async def purge_messages_botapi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    reply = update.effective_message.reply_to_message
    if not reply:
        await update.effective_message.reply_text("Reply to the message you want to start purging from.")
        return

    # From the replied message up to and including the command message
    message_id_from = reply.message_id
    message_id_to = update.effective_message.message_id

    # Ensure ascending order just in case
    if message_id_from > message_id_to:
        message_id_from, message_id_to = message_id_to, message_id_from

    messages_to_delete = list(range(message_id_from, message_id_to + 1))

    try:
        delete_messages = getattr(context.bot, "delete_messages", None)
        if delete_messages and len(messages_to_delete) <= 100:
            await delete_messages(chat_id=chat_id, message_ids=messages_to_delete)
        elif delete_messages:
            for chunk in _chunked(messages_to_delete, 100):
                await delete_messages(chat_id=chat_id, message_ids=chunk)
        else:
            # Fallback: delete one by one
            for msg_id in messages_to_delete:
                with contextlib.suppress(BadRequest):
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)

    except BadRequest:
        # Fallback to single deletes if bulk fails for any reason
        for msg_id in messages_to_delete:
            with contextlib.suppress(BadRequest):
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception as e:
        logging.exception(e)
        with contextlib.suppress(BadRequest):
            await update.effective_message.reply_text("An error occurred while purging.")
        return f"#PURGE_FAILED \n<b>Admin:</b> {update.effective_user.first_name}\n<b>Chat:</b> {update.effective_chat.title}\n"

    # Send an ephemeral "Purge completed." message and auto-delete it
    info_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"Purge completed. Deleted {len(messages_to_delete)} message(s).",
    )
    asyncio.create_task(_delete_message_later(context.bot, chat_id, info_msg.message_id, delay=AUTO_DELETE_AFTER))

    return (
        f"#PURGE_COMPLETED \n"
        f"<b>Admin:</b> {update.effective_user.first_name}\n"
        f"<b>Chat:</b> {update.effective_chat.title}\n"
        f"<b>Messages:</b> {len(messages_to_delete)}\n"
    )


__mod_name__ = "Purges"
__command_list__ = ["del", "purge"]
