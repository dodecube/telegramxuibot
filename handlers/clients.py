import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from config import config
from database import is_admin
from xui_api import MultiPanelManager, format_expire, format_traffic
from keyboards import clients_list_kb, client_actions_kb, extend_kb, limit_kb, panels_kb
from utils import generate_qr, format_client_info

log = logging.getLogger(__name__)
router = Router()
manager: MultiPanelManager = None

def set_manager(m: MultiPanelManager):
    global manager
    manager = m

# кэш списка для пагинации (в памяти)
clients_cache = {}  # user_id -> list
client_panel_map = {} # email -> panel_name (чтобы найти панель быстро)

class SearchState(StatesGroup):
    wait_query = State()

async def get_all_clients(panel_filter=None):
    all_clients = []
    for panel in manager.clients:
        try:
            await panel.login()
            clients = await panel.list_clients()
            for c in clients:
                c["_panel"] = panel.name
                client_panel_map[c["email"]] = panel.name
            all_clients.extend(clients)
        except Exception as e:
            log.warning(f"get_all_clients {panel.name} failed: {e}")
    # фильтр по панели если нужно
    if panel_filter:
        all_clients = [c for c in all_clients if c["_panel"]==panel_filter]
    # сортировка по email
    all_clients.sort(key=lambda x: x["email"])
    return all_clients

@router.message(F.text == "📋 Список клиентов")
@router.message(Command("list"))
async def list_clients_cmd(message: Message, state: FSMContext):
    if not await is_admin(config.db_path, message.from_user.id):
        return
    # если много панелей — спросить панель
    if len(manager.clients) > 1:
        await message.answer("🌍 Выбери сервер (или покажу всех):", reply_markup=all_panels_kb_with_all())
        return
    await show_clients_page(message, page=0)

def all_panels_kb_with_all():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🌍 Все сервера", callback_data="clients_panel_ALL")
    for p in manager.clients:
        b.button(text=p.name, callback_data=f"clients_panel_{p.name}")
    b.adjust(1)
    return b.as_markup()

@router.callback_query(F.data.startswith("clients_panel_"))
async def cb_clients_panel(query: CallbackQuery):
    panel_name = query.data.replace("clients_panel_", "")
    await query.message.edit_text(f"⏳ Загружаю клиентов...")
    if panel_name == "ALL":
        clients = await get_all_clients()
    else:
        clients = await get_all_clients(panel_filter=panel_name)
    await show_clients_page(query.message, page=0, clients=clients, edit=True)
    await query.answer()

async def show_clients_page(message, page=0, clients=None, edit=False):
    if clients is None:
        # грузим всех
        msg = await message.answer("⏳ Загружаю клиентов...") if not edit else message
        clients = await get_all_clients()
        if not edit:
            try: await msg.delete()
            except: pass
    # кэш
    # сохраняем в глобальный кэш по сообщению юзера (костыль — по chat id)
    # для упрощения — по message.chat.id
    chat_id = message.chat.id if hasattr(message, "chat") else 0
    clients_cache[chat_id] = clients
    # также по query.from_user если edit
    if hasattr(message, "message"):
        pass

    if not clients:
        await message.answer("📭 Клиентов пока нет") if not edit else await message.edit_text("📭 Клиентов пока нет")
        return

    text = f"📋 <b>Клиенты ({len(clients)})</b> — выбери для действий:\nНажми на имя, чтобы открыть карточку."
    kb = clients_list_kb(clients, page=page)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("clients_page_"))
async def cb_clients_page(query: CallbackQuery):
    page = int(query.data.replace("clients_page_", ""))
    chat_id = query.message.chat.id
    clients = clients_cache.get(chat_id)
    if not clients:
        clients = await get_all_clients()
        clients_cache[chat_id] = clients
    kb = clients_list_kb(clients, page=page)
    text = f"📋 <b>Клиенты ({len(clients)})</b> — страница {page+1}"
    try:
        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except:
        pass
    await query.answer()

