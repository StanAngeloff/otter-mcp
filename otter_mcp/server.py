from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from mcp.server.fastmcp import Context, FastMCP

from .client import OtterClient


@dataclass
class AppContext:
    client: OtterClient


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    email = os.environ.get("OTTER_EMAIL", "")
    password = os.environ.get("OTTER_PASSWORD", "")
    totp_secret = os.environ.get("OTTER_TOTP_SECRET", "")
    if not email or not password or not totp_secret:
        raise RuntimeError(
            "OTTER_EMAIL, OTTER_PASSWORD, and OTTER_TOTP_SECRET "
            "environment variables are required"
        )
    client = OtterClient(email, password, totp_secret)
    if not await client.try_resume():
        await client.login()
    try:
        yield AppContext(client=client)
    finally:
        await client.close()


mcp = FastMCP("otter", lifespan=lifespan)


def _client(ctx: Context) -> OtterClient:
    return ctx.request_context.lifespan_context.client


def _format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "?"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 60}m"


def _format_ts(epoch: int | float | None) -> str:
    if not epoch:
        return "?"
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_offset(ms: int) -> str:
    total_seconds = ms // 1000
    h, remainder = divmod(total_seconds, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


@mcp.tool()
async def list_conversations(
    ctx: Context,
    page_size: int = 20,
    cursor: str | None = None,
) -> str:
    """List conversations from your Otter.ai homepage feed.

    Returns a list of conversations with their ID, date, duration, and title.
    Use the cursor from the output to fetch the next page.
    """
    client = _client(ctx)
    last_load_ts = int(cursor) if cursor else None
    data = await client.list_conversations(
        page_size=page_size, last_load_ts=last_load_ts
    )

    lines = []
    for s in data.get("speeches", []):
        otid = s.get("otid", "?")
        title = s.get("title", "Untitled")
        duration = _format_duration(s.get("duration"))
        date = _format_ts(s.get("created_at") or s.get("start_time"))
        lines.append(f"{otid} | {date} | {duration} | {title}")

    if not lines:
        lines.append("No conversations found.")

    if data.get("end_of_list"):
        lines.append("---\nEnd of list.")
    elif ts := data.get("last_load_ts"):
        lines.append(f"---\nNext cursor: {ts}")

    return "\n".join(lines)


@mcp.tool()
async def search(ctx: Context, query: str) -> str:
    """Search conversations by text query.

    Not yet implemented — a HAR capture of the search flow is needed.
    """
    return (
        "Search is not yet implemented. "
        "A HAR capture of the search flow is needed to reverse-engineer the endpoint."
    )


@mcp.tool()
async def get_transcript(ctx: Context, otid: str) -> str:
    """Get the full transcript of an Otter.ai conversation as plain text.

    Returns speaker-attributed transcript with timestamps.
    Pass the otid from list_conversations.
    """
    client = _client(ctx)
    speech = await client.get_speech(otid)
    speakers = await client.get_speakers()

    title = speech.get("title", "Untitled")
    duration = _format_duration(speech.get("duration"))
    date = _format_ts(speech.get("created_at") or speech.get("start_time"))

    lines: list[str] = [title, f"{date} | {duration}", ""]

    transcripts = speech.get("transcripts", [])
    transcripts.sort(key=lambda t: t.get("start_offset", 0))

    prev_speaker: str | None = None
    prev_ts = "00:00"
    pending: list[str] = []

    def flush() -> None:
        nonlocal prev_speaker, pending
        if prev_speaker is not None and pending:
            lines.append(f"[{prev_ts}] {prev_speaker}:")
            lines.append(" ".join(pending))
            lines.append("")
        prev_speaker = None
        pending = []

    for t in transcripts:
        speaker_id = t.get("speaker_id")
        speaker_name = speakers.get(speaker_id, f"Speaker {speaker_id}")
        text = t.get("transcript", "").strip()
        ts = _format_offset(t.get("start_offset", 0))

        if not text:
            continue

        if speaker_name == prev_speaker:
            pending.append(text)
        else:
            flush()
            prev_speaker = speaker_name
            prev_ts = ts
            pending = [text]

    flush()

    return "\n".join(lines)


def main() -> None:
    mcp.run(transport="stdio")
