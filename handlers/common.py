from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from config import config
from database import is_admin
from keyboards import main_menu_kb, cancel_kb, panels_kb, inbounds_kb, traffic_kb, expire_kb
from xui_api import MultiPanelManager, format_traffic, format_expire
from utils import sanitize_email, is_valid_email, generate_qr, format_client_info, human_bytes
import logging

log = logging.getLogger(__name__)
router = Router()

manager: MultiPanelManager = None

def set_manager(m: MultiPanelManager):
    global manager
    manager = m

# FSM для создания клиента
class CreateClient(StatesGroup):
    choose_panel = State()
    choose_inbound = State()
    enter_name = State()
    choose_traffic = State()
    choose_expire = State()
    confirm = State()


@router.message(CommandStart())
async def start(message: Message):
    if not await is_admin(config.db_path, message.from_user.id):
        await message.answer("⛔ У тебя нет доступа. Попроси админа добавить твой ID:\n<code>{}</code>".format(message.from_user.id), parse_mode="HTML")
        return
    is_super = message.from_user.id == config.superadmin_id
    await message.answer(
        "👋 <b>3X-UI Бот</b>\n\n"
        "Быстрое создание клиентов для 3x-ui / Xray.\n\n"
        "Команды:\n"
        "• ➕ Создать клиента — пошаговый мастер\n"
        "• 📋 Список — все юзеры с пагинацией\n"
        "• 🔍 Найти — по имени\n"
        "• 📊 Инбаунды — проверить сервера\n\n"
        "💡 Подсказка: просто нажми кнопку ниже.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_superadmin=is_super)
    )

@router.message(F.text == "ℹ️ Помощь")
@router.message(Command("help"))
async def help_cmd(message: Message):
    if not await is_admin(config.db_path, message.from_user.id):
        return
    await message.answer(
        "📖 <b>Помощь по боту</b>\n\n"
        "<b>Создание клиента:</b>\n"
        "1. Выбери сервер (если их несколько)\n"
        "2. Выбери инбаунд (VLESS/Vmess/Trojan)\n"
        "3. Введи имя клиента (латиницей, 2-32 символа)\n"
        "4. Выбери лимит трафика\n"
        "5. Выбери срок\n"
        "→ Бот выдаст ссылку + QR\n\n"
        "<b>Управление:</b>\n"
        "• Продлить, сменить лимит, сбросить трафик, удалить — через карточку клиента\n"
        "• Админов добавляет только супер-админ\n\n"
        "<b>Техническое:</b>\n"
        f"Панелей: {len(config.panels)}\n"
        f"Супер-админ: <code>{config.superadmin_id}</code>\n"
        f"БД: <code>{config.db_path}</code>",
        parse_mode="HTML"
    )

@router.message(F.text == "📊 Инбаунды / Сервера")
@router.message(Command("inbounds"))
async def show_inbounds(message: Message, state: FSMContext):
    if not await is_admin(config.db_path, message.from_user.id):
        return
    await list_panels(message)

async def list_panels(message: Message):
    if len(manager.clients) == 1:
        await show_inbounds_for_panel(message, manager.get_default())
    else:
        await message.answer("Выбери сервер:", reply_markup=panels_kb([p for p in manager.clients], prefix="show_inbounds_"))

def format_inbound(ib):
    import json
    settings = json.loads(ib.get("settings","{}") or "{}")
    clients = len(settings.get("clients", []))
    stream = json.loads(ib.get("streamSettings","{}") or "{}")
    sec = stream.get("security","none")
    net = stream.get("network","tcp")
    return (
        f"🔹 <b>{ib.get('remark') or 'Без имени'}</b> (ID {ib.get('id')})\n"
        f"   Протокол: <code>{ib.get('protocol')}</code> | Порт: <code>{ib.get('port')}</code>\n"
        f"   Сеть: {net} | Защита: {sec} | Клиентов: {clients} | {'✅ ON' if ib.get('enable') else '❌ OFF'}"
    )

