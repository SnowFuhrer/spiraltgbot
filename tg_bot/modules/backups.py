import json, time
from io import BytesIO
from typing import Optional

from telegram import Message, Update
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import tg_bot.modules.sql.notes_sql as sql
from tg_bot import dispatcher, log as LOGGER, OWNER_ID
# from tg_bot.__main__ import DATA_IMPORT  # avoid circular import
from tg_bot.modules.helper_funcs.alternate import typing_action
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit
import tg_bot.modules.sql.rules_sql as rulessql
from tg_bot.modules.language import gs
import tg_bot.modules.sql.blacklist_sql as blacklistsql
from tg_bot.modules.sql import disable_sql as disabledsql
import tg_bot.modules.sql.locks_sql as locksql
from tg_bot.modules.connection import connected

from ..modules.helper_funcs.anonymous import user_admin, AdminPerms


def get_help(chat):
    return gs(chat, "backup_help")


__mod_name__ = "Backup"


def _data_import_modules():
    try:
        from tg_bot.__main__ import DATA_IMPORT
        return DATA_IMPORT
    except Exception:
        return []


@kigcmd(command='import')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@typing_action
@rate_limit(40, 60)
async def import_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = await dispatcher.bot.get_chat(conn)
        chat_name = chat.title
    else:
        if update.effective_message.chat.type == "private":
            await update.effective_message.reply_text("This is a group only command!")
            return ""
        chat = update.effective_chat
        chat_name = update.effective_message.chat.title

    if msg.reply_to_message and msg.reply_to_message.document:
        try:
            file_info = await context.bot.get_file(msg.reply_to_message.document.file_id)
        except BadRequest:
            await msg.reply_text(
                "Try downloading and uploading the file yourself again, This one seem broken to me!",
            )
            return

        try:
            bio = await file_info.download_to_memory()
            bio.seek(0)
            data = json.load(bio)
        except json.JSONDecodeError:
            await msg.reply_text("This doesn't look like a valid Spiral backup JSON.")
            return

        # only import one group
        if len(data) > 1 and str(chat.id) not in data:
            await msg.reply_text(
                "There are more than one group in this file and the chat.id is not same! How am i supposed to import it?",
            )
            return

        # Check if backup is this chat
        try:
            if data.get(str(chat.id)) is None:
                if conn:
                    text = "Backup comes from another chat, I can't return another chat to chat *{}*".format(
                        chat_name,
                    )
                else:
                    text = "Backup comes from another chat, I can't return another chat to this chat"
                await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)
                return
        except Exception:
            await msg.reply_text("There was a problem while importing the data!")
            return

        # Check if backup is from self
        try:
            if str(context.bot.id) != str(data[str(chat.id)]["bot"]):
                await msg.reply_text(
                    "Backup from another bot that is not suggested might cause the problem, documents, photos, videos, audios, records might not work as it should be.",
                )
        except Exception:
            pass

        # Select data source
        if str(chat.id) in data:
            data = data[str(chat.id)]["hashes"]
        else:
            data = data[list(data.keys())[0]]["hashes"]

        try:
            for mod in _data_import_modules():
                mod.__import_data__(int(chat.id), data)
        except Exception:
            await msg.reply_text(
                "An error occurred while recovering your data. The process failed. If you experience a problem with this, please take it to @YorkTownEagleUnion",
            )
            LOGGER.exception(
                "Import for the chat %s with the name %s failed.",
                str(chat.id),
                str(chat.title),
            )
            return

        text = "Backup fully restored on *{}*.".format(chat_name) if conn else "Backup fully restored"
        await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@kigcmd(command='export')
