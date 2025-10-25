from functools import wraps
from telegram.error import BadRequest
from telegram.constants import ChatAction


async def send_message(message, text, *args, **kwargs):
    try:
        return await message.reply_text(text, *args, **kwargs)
    except BadRequest as err:
        if "Reply message not found" in str(err):
            return await message.reply_text(text, quote=False, *args, **kwargs)


def typing_action(func):
    """Sends typing action while processing func command."""
    @wraps(func)
    async def command_func(update, context, *args, **kwargs):
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
        return await func(update, context, *args, **kwargs)

    return command_func


def send_action(action):
    """Sends `action` while processing func command."""
    def decorator(func):
        @wraps(func)
        async def command_func(update, context, *args, **kwargs):
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=action
            )
            return await func(update, context, *args, **kwargs)

        return command_func

    return decorator
