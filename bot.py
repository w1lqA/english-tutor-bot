import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

import config
from telegram_handler import router

log = logging.getLogger("bot")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    session = AiohttpSession(proxy=config.PROXY_URL)
    bot = Bot(token=config.BOT_TOKEN, session=session)
    dp = Dispatcher()
    dp.include_router(router)

    log.info("Bot started (proxy: %s)", "on" if config.PROXY_URL else "off")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())