# telegramxuibot — ТГ бот для быстрого создания юзеров 3x-ui

Быстрый Telegram-бот на Python (aiogram 3) для управления клиентами 3x-ui / Xray.

Поддерживает:
- 🔐 Админы через `.env` + управление админами прямо из бота (супер-админ)
- 🌍 Несколько панелей / серверов одновременно
- ⚡ Создание клиента за 15 секунд: выбор сервера → инбаунда → имя → трафик → срок → QR+ссылка
- 📋 Список всех клиентов с пагинацией
- 🔍 Поиск по имени
- 📊 Информация по трафику, сброс трафика, продление, смена лимита, удаление
- 📱 QR-код + готовая `vless://` / `vmess://` / `trojan://` ссылка (Reality, XTLS, WS — автоопределение)
- 🐳 Docker / systemd

---

## 1. Установка

### Вариант A: Docker (рекомендуется)

```bash
git clone https://github.com/dodecube/telegramxuibot.git
cd telegramxuibot

# скопируй пример конфига
cp .env.example .env
nano .env   # заполни BOT_TOKEN, PANEL_URL, ADMIN_IDS

docker compose up -d --build
docker logs -f telegramxuibot
```

### Вариант B: Вручную (VPS без docker)

```bash
git clone https://github.com/dodecube/telegramxuibot.git
cd telegramxuibot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env

python bot.py
# для автозапуска — добавь systemd сервис (см. ниже)
```

---

## 2. Настройка `.env`

Минимальный `.env`:
```env
BOT_TOKEN=1234567890:AAH.....
ADMIN_IDS=123456789,987654321
SUPERADMIN_ID=123456789

PANEL_URL=https://vpn.example.com:2053/abc123panel
PANEL_USERNAME=admin
PANEL_PASSWORD=supersecret

DEFAULT_EXPIRE_DAYS=30
DEFAULT_TRAFFIC_GB=0
```

Где взять:
- `BOT_TOKEN` — у [@BotFather](https://t.me/BotFather) → `/newbot`
- `ADMIN_IDS` — у [@userinfobot](https://t.me/userinfobot) узнай свой ID. Перечисли через запятую. Можно прописать сколько угодно админов.
- `PANEL_URL` — скопируй из браузера когда открыта панель 3x-ui. Важно: до `/panel` включая рандомный путь, без слеша в конце. Пример: `https://1.2.3.4:2053/abcd123`
- `PANEL_USERNAME` / `PANEL_PASSWORD` — логин от панели 3x-ui (тот же что вводишь в браузер).
- `SUPERADMIN_ID` — главный админ. Только он может добавлять/удалять других админов через кнопку 👑 Админы. Если не указан — первый из `ADMIN_IDS`.

### Несколько серверов

Если у тебя 2-3-10 панелей — заполни `PANELS_JSON` (тогда `PANEL_URL` игнорируется):

```env
PANELS_JSON='[
  {"name":"🇩🇪 DE-1","url":"https://de1.example.com:2053/xxx","username":"admin","password":"pass1","default_inbound_id":1},
  {"name":"🇫🇮 FI-1","url":"https://fi1.example.com:2053/xxx","username":"admin","password":"pass2"}
]'
```

Бот покажет выбор сервера при создании клиента и в списке.

---

## 3. Как прописать админов

### Способ 1: через `.env` (при старте)
```env
ADMIN_IDS=111,222,333
SUPERADMIN_ID=111
```
Перезапусти бота: `docker compose restart`

### Способ 2: через бота (на горячую)
1. Зайди как супер-админ
2. Нажми `👑 Админы` → `➕ Добавить админа` → отправь ID числом (или перешли сообщение от человека)
3. Админ сразу получит доступ без перезапуска
4. Удалить — нажми на админа в списке → подтверди

БД хранится в `data/bot.db` (sqlite) — не удаляй этот файл.

### Быстрые команды (только супер-админ)
```
/addadmin 123456789
/deladmin 123456789
/admins — список админов
```

---

## 4. Использование

1. Открой бота в ТГ → `/start`
2. Нажми **➕ Создать клиента**
3. Выбери сервер (если их несколько) → инбаунд (VLESS Reality / VMess / Trojan)
4. Введи имя — латиницей, 2-32 символа: `ivan`, `maria_iphone`
5. Выбери лимит трафика (0 = безлимит) и срок
6. Получи ссылку + QR — отправь клиенту

**Другие кнопки:**
- `📋 Список клиентов` — все юзеры со всех панелей, пагинация, карточка с действиями
- `🔍 Найти клиента` — поиск по части имени
- `📊 Инбаунды / Сервера` — проверка подключения к панелям, список протоколов/портов
- В карточке клиента: `QR`, `Трафик`, `Продлить`, `Лимит`, `Сброс трафика`, `Удалить`

---

## 5. Структура проекта
```
telegramxuibot/
├── bot.py              # точка входа, polling
├── config.py           # загрузка .env, мульти-панели
├── database.py         # sqlite админы
├── xui_api.py          # обёртка над 3x-ui API (login, addClient, list и тд)
├── keyboards.py        # все клавиатуры
├── utils.py            # QR, форматтеры
├── handlers/
│   ├── common.py       # /start, создание клиента (FSM)
│   ├── clients.py      # список, поиск, действия с клиентом
│   └── admins.py       # управление админами
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## 6. Systemd (если без Docker)

`/etc/systemd/system/telegramxuibot.service`:
```ini
[Unit]
Description=Telegram XUI Bot
After=network.target

[Service]
WorkingDirectory=/opt/telegramxuibot
ExecStart=/opt/telegramxuibot/.venv/bin/python bot.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegramxuibot
sudo journalctl -u telegramxuibot -f
```

---

## 7. Частые проблемы

**❌ Login failed / 401** — проверь `PANEL_URL` (должен быть с портом и путём панели), логин/пароль панели. Попробуй открыть тот же URL в браузере с VPS через `curl -k`.

**❌ addClient failed** — убедись что инбаунд включён (Enable). Для VLESS Reality у клиентов должен быть `flow: xtls-rprx-vision` — бот ставит его автоматически.

**Ссылка с неправильным доменом** — бот берёт хост из `PANEL_URL`. Если панель на IP, а клиентам нужен домен — в панели укажи `Address` (в настройках инбаунда) или поставь в `PANEL_URL` домен вместо IP.

**Самоподписанный сертификат** — нормально, бот отключает проверку SSL (`ssl=False`).

---

## 8. Безопасность

- Никогда не коммить `.env` с токенами
- `data/bot.db` содержит только ID админов — бэкапь при необходимости
- Ограничь доступ к серверу, где лежит `.env`

---

MIT — делай что хочешь, но без гарантий.