# Обработка выбора клиента -> показываем карточку с действиями
@router.callback_query(F.data.startswith("client_"))
async def cb_client_card(query: CallbackQuery):
    # формат client_inboundId:email
    raw = query.data.replace("client_", "")
    try:
        inbound_part, email = raw.split(":", 1)
        inbound_id = int(inbound_part)
    except:
        await query.answer("Ошибка парсера", show_alert=True)
        return

    # найти панель и клиента
    panel_name = client_panel_map.get(email)
    # если нет в кэше — ищем перебором
    target_panel = None
    target_client = None
    for panel in manager.clients:
        try:
            await panel.login()
            c = await panel.get_client(email)
            if c and c["inbound_id"]==inbound_id:
                target_panel = panel
                target_client = c
                break
            # fallback — листинг
            if not target_client:
                clients = await panel.list_clients(inbound_id=inbound_id)
                for cc in clients:
                    if cc["email"]==email:
                        target_panel = panel
                        target_client = cc
                        break
        except: continue
        if target_client:
            break

    if not target_client:
        await query.answer("Клиент не найден (возможно уже удалён)", show_alert=True)
        return

    # получаем свежий трафик
    try:
        stat = await target_panel.get_client_traffic(inbound_id, email)
        if stat:
            target_client["up"] = stat.get("up", target_client.get("up",0))
            target_client["down"] = stat.get("down", target_client.get("down",0))
            target_client["total"] = target_client["up"]+target_client["down"]
    except:
        pass

    text = format_client_info(target_client) + f"\n\n🌍 Панель: <b>{target_panel.name}</b>"
    kb = client_actions_kb(inbound_id, email)
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data == "back_to_clients")
async def cb_back_to_clients(query: CallbackQuery):
    chat_id = query.message.chat.id
    clients = clients_cache.get(chat_id) or await get_all_clients()
    await query.message.edit_text(f"📋 <b>Клиенты ({len(clients)})</b>", reply_markup=clients_list_kb(clients, page=0), parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data == "close")
async def cb_close(query: CallbackQuery):
    await query.message.delete()
    await query.answer()

