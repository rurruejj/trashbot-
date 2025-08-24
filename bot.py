import os
import asyncio
import json
import base64
import html
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery, FSInputFile, WebAppInfo
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from db import (
    init_db, save_user_info, get_user_info, add_request,
    mark_request_completed, clear_all_data, get_user_id_by_request_id
)

from aiohttp import web

# ====== НАСТРОЙКИ ======
BOT_TOKEN = "8278093306:AAFbhmogmEOS-wVYGSDbIW45jD5jcxSX3ZE"
ADMIN_ID = 1851886180
CHANNEL_USERNAME = "@udveri_ru"
WEBAPP_TARIFFS_URL = "https://udveri-tariffs.vercel.app/"
WEBAPP_VERSION = "2025-08-13-1"

PHOTO_PATHS = [
    ['photo1.jpg', 'фото1.jpg', 'фото 1.jpg', 'Фото 1.jpg', '1.jpg'],
    ['photo2.jpg', 'фото2.jpg', 'фото 2.jpg', 'Фото 2.jpg', '2.jpg'],
    ['photo3.jpg', 'фото3.jpg', 'фото 3.jpg', 'Фото 3.jpg', '3.jpg'],
    ['photo4.jpg', 'фото4.jpg', 'фото 4.jpg', 'Фото 4.jpg', '4.jpg'],
    ['photo5.jpg', 'фото5.jpg', 'фото 5.jpg', 'Фото 5.jpg', '5.jpg'],
]

INTRO_CAPTIONS = [
    "Оставьте заявку",
    "Выставите за дверь",
    "Ожидайте курьера",
    "Мы заберем",
    "До бака донесем"
]

# FSM
user_states = {}

# ====== ВСПОМОГАТЕЛЬНЫЕ ======
def _miniapp_url_for_user(user_id: int) -> str:
    info = get_user_info(user_id) or {}
    payload = {
        "user_id": user_id,
        "first_name": info.get("first_name") or "",
        "street": info.get("street") or "",
        "house": info.get("house") or "",
        "flat": info.get("flat") or "",
        "entrance": info.get("entrance") or "",
        "floor": info.get("floor") or "",
        "phone": info.get("phone") or "",
        "tab": "menu"
    }
    p = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    sep = "&" if "?" in WEBAPP_TARIFFS_URL else "?"
    return f"{WEBAPP_TARIFFS_URL}{sep}v={WEBAPP_VERSION}&p={p}"

def _tab_url(base_url: str, tab: str) -> str:
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}tab={tab}"

