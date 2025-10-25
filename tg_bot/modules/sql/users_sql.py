import threading

from sqlalchemy.sql.sqltypes import BigInteger

from tg_bot.modules.sql import BASE, SESSION
from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    UnicodeText,
    UniqueConstraint,
    func,
)

from tg_bot.modules.sql.cache_utils import cached, clear_cache, invalidate_cache_pattern


class Users(BASE):
    __tablename__ = "users"
    user_id = Column(BigInteger, primary_key=True)
    username = Column(UnicodeText)

    def __init__(self, user_id, username=None):
        self.user_id = user_id
        self.username = username

    def __repr__(self):
        return "<User {} ({})>".format(self.username, self.user_id)


class Chats(BASE):
    __tablename__ = "chats"
    chat_id = Column(String(14), primary_key=True)
    chat_name = Column(UnicodeText, nullable=False)

    def __init__(self, chat_id, chat_name):
        self.chat_id = str(chat_id)
        self.chat_name = chat_name

    def __repr__(self):
        return "<Chat {} ({})>".format(self.chat_name, self.chat_id)


class ChatMembers(BASE):
    __tablename__ = "chat_members"
    priv_chat_id = Column(BigInteger, primary_key=True)
    # NOTE: Use dual primary key instead of private primary key?
    chat = Column(
        String(14),
        ForeignKey("chats.chat_id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    user = Column(
        BigInteger,
        ForeignKey("users.user_id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    __table_args__ = (UniqueConstraint("chat", "user", name="_chat_members_uc"),)

    def __init__(self, chat, user):
        self.chat = chat
        self.user = user

    def __repr__(self):
        # Avoid referencing relationships that are not defined
        return "<Chat user {} in chat {}>".format(self.user, self.chat)


Users.__table__.create(checkfirst=True)
Chats.__table__.create(checkfirst=True)
ChatMembers.__table__.create(checkfirst=True)

INSERTION_LOCK = threading.RLock()


def ensure_bot_in_db_by_values(bot_id: int, username: str | None):
    """
    Insert/merge the bot into the users table using known id/username.
    Call this from post_init after the bot is initialized (PTB 20+).
    """
    with INSERTION_LOCK:
        bot = SESSION.get(Users, bot_id)
        if not bot:
            bot = Users(bot_id, username)
            SESSION.add(bot)
        else:
            bot.username = username
        SESSION.commit()
        invalidate_user_cache(bot_id)


async def ensure_bot_in_db_app(app):
    """
    PTB 20+ helper: call from Application.post_init.
    """
    me = await app.bot.get_me()
    ensure_bot_in_db_by_values(me.id, me.username)


def update_user(user_id, username, chat_id=None, chat_name=None):
    with INSERTION_LOCK:
        user = SESSION.get(Users, user_id)
        if not user:
            user = Users(user_id, username)
            SESSION.add(user)
            SESSION.flush()
        else:
            user.username = username

        if not chat_id or not chat_name:
            SESSION.commit()
            invalidate_user_cache(user_id)
            return

        chat = SESSION.get(Chats, str(chat_id))
        if not chat:
            chat = Chats(str(chat_id), chat_name)
            SESSION.add(chat)
            SESSION.flush()
        else:
            chat.chat_name = chat_name

        member = (
            SESSION.query(ChatMembers)
            .filter(ChatMembers.chat == chat.chat_id, ChatMembers.user == user.user_id)
            .first()
        )
        if not member:
            chat_member = ChatMembers(chat.chat_id, user.user_id)
            SESSION.add(chat_member)

        SESSION.commit()
        invalidate_user_cache(user_id)
        invalidate_chat_cache(chat_id)


@cached(ttl=300)
def get_userid_by_name(username):
    return [
        user.user_id
        for user in SESSION.query(Users)
        .filter(func.lower(Users.username) == username.lower())
        .all()
    ]


@cached(ttl=300)
def get_name_by_userid(user_id):
    user = SESSION.get(Users, int(user_id))
    return user.username if user else None


@cached(ttl=300)
def get_chat_members(chat_id):
    return [
        member.user
        for member in SESSION.query(ChatMembers)
        .filter(ChatMembers.chat == str(chat_id))
        .all()
    ]


@cached(ttl=300)
def get_all_chats():
    return [chat.chat_id for chat in SESSION.query(Chats).all()]


@cached(ttl=300)
def get_all_users():
    return [user.user_id for user in SESSION.query(Users).all()]


@cached(ttl=300)
def get_user_num_chats(user_id):
    return SESSION.query(ChatMembers).filter(ChatMembers.user == int(user_id)).count()


@cached(ttl=300)
def get_user_com_chats(user_id):
    chat_members = (
        SESSION.query(ChatMembers).filter(ChatMembers.user == int(user_id)).all()
    )
    return [member.chat for member in chat_members]


@cached(ttl=300)
def num_chats():
    return SESSION.query(Chats).count()


@cached(ttl=300)
def num_users():
    return SESSION.query(Users).count()


def migrate_chat(old_chat_id, new_chat_id):
    with INSERTION_LOCK:
        chat = SESSION.get(Chats, str(old_chat_id))
        if chat:
            chat.chat_id = str(new_chat_id)
            SESSION.add(chat)

        SESSION.flush()

        chat_members = (
            SESSION.query(ChatMembers)
            .filter(ChatMembers.chat == str(old_chat_id))
            .all()
        )
        for member in chat_members:
            member.chat = str(new_chat_id)
            SESSION.add(member)

        SESSION.commit()
        invalidate_chat_cache(old_chat_id)
        invalidate_chat_cache(new_chat_id)


def del_user(user_id):
    with INSERTION_LOCK:
        curr = SESSION.get(Users, user_id)
        if curr:
            SESSION.delete(curr)
            SESSION.commit()
            invalidate_user_cache(user_id)
            return True

        SESSION.query(ChatMembers).filter(ChatMembers.user == user_id).delete()
        SESSION.commit()
        invalidate_user_cache(user_id)
    return False


def rem_chat(chat_id):
    with INSERTION_LOCK:
        chat = SESSION.get(Chats, str(chat_id))
        if chat:
            SESSION.delete(chat)
            SESSION.commit()
            invalidate_chat_cache(chat_id)
        else:
            SESSION.close()


def invalidate_user_cache(user_id):
    invalidate_cache_pattern(f"*:{user_id}:*")


def invalidate_chat_cache(chat_id):
    invalidate_cache_pattern(f"*:{chat_id}:*")


def invalidate_all_cache():
    clear_cache()