# ===== ДЕЙСТВИЯ С КЛИЕНТОМ =====
@router.callback_query(F.data.startswith("act_qr:"))
async def act_qr(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    inbound_id = int(inbound_id)
    # найти панель
    panel = None
    for p in manager.clients:
        c = await p.get_client(email) if p else None
        if c:
            panel = p
            break
        # пробуем иначе: в кэше панели имя
        if client_panel_map.get(email)==p.name:
            panel = p
            break
    if not panel:
        panel = manager.get_default()

    try:
        await panel.login()
        inbound = await panel.get_inbound(inbound_id)
        # найти клиента внутри inbound settings
        import json
        settings = json.loads(inbound.get("settings","{}") or "{}")
        clients = settings.get("clients", [])
        target = next((x for x in clients if x.get("email")==email), None)
        if not target:
            await query.answer("Клиент не найден в inbound", show_alert=True)
            return
        link = panel.build_link(target, inbound)
        qr = generate_qr(link)
        await query.message.answer_photo(qr, caption=f"🔗 <code>{link}</code>\n\n👤 {email}\n📦 {inbound.get('remark')} | {panel.name}", parse_mode="HTML")
        await query.answer()
    except Exception as e:
        await query.answer(f"Ошибка: {e}", show_alert=True)

@router.callback_query(F.data.startswith("act_info:"))
async def act_info(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    inbound_id = int(inbound_id)
    # найти панель
    panel = manager.get_panel(client_panel_map.get(email, "")) or manager.get_default()
    try:
        await panel.login()
        c = await panel.get_client(email)
        if not c:
            await query.answer("Не найдено", show_alert=True)
            return
        # свежий трафик
        stat = await panel.get_client_traffic(inbound_id, email)
        if stat:
            c["up"] = stat.get("up", c.get("up",0))
            c["down"] = stat.get("down", c.get("down",0))
        text = format_client_info(c) + f"\n\n🌍 {panel.name}"
        await query.message.edit_text(text, reply_markup=client_actions_kb(inbound_id, email), parse_mode="HTML")
    except Exception as e:
        await query.answer(f"Ошибка: {e}", show_alert=True)
    await query.answer()

@router.callback_query(F.data.startswith("act_extend:"))
async def act_extend(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    await query.message.edit_text(f"⏩ Продлить <b>{email}</b>\nВыбери срок:", reply_markup=extend_kb(int(inbound_id), email), parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("extend_"))
async def cb_extend(query: CallbackQuery):
    # extend_inbound:email:days
    raw = query.data.replace("extend_","")
    try:
        inbound_str, email, days_str = raw.split(":")
        inbound_id = int(inbound_str)
        days = int(days_str)
    except:
        await query.answer("Ошибка парсера", show_alert=True)
        return
    panel = manager.get_panel(client_panel_map.get(email,"")) or manager.get_default()
    await query.message.edit_text("⏳ Продлеваю...")
    try:
        await panel.login()
        await panel.update_client(inbound_id, email, expire_days=days)
        label = "бессрочно" if days==0 else f"+{days} дн."
        await query.message.edit_text(f"✅ Продлён {email}: {label}", reply_markup=client_actions_kb(inbound_id, email), parse_mode="HTML")
    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("act_limit:"))
async def act_limit(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    await query.message.edit_text(f"💾 Сменить лимит для <b>{email}</b>:", reply_markup=limit_kb(int(inbound_id), email), parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("limit_"))
async def cb_limit(query: CallbackQuery):
    raw = query.data.replace("limit_","")
    inbound_str, email, gb_str = raw.split(":")
    inbound_id = int(inbound_str)
    gb = int(gb_str)
    panel = manager.get_panel(client_panel_map.get(email,"")) or manager.get_default()
    await query.message.edit_text("⏳ Меняю лимит...")
    try:
        await panel.login()
        await panel.update_client(inbound_id, email, total_gb=gb)
        label = "∞ безлимит" if gb==0 else f"{gb} ГБ"
        await query.message.edit_text(f"✅ Лимит {email}: {label}", reply_markup=client_actions_kb(inbound_id, email), parse_mode="HTML")
    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("act_reset:"))
async def act_reset(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    inbound_id = int(inbound_id)
    # подтверждение
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сбросить", callback_data=f"reset_confirm:{inbound_id}:{email}"), InlineKeyboardButton(text="❌ Отмена", callback_data=f"client_{inbound_id}:{email}")]
    ])
    await query.message.edit_text(f"⚠️ Сбросить трафик у <b>{email}</b>?\nСчётчики обнулятся.", reply_markup=kb, parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("reset_confirm:"))
async def cb_reset_confirm(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    inbound_id = int(inbound_id)
    panel = manager.get_panel(client_panel_map.get(email,"")) or manager.get_default()
    await query.message.edit_text("⏳ Сбрасываю...")
    try:
        await panel.login()
        await panel.reset_client_traffic(inbound_id, email)
        await query.message.edit_text(f"✅ Трафик сброшен: {email}", reply_markup=client_actions_kb(inbound_id, email), parse_mode="HTML")
    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка сброса: <code>{e}</code>\nПопробуй через панель вручную.", parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("act_del:"))
async def act_del(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    inbound_id = int(inbound_id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ УДАЛИТЬ", callback_data=f"del_confirm:{inbound_id}:{email}"), InlineKeyboardButton(text="❌ Отмена", callback_data=f"client_{inbound_id}:{email}")]
    ])
    await query.message.edit_text(f"⚠️ Удалить клиента <b>{email}</b>?\nДействие необратимо!", reply_markup=kb, parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("del_confirm:"))
async def cb_del_confirm(query: CallbackQuery):
    _, inbound_id, email = query.data.split(":",2)
    inbound_id = int(inbound_id)
    panel = manager.get_panel(client_panel_map.get(email,"")) or manager.get_default()
    await query.message.edit_text("⏳ Удаляю...")
    try:
        await panel.login()
        await panel.delete_client_by_email(inbound_id, email)
        await query.message.edit_text(f"✅ Удалён: <b>{email}</b>", parse_mode="HTML")
        # чистим кэш
        client_panel_map.pop(email, None)
    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка удаления: <code>{e}</code>\nПопробуй удалить по UUID через панель.", parse_mode="HTML")
    await query.answer()

# ===== ПОИСК =====
@router.message(F.text == "🔍 Найти клиента")
@router.message(Command("search"))
async def search_start(message: Message, state: FSMContext):
    if not await is_admin(config.db_path, message.from_user.id):
        return
    await state.set_state(SearchState.wait_query)
    await message.answer("🔍 Введи имя (часть email) для поиска:\nНапример: <code>ivan</code>", parse_mode="HTML")

@router.message(Command("find"))
async def find_cmd(message: Message):
    # /find ivan
    if not await is_admin(config.db_path, message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Используй: /find <часть_имени>")
        return
    query = parts[1].strip().lower()
    await do_search(message, query)

@router.message(SearchState.wait_query)
async def search_query(message: Message, state: FSMContext):
    if not await is_admin(config.db_path, message.from_user.id):
        return
    if message.text == "❌ Отмена":
        await state.clear()
        return
    query = message.text.strip().lower()
    await state.clear()
    await do_search(message, query)

async def do_search(message: Message, query: str):
    await message.answer(f"⏳ Ищу <code>{query}</code>...", parse_mode="HTML")
    clients = await get_all_clients()
    matched = [c for c in clients if query in c["email"].lower()]
    if not matched:
        await message.answer(f"Ничего не найдено по <code>{query}</code>", parse_mode="HTML")
        return
    text = f"🔍 Найдено {len(matched)} по <code>{query}</code>:"
    await message.answer(text, reply_markup=clients_list_kb(matched, page=0), parse_mode="HTML")

