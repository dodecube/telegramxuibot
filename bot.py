import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import config
from database import init_db
from xui_api import MultiPanelManager

# логгирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger(__name__)

async def setup_commands(bot: Bot):
    cmds = [
        BotCommand(command="start", description="Меню"),
        BotCommand(command="create", description="Создать клиента"),
        BotCommand(command="list", description="Список клиентов"),
        BotCommand(command="search", description="Найти клиента"),
        BotCommand(command="find", description="Быстрый поиск /find имя"),
        BotCommand(command="inbounds", description="Инбаунды / сервера"),
        BotCommand(command="admins", description="Админы (супер-админ)"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(cmds)

async def main():
    if not config.bot_token or ":" not in config.bot_token:
        log.error("BOT_TOKEN невалидный! Проверь .env")
        return

    log.info(f"Админы: {config.admin_ids} | Супер-админ: {config.superadmin_id}")
    log.info(f"Панелей: {len(config.panels)} -> {[p.name+':'+p.url for p in config.panels]}")
    log.info(f"БД: {config.db_path}")

    # инициализация БД
    await init_db(config.db_path, config.admin_ids)

    # панели
    manager = MultiPanelManager(config.panels)

    # бот
    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # прокидываем manager в хендлеры
    from handlers import common, clients, admins
    common.set_manager(manager)
    clients.set_manager(manager)

    dp.include_router(common.router)
    dp.include_router(clients.router)
    dp.include_router(admins.router)

    # middleware для проверки админа (можно раскомментировать чтобы резать всё)
    # но лучше проверять внутри хендлеров чтобы давать понятный ответ

    await setup_commands(bot)
    log.info("Бот запущен — жду сообщения...")

    # пробуем залогиниться во все панели сразу, чтобы проверить конфиг
    for p in manager.clients:
        try:
            await p.login()
            log.info(f"✅ Панель {p.name} — логин OK")
        except Exception as e:
            log.warning(f"⚠️ Панель {p.name} — логин FAIL: {e}")

    try:
        await dp.start_polling(bot)
    finally:
        await manager.close_all()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлен")