async def show_inbounds_for_panel(message_or_query, panel):
    try:
        await panel.login()
        inbounds = await panel.get_inbounds()
    except Exception as e:
        await message_or_query.answer(f"❌ Ошибка подключения к панели <b>{panel.name}</b>: <code>{e}</code>", parse_mode="HTML")
        return

    if not inbounds:
        await message_or_query.answer(f"Панель <b>{panel.name}</b>: инбаундов нет", parse_mode="HTML")
        return

    text = f"📊 <b>{panel.name}</b> — инбаунды ({len(inbounds)}):\n\n"
    for ib in inbounds:
        text += format_inbound(ib) + "\n\n"
    await message_or_query.answer(text, parse_mode="HTML")

# ===== СОЗДАНИЕ КЛИЕНТА =====
@router.message(F.text == "➕ Создать клиента")
@router.message(Command("create"))
async def create_start(message: Message, state: FSMContext):
    if not await is_admin(config.db_path, message.from_user.id):
        return
    await state.clear()
    if len(manager.clients) > 1:
        await state.set_state(CreateClient.choose_panel)
        await message.answer("🌍 Выбери сервер:", reply_markup=panels_kb([p for p in manager.clients], prefix="create_panel_"))
    else:
        # сразу к инбаундам
        await choose_inbound_step(message, manager.get_default(), state)

async def choose_inbound_step(message, panel, state: FSMContext):
    try:
        await panel.login()
        inbounds = await panel.get_inbounds()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()
        return

    # фильтр только включенных
    # показываем все, но помечаем
    if not inbounds:
        await message.answer("❌ Инбаундов не найдено")
        await state.clear()
        return

    # если есть default_inbound_id
    if panel.default_inbound_id:
        # сразу пропускаем выбор?
        # нет, дадим выбрать но подсветим
        pass

    await state.set_state(CreateClient.choose_inbound)
    await state.update_data(panel_name=panel.name)
    await message.answer(f"📦 Сервер <b>{panel.name}</b>: выбери инбаунд:", reply_markup=inbounds_kb(inbounds, prefix="create_inbound_"), parse_mode="HTML")

# выбор панели при создании
@router.callback_query(F.data.startswith("create_panel_"))
async def cb_create_panel(query: CallbackQuery, state: FSMContext):
    panel_name = query.data.replace("create_panel_", "")
    panel = manager.get_panel(panel_name)
    if not panel:
        await query.answer("Панель не найдена", show_alert=True)
        return
    await query.message.edit_text(f"Выбран сервер: {panel_name}")
    await choose_inbound_step(query.message, panel, state)
    await query.answer()

@router.callback_query(F.data.startswith("create_inbound_"))
async def cb_create_inbound(query: CallbackQuery, state: FSMContext):
    inbound_id = int(query.data.replace("create_inbound_", ""))
    data = await state.get_data()
    panel_name = data.get("panel_name")
    await state.update_data(inbound_id=inbound_id)
    await state.set_state(CreateClient.enter_name)
    await query.message.edit_text(f"✅ Инбаунд ID {inbound_id} выбран.\n\n👤 Введи имя клиента (2-32 латиницей, без пробелов):\nНапример: <code>ivan</code>, <code>john_iphone</code>", parse_mode="HTML")
    # показываем клавиатуру отмены
    await query.message.answer("Жду имя...", reply_markup=cancel_kb())
    await query.answer()

@router.message(StateFilter(CreateClient.enter_name))
async def create_enter_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=main_menu_kb(is_superadmin=message.from_user.id==config.superadmin_id))
        return
    raw = sanitize_email(message.text)
    if not is_valid_email(raw):
        await message.answer("❌ Неверное имя. Используй 2-32 символа латиницей: a-z, 0-9, . _ -")
        return
    # проверка на существование
    data = await state.get_data()
    panel = manager.get_panel(data["panel_name"])
    try:
        clients = await panel.list_clients(inbound_id=data["inbound_id"])
        if any(c["email"]==raw for c in clients):
            await message.answer(f"❌ Клиент <code>{raw}</code> уже существует в этом инбаунде. Придумай другое имя.", parse_mode="HTML")
            return
    except Exception as e:
        log.warning(f"check exists failed: {e}")

    await state.update_data(email=raw)
    await state.set_state(CreateClient.choose_traffic)
    await message.answer(f"Имя: <b>{raw}</b> ✅\n\n💾 Выбери лимит трафика:", reply_markup=traffic_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("traffic_"), StateFilter(CreateClient.choose_traffic))
