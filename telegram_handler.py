import asyncio
import io
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

import llm
from formatter import format_vocabulary_analysis
from vocabulary import is_vocabulary_post

log = logging.getLogger(__name__)
router = Router()

ALBUM_WAIT_SECONDS = 3.0   # wait for all photos of an album to arrive
MAX_IMAGES = 10

_albums: dict[str, list[Message]] = {}
_tasks: set[asyncio.Task] = set()


@router.channel_post()
async def on_channel_post(message: Message) -> None:
    """Routing log only. The reply is sent from on_discussion_copy below."""
    text = message.text or message.caption
    preview = (text or "").replace("\n", " ")[:80]
    log.info("Received channel post id=%s chat=%s text=%r",
             message.message_id, message.chat.id, preview)
    if not text:
        log.info("Post ignored: empty text/caption (may be an album photo; caption is checked later)")
    elif not is_vocabulary_post(text):
        log.info("Post ignored: no #vocabulary tag")
    else:
        log.info("Vocabulary post detected (id=%s)", message.message_id)


@router.message(F.is_automatic_forward)
async def on_discussion_copy(message: Message, bot: Bot) -> None:
    """Telegram's automatic copy of a channel post in the linked discussion group."""
    group_id = message.media_group_id
    if group_id is None:
        await _process(bot, [message])
        return

    # Album: every photo arrives as its own message; collect them, then process once.
    batch = _albums.setdefault(group_id, [])
    batch.append(message)
    if len(batch) == 1:
        task = asyncio.create_task(_flush_album(bot, group_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


async def _flush_album(bot: Bot, group_id: str) -> None:
    await asyncio.sleep(ALBUM_WAIT_SECONDS)
    await _process(bot, _albums.pop(group_id, []))


async def _download(bot: Bot, file_id: str) -> bytes:
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


async def _process(bot: Bot, messages: list[Message]) -> None:
    try:
        if not messages:
            return
        messages.sort(key=lambda m: m.message_id)
        first = messages[0]  # the comment is attached to this message's thread

        text = next((m.text or m.caption for m in messages if (m.text or m.caption)), None)
        if not is_vocabulary_post(text):
            log.info("Discussion copy ignored: no #vocabulary tag")
            return

        photo_ids = [m.photo[-1].file_id for m in messages if m.photo][:MAX_IMAGES]
        log.info("Vocabulary post in discussion (group msg id=%s, %d image(s))",
                 first.message_id, len(photo_ids))

        images = [await _download(bot, fid) for fid in photo_ids]

        log.info("Sending vocabulary analysis request")
        try:
            analysis = await llm.analyze_vocabulary(text, images)
        except llm.LLMError as e:
            log.error("LLM failed: %s", e)
            await first.reply("⚠️ Analysis failed. See the bot logs for details.")
            return
        log.info("LLM response received (%d item(s))", len(analysis.items))

        log.info("Sending analysis to discussion thread")
        for part in format_vocabulary_analysis(analysis):
            await first.reply(part, parse_mode="HTML")
        log.info("Done")

    except TelegramAPIError as e:
        log.error("Telegram error: %s", e)
    except Exception:
        log.exception("Unexpected error while processing post")