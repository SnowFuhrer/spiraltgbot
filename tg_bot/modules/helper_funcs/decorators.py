import logging
import time
import redis
import inspect
from functools import wraps
from typing import Optional, List, Callable, Union

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ChosenInlineResultHandler,
    ContextTypes,
    filters as tg_filters,
)

from tg_bot import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, dispatcher
from tg_bot.modules.helper_funcs.handlers import CustomCommandHandler


# If you have PTB20-compatible disable handlers, keep these imports.
# Otherwise, the fallback below uses regular handlers.
try:
    from tg_bot.modules.disable import (
        DisableAbleCommandHandler,
        DisableAbleMessageHandler,
    )
    HAS_DISABLEABLE = True
except Exception:
    DisableAbleCommandHandler = None
    DisableAbleMessageHandler = None
    HAS_DISABLEABLE = False

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
)


def rate_limit(messages_per_window: int, window_seconds: int):
    """
    Async-safe Redis-backed rate limiter decorator.
    Drops execution when the user exceeds messages_per_window within window_seconds.
    """
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                user_id = update.effective_user.id if update.effective_user else 0
                current_time = time.time()
                key = f"rate_limit:{user_id}"

                user_history = [float(t) for t in redis_client.lrange(key, 0, -1)]
                user_history = [t for t in user_history if current_time - t <= window_seconds]

                if len(user_history) >= messages_per_window:
                    logging.info(
                        f"Rate limit exceeded for user {user_id}. "
                        f"Allowed {messages_per_window} updates in {window_seconds} seconds."
                    )
                    return

                pipe = redis_client.pipeline()
                pipe.lpush(key, current_time)
                pipe.ltrim(key, 0, messages_per_window - 1)
                pipe.expire(key, window_seconds)
                pipe.execute()

                return await func(update, context)
            return wrapper
        else:
            @wraps(func)
            def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                user_id = update.effective_user.id if update.effective_user else 0
                current_time = time.time()
                key = f"rate_limit:{user_id}"

                user_history = [float(t) for t in redis_client.lrange(key, 0, -1)]
                user_history = [t for t in user_history if current_time - t <= window_seconds]

                if len(user_history) >= messages_per_window:
                    logging.info(
                        f"Rate limit exceeded for user {user_id}. "
                        f"Allowed {messages_per_window} updates in {window_seconds} seconds."
                    )
                    return

                pipe = redis_client.pipeline()
                pipe.lpush(key, current_time)
                pipe.ltrim(key, 0, messages_per_window - 1)
                pipe.expire(key, window_seconds)
                pipe.execute()

                return func(update, context)
            return wrapper
    return decorator


class KigyoTelegramHandler:
    """
    PTB 20+ compatible decorator helper to register handlers on the Application
    (or a DispatcherShim exposing add_handler/remove_handler).
    """
    def __init__(self, dispatcher: Application):
        self._dispatcher = dispatcher

    @property
    def application(self) -> Application:
        # Back-compat attribute name used elsewhere in the codebase
        return self._dispatcher

    def _add_handler(self, handler, group: Optional[int] = None):
        if group is not None:
            self._dispatcher.add_handler(handler, group=group)
        else:
            self._dispatcher.add_handler(handler)

    def command(
        self,
        command: Union[str, List[str]],
        filters: Optional[tg_filters.BaseFilter] = None,
        admin_ok: bool = False,     # kept for compatibility; pass through if your DisableAble* uses it
        pass_args: bool = False,    # ignored in PTB 20+
        pass_chat_data: bool = False,  # ignored in PTB 20+
        can_disable: bool = True,
        group: Optional[int] = 40,
        block: bool = False,
    ):
        def decorator(func: Callable):
            commands = [command] if isinstance(command, str) else command

            # Prefer your disableable handler if it’s PTB20-ready; otherwise fall back to CustomCommandHandler.
            if can_disable and HAS_DISABLEABLE and DisableAbleCommandHandler is not None:
                handler = DisableAbleCommandHandler(
                    commands,
                    func,
                    filters=filters,
                    admin_ok=admin_ok,  # if your implementation supports it
                    block=block,
                )
            else:
                handler = CustomCommandHandler(
                    commands,
                    func,
                    extra_filters=filters,
                    block=block,
                )

            # FIX: call the correct helper
            self._add_handler(handler, group)
            logging.debug(f"[KIGCMD] Loaded handler {commands} for function {func.__name__}")
            return func
        return decorator

    def message(
        self,
        pattern: Optional[tg_filters.BaseFilter] = None,
        can_disable: bool = True,
        group: Optional[int] = 60,
        friendly: Optional[str] = None,  # kept for compatibility with your DisableAbleMessageHandler
        block: bool = False,
    ):
        def decorator(func: Callable):
            message_filter = pattern if pattern is not None else tg_filters.ALL

            if can_disable and HAS_DISABLEABLE and DisableAbleMessageHandler is not None:
                handler = DisableAbleMessageHandler(
                    message_filter,
                    func,
                    friendly=friendly,
                    block=block,
                )
            else:
                handler = MessageHandler(message_filter, func, block=block)

            self._add_handler(handler, group)
            logging.debug(f"[KIGMSG] Loaded filter for function {func.__name__}")
            return func
        return decorator

    def callbackquery(self, pattern: str = None, block: bool = False):
        def decorator(func: Callable):
            handler = CallbackQueryHandler(func, pattern=pattern, block=block)
            self._add_handler(handler)
            logging.debug(f"[KIGCALLBACK] Loaded callbackquery handler for function {func.__name__}")
            return func
        return decorator

    def inlinequery(
        self,
        pattern: Optional[str] = None,
        block: bool = False,
        chat_types: Optional[List[str]] = None,  # PTB 20 expects ChatType values; keep as-is for compatibility
    ):
        def decorator(func: Callable):
            handler = InlineQueryHandler(
                func,
                pattern=pattern,
                block=block,
                chat_types=chat_types,
            )
            self._add_handler(handler)
            logging.debug(f"[KIGINLINE] Loaded inlinequery handler for function {func.__name__}")
            return func
        return decorator

    def chosen(self, block: bool = False):
        """
        Decorator to register a ChosenInlineResultHandler.
        Fires when a user selects (sends) one of your inline results.
        """
        def decorator(func: Callable):
            handler = ChosenInlineResultHandler(func, block=block)
            self._add_handler(handler)
            logging.debug(f"[KIGCHOSEN] Loaded chosen_inline_result handler for function {func.__name__}")
            return func
        return decorator


kigyo_handler = KigyoTelegramHandler(dispatcher)

kigcmd = kigyo_handler.command
kigmsg = kigyo_handler.message
kigcallback = kigyo_handler.callbackquery
kiginline = kigyo_handler.inlinequery
kigchosen = kigyo_handler.chosen
