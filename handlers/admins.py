import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from config import config
from database import is_admin, add_admin, remove_admin, list_admins_detailed, get_admins
from keyboards import admins_kb

log = logging.getLogger(__name__)
router = Router()

class AdminAddState(StatesGroup):
    wait_id = State()

def is_superadmin(user_id: int) -> bool:
    return user_id == config.superadmin_id

@router.message(F.text == "👑 Админы")
@router.message(Command("admins"))
async def admins_list(message: Message):
    if not await is_admin(config.db_path, message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    if not is_superadmin(message.from_user.id):
        await message.answer("⛔ Только супер-админ может управлять админами.\nСупер-админ: <code>{}</code>".format(config.superadmin_id), parse_mode="HTML")
        return
    admins = await list_admins_detailed(config.db_path)
    text = "👑 <b>Админы бота</b>\n\n"
    for a in admins:
        marker = " 👑" if a["user_id"]==config.superadmin_id else ""
        text += f"• <code>{a['user_id']}</code> @{a['username'] or ''}{marker}\n"
    text += "\nНажми на админа чтобы удалить, или добавь нового."
    await message.answer(text, reply_markup=admins_kb(admins), parse_mode="HTML")

@router.callback_query(F.data == "admin_add")
async def admin_add_start(query: CallbackQuery, state: FSMContext):
    if not is_superadmin(query.from_user.id):
        await query.answer("Только супер-админ", show_alert=True)
        return
    await state.set_state(AdminAddState.wait_id)
    await query.message.answer("➕ Отправь ID нового админа (число).\nЛибо перешли сообщение от пользователя — бот возьмёт ID.\n\nУзнать ID можно через @userinfobot")
    await query.answer()

@router.message(AdminAddState.wait_id)
async def admin_add_process(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        return
    # поддержка пересылки
    user_id = None
    username = None
    if message.forward_from:
        user_id = message.forward_from.id
        username = message.forward_from.username
    else:
        # пробуем распарсить число
        txt = message.text.strip().replace("@","")
        if txt.isdigit():
            user_id = int(txt)
        elif message.entities:
            # упомянутый пользователь?
            for ent in message.entities:
                if ent.type in ("text_mention","mention"):
                    # text_mention has user
                    if getattr(ent, "user", None):
                        user_id = ent.user.id
                        username = ent.user.username
                    break
        # пробуем достать id из текста с пробелом "123456 username"
        if not user_id and " " in txt:
            parts = txt.split()
            if parts[0].isdigit():
                user_id = int(parts[0])
                username = parts[1] if len(parts)>1 else None

    if not user_id:
        await message.answer("❌ Не могу получить ID. Отправь число, например: <code>123456789</code>", parse_mode="HTML")
        return

    await add_admin(config.db_path, user_id, username=username, added_by=message.from_user.id)
    # обновляем конфиг в памяти
    if user_id not in config.admin_ids:
        config.admin_ids.append(user_id)
    await state.clear()
    await message.answer(f"✅ Админ <code>{user_id}</code> @{username or ''} добавлен", parse_mode="HTML")
    # показать обновленный список
    admins = await list_admins_detailed(config.db_path)
    await message.answer("👑 Обновлённый список:", reply_markup=admins_kb(admins), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_del_"))
async def admin_del(query: CallbackQuery):
    if not is_superadmin(query.from_user.id):
        await query.answer("Только супер-админ", show_alert=True)
        return
    user_id = int(query.data.replace("admin_del_",""))
    if user_id == config.superadmin_id:
        await query.answer("Нельзя удалить супер-админа!", show_alert=True)
        return
    if user_id == query.from_user.id:
        await query.answer("Нельзя удалить себя!", show_alert=True)
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_del_confirm_{user_id}"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_del_cancel")]
    ])
    await query.message.edit_text(f"Удалить админа <code>{user_id}</code>?", reply_markup=kb, parse_mode="HTML")
    await query.answer()

@router.callback_query(F.data.startswith("admin_del_confirm_"))
async def admin_del_confirm(query: CallbackQuery):
    if not is_superadmin(query.from_user.id):
        return
    user_id = int(query.data.replace("admin_del_confirm_",""))
    ok = await remove_admin(config.db_path, user_id)
    if user_id in config.admin_ids:
        config.admin_ids.remove(user_id)
    await query.answer("Удалён" if ok else "Не найден")
    admins = await list_admins_detailed(config.db_path)
    text = "👑 <b>Админы</b> (обновлено):\n\n"
    for a in admins:
        marker = " 👑" if a["user_id"]==config.superadmin_id else ""
        text += f"• <code>{a['user_id']}</code> @{a['username'] or ''}{marker}\n"
    try:
        await query.message.edit_text(text, reply_markup=admins_kb(admins), parse_mode="HTML")
    except:
        await query.message.answer(text, reply_markup=admins_kb(admins), parse_mode="HTML")

@router.callback_query(F.data == "admin_del_cancel")
async def admin_del_cancel(query: CallbackQuery):
    await query.message.delete()
    await query.answer()

# команда быстрого добавления для супер-админа
@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message):
    if not is_superadmin(message.from_user.id):
        await message.answer("Только супер-админ")
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Используй: <code>/addadmin 123456789</code>", parse_mode="HTML")
        return
    uid = int(parts[1])
    await add_admin(config.db_path, uid, added_by=message.from_user.id)
    if uid not in config.admin_ids:
        config.admin_ids.append(uid)
    await message.answer(f"✅ Админ {uid} добавлен")

@router.message(Command("deladmin"))
async def cmd_deladmin(message: Message):
    if not is_superadmin(message.from_user.id):
        await message.answer("Только супер-админ")
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Используй: <code>/deladmin 123456789</code>", parse_mode="HTML")
        return
    uid = int(parts[1])
    if uid == config.superadmin_id:
        await message.answer("Нельзя удалить супер-админа")
        return
    ok = await remove_admin(config.db_path, uid)
    if uid in config.admin_ids:
        config.admin_ids.remove(uid)
    await message.answer("✅ Удалён" if ok else "Не найден")
