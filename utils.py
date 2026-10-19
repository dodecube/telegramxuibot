import re
import qrcode
import io
from aiogram.types import BufferedInputFile

def is_valid_email(name: str) -> bool:
    # для 3x-ui email это просто идентификатор, без @
    # разрешаем буквы, цифры, -, _, .
    return bool(re.match(r'^[a-zA-Z0-9._-]{2,32}$', name))

def sanitize_email(name: str) -> str:
    name = name.strip().lower().replace(" ", "_")
    name = re.sub(r'[^a-z0-9._-]', '', name)
    return name[:32]

def generate_qr(link: str) -> BufferedInputFile:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="qr.png")

def human_bytes(b: int) -> str:
    if b == 0:
        return "0 Б"
    if b >= 1024**3:
        return f"{b/1024**3:.2f} ГБ"
    if b >= 1024**2:
        return f"{b/1024**2:.1f} МБ"
    if b >= 1024:
        return f"{b/1024:.1f} КБ"
    return f"{b} Б"

def format_client_info(c: dict) -> str:
    from xui_api import format_expire, format_traffic
    up = c.get("up",0)
    down = c.get("down",0)
    total_used = up+down
    total_gb = c.get("totalGB",0)
    limit = format_traffic(total_gb)
    used = human_bytes(total_used)
    remain = human_bytes(total_gb - total_used) if total_gb else "∞"
    expire = format_expire(c.get("expiryTime",0))
    return (
        f"👤 <b>{c.get('email')}</b>\n"
        f"📦 Инбаунд: <code>{c.get('inbound_remark')}</code> (ID {c.get('inbound_id')}) | {c.get('protocol')}:{c.get('port')}\n"
        f"🆔 UUID: <code>{c.get('uuid')}</code>\n"
        f"📊 Трафик: {used} / {limit} (осталось {remain})\n"
        f"   ⬆️ {human_bytes(up)} ⬇️ {human_bytes(down)}\n"
        f"⏰ Срок: {expire}\n"
        f"🔒 Лимит IP: {c.get('limitIp') or 'нет'}\n"
        f"✅ Включен: {'да' if c.get('enable') else 'нет'}"
    )
