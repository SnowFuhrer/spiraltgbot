import html
import json
import asyncio
from functools import partial
from platform import python_version
from typing import List
from uuid import uuid4
from tg_bot.modules.songsearch import inline_songsearch_router
from tg_bot.modules.ltc_inline import inline_ltc_router

import requests
from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
    __version__ as TG_VER,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import tg_bot.modules.sql.users_sql as sql
from tg_bot import (
    OWNER_ID,
    SUDO_USERS,
    SUPPORT_USERS,
    DEV_USERS,
    SARDEGNA_USERS,
    WHITELIST_USERS,
    log,
)
from tg_bot.modules.helper_funcs.decorators import kiginline, rate_limit


def remove_prefix(text: str, prefix: str) -> str:
    return text[len(prefix) :] if text.startswith(prefix) else text


@kiginline()
@rate_limit(40, 60)
async def inlinequery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = (update.inline_query.query or "").strip()

    # Map commands to handlers
    inline_funcs = {
        ".info": inlineinfo,
        ".about": about,
        ".song": inline_songsearch_router,
        ".songsearch": inline_songsearch_router,
        ".hymn": inline_songsearch_router,
        ".ltc": inline_ltc_router,
    }

    cmd = query.split(" ", 1)[0] if query else ""
    if cmd in inline_funcs:
        arg = remove_prefix(query, cmd).strip()
        await inline_funcs[cmd](arg, update, context)
        return

    # Help cards
    help_cards = [
        {
            "title": "Sheet Music Search",
            "description": "Searches songs on Stanza, PrairieView Press and The Acappella Store(WIP).",
            "message_text": "Click below to search",
            "thumbnail_url": "https://res.cloudinary.com/dibpndwxe/image/upload/v1761714672/photo_2025-10-28_00-20-47_vnvpdm.jpg",
            "switch_text": ".song",
        },
        {
            "title": "Account info on Spiral",
            "description": "Look up a Telegram account in Spiral database",
            "message_text": "Click the button below to look up a person in Spiral database using their Telegram ID",
            "thumbnail_url": "https://telegra.ph/file/3ce9045b1c7faf7123c67.jpg",
            "switch_text": ".info ",
        },
        {
            "title": "About",
            "description": "Know about Spiral",
            "message_text": "Click below to see what Spiral is about",
            "thumbnail_url": "https://telegra.ph/file/3ce9045b1c7faf7123c67.jpg",
            "switch_text": ".about",
        },
    ]

    results: List[InlineQueryResultArticle] = []
    for card in help_cards:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Click Here",
                        switch_inline_query_current_chat=card["switch_text"],
                    )
                ]
            ]
        )
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=card["title"],
                description=card["description"],
                input_message_content=InputTextMessageContent(
                    card["message_text"],
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                ),
                reply_markup=kb,
                thumbnail_url=card["thumbnail_url"],  # renamed from thumb_url
            )
        )

    await update.inline_query.answer(results, cache_time=5)


async def inlineinfo(query: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    log.info(update.inline_query.query)

    user_id = update.effective_user.id
    search = query or user_id

    try:
        target = await bot.get_chat(int(search))
    except (BadRequest, ValueError, TelegramError):
        target = await bot.get_chat(user_id)

    # Track user
    sql.update_user(target.id, target.username)

    text = (
        f"<b>Information:</b>\n"
        f"• ID: <code>{target.id}</code>\n"
        f"• First Name: {html.escape(target.first_name or '')}"
    )
    if target.last_name:
        text += f"\n• Last Name: {html.escape(target.last_name)}"
    if target.username:
        text += f"\n• Username: @{html.escape(target.username)}"
    text += f"\n• Permanent user link: {mention_html(target.id, 'link')}"

    nation_level_present = False
    if target.id == OWNER_ID:
        text += "\n\nThis person is my owner"
        nation_level_present = True
    elif target.id in DEV_USERS:
        text += "\n\nThis person is part of the developers"
        nation_level_present = True
    elif target.id in SUDO_USERS:
        text += "\n\nThis person is a sudo user"
        nation_level_present = True
    elif target.id in SUPPORT_USERS:
        text += "\n\nThis person is a support user"
        nation_level_present = True
    elif target.id in SARDEGNA_USERS:
        text += "\n\nThe Nation level of this person is Sardegna"
        nation_level_present = True
    elif target.id in WHITELIST_USERS:
        text += "\n\nThis person is whitelisted"
        nation_level_present = True

    if nation_level_present:
        # Small help link for nations
        text += f' [<a href="https://t.me/{bot.username}?start=nations">?</a>]'

    num_chats = sql.get_user_num_chats(target.id)
    text += f"\n• <b>Chat count</b>: <code>{num_chats}</code>"

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text="Report Error", url="https://t.me/enrapturedoverwatch_bot"),
                InlineKeyboardButton(text="Search again", switch_inline_query_current_chat=".info "),
            ]
        ]
    )

    results = [
        InlineQueryResultArticle(
            id=str(uuid4()),
            title=f"User info of {html.escape(target.first_name or 'User')}",
            input_message_content=InputTextMessageContent(
                text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            ),
            reply_markup=kb,
            thumbnail_url="https://telegra.ph/file/3ce9045b1c7faf7123c67.jpg",
        )
    ]
    await update.inline_query.answer(results, cache_time=5)


