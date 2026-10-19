import os
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

@dataclass
class PanelConfig:
    name: str
    url: str
    username: str
    password: str
    default_inbound_id: Optional[int] = None

@dataclass
class Config:
    bot_token: str
    admin_ids: List[int]
    superadmin_id: int
    panels: List[PanelConfig]
    default_inbound_id: Optional[int]
    default_expire_days: int
    default_traffic_gb: int
    db_path: str

def parse_int_list(s: str) -> List[int]:
    if not s:
        return []
    return [int(x.strip()) for x in s.split(",") if x.strip().isdigit() or x.strip().lstrip("-").isdigit()]

def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN не задан! Скопируй .env.example в .env и заполни.")

    admin_ids = parse_int_list(os.getenv("ADMIN_IDS", ""))
    if not admin_ids:
        logging.warning("ADMIN_IDS пуст — никто не сможет пользоваться ботом кроме SUPERADMIN")

    superadmin_raw = os.getenv("SUPERADMIN_ID", "").strip()
    superadmin_id = int(superadmin_raw) if superadmin_raw.isdigit() else (admin_ids[0] if admin_ids else 0)

    # включаем супер-админа в список админов
    if superadmin_id and superadmin_id not in admin_ids:
        admin_ids.append(superadmin_id)

    panels_json = os.getenv("PANELS_JSON", "").strip()
    panels: List[PanelConfig] = []

    if panels_json:
        try:
            data = json.loads(panels_json)
            for p in data:
                panels.append(PanelConfig(
                    name=p.get("name", p.get("url","panel")),
                    url=p.get("url","").rstrip("/"),
                    username=p.get("username",""),
                    password=p.get("password",""),
                    default_inbound_id=int(p["default_inbound_id"]) if p.get("default_inbound_id") not in (None,"") else None
                ))
        except Exception as e:
            raise RuntimeError(f"PANELS_JSON невалидный JSON: {e}")
    else:
        url = os.getenv("PANEL_URL","").strip().rstrip("/")
        if not url:
            raise RuntimeError("PANEL_URL не задан (или PANELS_JSON)")
        panels.append(PanelConfig(
            name=os.getenv("PANEL_NAME","Основной"),
            url=url,
            username=os.getenv("PANEL_USERNAME",""),
            password=os.getenv("PANEL_PASSWORD",""),
            default_inbound_id=int(os.getenv("DEFAULT_INBOUND_ID")) if os.getenv("DEFAULT_INBOUND_ID","").strip().isdigit() else None
        ))

    default_inbound_id = None
    if os.getenv("DEFAULT_INBOUND_ID","").strip().isdigit():
        default_inbound_id = int(os.getenv("DEFAULT_INBOUND_ID"))

    return Config(
        bot_token=bot_token,
        admin_ids=admin_ids,
        superadmin_id=superadmin_id,
        panels=panels,
        default_inbound_id=default_inbound_id,
        default_expire_days=int(os.getenv("DEFAULT_EXPIRE_DAYS","30") or 30),
        default_traffic_gb=int(float(os.getenv("DEFAULT_TRAFFIC_GB","0") or 0)),
        db_path=os.getenv("DB_PATH","data/bot.db"),
    )

config = load_config()