def miniapp_kb_for(user_id: int) -> types.InlineKeyboardMarkup:
    base_url = _miniapp_url_for_user(user_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Меню", web_app=WebAppInfo(url=base_url))
    kb.button(text="Профиль", web_app=WebAppInfo(url=_tab_url(base_url, "profile")))
    return kb.as_markup()

def find_intro_photo(name_variants):
    for name in name_variants:
        path = os.path.join("media", name)
        if os.path.exists(path):
            return FSInputFile(path)
    return None

def _format_address(info: dict) -> str:
    parts = []
    if info.get("street"):   parts.append(info["street"])
    if info.get("house"):    parts.append(f"д.{info['house']}")
    if info.get("flat"):     parts.append(f"кв.{info['flat']}")
    if info.get("entrance"): parts.append(f"подъезд {info['entrance']}")
    if info.get("floor"):    parts.append(f"этаж {info['floor']}")
    if info.get("city"):     parts.append(info["city"])
    return ", ".join(parts) if parts else "—"

def _format_user_link(u: types.User) -> str:
    if u.username:
        return f"@{u.username}"
    return f'<a href="tg://user?id={u.id}">{html.escape(u.first_name or "пользователь")}</a>'

# ====== ХЭНДЛЕРЫ ======
async def start_handler(message: Message, bot: Bot):
    user = message.from_user
    user_id = user.id
    try:
        save_user_info(
            user_id,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            username=user.username or ""
        )
    except Exception as e:
        print("save_user_info error:", e)

    info = get_user_info(user_id)
    if info and (info.get("street") or info.get("phone")):
        name = info.get('first_name') or user.first_name or ''
        await message.answer(
            f"Привет, {name}! Рад снова видеть тебя 👋",
            reply_markup=miniapp_kb_for(user_id)
        )
        return

    user_states[user_id] = {"step": "street"}
    await send_intro_photo(bot, user_id, 0)

async def webapp_entry(message: Message, bot: Bot):
    kb = InlineKeyboardBuilder()
    kb.button(text="Открыть мини-приложение", web_app=WebAppInfo(url=_miniapp_url_for_user(message.from_user.id)))
    await message.answer("Открой мини-приложение кнопкой ниже:", reply_markup=kb.as_markup())

async def send_intro_photo(bot: Bot, user_id: int, idx: int):
    if idx < 0 or idx >= len(PHOTO_PATHS):
        idx = 0
    photo = find_intro_photo(PHOTO_PATHS[idx])
    caption = INTRO_CAPTIONS[idx] if idx < len(INTRO_CAPTIONS) else ""
    kb = InlineKeyboardBuilder()
    if idx < len(PHOTO_PATHS) - 1:
        kb.button(text="Далее ➡️", callback_data=f"next:{idx+1}")
    else:
        kb.button(text="Перейти к согласию", callback_data="pd")
    if photo:
        await bot.send_photo(user_id, photo, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
    else:
        await bot.send_message(user_id, caption, reply_markup=kb.as_markup())

async def next_photo(callback: CallbackQuery, bot: Bot):
    idx = int(callback.data.split(":")[1])
    await callback.answer()
    await send_intro_photo(bot, callback.from_user.id, idx)

async def show_pd(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Согласен", callback_data="pd_ok")
    await bot.send_message(callback.from_user.id, "🛡️ Согласие на обработку персональных данных", reply_markup=kb.as_markup())

async def pd_ok(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_states[callback.from_user.id] = {"step": "street"}
    await bot.send_message(callback.from_user.id, "🏠 Введите улицу:")

async def text_handler(message: Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    step = user_states[user_id].get("step")

    # 🔧 изменено: сразу сохраняем в БД
    if step == "street":
        save_user_info(user_id, street=message.text.strip())
        user_states[user_id]["step"] = "house"
        await message.answer("Введите номер дома:")
    elif step == "house":
        save_user_info(user_id, house=message.text.strip())
        user_states[user_id]["step"] = "flat"
        await message.answer("Введите номер квартиры:")
    elif step == "flat":
        save_user_info(user_id, flat=message.text.strip())
        user_states[user_id]["step"] = "entrance"
        await message.answer("Введите подъезд:")
    elif step == "entrance":
        save_user_info(user_id, entrance=message.text.strip())
        user_states[user_id]["step"] = "floor"
        await message.answer("Введите этаж:")
    elif step == "floor":
        save_user_info(user_id, floor=message.text.strip())
        user_states[user_id]["step"] = "phone"
        await message.answer("Введите телефон:")
    elif step == "phone":
        save_user_info(user_id, phone=message.text.strip())
        user_states.pop(user_id, None)
        await message.answer("✅ Адрес сохранён. Открывайте меню:", reply_markup=miniapp_kb_for(user_id))

# === ПРИЁМ ДАННЫХ ИЗ МИНИ-АППА ===
async def webapp_data_handler(message: Message, bot: Bot):
    raw = message.web_app_data.data if message.web_app_data else None
    if not raw:
        return
    try:
        data = json.loads(raw)
    except Exception:
        return

    if data.get("type") == "create_request":
        bags = int(data.get("bags", 1))
        comment = data.get("comment", "")
        request_id = add_request(message.from_user.id, bags, comment)
        info = get_user_info(message.from_user.id) or {}
        addr  = _format_address(info)
        phone = info.get("phone") or "—"
        uname = _format_user_link(message.from_user)
        admin_text = (
            "🧺 <b>Заявка</b>\n"
            f"Пакеты: <b>{bags}</b>\n"
            f"Адрес: {addr}\n"
            f"Телефон: {phone}\n"
            f"Юзернейм: {uname}"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Забрал мусор", callback_data=f"complete:{request_id}")
        await bot.send_message(ADMIN_ID, admin_text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
        await message.answer("✅ Заявка отправлена администратору.")

async def complete_request(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) != 2:
        return
    request_id = int(parts[1])
    mark_request_completed(request_id)
    await callback.answer("Заявка отмечена выполненной ✅")
    user_id = get_user_id_by_request_id(request_id)
    if user_id:
        await bot.send_message(user_id, "✅ Ваша заявка выполнена.")
    await bot.edit_message_reply_markup(callback.message.chat.id, callback.message.message_id, reply_markup=None)

async def clear_command_handler(message: Message, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔️ У вас нет доступа к этой команде.")
    clear_all_data()
    user_states.clear()
    await message.answer("✅ Все данные очищены.")

# === HTTP эндпоинт для профиля ===
async def http_get_user(request: web.Request):
    user_id_raw = request.query.get("user_id")
    try:
        user_id = int(user_id_raw)
    except Exception:
        return web.json_response({"ok": False, "error": "bad user_id"}, status=400)

    info = get_user_info(user_id) or {}
    name = ((info.get("first_name") or "") + (" " + info.get("last_name") if info.get("last_name") else "")).strip() or "—"
    return web.json_response({
        "ok": True,
        "profile": {
            "name": name,
            "username": info.get("username") or "—",
            "phone": info.get("phone") or "—",
            "address": _format_address(info)
        }
    })

# ====== ТОЧКА ВХОДА ======
async def main():
    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.register(start_handler, CommandStart())
    dp.message.register(clear_command_handler, Command("clear"))
    dp.message.register(webapp_entry, Command("webapp"))
    dp.message.register(webapp_data_handler, F.web_app_data)
    dp.message.register(text_handler, F.text)
    dp.callback_query.register(next_photo, F.data.startswith("next:"))
    dp.callback_query.register(show_pd, F.data == "pd")
    dp.callback_query.register(pd_ok, F.data == "pd_ok")
    dp.callback_query.register(complete_request, F.data.startswith("complete:"))

    # 🔧 запускаем HTTP и бота параллельно
    app = web.Application()
    app.router.add_get("/get_user", http_get_user)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080")))
    await site.start()
    print("HTTP server started")

    # Параллельный запуск
    await asyncio.gather(dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())