@user_admin(AdminPerms.CAN_CHANGE_INFO)
@rate_limit(40, 60)
async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    chat_data = context.chat_data
    msg: Optional[Message] = update.effective_message
    user = update.effective_user
    chat_id = update.effective_chat.id
    chat = update.effective_chat
    current_chat_id = update.effective_chat.id

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = await dispatcher.bot.get_chat(conn)
        chat_id = conn
    else:
        if update.effective_message.chat.type == "private":
            await update.effective_message.reply_text("This is a group only command!")
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id

    jam = time.time()
    new_jam = jam + 86400  # once a day
    checkchat = get_chat(chat_id, chat_data)
    if checkchat.get("status"):
        if jam <= int(checkchat.get("value")):
            timeformatt = time.strftime(
                "%H:%M:%S %d/%m/%Y", time.localtime(checkchat.get("value")),
            )
            await update.effective_message.reply_text(
                "You can only backup once a day!\nYou can backup again at `{}`".format(
                    timeformatt,
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        else:
            if user.id != OWNER_ID:
                put_chat(chat_id, new_jam, chat_data)
    elif user.id != OWNER_ID:
        put_chat(chat_id, new_jam, chat_data)

    note_list = sql.get_all_chat_notes(chat_id)
    backup = {}
    buttonlist = []
    namacat = ""
    isicat = ""
    rules = ""
    count = 0

    # Notes
    for note in note_list:
        count += 1
        namacat += "{}<###splitter###>".format(note.name)
        if note.msgtype == 1:
            tombol = sql.get_buttons(chat_id, note.name)
            for btn in tombol:
                if btn.same_line:
                    buttonlist.append(
                        ("{}".format(btn.name), "{}".format(btn.url), True),
                    )
                else:
                    buttonlist.append(
                        ("{}".format(btn.name), "{}".format(btn.url), False),
                    )
            isicat += "###button###: {}<###button###>{}<###splitter###>".format(
                note.value, str(buttonlist),
            )
            buttonlist.clear()
        elif note.msgtype == 2:
            isicat += "###sticker###:{}<###splitter###>".format(note.file)
        elif note.msgtype == 3:
            isicat += "###file###:{}<###TYPESPLIT###>{}<###splitter###>".format(
                note.file, note.value,
            )
        elif note.msgtype == 4:
            isicat += "###photo###:{}<###TYPESPLIT###>{}<###splitter###>".format(
                note.file, note.value,
            )
        elif note.msgtype == 5:
            isicat += "###audio###:{}<###TYPESPLIT###>{}<###splitter###>".format(
                note.file, note.value,
            )
        elif note.msgtype == 6:
            isicat += "###voice###:{}<###TYPESPLIT###>{}<###splitter###>".format(
                note.file, note.value,
            )
        elif note.msgtype == 7:
            isicat += "###video###:{}<###TYPESPLIT###>{}<###splitter###>".format(
                note.file, note.value,
            )
        elif note.msgtype == 8:
            isicat += "###video_note###:{}<###TYPESPLIT###>{}<###splitter###>".format(
                note.file, note.value,
            )
        else:
            isicat += "{}<###splitter###>".format(note.value)
    notes = {
        "#{}".format(namacat.split("<###splitter###>")[x]): "{}".format(
            isicat.split("<###splitter###>")[x],
        )
        for x in range(count)
    }

    # Rules
    rules = rulessql.get_rules(chat_id)
    # Blacklist
    bl = list(blacklistsql.get_chat_blacklist(chat_id))
    # Disabled command
    disabledcmd = list(disabledsql.get_all_disabled(chat_id))

    # Locked
    curr_locks = locksql.get_locks(chat_id)
    curr_restr = locksql.get_restr(chat_id)

    if curr_locks:
        locked_lock = {
            "sticker": curr_locks.sticker,
            "audio": curr_locks.audio,
            "voice": curr_locks.voice,
            "document": curr_locks.document,
            "video": curr_locks.video,
            "contact": curr_locks.contact,
            "photo": curr_locks.photo,
            "gif": curr_locks.gif,
            "url": curr_locks.url,
            "bots": curr_locks.bots,
            "forward": curr_locks.forward,
            "game": curr_locks.game,
            "location": curr_locks.location,
            "rtl": curr_locks.rtl,
        }
    else:
        locked_lock = {}

    if curr_restr:
        locked_restr = {
            "messages": curr_restr.messages,
            "media": curr_restr.media,
            "other": curr_restr.other,
            "previews": curr_restr.preview,
            "all": all(
                [
                    curr_restr.messages,
                    curr_restr.media,
                    curr_restr.other,
                    curr_restr.preview,
                ],
            ),
        }
    else:
        locked_restr = {}

    locks = {"locks": locked_lock, "restrict": locked_restr}
    # Backing up
    backup[chat_id] = {
        "bot": context.bot.id,
        "hashes": {
            "info": {"rules": rules},
            "extra": notes,
            "blacklist": bl,
            "disabled": disabledcmd,
            "locks": locks,
        },
    }
    baccinfo = json.dumps(backup, indent=4).encode("utf-8")
    bio = BytesIO(baccinfo)
    bio.name = f"Spiral{chat_id}.json"
    tgl = time.strftime("%H:%M:%S - %d/%m/%Y", time.localtime(time.time()))

    await context.bot.send_chat_action(current_chat_id, ChatAction.UPLOAD_DOCUMENT)
    await context.bot.send_document(
        current_chat_id,
        document=bio,
        caption="*Successfully Exported backup:*\nChat: `{}`\nChat ID: `{}`\nOn: `{}`\n\nNote: This `Spiral-Backup` was specially made for notes.".format(
            chat.title, chat_id, tgl,
        ),
        timeout=360,
        reply_to_message_id=msg.message_id if msg else None,
        parse_mode=ParseMode.MARKDOWN,
    )


# Temporary data
def put_chat(chat_id, value, chat_data):
    status = value is not False
    chat_data[chat_id] = {"backups": {"status": status, "value": value}}


def get_chat(chat_id, chat_data):
    try:
        return chat_data[chat_id]["backups"]
    except KeyError:
        return {"status": False, "value": False}
