import re
import inspect
from typing import Iterable, List, Optional, Union

from telegram import Update
from telegram.ext import MessageHandler, ContextTypes
from telegram.ext import filters as tg_filters
from tg_bot import DEV_USERS, SUDO_USERS, WHITELIST_USERS, SUPPORT_USERS, SARDEGNA_USERS

from pyrate_limiter import (
    BucketFullException,
    Duration,
    RequestRate,
    Limiter,
    MemoryListBucket,
)

try:
    from tg_bot import CUSTOM_CMD
except Exception:
    CUSTOM_CMD = False

CMD_STARTERS: List[str] = (CUSTOM_CMD or ["/", "!"])


class AntiSpam:
    def __init__(self):
        self.whitelist = (
            (DEV_USERS or [])
            + (SUDO_USERS or [])
            + (WHITELIST_USERS or [])
            + (SUPPORT_USERS or [])
            + (SARDEGNA_USERS or [])
        )
        # Values are experimental
        Duration.CUSTOM = 15  # 15 seconds
        self.sec_limit = RequestRate(6, Duration.CUSTOM)     # 6 / 15s
        self.min_limit = RequestRate(20, Duration.MINUTE)    # 20 / minute
        self.hour_limit = RequestRate(100, Duration.HOUR)    # 100 / hour
        self.daily_limit = RequestRate(1000, Duration.DAY)   # 1000 / day
        self.limiter = Limiter(
            self.sec_limit,
            self.min_limit,
            self.hour_limit,
            self.daily_limit,
            bucket_class=MemoryListBucket,
        )

    def check_user(self, user_id: Optional[int]) -> bool:
        """
        Return True if user should be ignored (rate-limited), else False.
        """
        if user_id is None:
            return False
        if user_id in self.whitelist:
            return False
        try:
            self.limiter.try_acquire(user_id)
            return False
        except BucketFullException:
            return True


SpamChecker = AntiSpam()
MessageHandlerChecker = AntiSpam()


class CustomCommandHandler(MessageHandler):
    """
    PTB 20+ compatible handler that supports multiple command prefixes (e.g. '/', '!').

    It uses a Regex filter internally and:
    - Respects mentions: '/cmd@ThisBot' will only trigger if it matches context.bot.username.
    - Populates context.args similar to CommandHandler.
    - Applies AntiSpam checks before invoking your callback.
    """

    def __init__(
        self,
        command: Union[str, Iterable[str]],
        callback,
        *,
        extra_filters: Optional[tg_filters.BaseFilter] = None,
        block: bool = False,
        prefixes: Optional[Iterable[str]] = None,
        # legacy kwargs for compatibility (ignored)
        **kwargs,
    ):
        self._orig_callback = callback
        self._commands = [command] if isinstance(command, str) else list(command)
        self._prefixes = list(prefixes) if prefixes else list(CMD_STARTERS)

        cmds_pattern = "|".join(re.escape(c) for c in self._commands)
        prefixes_pattern = "".join(re.escape(p) for p in self._prefixes)

        # Start-anchored command with optional @mention and args after space or EOL
        self._regex = re.compile(
            rf"^(?P<prefix>[{prefixes_pattern}])(?P<cmd>{cmds_pattern})"
            r"(?:@(?P<mention>[A-Za-z0-9_]{5,64}))?(?:\s|$)",
            re.IGNORECASE,
        )

        base_filter = tg_filters.Regex(self._regex) & tg_filters.TEXT
        if extra_filters is not None:
            base_filter = base_filter & extra_filters

        super().__init__(base_filter, self._callback_wrapper, block=block)

    async def _callback_wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.text:
            return

        # Anti-spam
        user_id = update.effective_user.id if update.effective_user else None
        if SpamChecker.check_user(user_id):
            return

        m = self._regex.match(message.text)
        if not m:
            return

        mention = m.group("mention")
        if mention and context.bot and mention.lower() != (context.bot.username or "").lower():
            # Mention to another bot -> ignore
            return

        # Build args similar to CommandHandler
        args_str = message.text[m.end():].strip()
        args = args_str.split() if args_str else []

        # Try to set context.args if possible
        try:
            context.args = args  # PTB 20 DefaultContext usually allows this
        except Exception:
            # Fallback: store in bot_data for retrieval if needed
            context.bot_data["__custom_cmd_args__"] = args

        res = self._orig_callback(update, context)
        if inspect.isawaitable(res):
            await res