async def about(_: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = await context.bot.get_chat(user_id)
    sql.update_user(user.id, user.username)

    about_text = (
        f"<b>Spiral (@{context.bot.username})</b>\n"
        f"Maintained by <a href='https://t.me/snowfuhrer'>SnowFuhrer</a>\n"
        f"Built with ❤️  using python-telegram-bot v{str(TG_VER)}\n"
        f"Running on Python {python_version()}"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text="Support", url="https://t.me/spiralsupport"),
                InlineKeyboardButton(text="Channel", url="https://t.me/spiralsupport"),
                InlineKeyboardButton(text="Ping", callback_data="pingCB"),
            ],
            [
#                InlineKeyboardButton(
#                    text="GitLab", url="https://www.gitlab.com/Dank-del/EnterpriseALRobot"
#                ),
                InlineKeyboardButton(
                    text="GitHub", url="https://github.com/SnowFuhrer/spiraltgbot/"
                ),
            ],
        ]
    )

    results = [
        InlineQueryResultArticle(
            id=str(uuid4()),
            title=f"About Spiral (@{context.bot.username})",
            input_message_content=InputTextMessageContent(
                about_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            ),
            reply_markup=kb,
            thumbnail_url="https://telegra.ph/file/3ce9045b1c7faf7123c67.jpg",
        )
    ]
    await update.inline_query.answer(results)


MEDIA_QUERY = """query ($search: String) {
  Page (perPage: 10) {
    media (search: $search) {
      id
      title { romaji english native }
      type
      format
      status
      description
      episodes
      bannerImage
      duration
      chapters
      volumes
      genres
      synonyms
      averageScore
      airingSchedule(notYetAired: true) {
        nodes { airingAt timeUntilAiring episode }
      }
      siteUrl
    }
  }
}"""


@kiginline()
@rate_limit(40, 60)
async def media_query(query: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    results: List[InlineQueryResultArticle] = []

    try:
        # run blocking requests in a thread so we don't block the event loop
        post = partial(
            requests.post,
            "https://graphql.anilist.co",
            data=json.dumps({"query": MEDIA_QUERY, "variables": {"search": query}}),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15,
        )
        loop = asyncio.get_running_loop()
        r = await loop.run_in_executor(None, post)
        r.raise_for_status()
        data = r.json()["data"]["Page"]["media"]

        for item in data:
            title_en = item["title"].get("english") or "N/A"
            title_ja = item["title"].get("romaji") or "N/A"
            fmt = item.get("format") or "N/A"
            typ = item.get("type") or "N/A"
            img = f"https://img.anili.st/media/{item['id']}"
            aurl = item.get("siteUrl")

            # Clean description and escape for HTML
            desc_raw = item.get("description") or "N/A"
            try:
                desc_raw = (
                    desc_raw.replace("<br>", "").replace("</br>", "").replace("<i>", "").replace("</i>", "")
                )
            except AttributeError:
                pass
            description = html.escape(desc_raw or "N/A")
            if len(description) > 700:
                description = f"{description[:700]}....."

            avgsc = item.get("averageScore") or "N/A"
            status = item.get("status") or "N/A"
            genres = ", ".join(item.get("genres") or []) or "N/A"
            genres = html.escape(genres)

            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(text="Read More", url=aurl),
                        InlineKeyboardButton(
                            text="Search again", switch_inline_query_current_chat=".anilist "
                        ),
                    ],
                ]
            )

            txt = (
                f"<b>{html.escape(title_en)} | {html.escape(title_ja)}</b>\n"
                f"<b>Format</b>: <code>{html.escape(fmt)}</code>\n"
                f"<b>Type</b>: <code>{html.escape(typ)}</code>\n"
                f"<b>Average Score</b>: <code>{html.escape(str(avgsc))}</code>\n"
                f"<b>Status</b>: <code>{html.escape(status)}</code>\n"
                f"<b>Genres</b>: <code>{genres}</code>\n"
                f"<b>Description</b>: <code>{description}</code>\n"
                f"<a href='{img}'>&#xad</a>"
            )

            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"{title_en} | {title_ja} | {fmt}",
                    description=html.unescape(description),
                    input_message_content=InputTextMessageContent(
                        txt, parse_mode=ParseMode.HTML, disable_web_page_preview=False
                    ),
                    reply_markup=kb,
                    thumbnail_url=img,  # renamed from thumb_url
                )
            )
    except Exception as e:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Report error", url="https://t.me/enrapturedoverwatch_bot"),
                    InlineKeyboardButton(text="Search again", switch_inline_query_current_chat=".anilist "),
                ]
            ]
        )
        err = html.escape(str(e))
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"Media {query or ''} not found",
                input_message_content=InputTextMessageContent(
                    f"Media {html.escape(query or '')} not found due to <code>{err}</code>",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                ),
                reply_markup=kb,
                thumbnail_url="https://telegra.ph/file/cc83a0b7102ad1d7b1cb3.jpg",
            )
        )

    await update.inline_query.answer(results, cache_time=5)