async def cb_traffic(query: CallbackQuery, state: FSMContext):
    gb = int(query.data.replace("traffic_",""))
    await state.update_data(total_gb=gb)
    await state.set_state(CreateClient.choose_expire)
    label = "∞ Безлимит" if gb==0 else f"{gb} ГБ"
    await query.message.edit_text(f"Трафик: {label} ✅\n\n⏰ Выбери срок действия:")
    await query.message.edit_reply_markup(reply_markup=expire_kb())
    await query.answer()

@router.callback_query(F.data.startswith("expire_"), StateFilter(CreateClient.choose_expire))
async def cb_expire(query: CallbackQuery, state: FSMContext):
    days = int(query.data.replace("expire_",""))
    await state.update_data(expire_days=days)
    data = await state.get_data()
    email = data["email"]
    gb = data["total_gb"]
    panel_name = data["panel_name"]
    inbound_id = data["inbound_id"]
    traffic_label = "∞ Безлимит" if gb==0 else f"{gb} ГБ"
    expire_label = "♾️ Бессрочно" if days==0 else f"{days} дней"

    await state.set_state(CreateClient.confirm)
    text = (
        f"📋 <b>Подтверди создание:</b>\n\n"
        f"🌍 Сервер: <b>{panel_name}</b>\n"
        f"📦 Инбаунд: <code>{inbound_id}</code>\n"
        f"👤 Имя: <code>{email}</code>\n"
        f"💾 Трафик: {traffic_label}\n"
        f"⏰ Срок: {expire_label}\n\n"
        f"Создаём?"
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data="create_confirm"), InlineKeyboardButton(text="❌ Отмена", callback_data="create_cancel")]
    ])
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data == "create_confirm", StateFilter(CreateClient.confirm))
async def cb_create_confirm(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    panel = manager.get_panel(data["panel_name"])
    inbound_id = data["inbound_id"]
    email = data["email"]
    total_gb = data["total_gb"]
    expire_days = data["expire_days"]

    await query.message.edit_text("⏳ Создаю клиента...")
    try:
        await panel.login()
        result = await panel.add_client(inbound_id, email, total_gb=total_gb, expire_days=expire_days)
        client = result["client"]
        inbound = result["inbound"]
        link = panel.build_link(client, inbound)
        is_super = query.from_user.id == config.superadmin_id

        text = (
            f"✅ <b>Клиент создан!</b>\n\n"
            f"👤 <code>{email}</code>\n"
            f"🌍 {panel.name} | 📦 {inbound.get('remark')} ({inbound.get('protocol')}:{inbound.get('port')})\n"
            f"💾 {format_traffic(client.get('totalGB',0))} | ⏰ {format_expire(client.get('expiryTime',0))}\n\n"
            f"🔗 <code>{link}</code>\n\n"
            f"📱 Отсканируй QR ниже в Hiddify / V2RayTun / Streisand / Happ"
        )
        # QR
        try:
            qr_file = generate_qr(link)
            await query.message.answer_photo(qr_file, caption=text, parse_mode="HTML", reply_markup=main_menu_kb(is_superadmin=is_super))
            await query.message.delete()
        except Exception as e:
            log.warning(f"qr failed: {e}")
            await query.message.edit_text(text, parse_mode="HTML")
            await query.message.answer("Готово.", reply_markup=main_menu_kb(is_superadmin=is_super))
        log.info(f"Created client {email} on {panel.name}/{inbound_id} by {query.from_user.id}")

    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка создания: <code>{e}</code>", parse_mode="HTML")
        log.exception("create failed")
    await state.clear()
    await query.answer()

@router.callback_query(F.data == "create_cancel")
async def cb_create_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text("❌ Отменено")
    await query.message.answer("Меню:", reply_markup=main_menu_kb(is_superadmin=query.from_user.id==config.superadmin_id))
    await query.answer()

# показать инбаунды (кнопка)
@router.callback_query(F.data.startswith("show_inbounds_"))
async def cb_show_inbounds(query: CallbackQuery):
    panel_name = query.data.replace("show_inbounds_","")
    panel = manager.get_panel(panel_name)
    await query.message.edit_text(f"Загружаю {panel_name}...")
    await show_inbounds_for_panel(query.message, panel)
    await query.answer()

@router.message(F.text == "❌ Отмена")
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено", reply_markup=main_menu_kb(is_superadmin=message.from_user.id==config.superadmin_id))

