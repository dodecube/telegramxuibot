from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

def main_menu_kb(is_superadmin=False):
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Создать клиента")
    kb.button(text="📋 Список клиентов")
    kb.button(text="🔍 Найти клиента")
    kb.button(text="📊 Инбаунды / Сервера")
    if is_superadmin:
        kb.button(text="👑 Админы")
    kb.button(text="ℹ️ Помощь")
    kb.adjust(2,2,2)
    return kb.as_markup(resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

def confirm_kb():
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да", callback_data="confirm_yes")
    b.button(text="❌ Нет", callback_data="confirm_no")
    b.adjust(2)
    return b.as_markup()

def panels_kb(panels, prefix="panel_"):
    b = InlineKeyboardBuilder()
    for p in panels:
        b.button(text=p.name, callback_data=f"{prefix}{p.name}")
    b.adjust(1)
    return b.as_markup()

def inbounds_kb(inbounds, prefix="inbound_"):
    b = InlineKeyboardBuilder()
    for ib in inbounds:
        remark = ib.get("remark") or f"ID {ib.get('id')}"
        proto = ib.get("protocol","")
        port = ib.get("port","")
        text = f"{remark} [{proto}:{port}]"
        b.button(text=text[:64], callback_data=f"{prefix}{ib.get('id')}")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(1)
    return b.as_markup()

def traffic_kb():
    b = InlineKeyboardBuilder()
    for gb in [0, 10, 50, 100, 200, 500, 1000]:
        label = "∞ Безлимит" if gb==0 else f"{gb} ГБ"
        b.button(text=label, callback_data=f"traffic_{gb}")
    b.adjust(3)
    return b.as_markup()

def expire_kb():
    b = InlineKeyboardBuilder()
    for d, label in [(7,"7 дней"), (30,"30 дней"), (90,"90 дней"), (180,"180 дней"), (365,"365 дней"), (0,"♾️ Бессрочно")]:
        b.button(text=label, callback_data=f"expire_{d}")
    b.adjust(3)
    return b.as_markup()

def clients_list_kb(clients, page=0, per_page=8):
    b = InlineKeyboardBuilder()
    total = len(clients)
    start = page*per_page
    chunk = clients[start:start+per_page]
    for c in chunk:
        email = c["email"]
        # показываем коротко: email + inbound
        text = f"{email} ({c['inbound_remark'][:15]})"
        b.button(text=text[:64], callback_data=f"client_{c['inbound_id']}:{email}")
    # пагинация
    has_prev = page > 0
    has_next = (page+1)*per_page < total
    if has_prev:
        b.button(text="⬅️ Назад", callback_data=f"clients_page_{page-1}")
    if has_next:
        b.button(text="➡️ Далее", callback_data=f"clients_page_{page+1}")
    b.button(text="🔄 Обновить", callback_data=f"clients_page_{page}")
    b.button(text="❌ Закрыть", callback_data="close")
    # раскладка: клиенты по 1 в ряд, пагинация отдельно
    if chunk:
        b.adjust(1,2,1)
    else:
        b.adjust(2,1)
    return b.as_markup()

def client_actions_kb(inbound_id, email):
    b = InlineKeyboardBuilder()
    b.button(text="📱 QR / Ссылка", callback_data=f"act_qr:{inbound_id}:{email}")
    b.button(text="📊 Трафик", callback_data=f"act_info:{inbound_id}:{email}")
    b.button(text="⏩ Продлить", callback_data=f"act_extend:{inbound_id}:{email}")
    b.button(text="💾 Лимит", callback_data=f"act_limit:{inbound_id}:{email}")
    b.button(text="🔄 Сброс трафика", callback_data=f"act_reset:{inbound_id}:{email}")
    b.button(text="🗑️ Удалить", callback_data=f"act_del:{inbound_id}:{email}")
    b.button(text="⬅️ Назад", callback_data=f"back_to_clients")
    b.adjust(2,2,2,1)
    return b.as_markup()

def extend_kb(inbound_id, email):
    b = InlineKeyboardBuilder()
    for d in [7,14,30,90,180,365]:
        b.button(text=f"+{d} дн.", callback_data=f"extend_{inbound_id}:{email}:{d}")
    b.button(text="♾️ Сделать бессрочным", callback_data=f"extend_{inbound_id}:{email}:0")
    b.button(text="⬅️ Назад", callback_data=f"client_{inbound_id}:{email}")
    b.adjust(3)
    return b.as_markup()

def limit_kb(inbound_id, email):
    b = InlineKeyboardBuilder()
    for gb in [0,10,50,100,200,500,1000]:
        label = "∞ Безлимит" if gb==0 else f"{gb} ГБ"
        b.button(text=label, callback_data=f"limit_{inbound_id}:{email}:{gb}")
    b.button(text="⬅️ Назад", callback_data=f"client_{inbound_id}:{email}")
    b.adjust(3)
    return b.as_markup()

def admins_kb(admins):
    b = InlineKeyboardBuilder()
    for a in admins:
        label = f"{a.get('username') or ''} {a['user_id']}".strip()
        b.button(text=f"🗑️ {label}", callback_data=f"admin_del_{a['user_id']}")
    b.button(text="➕ Добавить админа", callback_data="admin_add")
    b.button(text="⬅️ Назад", callback_data="close")
    b.adjust(1)
    return b.as_markup()
