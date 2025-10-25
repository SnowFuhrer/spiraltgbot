
from telegram import Message
from telegram.ext.filters import MessageFilter  # PTB 20+: moved here

from tg_bot import SUPPORT_USERS, SUDO_USERS, DEV_USERS


class CustomFilters:
    class _Supporters(MessageFilter):
        def filter(self, message: Message) -> bool:
            return bool(message.from_user and message.from_user.id in SUPPORT_USERS)

    support_filter = _Supporters()

    class _Sudoers(MessageFilter):
        def filter(self, message: Message) -> bool:
            return bool(message.from_user and message.from_user.id in SUDO_USERS)

    sudo_filter = _Sudoers()

    class _Developers(MessageFilter):
        def filter(self, message: Message) -> bool:
            return bool(message.from_user and message.from_user.id in DEV_USERS)

    dev_filter = _Developers()

    class _MimeType(MessageFilter):
        def __init__(self, mimetype: str):
            self.mime_type = mimetype
            self.name = f"CustomFilters.mime_type({self.mime_type})"

        def filter(self, message: Message) -> bool:
            return bool(message.document and message.document.mime_type == self.mime_type)

    mime_type = _MimeType

    class _HasText(MessageFilter):
        def filter(self, message: Message) -> bool:
            return bool(
                message.text
                or message.sticker
                or message.photo
                or message.document
                or message.video
                or message.audio
                or message.voice
                or message.animation
                or message.video_note
            )

    has_text = _HasText()
