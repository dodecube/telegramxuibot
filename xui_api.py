import uuid
import json
import time
import random
import string
import logging
import aiohttp
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin

log = logging.getLogger(__name__)

class XUIApiError(Exception):
    pass

def gen_uuid() -> str:
    return str(uuid.uuid4())

def gen_subid(length=12) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def to_gb_bytes(gb: int) -> int:
    return int(gb * 1024**3) if gb else 0

def format_traffic(bytes_val: int) -> str:
    if not bytes_val:
        return "∞ безлимит"
    gb = bytes_val / 1024**3
    if gb < 1:
        return f"{bytes_val/1024**2:.1f} MB"
    return f"{gb:.1f} GB"

def format_expire(expire_ms: int) -> str:
    if not expire_ms or expire_ms == 0:
        return "♾️ без срока"
    # XUI хранит в миллисекундах
    sec = expire_ms / 1000
    dt = time.strftime("%d.%m.%Y %H:%M", time.localtime(sec))
    days_left = (sec - time.time()) / 86400
    if days_left < 0:
        return f"{dt} (просрочен)"
    return f"{dt} (осталось {days_left:.0f} дн.)"

class XuiClient:
    def __init__(self, name: str, url: str, username: str, password: str, default_inbound_id: Optional[int]=None):
        self.name = name
        self.base_url = url.rstrip("/")
        self.username = username
        self.password = password
        self.default_inbound_id = default_inbound_id
        self.session: Optional[aiohttp.ClientSession] = None
        self.cookies = {}

    async def ensure_session(self):
        if not self.session or self.session.closed:
            # Отключаем проверку SSL для самоподписанных сертов (частый кейс у панелей)
            connector = aiohttp.TCPConnector(ssl=False)
            self.session = aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=20))

    async def login(self):
        await self.ensure_session()
        url = f"{self.base_url}/login"
        data = {"username": self.username, "password": self.password}
        log.info(f"[{self.name}] Login -> {url}")
        async with self.session.post(url, data=data) as resp:
            text = await resp.text()
            # 3x-ui ставит куку 3x-ui или session
            if resp.status != 200:
                raise XUIApiError(f"Login failed {resp.status}: {text[:500]}")
            # Проверка успешности — в куках должна быть сессия или в теле success
            try:
                j = await resp.json(content_type=None)
                if not j.get("success"):
                    raise XUIApiError(f"Login не успешен: {j}")
            except:
                # некоторые версии возвращают HTML редирект — считаем успехом если кука есть
                pass
            # сохраняем куки
            self.cookies = {k: v.value for k,v in resp.cookies.items()}
            if not self.cookies:
                # пробуем сохранить из сессии
                self.cookies = {c.key: c.value for c in self.session.cookie_jar}
            log.info(f"[{self.name}] Login OK, cookies: {list(self.cookies.keys())}")

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        await self.ensure_session()
        url = f"{self.base_url}{path}"
        # автоматом добавляем куки
        headers = kwargs.pop("headers", {})
        # ретрай логина при 401/302
        for attempt in range(2):
            async with self.session.request(method, url, headers=headers, cookies=self.cookies, **kwargs) as resp:
                if resp.status in (401, 302, 403) and attempt == 0:
                    log.warning(f"[{self.name}] {resp.status} -> перелогин")
                    await self.login()
                    continue
                text = await resp.text()
                if resp.status >= 400:
                    raise XUIApiError(f"{method} {path} {resp.status}: {text[:1000]}")
                try:
                    return json.loads(text)
                except:
                    return text
        raise XUIApiError("Не удалось выполнить запрос после перелогина")

    async def get_inbounds(self) -> List[Dict]:
        data = await self._request("POST", "/panel/api/inbounds/list")
        if isinstance(data, dict) and "obj" in data:
            return data["obj"]
        if isinstance(data, list):
            return data
        raise XUIApiError(f"Неожиданный ответ inbounds/list: {data}")

    async def get_inbound(self, inbound_id: int) -> Dict:
        data = await self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")
        if isinstance(data, dict) and "obj" in data:
            return data["obj"]
        return data

    async def add_client(self, inbound_id: int, email: str, uuid_str: str = None, limit_ip: int = 0, total_gb: int = 0, expire_days: int = 0, flow: str = "") -> Dict:
        """
        Универсальное создание клиента. Работает для VLESS/VMess/Trojan/Shadowsocks.
        Для VLESS Reality flow обычно "xtls-rprx-vision"
        """
        inbound = await self.get_inbound(inbound_id)
        protocol = inbound.get("protocol", "")
        settings = json.loads(inbound.get("settings", "{}"))

        uuid_str = uuid_str or gen_uuid()
        # expiry
        if expire_days and expire_days > 0:
            expiry_time = int((time.time() + expire_days*86400) * 1000)
        else:
            expiry_time = 0

        total = to_gb_bytes(total_gb)

        # Определяем нужные поля для клиента
        new_client = {}
        # Большинство протоколов используют поле id
        # Trojan/Shadowsocks — password
        if protocol in ("vless", "vmess"):
            new_client = {
                "id": uuid_str,
                "email": email,
                "limitIp": limit_ip,
                "totalGB": total,
                "expiryTime": expiry_time,
                "enable": True,
                "tgId": "",
                "subId": gen_subid(),
            }
            if flow and protocol == "vless":
                new_client["flow"] = flow
            # если в инбаунде Reality — обязательно flow
            # пробуем угадать flow из существующих клиентов
            if protocol == "vless" and not flow:
                clients = settings.get("clients", [])
                # если у всех flow vision — ставим vision
                if clients and all(c.get("flow") for c in clients):
                    new_client["flow"] = "xtls-rprx-vision"
        elif protocol == "trojan":
            new_client = {
                "password": uuid_str,
                "email": email,
                "limitIp": limit_ip,
                "totalGB": total,
                "expiryTime": expiry_time,
                "enable": True,
                "tgId": "",
                "subId": gen_subid(),
            }
        elif protocol == "shadowsocks":
            # SS в 3x-ui: method, password, email
            # password генерируем как uuid или случайный
            new_client = {
                "password": uuid_str,
                "email": email,
                "method": settings.get("method", "aes-256-gcm"),
                "limitIp": limit_ip,
                "totalGB": total,
                "expiryTime": expiry_time,
                "enable": True,
                "tgId": "",
                "subId": gen_subid(),
            }
        else:
            # fallback
            new_client = {
                "id": uuid_str,
                "email": email,
                "limitIp": limit_ip,
                "totalGB": total,
                "expiryTime": expiry_time,
                "enable": True,
                "tgId": "",
                "subId": gen_subid(),
            }

        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [new_client]}, ensure_ascii=False)
        }
        log.info(f"[{self.name}] addClient inbound={inbound_id} email={email} proto={protocol}")
        res = await self._request("POST", "/panel/api/inbounds/addClient", json=payload)
        if isinstance(res, dict) and not res.get("success", True):
            raise XUIApiError(f"addClient failed: {res}")
        return {"client": new_client, "inbound": inbound, "result": res}

    async def delete_client(self, inbound_id: int, client_uuid_or_email: str):
        # Новый API: /panel/api/inbounds/{id}/delClient/{clientId}
        # Старый: /panel/api/inbounds/updateClient ... — пробуем новый
        # clientId — это email или uuid в зависимости от версии. Пробуем оба пути
        # Способ 1: новый
        try:
            res = await self._request("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid_or_email}")
            if isinstance(res, dict) and res.get("success"):
                return res
        except Exception as e:
            log.warning(f"delClient new api failed: {e}")

        # Способ 2: через remove через settings — достаем inbound и убираем клиента
        inbound = await self.get_inbound(inbound_id)
        settings = json.loads(inbound.get("settings","{}"))
        clients = settings.get("clients", [])
        # ищем по id/password/email
        new_clients = []
        found = False
        for c in clients:
            if c.get("id") == client_uuid_or_email or c.get("password") == client_uuid_or_email or c.get("email") == client_uuid_or_email:
                found = True
                continue
            new_clients.append(c)
        if not found:
            raise XUIApiError("Клиент не найден в inbound")

        # Обновляем через addClient? Нет, есть update? Пробуем старый endpoint
        # В 3x-ui нет прямого удаления через settings, но можно пересоздать? Альтернатива — delClient по email
        # Попробуем еще раз по email если передавали uuid
        raise XUIApiError(f"Не удалось удалить {client_uuid_or_email}, попробуй удалить по email")

    async def delete_client_by_email(self, inbound_id: int, email: str):
        # Пробуем new API по email (работает в свежих версиях)
        return await self.delete_client(inbound_id, email)

    async def update_client(self, inbound_id: int, email: str, total_gb: int = None, expire_days: int = None, reset_traffic: bool = False):
        """
        Обновление лимитов/продление. Использует /panel/api/inbounds/updateClient/{uuid}
        """
        inbound = await self.get_inbound(inbound_id)
        settings = json.loads(inbound.get("settings","{}"))
        clients = settings.get("clients", [])
        target = next((c for c in clients if c.get("email")==email), None)
        if not target:
            raise XUIApiError(f"Клиент {email} не найден")

        client_id = target.get("id") or target.get("password")

        payload_client = target.copy()

        if total_gb is not None:
            payload_client["totalGB"] = to_gb_bytes(total_gb)

        if expire_days is not None:
            if expire_days == 0:
                payload_client["expiryTime"] = 0
            else:
                # продлеваем от текущего expiry или от сейчас
                current_expiry = payload_client.get("expiryTime", 0)
                base = current_expiry/1000 if current_expiry and current_expiry/1000 > time.time() else time.time()
                payload_client["expiryTime"] = int((base + expire_days*86400)*1000)

        # Сброс трафика — отдельный endpoint
        if reset_traffic:
            # трафик хранится не в clients, а в статистике, сброс через reset
            pass

        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [payload_client]}, ensure_ascii=False)
        }
        res = await self._request("POST", f"/panel/api/inbounds/updateClient/{client_id}", json=payload)
        if isinstance(res, dict) and not res.get("success", True):
            raise XUIApiError(f"updateClient failed: {res}")

        # сброс трафика если нужно
        if reset_traffic:
            # пробуем несколько вариантов эндпоинта
            for path in [f"/panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}", f"/panel/api/inbounds/resetClientTraffic/{email}"]:
                try:
                    r = await self._request("POST", path)
                    break
                except:
                    continue
        return res

    async def reset_client_traffic(self, inbound_id: int, email: str):
        for path in [f"/panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}", f"/panel/api/inbounds/resetClientTraffic/{email}", f"/panel/api/inbounds/{inbound_id}/resetClientTraffic/{await self._email_to_uuid(inbound_id, email)}"]:
            try:
                return await self._request("POST", path)
            except Exception as e:
                last = e
        raise last

    async def _email_to_uuid(self, inbound_id: int, email: str):
        inbound = await self.get_inbound(inbound_id)
        settings = json.loads(inbound.get("settings","{}"))
        for c in settings.get("clients",[]):
            if c.get("email")==email:
                return c.get("id") or c.get("password") or email
        return email

    async def get_client_traffic(self, inbound_id: int, email: str) -> Optional[Dict]:
        """
        Трафик лежит в /panel/api/inbounds/getClientTraffics/{email} или в общем списке clientTraffics
        """
        # пробуем новый эндпоинт
        try:
            data = await self._request("GET", f"/panel/api/inbounds/getClientTraffics/{email}")
            if isinstance(data, dict) and "obj" in data:
                return data["obj"]
            return data
        except:
            pass
        # fallback — ищем в inbound clientStats
        try:
            inbound = await self.get_inbound(inbound_id)
            stats = inbound.get("clientStats", [])
            for s in stats:
                if s.get("email") == email:
                    return s
        except:
            pass
        return None

    async def list_clients(self, inbound_id: int = None) -> List[Dict]:
        inbounds = await self.get_inbounds()
        result = []
        for ib in inbounds:
            if inbound_id and ib.get("id") != inbound_id:
                continue
            settings = json.loads(ib.get("settings","{}") or "{}")
            clients = settings.get("clients", [])
            stats_map = {s.get("email"): s for s in (ib.get("clientStats") or [])}
            for c in clients:
                email = c.get("email")
                stat = stats_map.get(email, {})
                result.append({
                    "inbound_id": ib.get("id"),
                    "inbound_remark": ib.get("remark",""),
                    "protocol": ib.get("protocol",""),
                    "port": ib.get("port"),
                    "email": email,
                    "uuid": c.get("id") or c.get("password"),
                    "flow": c.get("flow",""),
                    "limitIp": c.get("limitIp"),
                    "totalGB": c.get("totalGB",0),
                    "expiryTime": c.get("expiryTime",0),
                    "enable": c.get("enable"),
                    "up": stat.get("up",0),
                    "down": stat.get("down",0),
                    "total": stat.get("up",0)+stat.get("down",0),
                    "online": stat.get("enable", False),
                })
        return result

    async def get_client(self, email: str) -> Optional[Dict]:
        clients = await self.list_clients()
        for c in clients:
            if c["email"] == email:
                return c
        return None

    def build_link(self, client: Dict, inbound: Dict) -> str:
        """Собирает VLESS/VMess/Trojan ссылку для импорта"""
        protocol = inbound.get("protocol","")
        stream = json.loads(inbound.get("streamSettings","{}") or "{}")
        reality = stream.get("realitySettings",{})
        # базовые параметры
        port = inbound.get("port")
        # address — берем из inbound: если указан host, иначе нужно подставить домен панели
        # Часто в 3x-ui в inbound нет домена — берем из panel url
        from urllib.parse import urlparse
        parsed = urlparse(self.base_url)
        host = parsed.hostname or "YOUR_DOMAIN"
        # Пытаемся достать домен из remark или из reality dest
        # Лучший вариант — владелец сам укажет внешний домен в панели (Inbound -> Address)
        # Но если не указан — подставляем хост панели
        # Также пробуем вытащить serverName / dest
        security = stream.get("security","")
        net = stream.get("network","tcp")
        sni = reality.get("serverName","") or stream.get("tlsSettings",{}).get("serverName","")
        pbk = reality.get("publicKey","")
        sid = reality.get("shortIds", [""])[0] if reality.get("shortIds") else ""
        spx = reality.get("spiderX","") or "/"

        email = client.get("email","")
        uuid_str = client.get("id") or client.get("password","")
        flow = client.get("flow","")

        if protocol == "vless":
            # vless://uuid@host:port?params#remark
            params = []
            params.append(f"security={security or 'reality'}")
            params.append(f"encryption=none")
            if flow:
                params.append(f"flow={flow}")
            params.append(f"type={net}")
            if security == "reality":
                if sni: params.append(f"sni={sni}")
                if pbk: params.append(f"pbk={pbk}")
                if sid: params.append(f"sid={sid}")
                if spx and spx != "/": params.append(f"spx={spx}")
                # fp
                fp = reality.get("settings",{}).get("fingerprint","") or stream.get("realitySettings",{}).get("fingerprint","") or "chrome"
                # Но в старых версиях fingerprint внутри realitySettings напрямую?
                # попробуем еще
                if not fp:
                    fp = "chrome"
                params.append(f"fp={fp}")
            else:
                # tls
                if sni: params.append(f"sni={sni}")
                if security == "tls":
                    params.append("fp=chrome")
            query = "&".join(params)
            remark = f"{inbound.get('remark','')} - {email}"
            return f"vless://{uuid_str}@{host}:{port}?{query}#{remark}"

        elif protocol == "vmess":
            import base64
            vmess_json = {
                "v": "2",
                "ps": f"{inbound.get('remark','')} - {email}",
                "add": host,
                "port": str(port),
                "id": uuid_str,
                "aid": "0",
                "net": net,
                "type": "none",
                "host": "",
                "path": stream.get("wsSettings",{}).get("path","") if net=="ws" else "",
                "tls": security,
                "sni": sni,
            }
            b64 = base64.b64encode(json.dumps(vmess_json).encode()).decode()
            return f"vmess://{b64}"

        elif protocol == "trojan":
            params = []
            if security in ("tls","reality"):
                params.append(f"security={security}")
                if sni: params.append(f"sni={sni}")
            query = "&".join(params)
            remark = f"{inbound.get('remark','')} - {email}"
            return f"trojan://{uuid_str}@{host}:{port}?{query}#{remark}"

        elif protocol == "shadowsocks":
            import base64
            method = client.get("method") or inbound.get("settings","")
            # пробуем достать method
            try:
                method = json.loads(inbound.get("settings","{}")).get("method","aes-256-gcm")
            except:
                method = "aes-256-gcm"
            userinfo = base64.b64encode(f"{method}:{uuid_str}".encode()).decode()
            remark = f"{inbound.get('remark','')} - {email}"
            return f"ss://{userinfo}@{host}:{port}#{remark}"

        return f"{uuid_str}@{host}:{port} ({protocol})"

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

class MultiPanelManager:
    def __init__(self, panels: List):
        from config import PanelConfig as PC
        self.clients: List[XuiClient] = []
        for p in panels:
            self.clients.append(XuiClient(p.name, p.url, p.username, p.password, p.default_inbound_id))

    def get_panel(self, name: str) -> Optional[XuiClient]:
        for c in self.clients:
            if c.name == name:
                return c
        return None

    def get_default(self) -> XuiClient:
        return self.clients[0] if self.clients else None

    async def close_all(self):
        for c in self.clients:
            await c.close()
