import math
import urllib.request as urllib
from html import escape
from io import BytesIO
from urllib.error import HTTPError

from PIL import Image
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    InputSticker,
    # BufferedInputFile  # do not import unconditionally
)
from telegram.constants import ParseMode, StickerFormat
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from telegram.helpers import mention_html
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit

# PTB compatibility: use BufferedInputFile if available, else fall back to BytesIO
try:
    from telegram import BufferedInputFile  # newer PTB
except Exception:
    BufferedInputFile = None


def to_input_file(data: bytes, filename: str):
    """
    Return a file-like object suitable for Telegram uploads.
    Prefer BufferedInputFile when available, otherwise use BytesIO with a name.
    """
    if BufferedInputFile:
        return BufferedInputFile(data, filename)
    bio = BytesIO(data)
    bio.name = filename
    return bio


async def get_sticker_count(bot: Bot, packname: str) -> int:
    resp = await bot.get_sticker_set(name=packname)
    return len(resp.stickers)


@kigcmd(command='stickerid')
@rate_limit(40, 60)
async def stickerid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.sticker:
        await update.effective_message.reply_text(
            "Hello "
            + f"{mention_html(msg.from_user.id, msg.from_user.first_name)}"
            + ", The sticker id you are replying is :\n <code>"
            + escape(msg.reply_to_message.sticker.file_id)
            + "</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.effective_message.reply_text(
            "Hello "
            + f"{mention_html(msg.from_user.id, msg.from_user.first_name)}"
            + ", Please reply to sticker message to get id sticker",
            parse_mode=ParseMode.HTML,
        )


@kigcmd(command='getsticker')
@rate_limit(40, 60)
async def getsticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.sticker:
        file_id = msg.reply_to_message.sticker.file_id
        is_animated = msg.reply_to_message.sticker.is_animated
        bot = context.bot
        new_file = await bot.get_file(file_id)
        data = await new_file.download_as_bytearray()

        filename = "animated_sticker.tgs.rename_me" if is_animated else "sticker.png"
        chat_id = update.effective_chat.id
        input_file = to_input_file(bytes(data), filename)

        await bot.send_document(
            chat_id,
            document=input_file,
            disable_content_type_detection=True
        )
    else:
        await update.effective_message.reply_text(
            "Please reply to a sticker for me to upload its PNG."
        )


