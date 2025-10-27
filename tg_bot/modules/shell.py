import subprocess
import asyncio
import contextlib
import os
import platform
import shlex
import signal
import subprocess as sp
from io import BytesIO
from tg_bot import log as LOGGER, SYS_ADMIN
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, filters
from tg_bot.modules.helper_funcs.decorators import kigcmd, rate_limit
from telegram import InputFile


def _limit_ping(cmd: str) -> str:
    # Add sane limits to ping so it doesn't run forever
    try:
        toks = shlex.split(cmd)
    except ValueError:
        return cmd  # if parsing fails, leave as-is
    if not toks or toks[0] != "ping":
        return cmd

    sysname = platform.system()
    if sysname == "Windows":
        if "-n" not in toks:
            toks[1:1] = ["-n", "4"]        # 4 packets
        if "-w" not in toks:
            toks += ["-w", "5000"]         # 5s timeout per request (ms)
    else:
        if "-c" not in toks:
            toks[1:1] = ["-c", "4"]        # 4 packets
        # prefer overall deadline if not already present
        if "-w" not in toks and "--deadline" not in toks:
            toks += ["-w", "5"]            # 5s overall deadline
    return " ".join(shlex.quote(t) for t in toks)


async def _run_shell(cmd: str, *, timeout: float = 15.0):
    """
    Run a shell command asynchronously with a hard timeout.
    Returns (stdout_str, stderr_str, returncode, timed_out: bool)
    """
    cmd = _limit_ping(cmd)

    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # own process group for clean kill
    else:
        kwargs["creationflags"] = sp.CREATE_NEW_PROCESS_GROUP

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )

    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (out_b.decode(errors="replace"),
                err_b.decode(errors="replace"),
                proc.returncode,
                False)
    except asyncio.TimeoutError:
        # Try graceful terminate, then force kill
        with contextlib.suppress(ProcessLookupError, ProcessExitedException):
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            await proc.wait()
        return ("", f"[Timed out after {timeout}s]\n", None, True)


@kigcmd(command='sh', filters=filters.User(SYS_ADMIN))
@rate_limit(40, 60)
async def shell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    parts = message.text.split(" ", 1)
    if len(parts) == 1 or not parts[1].strip():
        await message.reply_text("No command to execute was given.")
        return

    cmd = parts[1].strip()

    # Run asynchronously with a hard timeout
    stdout, stderr, rc, timed_out = await _run_shell(cmd, timeout=20.0)

    # Keep Markdown simple; avoid breaking inline code by sanitizing backticks
    def md(s: str) -> str:
        return s.replace("`", "ˋ")

    reply = ""
    if stdout:
        reply += f"*Stdout*\n`{md(stdout)}`\n"
    if stderr:
        reply += f"*Stderr*\n`{md(stderr)}`\n"
    if not stdout and not stderr:
        reply = "`(no output)`\n"

    suffix = f"\nExit: {rc if rc is not None else 'n/a'}"
    if timed_out:
        suffix += " (timeout)"
    reply += suffix

    # Send as file if too long
    if len(reply) > 3500:
        buf = BytesIO(reply.encode())
        buf.name = "shell_output.txt"
        await message.reply_document(document=buf, caption="Command output")
    else:
        await message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

__mod_name__ = "Shell"
