import os
import sys
import time
import asyncio
import shutil
import zipfile
import tempfile
from typing import Optional, Tuple, Dict, Any, List

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest
from telegram.ext import ContextTypes, filters, MessageHandler

from tg_bot import application
from tg_bot.modules.helper_funcs.decorators import kigcmd, kigmsg, rate_limit

__mod_name__ = "Segment"

# --------- Helpers ---------
ALLOWED_EXTS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus",
    ".wma", ".amr",
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi"  # videos (audio will be extracted)
}

MEDIA_GROUP_TTL_SEC = 15 * 60  # keep albums in cache for 15 minutes


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _allowed_doc(fn: Optional[str], mime: Optional[str]) -> bool:
    if fn:
        ext = os.path.splitext(fn)[1].lower()
        if ext in ALLOWED_EXTS:
            return True
    if mime and (mime.startswith("audio/") or mime.startswith("video/")):
        return True
    return False


def _pick_media_from_message(msg) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (file_id, filename_hint) from a message's media.
    Supports: audio, voice, video, video_note, document (by extension/mime).
    """
    if not msg:
        return None, None

    # audio
    if getattr(msg, "audio", None):
        fn = msg.audio.file_name or "audio.mp3"
        return msg.audio.file_id, fn

    # voice (ogg/opus)
    if getattr(msg, "voice", None):
        return msg.voice.file_id, "voice.ogg"

    # video
    if getattr(msg, "video", None):
        fn = msg.video.file_name or "video.mp4"
        return msg.video.file_id, fn

    # video_note
    if getattr(msg, "video_note", None):
        return msg.video_note.file_id, "video_note.mp4"

    # document (check extension/mime)
    if getattr(msg, "document", None):
        fn = msg.document.file_name or "file.bin"
        mime = msg.document.mime_type or ""
        if _allowed_doc(fn, mime):
            return msg.document.file_id, fn

    return None, None


async def _safe_edit(bot, chat_id: int, message_id: int, text: str):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        # Ignore harmless edit errors
        if e.message not in ("Message is not modified", "Message to edit not found"):
            raise


def _parse_args(args: Any) -> Dict[str, Any]:
    """
    Parse simple flags:
      --min <sec>         minimum exported clip length (default: 10)
      --target <int>      approx cap per class (0 disables capping, default: 0)
      --pad <sec>         padding pre for singing segments (default: 2.7)
      --pad-pre <sec>     padding before singing segments
      --pad-post <sec>    padding after singing segments (default: 0)
      --zip               force zip output instead of sending many clips
    """
    opts = {
        "export_min": None,         # float or None
        "target_per_class": None,   # int or None
        "pad": None,                # float or None (applies to pre)
        "pad_pre": None,            # float or None
        "pad_post": None,           # float or None
        "zip_output": False,
    }
    i = 0
    while i < len(args):
        a = args[i].lower()
        try:
            if a == "--min" and i + 1 < len(args):
                opts["export_min"] = float(args[i + 1]); i += 2; continue
            if a == "--target" and i + 1 < len(args):
                opts["target_per_class"] = int(args[i + 1]); i += 2; continue
            if a == "--pad" and i + 1 < len(args):
                opts["pad"] = float(args[i + 1]); i += 2; continue
            if a == "--pad-pre" and i + 1 < len(args):
                opts["pad_pre"] = float(args[i + 1]); i += 2; continue
            if a == "--pad-post" and i + 1 < len(args):
                opts["pad_post"] = float(args[i + 1]); i += 2; continue
            if a == "--zip":
                opts["zip_output"] = True; i += 1; continue
        except Exception:
            # ignore parse errors; leave defaults
            i += 1
            continue
        i += 1
    return opts


def _zip_outputs(base_dir: str, outputs: Dict[str, Any]) -> Optional[str]:
    files = (outputs.get("speech", []) or []) + (outputs.get("music", []) or [])
    if not files:
        return None
    zip_path = os.path.join(base_dir, "segments.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            arc = os.path.basename(p)
            try:
                zf.write(p, arcname=arc)
            except Exception:
                pass
    return zip_path


async def _send_audio_file(bot, chat_id: int, path: str, caption: Optional[str] = None):
    with open(path, "rb") as f:
        await bot.send_audio(
            chat_id,
            audio=f,
            caption=caption or "",
            read_timeout=180,
            write_timeout=180,
        )


async def _send_document_file(bot, chat_id: int, path: str, caption: Optional[str] = None):
    with open(path, "rb") as f:
        await bot.send_document(
            chat_id,
            document=f,
            filename=os.path.basename(path),
            caption=caption or "",
            read_timeout=180,
            write_timeout=180,
        )


# --------- Media group cache ---------
def _purge_old_groups(chat_data: Dict):
    now = time.time()
    mg = chat_data.get("_media_groups", {})
    to_del = [k for k, v in mg.items() if now - v.get("ts", now) > MEDIA_GROUP_TTL_SEC]
    for k in to_del:
        mg.pop(k, None)


def _add_to_media_group_cache(chat_data: Dict, media_group_id: str, file_id: str, filename: Optional[str]):
    mg = chat_data.setdefault("_media_groups", {})
    entry = mg.get(media_group_id)
    if not entry:
        entry = {"ts": time.time(), "items": []}
        mg[media_group_id] = entry
    entry["ts"] = time.time()
    # avoid duplicates
    if file_id not in [x[0] for x in entry["items"]]:
        entry["items"].append((file_id, filename or "input.bin"))


try:
    DOC_ALL = filters.Document.ALL
except AttributeError:
    DOC_ALL = filters.ATTACHMENT  # broad fallback; we still filter in code

MEDIA_CACHE_FILTER = (
    filters.AUDIO | filters.VOICE | filters.VIDEO | getattr(filters, "VIDEO_NOTE", filters.ALL) | DOC_ALL
)


@kigmsg(MEDIA_CACHE_FILTER)
async def _cache_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not getattr(msg, "media_group_id", None):
        return
    file_id, filename_hint = _pick_media_from_message(msg)
    if not file_id:
        return
    _add_to_media_group_cache(context.chat_data, msg.media_group_id, file_id, filename_hint)
    _purge_old_groups(context.chat_data)


# Ensure the cache handler runs very early so we see all album items
application.add_handler(MessageHandler(MEDIA_CACHE_FILTER, _cache_media_group), group=-100)


# --------- Command ---------
@kigcmd(command="segment")
@rate_limit(40, 60)
async def segment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args or []

    # Require ffmpeg in PATH for exporting clips
    if not _has_ffmpeg():
        await msg.reply_text("ffmpeg is not available on this host. Please install ffmpeg and try again.")
        return

    # Accept media from reply first; otherwise from this message itself
    src_msg = msg.reply_to_message or msg
    file_id, filename_hint = _pick_media_from_message(src_msg)

    # If replying to an album item, try to process the whole album
    processed_album = False
    if src_msg and getattr(src_msg, "media_group_id", None):
        # Ensure current item is in cache
        if file_id:
            _add_to_media_group_cache(context.chat_data, src_msg.media_group_id, file_id, filename_hint)
        _purge_old_groups(context.chat_data)

        entry = context.chat_data.get("_media_groups", {}).get(src_msg.media_group_id)
        items: List[Tuple[str, str]] = []
        if entry and entry.get("items"):
            for fid, fn in entry["items"]:
                items.append((fid, fn or "input.bin"))

        if len(items) > 1:
            opts = _parse_args(args)
            status = await msg.reply_text(f"Processing album ({len(items)} items)...")
            n = len(items)
            for i, (fid, fn) in enumerate(items, 1):
                prefix = f"[{i}/{n}] "
                await _worker(
                    context,
                    chat_id,
                    status.message_id,
                    fid,
                    fn or "input.bin",
                    user.id,
                    opts,
                    status_prefix=prefix,
                    delete_status=(i == n),
                )
            processed_album = True

    if processed_album:
        return

    if not file_id:
        await msg.reply_text("Please reply to an audio/video/voice/document message, or attach one with the command.\nUsage: /segment [--min 10] [--target 0] [--pad 2.7] [--pad-pre 2.7] [--pad-post 0] [--zip]")
        return

    opts = _parse_args(args)
    status = await msg.reply_text("Downloading media... This may take a while the first time (model download).")

    await _worker(context, chat_id, status.message_id, file_id, filename_hint, user.id, opts)


async def _worker(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    status_mid: int,
    file_id: str,
    filename_hint: str,
    user_id: int,
    opts: Dict[str, Any],
    status_prefix: str = "",
    delete_status: bool = True,
):
    bot = context.bot
    tmpdir = tempfile.mkdtemp(prefix="segment_")
    input_path = os.path.join(tmpdir, filename_hint or "input.bin")
    out_dir = os.path.join(tmpdir, "out")

    try:
        # 1) Download
        await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Downloading media...")
        f = await bot.get_file(file_id)
        await f.download_to_drive(custom_path=input_path)

        # 2) Import the helper_funcs segmenter lazily (heavy)
        await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Preparing segmenter...")
        try:
            # Ensure tg_bot is importable if running in different cwd
            sys.path.append(os.getcwd())
            from tg_bot.modules.helper_funcs import segmenter as seg
        except Exception as e:
            await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Failed to import segmenter module.\n`{e}`")
            return

        # 3) Apply CLI-like options to module globals
        if opts.get("export_min") is not None:
            seg.EXPORT_MIN_SEC = float(opts["export_min"])
        if opts.get("target_per_class") is not None:
            seg.TARGET_PER_CLASS = int(opts["target_per_class"])
        # Handle singing padding
        if opts.get("pad") is not None:
            seg.SINGING_PAD_PRE_SEC = float(opts["pad"])
        if opts.get("pad_pre") is not None:
            seg.SINGING_PAD_PRE_SEC = float(opts["pad_pre"])
        if opts.get("pad_post") is not None:
            seg.SINGING_PAD_POST_SEC = float(opts["pad_post"])

        # 4) Segment
        await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Segmenting... This can take several minutes for long files.")
        outputs = await asyncio.to_thread(seg.segment_audio, input_path, out_dir)
        if not outputs:
            outputs = {'speech': [], 'music': []}
        speech = outputs.get('speech', []) or []
        music = outputs.get('music', []) or []
        total = len(speech) + len(music)

        if total == 0:
            await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}No segments found (file might be too short or silent).")
            return

        # 5) Upload results
        use_zip = opts.get("zip_output") or total > 24
        if use_zip:
            await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Packaging {total} clips into a zip and uploading...")
            zpath = _zip_outputs(tmpdir, outputs)
            if not zpath or not os.path.exists(zpath):
                await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Failed to create zip archive.")
                return
            cap = f"Segmentation complete.\nSpeech: {len(speech)}\nMusic: {len(music)}\nPacked: {os.path.basename(zpath)}"
            await _send_document_file(bot, chat_id, zpath, cap)
            if delete_status:
                try:
                    await bot.delete_message(chat_id, status_mid)
                except Exception:
                    pass
            return

        # Otherwise, send each clip (capped to be friendly)
        max_send = 20
        await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Uploading {min(total, max_send)} of {total} clips (sending more as zip is recommended for large outputs).")

        async def send_many(paths, label, limit):
            sent_count = 0
            for p in paths[:limit]:
                cap = f"{label}: {os.path.basename(p)}"
                try:
                    await _send_audio_file(bot, chat_id, p, cap)
                except TelegramError:
                    # fallback to document on audio send error
                    await _send_document_file(bot, chat_id, p, cap)
                sent_count += 1
            return sent_count

        # Send speech first, then music up to max_send total
        speech_to_send = min(len(speech), max_send)
        speech_sent = await send_many(speech, "speech", speech_to_send)
        remaining = max_send - speech_sent
        music_sent = await send_many(music, "music", max(0, remaining))

        remain_total = total - (speech_sent + music_sent)
        if remain_total > 0:
            # Zip the remaining ones
            remaining_outputs = {
                'speech': speech[speech_sent:],
                'music': music[music_sent:],
            }
            zpath = _zip_outputs(tmpdir, remaining_outputs)
            if zpath and os.path.exists(zpath):
                await _send_document_file(bot, chat_id, zpath, f"Remaining {remain_total} clips (zipped).")

        await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Done. Speech: {len(speech)}, Music: {len(music)}.")
        await asyncio.sleep(2.0)
        if delete_status:
            try:
                await bot.delete_message(chat_id, status_mid)
            except Exception:
                pass

    except Exception as e:
        try:
            await _safe_edit(bot, chat_id, status_mid, f"{status_prefix}Segmentation failed: `{e}`")
        except Exception:
            pass
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def get_help(_chat_id):
    return (
        "*Segment audio* into speech/music (singing labeled) using YAMNet.\n"
        "Usage:\n"
        "  /segment — reply to an audio/video/voice/document message\n\n"
        "Options:\n"
        "  --min <sec>      minimum exported clip length (default 10)\n"
        "  --target <int>   approx cap per class (0 disables, default 0)\n"
        "  --pad <sec>      padding before singing segments (default 2.7)\n"
        "  --pad-pre <sec>  padding before singing segments\n"
        "  --pad-post <sec> padding after singing segments (default 0)\n"
        "  --zip            zip outputs instead of sending many clips\n\n"
        "_Notes:_\n"
        "- First run may take longer (model download).\n"
        "- ffmpeg is required on the host.\n"
        "- Replying to an album will process all cached items from that album."
    )