@kigcmd(command=["steal", "kang"])
@rate_limit(40, 60)
async def kang(update: Update, context: ContextTypes.DEFAULT_TYPE):  # sourcery no-metrics
    global ppref
    msg = update.effective_message
    user = update.effective_user
    args = context.args
    is_animated = False
    is_video = False
    file_id = None
    sticker_emoji = "🤔"
    sticker_data_bytes = None

    if not msg.reply_to_message and not args:
        packs = ""
        packnum = 0
        packname = f"a{user.id}_by_{context.bot.username}"
        max_stickers = 120

        while True:
            last_set = False
            try:
                if await get_sticker_count(context.bot, packname) >= max_stickers:
                    packnum += 1
                    if is_animated:
                        packname = f"animated{packnum}_{user.id}_by_{context.bot.username}"
                        ppref = "animated"
                    elif is_video:
                        packname = f"vid{packnum}_{user.id}_by_{context.bot.username}"
                        ppref = "vid"
                    else:
                        packname = f"a{packnum}_{user.id}_by_{context.bot.username}"
                        ppref = ""
                else:
                    last_set = True
                    # ensure ppref defined for the current line
                    ppref = "animated " if is_animated else "vid " if is_video else ""
                packs += f"[{ppref}pack{packnum if packnum != 0 else ''}](t.me/addstickers/{packname})\n"
            except TelegramError as e:
                if e.message == "Stickerset_invalid":
                    last_set = True
                else:
                    print(e)
                    break

            if last_set and is_animated:
                break
            elif last_set:
                packname = f"animated_{user.id}_by_{context.bot.username}"
                packnum = 0
                max_stickers = 50
                is_animated = True

        if not packs:
            packs = "Looks like you don't have any packs! Please reply to a sticker, or image to kang it and create a new pack!"
        else:
            packs = "Please reply to a sticker, or image to kang it!\nOh, by the way, here are your packs:\n" + packs

        await msg.reply_text(packs, parse_mode=ParseMode.MARKDOWN)
        return

    if rep := msg.reply_to_message:
        if rep.sticker:
            is_animated = rep.sticker.is_animated
            is_video = rep.sticker.is_video
            file_id = rep.sticker.file_id
            if not args:
                sticker_emoji = rep.sticker.emoji
        elif rep.photo:
            file_id = rep.photo[-1].file_id
        elif rep.video:
            file_id = rep.video.file_id
            is_video = True
        elif rep.animation:
            file_id = rep.animation.file_id
            is_video = True
        elif doc := rep.document:
            file_id = rep.document.file_id
            if doc.mime_type == 'video/webm':
                is_video = True
        else:
            await msg.reply_text("Yea, I can't steal that.")
            return

        if args:
            sticker_emoji = args[0]

        tg_file = await context.bot.get_file(file_id)
        sticker_data_bytes = bytes(await tg_file.download_as_bytearray())
    else:
        url = args[0]
        if len(args) >= 2:
            sticker_emoji = args[1]
        try:
            resp = urllib.urlopen(url)
            mime = resp.getheader('Content-Type')
            if mime not in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'application/x-tgsticker', 'video/webm']:
                await msg.reply_text("I can only kang images m8.")
                return
            if mime == "application/x-tgsticker":
                is_animated = True
            if mime == "video/webm":
                is_video = True
            sticker_data_bytes = resp.read()
        except ValueError:
            await msg.reply_text("Yea, that's not a URL I can download from.")
            return
        except HTTPError as e:
            await msg.reply_text(f"Error downloading the file: {e.code} {e.msg}")
            return

    packnum = 0
    packname_found = False
    invalid = False

    if is_animated:
        packname = f"animated_{user.id}_by_{context.bot.username}"
        max_stickers = 50
    elif is_video:
        packname = f"vid_{user.id}_by_{context.bot.username}"
        max_stickers = 50
    else:
        packname = f"a{user.id}_by_{context.bot.username}"
        max_stickers = 120

    while not packname_found:
        try:
            if await get_sticker_count(context.bot, packname) >= max_stickers:
                packnum += 1
                if is_animated:
                    packname = f"animated{packnum}_{user.id}_by_{context.bot.username}"
                elif is_video:
                    packname = f"vid{packnum}_{user.id}_by_{context.bot.username}"
                else:
                    packname = f"a{packnum}_{user.id}_by_{context.bot.username}"
            else:
                packname_found = True
        except TelegramError as e:
            if e.message == "Stickerset_invalid":
                packname_found = True
                invalid = True
            else:
                raise

    # Ensure correct size/format for static stickers
    if not is_animated and not is_video:
        try:
            im = Image.open(BytesIO(sticker_data_bytes))
            if (im.width and im.height) < 512:
                size1 = im.width
                size2 = im.height
                if size1 > size2:
                    scale = 512 / size1
                    size1new = 512
                    size2new = size2 * scale
                else:
                    scale = 512 / size2
                    size1new = size1 * scale
                    size2new = 512
                size1new = math.floor(size1new)
                size2new = math.floor(size2new)
                sizenew = (size1new, size2new)
                im = im.resize(sizenew)
            else:
                maxsize = (512, 512)
                im.thumbnail(maxsize)
            out = BytesIO()
            im.save(out, 'PNG')
            sticker_data_bytes = out.getvalue()
        except OSError:
            await msg.reply_text("I can only steal images m8.")
            return

    filename = (
        "sticker.tgs" if is_animated else "sticker.webm" if is_video else "sticker.png"
    )
    sticker_input = InputSticker(
        sticker=to_input_file(sticker_data_bytes, filename),
        emoji_list=[sticker_emoji],
    )

    try:
        if invalid:
            raise TelegramError("Stickerset_invalid")
        await context.bot.add_sticker_to_set(
            user_id=user.id,
            name=packname,
            sticker=sticker_input,
        )
        await msg.reply_text(
            f"Sticker successfully added to [pack](t.me/addstickers/{packname})"
            + f"\nEmoji is: {sticker_emoji}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as e:
        if e.message == "Stickerset_invalid":
            await makepack_internal(
                update,
                context,
                msg,
                user,
                sticker_emoji,
                packname,
                packnum,
                sticker_input=sticker_input,
                is_animated=is_animated,
                is_video=is_video,
            )
        elif e.message == "Stickers_too_much":
            await msg.reply_text("Max packsize reached. Press F to pay respecc.")
        elif e.message == "Invalid sticker emojis":
            await msg.reply_text("I can't kang with that emoji!")
        elif e.message == "Sticker_video_nowebm":
            await msg.reply_text(
                "This media format isn't supported, I need it in a webm format, "
                "[see this guide](https://core.telegram.org/stickers/webm-vp9-encoding).",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        elif e.message == "Internal Server Error: sticker set not found (500)":
            await msg.reply_text(
                f"Sticker successfully added to [pack](t.me/addstickers/{packname})\n"
                + f"Emoji is: {sticker_emoji}", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await msg.reply_text(f"Oops! looks like something happened that shouldn't happen! ({e.message})")
            raise


async def makepack_internal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    msg,
    user,
    emoji,
    packname,
    packnum,
    sticker_input: InputSticker,
    is_animated: bool,
    is_video: bool,
):
    name = user.first_name[:50]
    try:
        extra_version = ""
        if packnum > 0:
            extra_version = f" {packnum}"
        title = f"{name}s {'animated ' if is_animated else 'video ' if is_video else ''}kang pack{extra_version}"
        success = await context.bot.create_new_sticker_set(
            user_id=user.id,
            name=packname,
            title=title,
            stickers=[sticker_input],
            sticker_format=StickerFormat.ANIMATED if is_animated else StickerFormat.VIDEO if is_video else StickerFormat.STATIC,
        )
    except TelegramError as e:
        print(e)
        if e.message == 'Sticker set name is already occupied':
            await msg.reply_text(
                'Your pack can be found [here](t.me/addstickers/%s)'
                % packname,
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        elif e.message in ('Peer_id_invalid', 'bot was blocked by the user'):
            await msg.reply_text(
                'Contact me in PM first.',
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text='Start',
                                url=f't.me/{context.bot.username}',
                            )
                        ]
                    ]
                ),
            )
            return
        elif (
            e.message
            == 'Internal Server Error: created sticker set not found (500)'
        ):
            success = True
        elif e.message == 'Sticker_video_nowebm':
            await msg.reply_text(
                "This media format isn't supported, I need it in a webm format, "
                "[see this guide](https://core.telegram.org/stickers/webm-vp9-encoding).",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return
        else:
            success = False

    if success:
        await msg.reply_text(
            f"Sticker pack successfully created. Get it [here](t.me/addstickers/{packname})",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await msg.reply_text("Failed to create sticker pack. Possibly due to blek mejik.")
