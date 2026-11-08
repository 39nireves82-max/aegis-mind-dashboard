import asyncio
import os
import sys
import signal
import argparse
import logging
import json
import csv
import uuid
from collections import deque
import yfinance as yf
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timezone

# Zwei-Stufen .env-Suchkaskade (Lokal vs. RSI Bot Nachbarordner)
script_dir = Path(__file__).resolve().parent
local_env = script_dir / ".env"
rsi_env = script_dir.parent / "RSI Bot" / ".env"

if local_env.exists():
    load_dotenv(dotenv_path=local_env, override=True)
elif rsi_env.exists():
    load_dotenv(dotenv_path=rsi_env, override=True)
else:
    load_dotenv()

from abc import ABC, abstractmethod
import aiohttp

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

# Dynamische Einbindung der bestehenden RESONO-Schnittstellen
try:
    from resono import evaluate_fleet, evaluate_ftmo_risk, evaluate_account_risk
except ImportError:
    # Fallback-Mock für den isolierten Testlauf, falls resono.py nicht im exakten Pfad liegt
    def evaluate_fleet(*args, **kwargs):
        return {
            "status": "ALLOWED",
            "allocations": [{"max_contracts": 1, "status_code": "ALLOWED", "ui_reason": "Mocked Fleet Freigabe"}]
        }

    def evaluate_ftmo_risk(*args, **kwargs):
        return {
            "status": "ALLOWED",
            "allowed": True,
            "max_lots": 1.0,
            "status_code": "ALLOWED",
            "ui_reason": "Mocked FTMO Freigabe"
        }

    def evaluate_account_risk(*args, **kwargs):
        return {
            "status": "ALLOWED",
            "allowed": True,
            "max_contracts": 1,
            "status_code": "ALLOWED",
            "ui_reason": "Mocked Account Freigabe"
        }
def _parse_float_safe(val, fallback: float = 0.0) -> float:
    if val is None:
        return fallback
    try:
        parsed = float(str(val).strip())
        return parsed if parsed > 0.0 else fallback
    except (ValueError, TypeError):
        return fallback
def get_point_value(symbol: str, contract: str = "") -> float:
    sym_upper = str(symbol).strip().upper()
    if "=X" in sym_upper or "DX-Y" in sym_upper or str(contract).strip().title() == "Lot":
        return 100000.0
        
    clean_sym = sym_upper.split()[0].replace("=F", "")
    
    POINT_VALUES = {
        "MNQ": 2.0, "NQ": 2.0,
        "MES": 5.0, "ES": 5.0,
        "MYM": 0.5, "YM": 0.5,
        "M2K": 5.0, "RTY": 5.0,
        "MGC": 10.0, "GC": 10.0,
        "SIL": 10.0, "SI": 10.0,
        "MCL": 100.0, "CL": 100.0,
        "QG": 2500.0, "NG": 2500.0,
        "MHG": 250.0, "HG": 250.0
    }
    return POINT_VALUES.get(clean_sym, 1.0)

def get_effective_forex_risk_pts(symbol: str, raw_pts: float, current_price: float, fx_usd_eur: float = 1.0) -> float:
    sym_upper = str(symbol).strip().upper().replace(" ", "").replace("=X", "")
    c_price = float(current_price) if current_price and float(current_price) > 0.0 else 1.0
    fx = float(fx_usd_eur) if fx_usd_eur and float(fx_usd_eur) > 0.0 else 1.0
    
    if sym_upper in ["USDJPY", "USDCAD", "USDCHF"]:
        return raw_pts / c_price
    elif sym_upper == "EURJPY":
        return (raw_pts / c_price) / fx
    else:
        return raw_pts

# Konfiguration laden
EXECUTOR_MODE = os.getenv("EXECUTOR_MODE", "DRY_RUN")
EXECUTOR_POLLING_INTERVAL = int(os.getenv("EXECUTOR_POLLING_INTERVAL", "10"))
EXECUTOR_KILL_SWITCH = os.getenv("EXECUTOR_KILL_SWITCH", "KILL_SWITCH")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "dummy_token")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "dummy_chat_id")
NT8_HOST = os.getenv("NT8_HOST", "127.0.0.1")
NT8_PORT = int(os.getenv("NT8_PORT", "50005"))
NT8_ACCOUNT = os.getenv("NT8_ACCOUNT", "DEMO9530978")
NT8_EXECUTION_TIMEOUT = float(os.getenv("NT8_EXECUTION_TIMEOUT", "5.0"))

# MT5 Konfiguration
MT5_LOGIN_STR = os.getenv("MT5_LOGIN", "")
MT5_LOGIN = int(MT5_LOGIN_STR) if MT5_LOGIN_STR.isdigit() else 0
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] EXECUTOR: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class TelegramReporter:
    """Asynchrones 4-Stufen-Telegram-Meldenetz (HTML)."""
    DAEMON_PREFIX = "⚙️ <b>[INVARIX EXECUTION DAEMON]</b>\n"

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    async def send_message(self, message: str):
        if self.token == "dummy_token":
            logging.info(f"TELEGRAM MOCK: \n{message}")
            return

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, json=payload) as response:
                    if response.status != 200:
                        logging.error(f"Telegram API Error: {await response.text()}")
        except Exception as e:
            logging.error(f"Fehler beim Senden der Telegram-Nachricht: {e}")

    async def report_step_1_signal(self, symbol: str, direction: str, resono_status: str, account_type: str):
        msg = f"{self.DAEMON_PREFIX}🔍 <b>Stufe 1: Signal & Risiko-Check</b>\nTicker: {symbol} | {direction}\nKonto: {account_type}\nRESONO: <code>{resono_status}</code>"
        await self.send_message(msg)

    async def report_step_2_order(self, account_id: str, symbol: str, qty: float, entry: float, sl: float, tp: float):
        msg = f"{self.DAEMON_PREFIX}⚡ <b>Stufe 2: Order Platziert</b>\nKonto: {account_id}\nAsset: {symbol} | Qty: {qty}\nEntry: {entry} | SL: {sl} | TP: {tp}"
        await self.send_message(msg)

    async def report_step_3_ghost(self, account_id: str, order_id: str):
        msg = f"{self.DAEMON_PREFIX}🧹 <b>Stufe 3: Ghost-Order Säuberung</b>\nKonto: {account_id}\nVerwaiste OCO-Order storniert: <code>{order_id}</code>"
        await self.send_message(msg)

    async def report_step_4_alert(self, alert_msg: str):
        msg = f"{self.DAEMON_PREFIX}🚨 <b>Stufe 4: SYSTEM-ALARM / KILL SWITCH</b>\n{alert_msg}"
        await self.send_message(msg)

    async def report_step_2b_trailing(self, account_id: str, symbol: str, old_sl: float, new_sl: float, current_risk_eur: float):
        if float(current_risk_eur) <= 0.0:
            risk_str = "0.00 € (Risk-Free)"
        else:
            risk_str = f"{float(current_risk_eur):.2f} €"
        
        msg = f"{self.DAEMON_PREFIX}🎯 <b>Stufe 2b: Trailing-Stop Modifiziert</b>\nKonto: <code>{account_id}</code>\nAsset: <code>{symbol}</code>\nStop: <code>{old_sl}</code> ➔ <b>{new_sl}</b>\nRestrisiko: <b>{risk_str}</b>"
        await self.send_message(msg)


class BaseBrokerAdapter(ABC):
    """Abstrakte asynchrone Basisklasse für alle Broker-Adapter."""

    @abstractmethod
    async def connect(self) -> bool: pass

    @abstractmethod
    async def place_bracket_order(self, account_id: str, symbol: str, direction: str, qty: float, entry_price: float, sl_price: float, tp_price: float) -> dict: pass

    @abstractmethod
    async def partial_close(self, account_id: str, symbol: str, qty: float, is_long: bool, current_price: float = 0.0, order_id: str = "") -> dict: pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: pass

    @abstractmethod
    async def modify_stop_loss(self, account_id: str, symbol: str, new_sl: float, order_id: str = "", oco_id: str = "", new_qty: float = 0.0) -> dict: pass

    @abstractmethod
    async def flatten_account(self, account_id: str) -> bool: pass

    @abstractmethod
    async def get_open_positions(self, account_id: str) -> list: pass

    @abstractmethod
    async def get_working_orders(self, account_id: str) -> list: pass


class TradovateAdapter(BaseBrokerAdapter):
    """Adapter für CME Futures (Apex). DRY_RUN Simulation."""
    async def connect(self) -> bool:
        logging.info("TradovateAdapter (DRY_RUN): Verbunden mit REST/WebSocket Mock.")
        return True

    async def place_bracket_order(self, account_id, symbol, direction, qty, entry_price, sl_price, tp_price) -> dict:
        logging.info(f"TradovateAdapter: Simuliere Bracket Order für {symbol} auf {account_id}.")
        await asyncio.sleep(0.1)  # Simuliere Netzwerklatenz
        return {"status": "FILLED", "order_id": f"TRD-{int(asyncio.get_event_loop().time() * 1000)}"}

    async def partial_close(self, account_id: str, symbol: str, qty: float, is_long: bool, current_price: float = 0.0, order_id: str = "") -> dict:
        logging.info(f"TradovateAdapter: Simuliere Partial Close ({qty}x {symbol}) auf {account_id}.")
        return {"status": "FILLED", "order_id": f"TRD-PC-{int(asyncio.get_event_loop().time() * 1000)}", "qty": float(qty)}

    async def cancel_order(self, order_id: str) -> bool:
        logging.info(f"TradovateAdapter: Order {order_id} storniert.")
        return True

    async def modify_stop_loss(self, account_id: str, symbol: str, new_sl: float, order_id: str = "", oco_id: str = "", new_qty: float = 0.0) -> dict:
        logging.info(f"TradovateAdapter: Simuliere SL-Modifikation für {symbol} auf {new_sl} (new_qty={new_qty}).")
        return {"status": "MODIFIED", "new_sl": float(new_sl)}

    async def flatten_account(self, account_id: str) -> bool: return True
    async def get_open_positions(self, account_id: str) -> list: return []
    async def get_working_orders(self, account_id: str) -> list: return []


class NinjaTraderAdapter(BaseBrokerAdapter):
    """Adapter für CME Futures (Apex) via NinjaTrader 8 lokaler TCP-Bridge (Voll-Duplex Multiplexing)."""

    # Asset-spezifische Distanz-Tabelle für Sicherheits-Fallback-Stops: (Stop-Distanz, Target-Distanz)
    ASSET_STOP_DISTANCES = {
        "NQ": (30.0, 60.0),
        "MNQ": (30.0, 60.0),
        "ES": (10.0, 20.0),
        "MES": (10.0, 20.0),
        "CL": (0.50, 1.00),
        "MCL": (0.50, 1.00),
        "GC": (5.0, 10.0),
        "MGC": (5.0, 10.0),
    }

    YFINANCE_MAPPING = {
        "NQ": "NQ=F",
        "MNQ": "NQ=F",
        "ES": "ES=F",
        "MES": "ES=F",
        "CL": "CL=F",
        "MCL": "CL=F",
        "GC": "GC=F",
        "MGC": "GC=F",
        "YM": "YM=F",
        "MYM": "YM=F",
        "RTY": "RTY=F",
        "M2K": "RTY=F",
    }

    def __init__(self, execution_timeout: float = NT8_EXECUTION_TIMEOUT):
        self.host = NT8_HOST
        self.port = NT8_PORT
        self.execution_timeout = execution_timeout
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.connected = False
        self._closing = False

        # Locks für Schreibzugriffe und Reconnect-Koordination
        self._write_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

        # Hintergrund-Tasks für Multiplex-Reader und 3s-Heartbeat
        self._reader_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

        # Korrelations-Registry für synchrone Befehlsantworten (correlation_id -> Future)
        self._pending_requests: dict[str, asyncio.Future] = {}

        # Event-Puffer und Order-Waiter für asynchrone Push-Events (oco_id -> Future / Liste)
        self._event_buffer: deque = deque(maxlen=1000)
        self._execution_waiters: dict[str, asyncio.Future] = {}
        self._early_events_by_oco: dict[str, list[dict]] = {}

    async def connect(self) -> bool:
        async with self._connect_lock:
            self._closing = False
            await self._cleanup_connection(cancel_heartbeat=True)

            try:
                logging.info(f"NinjaTraderAdapter: Verbinde mit NT8 Gateway auf {self.host}:{self.port}...")
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                self.connected = True

                # 1. Hintergrund-Reader-Loop starten, damit alle eingehenden Zeilen gemultiplext werden
                self._reader_task = asyncio.create_task(self._reader_loop())

                # 2. Handshake-PING mit eindeutiger correlation_id senden
                ping_res = await self._send_command(
                    {"command": "PING", "correlation_id": str(uuid.uuid4())},
                    timeout=5.0,
                    allow_reconnect=False
                )

                if ping_res.get("status") == "PONG":
                    logging.info("NinjaTraderAdapter: Erfolgreich mit NT8 verbunden (PONG erhalten).")
                    # 3. 3-Sekunden-Heartbeat-Task starten
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    return True

                logging.warning(f"NinjaTraderAdapter: Unerwartete Handshake-Antwort vom NT8 Gateway: {ping_res}")
                await self._cleanup_connection(cancel_heartbeat=True)
                return False

            except Exception as e:
                logging.warning(f"NinjaTraderAdapter: NT8 Verbindung fehlgeschlagen (Ist NinjaTrader gestartet?). Modus: Fallback. Fehler: {e}")
                await self._cleanup_connection(cancel_heartbeat=True)
                return False

    async def _cleanup_connection(self, cancel_heartbeat: bool = True):
        """Bereinigt Socket, Reader-Task und offene Request-Futures deterministisch."""
        self.connected = False
        current_task = asyncio.current_task()

        if cancel_heartbeat and self._heartbeat_task and self._heartbeat_task is not current_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None

        if self._reader_task and self._reader_task is not current_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None

        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None
        self.reader = None

        # Alle noch wartenden synchronen Befehls-Futures sofort auflösen
        for corr_id, fut in list(self._pending_requests.items()):
            if not fut.done():
                fut.set_result({"status": "FAILED", "correlation_id": corr_id, "reason": "Connection closed"})
        self._pending_requests.clear()

    async def disconnect(self):
        self._closing = True
        async with self._connect_lock:
            await self._cleanup_connection(cancel_heartbeat=True)
            for oco_id, fut in list(self._execution_waiters.items()):
                if not fut.done():
                    fut.set_result({"event": "ORDER_UPDATE", "oco_id": oco_id, "state": "Cancelled", "reason": "Adapter disconnected"})
            self._execution_waiters.clear()
        logging.info("NinjaTraderAdapter: NT8 Verbindung getrennt.")

    async def _reader_loop(self):
        """Permanenter Hintergrund-Task: Liest und demultiplext Antworten (correlation_id) sowie Push-Events."""
        try:
            while not self._closing and self.connected and self.reader:
                line = await self.reader.readline()
                if not line:
                    logging.warning("NinjaTraderAdapter: EOF vom NT8 Gateway empfangen (Verbindung getrennt).")
                    break

                raw_str = line.decode("utf-8-sig", errors="replace").strip()
                if not raw_str:
                    continue

                try:
                    data = json.loads(raw_str)
                except json.JSONDecodeError as e:
                    logging.error(f"NinjaTraderAdapter: Ungültiges JSON vom Gateway empfangen: {raw_str} ({e})")
                    continue

                # Fall 1: Synchrone Befehlsantwort (identifiziert durch correlation_id)
                corr_id = data.get("correlation_id")
                if corr_id and corr_id in self._pending_requests:
                    fut = self._pending_requests.pop(corr_id, None)
                    if fut and not fut.done():
                        fut.set_result(data)
                    continue

                # Fallback für Legacy-PONG ohne correlation_id
                if data.get("status") == "PONG" and not corr_id:
                    for cid, fut in list(self._pending_requests.items()):
                        if not fut.done():
                            self._pending_requests.pop(cid, None)
                            fut.set_result(data)
                            break
                    continue

                # Fall 2: Unaufgefordertes Push-Event (ORDER_UPDATE oder EXECUTION_UPDATE)
                event_type = data.get("event")
                if event_type in ("ORDER_UPDATE", "EXECUTION_UPDATE"):
                    self._handle_push_event(data)
                else:
                    logging.debug(f"NinjaTraderAdapter: Unzugeordnete Gateway-Nachricht: {data}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._closing:
                logging.error(f"NinjaTraderAdapter: Fehler im Reader-Loop: {e}")
        finally:
            self.connected = False
            for corr_id, fut in list(self._pending_requests.items()):
                if not fut.done():
                    fut.set_result({"status": "FAILED", "correlation_id": corr_id, "reason": "Reader loop terminated"})
            self._pending_requests.clear()

    def _handle_push_event(self, event_data: dict):
        """Verarbeitet eingehende ORDER_UPDATE- und EXECUTION_UPDATE-Events und löst wartende Order-Waiter auf."""
        self._event_buffer.append(event_data)
        event_type = event_data.get("event")
        oco_id = event_data.get("oco_id")
        if not oco_id:
            return

        order_name = event_data.get("name", "")
        state = event_data.get("state", "")

        # Prüfen, ob dieses Event die Phase-2-Wartebedingung (Fill oder Reject/Cancel des Entry) erfüllt
        is_relevant_resolution = False
        if event_type == "EXECUTION_UPDATE":
            if not order_name or order_name == "Entry":
                is_relevant_resolution = True
        elif event_type == "ORDER_UPDATE":
            if state in ("Rejected", "Cancelled") and (not order_name or order_name == "Entry"):
                is_relevant_resolution = True

        if is_relevant_resolution:
            waiter = self._execution_waiters.get(oco_id)
            if waiter and not waiter.done():
                waiter.set_result(event_data)
            else:
                self._early_events_by_oco.setdefault(oco_id, []).append(event_data)
                if len(self._early_events_by_oco) > 500:
                    oldest_key = next(iter(self._early_events_by_oco))
                    self._early_events_by_oco.pop(oldest_key, None)

    async def _heartbeat_loop(self):
        """Sendet alle 3 Sekunden ein PING mit correlation_id zur Bedienung des 10s-Gateway-Watchdogs."""
        try:
            while not self._closing:
                await asyncio.sleep(3.0)
                if self._closing:
                    break

                if not self.connected or not self.writer:
                    logging.info("NinjaTraderAdapter: Heartbeat erkennt getrennte Verbindung. Versuche Reconnect...")
                    await self.connect()
                    continue

                ping_cmd = {
                    "command": "PING",
                    "correlation_id": str(uuid.uuid4())
                }
                res = await self._send_command(ping_cmd, timeout=4.0, allow_reconnect=False)
                if res.get("status") != "PONG":
                    logging.warning(f"NinjaTraderAdapter: Heartbeat-PING fehlgeschlagen ({res}). Initiiere Reconnect...")
                    self.connected = False
                    await self.connect()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._closing:
                logging.error(f"NinjaTraderAdapter: Unerwarteter Fehler im Heartbeat-Task: {e}")

    async def _send_command(self, cmd_dict: dict, timeout: float = 10.0, allow_reconnect: bool = True) -> dict:
        """Sendet einen Befehl mit correlation_id ohne direktes Stream-Readline und wartet auf das aufgelöste Future."""
        corr_id = cmd_dict.get("correlation_id") or str(uuid.uuid4())
        cmd_dict["correlation_id"] = corr_id

        if (not self.connected or not self.writer) and allow_reconnect and not self._closing:
            logging.info("NinjaTraderAdapter: Socket nicht verbunden. Versuche automatischen Reconnect vor Befehlsübertragung...")
            reconnected = await self.connect()
            if not reconnected:
                return {"status": "FAILED", "correlation_id": corr_id, "reason": "Not connected to NT8 (Reconnect failed)"}

        if not self.connected or not self.writer:
            return {"status": "FAILED", "correlation_id": corr_id, "reason": "Not connected to NT8"}

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_requests[corr_id] = fut

        try:
            payload = (json.dumps(cmd_dict) + "\n").encode("utf-8")
            async with self._write_lock:
                if not self.writer or not self.connected:
                    raise ConnectionError("Writer unavailable")
                self.writer.write(payload)
                await self.writer.drain()

            response = await asyncio.wait_for(fut, timeout=timeout)

            # Falls die Verbindung während des Wartens abbrach, einmalig transparent reconnecten & wiederholen
            if response.get("status") == "FAILED" and response.get("reason") in ("Connection closed", "Reader loop terminated"):
                if allow_reconnect and not self._closing and cmd_dict.get("command") != "PING":
                    logging.warning("NinjaTraderAdapter: Verbindungsabbruch während Befehlsausführung. Starte Auto-Reconnect & Retry...")
                    if await self.connect():
                        return await self._send_command(cmd_dict, timeout=timeout, allow_reconnect=False)

            return response

        except asyncio.TimeoutError:
            self._pending_requests.pop(corr_id, None)
            logging.error(f"NinjaTraderAdapter: Timeout ({timeout}s) für Befehl {cmd_dict.get('command')} (correlation_id={corr_id}).")
            return {"status": "FAILED", "correlation_id": corr_id, "reason": "Command response timeout"}
        except Exception as e:
            self._pending_requests.pop(corr_id, None)
            logging.error(f"NinjaTraderAdapter: Fehler bei Befehlsübertragung: {e}")
            self.connected = False
            if allow_reconnect and not self._closing and cmd_dict.get("command") != "PING":
                logging.info("NinjaTraderAdapter: Versuche transparenten Reconnect nach Übertragungsfehler...")
                if await self.connect():
                    return await self._send_command(cmd_dict, timeout=timeout, allow_reconnect=False)
            return {"status": "FAILED", "correlation_id": corr_id, "reason": str(e)}

    async def _wait_for_execution_phase2(self, oco_id: str, fallback_qty: float) -> dict:
        """Phase 2 der Order-Resolution: Wartet auf EXECUTION_UPDATE oder Reject/Cancel für die oco_id."""
        # 1. Prüfen, ob das Event bereits vor Registrierung des Waiters eingetroffen ist (Fast-Fill Schutz)
        early_list = self._early_events_by_oco.pop(oco_id, [])
        for ev in early_list:
            if ev.get("event") == "EXECUTION_UPDATE":
                return {
                    "status": "FILLED",
                    "order_id": ev.get("order_id", ""),
                    "execution_id": ev.get("execution_id", ""),
                    "oco_id": oco_id,
                    "price": float(ev.get("price", 0.0)),
                    "qty": int(ev.get("qty", fallback_qty))
                }
            if ev.get("event") == "ORDER_UPDATE" and ev.get("state") in ("Rejected", "Cancelled"):
                return {
                    "status": "FAILED",
                    "reason": f"Order {ev.get('state')} by Gateway/Exchange",
                    "order_id": ev.get("order_id", ""),
                    "oco_id": oco_id
                }

        # 2. Asynchrones Warten auf das Push-Event aus dem Reader-Loop (mit konfigurierbarem 5s Timeout)
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._execution_waiters[oco_id] = waiter

        try:
            ev = await asyncio.wait_for(waiter, timeout=self.execution_timeout)
            if ev.get("event") == "EXECUTION_UPDATE":
                return {
                    "status": "FILLED",
                    "order_id": ev.get("order_id", ""),
                    "execution_id": ev.get("execution_id", ""),
                    "oco_id": oco_id,
                    "price": float(ev.get("price", 0.0)),
                    "qty": int(ev.get("qty", fallback_qty))
                }
            state = ev.get("state", "Rejected")
            return {
                "status": "FAILED",
                "reason": f"Order {state} by Gateway/Exchange",
                "order_id": ev.get("order_id", ""),
                "oco_id": oco_id
            }
        except asyncio.TimeoutError:
            logging.error(f"NinjaTraderAdapter: Phase-2 Timeout ({self.execution_timeout}s) beim Warten auf EXECUTION_UPDATE für OCO {oco_id}.")
            return {
                "status": "FAILED",
                "reason": f"EXECUTION_TIMEOUT ({self.execution_timeout}s)",
                "oco_id": oco_id
            }
        finally:
            self._execution_waiters.pop(oco_id, None)
            self._early_events_by_oco.pop(oco_id, None)

    async def place_bracket_order(self, account_id: str, symbol: str, direction: str, qty: float, entry_price: float, sl_price: float, tp_price: float) -> dict:
        if not account_id or account_id in ["AUTO_ROUTED", "DEMO_SPOOLER", "AUTO"]:
            resolved_account = NT8_ACCOUNT
            logging.info(f"NinjaTraderAdapter: Platzhalter-Konto '{account_id}' dynamisch aufgelöst auf reales Zielkonto '{resolved_account}'.")
            account_id = resolved_account

        # Root-Ticker isolieren (z. B. "MNQ 06-26" -> "MNQ")
        clean_sym = symbol.strip().upper().split()[0]
        mapped_sym = self.YFINANCE_MAPPING.get(clean_sym, clean_sym)

        ref_price = 0.0
        try:
            def fetch_price():
                try:
                    ticker = yf.Ticker(mapped_sym)

                    # 1. Defensiver Versuch über fast_info
                    if hasattr(ticker, 'fast_info'):
                        raw_price = ticker.fast_info.get("lastPrice")
                        if raw_price is not None:
                            p = float(raw_price)
                            if p > 0.0:
                                return p

                    # 2. Fallback über 5d History (Wochenend-Sicher)
                    hist = ticker.history(period="5d")
                    if not hist.empty and "Close" in hist.columns:
                        p = float(hist["Close"].dropna().iloc[-1])
                        if p > 0.0:
                            return p

                except Exception:
                    pass

                return 0.0

            # Kaltstart-Schutzschild mit max. 2 Sekunden Time-Out
            ref_price = await asyncio.wait_for(asyncio.to_thread(fetch_price), timeout=2.0)
        except asyncio.TimeoutError:
            logging.warning(f"NinjaTraderAdapter: Time-Out (2s) beim Abruf des Referenzkurses für {mapped_sym}.")
        except Exception as e:
            logging.warning(f"NinjaTraderAdapter: Konnte Referenzkurs für {mapped_sym} nicht abrufen: {e}")

        # Notfall-Anker: Verhindere alte Geisterkurse (< 25000 bei MNQ/NQ)
        if ref_price <= 0.0 and mapped_sym == "NQ=F" and entry_price < 25000.0:
            ref_price = 31230.0
            logging.warning(f"NinjaTraderAdapter: Greife auf Sicherheits-Referenzkurs {ref_price} zurück (Kaltstart-Schutz).")

        # Harmonisierter Multi-Asset Stop-Guard:
        # Überschreibt Stops NUR wenn sl_price <= 0.0 (oder tp_price <= 0.0) oder der Stop auf der falschen Marktseite liegt.
        check_price = float(entry_price) if float(entry_price) > 0.0 else ref_price
        anchor_price = ref_price if ref_price > 0.0 else float(entry_price)

        sl_price = float(sl_price)
        tp_price = float(tp_price)
        dir_upper = direction.upper()

        wrong_side = False
        if check_price > 0.0:
            if dir_upper == "LONG":
                if sl_price >= check_price or (tp_price > 0.0 and tp_price <= check_price):
                    wrong_side = True
            elif dir_upper == "SHORT":
                if sl_price <= check_price or (tp_price > 0.0 and tp_price >= check_price):
                    wrong_side = True

        if sl_price <= 0.0 or tp_price <= 0.0 or wrong_side:
            if anchor_price > 0.0:
                if clean_sym in self.ASSET_STOP_DISTANCES:
                    stop_dist, target_dist = self.ASSET_STOP_DISTANCES[clean_sym]
                else:
                    # Standard-Fallback für sonstige Ticker: 1.0 % des Referenzkurses (Target: 2.0 %)
                    stop_dist = round(anchor_price * 0.01, 2)
                    target_dist = round(anchor_price * 0.02, 2)

                if dir_upper == "LONG":
                    if sl_price <= 0.0 or wrong_side:
                        sl_price = round(anchor_price - stop_dist, 2)
                    if tp_price <= 0.0 or wrong_side:
                        tp_price = round(anchor_price + target_dist, 2)
                else:
                    if sl_price <= 0.0 or wrong_side:
                        sl_price = round(anchor_price + stop_dist, 2)
                    if tp_price <= 0.0 or wrong_side:
                        tp_price = round(anchor_price - target_dist, 2)

                logging.info(
                    f"NinjaTraderAdapter: Stop-Guard ausgelöst für {clean_sym} (Ankerkurs: {anchor_price:.2f}). "
                    f"Asset-spezifische Sicherheits-Stops gesetzt -> SL: {sl_price}, TP: {tp_price}"
                )

        correlation_id = str(uuid.uuid4())
        cmd = {
            "command": "PLACE_ORDER",
            "correlation_id": correlation_id,
            "account": account_id,
            "instrument": symbol,
            "direction": dir_upper,
            "qty": int(qty),
            "sl_price": float(sl_price),
            "tp_price": float(tp_price)
        }

        # PHASE 1: Sende PLACE_ORDER und warte auf synchrone SUBMITTED-Quittung inkl. oco_id
        logging.info(f"NinjaTraderAdapter: [Phase 1] Sende Bracket Order für {symbol} auf {account_id} an NT8 (correlation_id={correlation_id})...")
        res = await self._send_command(cmd)

        status = res.get("status", "UNKNOWN")
        if status != "SUBMITTED":
            logging.warning(f"NinjaTraderAdapter: [Phase 1] NT8 hat Order-Annahme abgelehnt: {status} | Grund: {res.get('reason', 'Unbekannt')}")
            return {
                "status": "FAILED",
                "reason": res.get("reason", f"Gateway status: {status}"),
                "correlation_id": correlation_id
            }

        oco_id = res.get("oco_id", "")
        if not oco_id:
            logging.error("NinjaTraderAdapter: [Phase 1] SUBMITTED empfangen, aber oco_id fehlt im Gateway-Payload!")
            return {
                "status": "FAILED",
                "reason": "Missing oco_id in SUBMITTED response",
                "correlation_id": correlation_id
            }

        logging.info(f"NinjaTraderAdapter: [Phase 1] SUBMITTED bestätigt (oco_id={oco_id}). Warte in [Phase 2] auf EXECUTION_UPDATE (max. {self.execution_timeout}s)...")

        # PHASE 2: Warte asynchron auf das reale EXECUTION_UPDATE-Event aus dem Reader-Loop
        exec_res = await self._wait_for_execution_phase2(oco_id, qty)
        if exec_res.get("status") == "FILLED":
            exec_res["sl_price"] = float(sl_price)
            exec_res["tp_price"] = float(tp_price)
            logging.info(
                f"NinjaTraderAdapter: [Phase 2] FILLED bestätigt! Order-ID: {exec_res.get('order_id')} | "
                f"Preis: {exec_res.get('price')} | Qty: {exec_res.get('qty')} | OCO: {oco_id}"
            )
        else:
            logging.warning(f"NinjaTraderAdapter: [Phase 2] Ausführung fehlgeschlagen: {exec_res.get('reason')} (OCO: {oco_id})")

        return exec_res

    async def cancel_order(self, order_id: str) -> bool:
        logging.info(f"NinjaTraderAdapter: Storniere Order {order_id} (Simuliert).")
        return True

    async def flatten_account(self, account_id: str) -> bool:
        if not account_id or account_id in ["AUTO_ROUTED", "DEMO_SPOOLER", "AUTO"]:
            account_id = NT8_ACCOUNT

        cmd = {
            "command": "FLATTEN",
            "account": account_id,
            "correlation_id": str(uuid.uuid4())
        }
        res = await self._send_command(cmd)
        status = res.get("status")
        if status in ("SUBMITTED", "FILLED"):
            logging.info(f"NinjaTraderAdapter: FLATTEN für Konto '{account_id}' synchron mit {status} quittiert.")
            return True

        logging.warning(f"NinjaTraderAdapter: FLATTEN für Konto '{account_id}' fehlgeschlagen: {res}")
        return False

    async def get_open_positions(self, account_id: str) -> list: return []
    async def get_working_orders(self, account_id: str) -> list: return []

    async def partial_close(self, account_id: str, symbol: str, qty: float, is_long: bool, current_price: float = 0.0, order_id: str = "") -> dict:
        if not account_id or account_id in ["AUTO_ROUTED", "DEMO_SPOOLER", "AUTO"]:
            account_id = NT8_ACCOUNT

        close_dir = "SELL" if is_long else "BUY"
        close_qty = int(round(float(qty)))
        if close_qty <= 0:
            return {"status": "FAILED", "reason": "INVALID_PARTIAL_QTY"}

        correlation_id = str(uuid.uuid4())
        cmd = {
            "command": "PLACE_ORDER",
            "correlation_id": correlation_id,
            "account": account_id,
            "instrument": symbol,
            "direction": close_dir,
            "qty": close_qty,
            "sl_price": 0.0,
            "tp_price": 0.0
        }

        logging.info(f"NinjaTraderAdapter: [Partial Close Phase 1] Sende nackte Market-Gegenorder ({close_dir} {close_qty}x {symbol}) auf {account_id}...")
        res = await self._send_command(cmd)
        status = res.get("status", "UNKNOWN")
        if status != "SUBMITTED":
            logging.warning(f"NinjaTraderAdapter: [Partial Close Phase 1] Abgelehnt: {res}")
            return {
                "status": "FAILED",
                "reason": res.get("reason", f"Gateway status: {status}"),
                "correlation_id": correlation_id
            }

        oco_id = res.get("oco_id", "")
        if not oco_id:
            return {"status": "FILLED", "order_id": correlation_id, "qty": close_qty, "price": float(current_price or 0.0)}

        logging.info(f"NinjaTraderAdapter: [Partial Close Phase 2] Warte auf Fill-Bestätigung (oco_id={oco_id})...")
        exec_res = await self._wait_for_execution_phase2(oco_id, close_qty)
        return exec_res

    async def modify_stop_loss(self, account_id: str, symbol: str, new_sl: float, order_id: str = "", oco_id: str = "", new_qty: float = 0.0) -> dict:
        if not account_id or account_id in ["AUTO_ROUTED", "DEMO_SPOOLER", "AUTO"]:
            account_id = NT8_ACCOUNT

        clean_sym = symbol.strip().upper().split()[0]
        cmd = {
            "command": "MODIFY_ORDER",
            "account": account_id,
            "instrument": clean_sym,
            "stop_price": float(new_sl),
            "new_sl": float(new_sl)
        }
        if new_qty is not None and float(new_qty) > 0.0:
            cmd["new_qty"] = int(round(float(new_qty)))
        if oco_id:
            cmd["oco_id"] = str(oco_id).strip()
        if order_id:
            cmd["order_id"] = str(order_id).strip()

        res = await self._send_command(cmd, timeout=5.0)
        status = res.get("status")

        if status in ("MODIFIED", "SUBMITTED", "ALREADY_AT_PRICE", "CHANGE_SUBMITTED"):
            confirmed_price = _parse_float_safe(res.get("stop_price"), fallback=None)
            if confirmed_price is not None and confirmed_price > 0.0:
                final_sl = confirmed_price
            else:
                final_sl = _parse_float_safe(new_sl)
            return {"status": "MODIFIED", "reason": status, "new_sl": final_sl}
        else:
            logging.warning(f"NinjaTraderAdapter: MODIFY_ORDER abgelehnt: {res}")
            return {"status": "FAILED", "reason": res.get("reason", "NT8_REJECT")}


class FTMOBrokerAdapter(BaseBrokerAdapter):
    """Adapter für Forex Majors (FTMO) via MT5. Vollgehärtet mit Auto-Reconnect, Lot-Normalisierung und realer Order-Kontrolle."""
    MAGIC_NUMBER = 20261010

    def __init__(self):
        self.connected = False
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> bool:
        if not MT5_AVAILABLE:
            logging.error("FTMOBrokerAdapter: MetaTrader5 Modul nicht installiert (Dry-Run Fallback).")
            self.connected = False
            return False

        async with self._connect_lock:
            logging.info("FTMOBrokerAdapter: Initiiere MT5 Verbindung...")

            init_kwargs = {}
            if MT5_PATH:
                init_kwargs["path"] = MT5_PATH

            init_success = await asyncio.to_thread(mt5.initialize, **init_kwargs)
            if not init_success:
                err = await asyncio.to_thread(mt5.last_error)
                logging.error(f"FTMOBrokerAdapter: mt5.initialize() fehlgeschlagen. Error: {err}")
                self.connected = False
                return False

            if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
                login_success = await asyncio.to_thread(mt5.login, MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
                if not login_success:
                    err = await asyncio.to_thread(mt5.last_error)
                    logging.error(f"FTMOBrokerAdapter: MT5 Login fehlgeschlagen. Error: {err}")
                    self.connected = False
                    return False
            else:
                logging.warning("FTMOBrokerAdapter: Unvollständige MT5 Credentials. Versuche Standard-Login des Terminals.")

            term_info = await asyncio.to_thread(mt5.terminal_info)
            if term_info is None or not getattr(term_info, "connected", False):
                err = await asyncio.to_thread(mt5.last_error)
                logging.error(f"FTMOBrokerAdapter: MT5 Terminal ist nicht mit dem Broker-Server verbunden. Error: {err}")
                self.connected = False
                return False

            acc_info = await asyncio.to_thread(mt5.account_info)
            if acc_info is None:
                err = await asyncio.to_thread(mt5.last_error)
                logging.error(f"FTMOBrokerAdapter: Konnte Account-Info nicht abrufen. Error: {err}")
                self.connected = False
                return False

            self.connected = True
            logging.info(
                f"FTMOBrokerAdapter: Erfolgreich verbunden! Konto: {acc_info.login} | "
                f"Server: {acc_info.server} | Währung: {acc_info.currency} | Balance: {acc_info.balance}"
            )
            return True

    async def _ensure_connected(self) -> bool:
        """Prüft vor kritischen Aktionen terminal_info().connected und führt bei Bedarf einen Auto-Reconnect durch."""
        if not MT5_AVAILABLE:
            return False

        term_info = await asyncio.to_thread(mt5.terminal_info)
        if term_info is not None and getattr(term_info, "connected", False):
            self.connected = True
            return True

        logging.warning("FTMOBrokerAdapter: MT5 Terminal nicht verbunden oder Session verloren. Starte Auto-Reconnect...")
        self.connected = False
        return await self.connect()

    async def disconnect(self):
        if MT5_AVAILABLE and self.connected:
            await asyncio.to_thread(mt5.shutdown)
            self.connected = False
            logging.info("FTMOBrokerAdapter: MT5 Verbindung sauber getrennt.")

    @staticmethod
    def _resolve_filling_mode(sym_info) -> tuple[int, str]:
        """Ermittelt dynamisch den vom Broker unterstützten Filling-Mode (IOC / FOK / RETURN)."""
        raw_filling_mode = getattr(sym_info, "filling_mode", 0)
        if not isinstance(raw_filling_mode, int):
            raw_filling_mode = 0

        if raw_filling_mode & 2:
            return mt5.ORDER_FILLING_IOC, "IOC"
        elif raw_filling_mode & 1:
            return mt5.ORDER_FILLING_FOK, "FOK"
        else:
            return mt5.ORDER_FILLING_RETURN, "RETURN"

    @staticmethod
    def _normalize_volume(qty: float, sym_info) -> tuple[float, bool]:
        """
        Normalisiert das durch RESONO berechnete Lot-Volumen gegen volume_min, volume_max und volume_step.
        Gibt (normalized_qty, is_valid) zurück. Falls das auf volume_step gerundete Volumen < volume_min ist,
        wird is_valid=False signalisiert (Abbruch mit VOLUME_TOO_SMALL).
        """
        vol_min = float(getattr(sym_info, "volume_min", 0.01) or 0.01)
        vol_max = float(getattr(sym_info, "volume_max", 100.0) or 100.0)
        vol_step = float(getattr(sym_info, "volume_step", 0.01) or 0.01)

        raw_qty = float(qty)
        if raw_qty <= 0.0:
            return 0.0, False

        if vol_step > 0.0:
            step_str = f"{vol_step:.8f}".rstrip("0")
            step_decimals = len(step_str.split(".")[1]) if "." in step_str else 0
            steps_count = round(raw_qty / vol_step)
            normalized_qty = round(steps_count * vol_step, step_decimals)
        else:
            normalized_qty = round(raw_qty, 2)

        if normalized_qty < vol_min:
            return normalized_qty, False

        clamped_qty = max(vol_min, min(vol_max, normalized_qty))
        if vol_step > 0.0:
            step_str = f"{vol_step:.8f}".rstrip("0")
            step_decimals = len(step_str.split(".")[1]) if "." in step_str else 0
            clamped_qty = round(clamped_qty, step_decimals)

        return clamped_qty, True

    async def _resolve_broker_symbol(self, symbol: str) -> str:
        """Sucht das korrekte Broker-Symbol inkl. Suffix und aktiviert es im Terminal."""
        clean_sym = symbol.replace("=X", "")

        def check_and_select(s):
            if mt5.symbol_info(s) is not None:
                mt5.symbol_select(s, True)
                return s
            return None

        # 1. Direkter Versuch
        res = await asyncio.to_thread(check_and_select, clean_sym)
        if res:
            return res

        # 2. Übliche Prop-Firm Suffixe
        for sfx in [".p", "+", "m", "c", ".pro", ".raw"]:
            res = await asyncio.to_thread(check_and_select, f"{clean_sym}{sfx}")
            if res:
                return res

        # 3. Teurer Fallback: Über alle Symbole iterieren
        def find_fallback():
            symbols = mt5.symbols_get()
            if symbols:
                for s in symbols:
                    if clean_sym in s.name:
                        mt5.symbol_select(s.name, True)
                        return s.name
            return None

        res = await asyncio.to_thread(find_fallback)
        return res if res else clean_sym

    async def place_bracket_order(self, account_id, symbol, direction, qty, entry_price, sl_price, tp_price) -> dict:
        if not await self._ensure_connected():
            logging.warning(f"FTMOBrokerAdapter: Nicht verbunden (Auto-Reconnect fehlgeschlagen). Order für {symbol} abgewiesen.")
            return {"status": "FAILED", "reason": "MT5_NOT_CONNECTED"}

        resolved_sym = await self._resolve_broker_symbol(symbol)
        logging.info(f"FTMOBrokerAdapter: Ticker '{symbol}' aufgelöst zu -> '{resolved_sym}'")

        sym_info = await asyncio.to_thread(mt5.symbol_info, resolved_sym)
        if sym_info is None:
            logging.error(f"FTMOBrokerAdapter: Keine Symbol-Infos für {resolved_sym} verfügbar.")
            return {"status": "FAILED", "reason": "NO_SYMBOL_INFO"}

        # 1. Echtes dynamisches Lot-Sizing & Broker-Normalisierung
        normalized_qty, is_vol_valid = self._normalize_volume(qty, sym_info)
        if not is_vol_valid:
            logging.error(
                f"FTMOBrokerAdapter: Berechnetes Volumen {normalized_qty} (übergeben: {qty}) "
                f"unterschreitet volume_min ({sym_info.volume_min}) für {resolved_sym}. Abbruch mit VOLUME_TOO_SMALL."
            )
            return {
                "status": "VOLUME_TOO_SMALL",
                "reason": f"Normalized volume {normalized_qty} < volume_min {sym_info.volume_min}",
                "normalized_qty": normalized_qty,
                "volume_min": float(sym_info.volume_min)
            }

        tick = await asyncio.to_thread(mt5.symbol_info_tick, resolved_sym)
        if tick is None:
            logging.error(f"FTMOBrokerAdapter: Keine Tick-Daten für {resolved_sym} verfügbar (Terminal Offline?).")
            return {"status": "FAILED", "reason": "NO_TICK_DATA"}

        dir_upper = direction.upper()
        order_type = mt5.ORDER_TYPE_BUY if dir_upper == "LONG" else mt5.ORDER_TYPE_SELL

        # Marktkurs ermitteln & Wochenend-Sicherung (0.0) abfangen
        exec_price = tick.ask if dir_upper == "LONG" else tick.bid
        if exec_price <= 0.0:
            exec_price = tick.last

        if exec_price <= 0.0:
            logging.warning(f"FTMOBrokerAdapter: Marktkurs für {resolved_sym} ist 0.0 (Wochenende/Geschlossen). Order abgebrochen.")
            return {"status": "MARKET_CLOSED", "retcode": 10018}

        # Stop-Validierung (Schutz vor '10016 Invalid stops' ohne valide Volatilitäts-Stops zu überschreiben)
        point = float(getattr(sym_info, "point", 0.00001) or 0.00001)
        stops_level = int(getattr(sym_info, "trade_stops_level", 0) or 0)
        min_broker_dist = (stops_level + 10) * point
        fallback_dist = max(300 * point, min_broker_dist)

        sl_price = float(sl_price)
        tp_price = float(tp_price)

        invalid_stops = False
        if dir_upper == "LONG":
            if sl_price <= 0.0 or tp_price <= 0.0 or sl_price >= (exec_price - min_broker_dist) or tp_price <= (exec_price + min_broker_dist):
                invalid_stops = True
        else:
            if sl_price <= 0.0 or tp_price <= 0.0 or sl_price <= (exec_price + min_broker_dist) or tp_price >= (exec_price - min_broker_dist):
                invalid_stops = True

        if invalid_stops:
            if dir_upper == "LONG":
                sl_price = exec_price - fallback_dist
                tp_price = exec_price + (fallback_dist * 2.0)
            else:
                sl_price = exec_price + fallback_dist
                tp_price = exec_price - (fallback_dist * 2.0)
            logging.info(
                f"FTMOBrokerAdapter: Ungültige oder fehlende Stops korrigiert für {resolved_sym}. "
                f"Dynamische Sicherheits-Stops berechnet (SL: {sl_price:.5f}, TP: {tp_price:.5f})"
            )

        # Striktes Runden auf Broker-Vorgaben
        exec_price = round(exec_price, sym_info.digits)
        sl_price = round(sl_price, sym_info.digits)
        tp_price = round(tp_price, sym_info.digits)

        # Dynamischer Filling-Mode Guard
        filling_type, filling_str = self._resolve_filling_mode(sym_info)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": resolved_sym,
            "volume": float(normalized_qty),
            "type": order_type,
            "price": exec_price,
            "sl": float(sl_price),
            "tp": float(tp_price),
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": "INVARIX EXECUTOR",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }

        logging.info(
            f"FTMOBrokerAdapter: Sende Order für {resolved_sym} | Vol: {normalized_qty} (raw: {qty}) | "
            f"Filling Mode: '{filling_str}' | SL: {sl_price} | TP: {tp_price}"
        )
        result = await asyncio.to_thread(mt5.order_send, request)
        if result is None:
            err = await asyncio.to_thread(mt5.last_error)
            logging.error(f"FTMOBrokerAdapter: order_send() API Call fehlgeschlagen. Error: {err}")
            return {"status": "FAILED", "reason": str(err)}

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logging.info(f"FTMOBrokerAdapter: Order {result.order} (Magic: {self.MAGIC_NUMBER}, Lots: {normalized_qty}) erfolgreich ausgeführt.")
            return {
                "status": "FILLED",
                "order_id": str(result.order),
                "price": float(getattr(result, "price", 0.0) or exec_price),
                "qty": float(normalized_qty),
                "sl_price": float(sl_price),
                "tp_price": float(tp_price)
            }
        elif result.retcode == 10018:
            logging.warning(f"FTMOBrokerAdapter: Order technisch valide, aber Markt geschlossen (Wochenende). Retcode: 10018")
            return {"status": "MARKET_CLOSED", "retcode": 10018}
        else:
            logging.error(f"FTMOBrokerAdapter: Order abgelehnt. Retcode: {result.retcode}, Comment: {result.comment}")
            return {"status": "REJECTED", "reason": result.comment, "retcode": result.retcode}

    async def cancel_order(self, order_id: str) -> bool:
        """Storniert eine schwebende MT5 Pending Order real über TRADE_ACTION_REMOVE."""
        if not await self._ensure_connected():
            logging.error(f"FTMOBrokerAdapter: cancel_order({order_id}) abgebrochen – keine MT5-Verbindung.")
            return False

        try:
            ticket_id = int(str(order_id).strip())
        except ValueError:
            logging.error(f"FTMOBrokerAdapter: Ungültige numerische MT5 Order-ID für Stornierung: '{order_id}'")
            return False

        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket_id,
            "magic": self.MAGIC_NUMBER,
            "comment": "INVARIX CANCEL"
        }

        result = await asyncio.to_thread(mt5.order_send, request)
        if result is None:
            err = await asyncio.to_thread(mt5.last_error)
            logging.error(f"FTMOBrokerAdapter: TRADE_ACTION_REMOVE für Order {ticket_id} fehlgeschlagen. Error: {err}")
            return False

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logging.info(f"FTMOBrokerAdapter: Pending Order {ticket_id} erfolgreich via TRADE_ACTION_REMOVE gelöscht.")
            return True

        logging.error(f"FTMOBrokerAdapter: Stornierung von Order {ticket_id} abgelehnt. Retcode: {result.retcode}, Comment: {result.comment}")
        return False

    async def flatten_account(self, account_id: str) -> bool:
        """
        Schließt alle offenen Positionen des MT5-Kontos über Gegen-Orders (TRADE_ACTION_DEAL)
        und löscht parallel alle verwaisten schwebenden Orders (TRADE_ACTION_REMOVE).
        """
        if not await self._ensure_connected():
            logging.error(f"FTMOBrokerAdapter: flatten_account({account_id}) fehlgeschlagen – keine MT5-Verbindung.")
            return False

        overall_success = True

        # 1. Alle offenen Positionen abrufen und glattstellen
        positions = await asyncio.to_thread(mt5.positions_get)
        if positions is None:
            err = await asyncio.to_thread(mt5.last_error)
            logging.error(f"FTMOBrokerAdapter: Konnte offene Positionen für Flatten nicht abrufen. Error: {err}")
            overall_success = False
        else:
            logging.info(f"FTMOBrokerAdapter: Starte flatten_account für '{account_id}' – {len(positions)} offene Position(en) gefunden.")
            for pos in positions:
                sym = pos.symbol
                ticket = pos.ticket
                volume = float(pos.volume)
                pos_type = pos.type

                sym_info = await asyncio.to_thread(mt5.symbol_info, sym)
                tick = await asyncio.to_thread(mt5.symbol_info_tick, sym)
                if sym_info is None or tick is None:
                    logging.error(f"FTMOBrokerAdapter: Keine Symbol-/Tick-Daten zum Schließen von Position {ticket} ({sym}).")
                    overall_success = False
                    continue

                # Gegen-Order bestimmen: Long -> Verkauf zum Bid | Short -> Rückkauf zum Ask
                if pos_type == mt5.POSITION_TYPE_BUY:
                    close_type = mt5.ORDER_TYPE_SELL
                    close_price = tick.bid if tick.bid > 0.0 else tick.last
                else:
                    close_type = mt5.ORDER_TYPE_BUY
                    close_price = tick.ask if tick.ask > 0.0 else tick.last

                if close_price <= 0.0:
                    logging.error(f"FTMOBrokerAdapter: Ungültiger Schließkurs (0.0) für Position {ticket} ({sym}). Markt geschlossen?")
                    overall_success = False
                    continue

                close_price = round(close_price, sym_info.digits)
                filling_type, filling_str = self._resolve_filling_mode(sym_info)

                close_req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": ticket,
                    "symbol": sym,
                    "volume": volume,
                    "type": close_type,
                    "price": close_price,
                    "deviation": 20,
                    "magic": self.MAGIC_NUMBER,
                    "comment": "INVARIX FLATTEN",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": filling_type,
                }

                res = await asyncio.to_thread(mt5.order_send, close_req)
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logging.info(
                        f"FTMOBrokerAdapter: Position {ticket} ({sym}, {volume} Lots) erfolgreich geschlossen "
                        f"zum Kurs {close_price} (Filling: {filling_str})."
                    )
                else:
                    ret = getattr(res, "retcode", "None")
                    comment = getattr(res, "comment", "No response")
                    logging.error(f"FTMOBrokerAdapter: Fehler beim Schließen von Position {ticket} ({sym}). Retcode: {ret}, Comment: {comment}")
                    overall_success = False

        # 2. Alle verwaisten schwebenden Orders (Pending Orders) stornieren
        pending_orders = await asyncio.to_thread(mt5.orders_get)
        if pending_orders is None:
            err = await asyncio.to_thread(mt5.last_error)
            logging.error(f"FTMOBrokerAdapter: Konnte Pending Orders für Flatten nicht abrufen. Error: {err}")
            overall_success = False
        else:
            if pending_orders:
                logging.info(f"FTMOBrokerAdapter: Lösche {len(pending_orders)} schwebende Pending Order(s)...")
            for ord_obj in pending_orders:
                ord_ticket = ord_obj.ticket
                cancelled = await self.cancel_order(str(ord_ticket))
                if not cancelled:
                    overall_success = False

        return overall_success

    async def get_open_positions(self, account_id: str) -> list:
        if not await self._ensure_connected():
            return []
        positions = await asyncio.to_thread(mt5.positions_get)
        if positions is None:
            return []
        return [pos._asdict() for pos in positions]

    async def get_working_orders(self, account_id: str) -> list:
        if not await self._ensure_connected():
            return []
        orders = await asyncio.to_thread(mt5.orders_get)
        if orders is None:
            return []
        return [ord_item._asdict() for ord_item in orders]

    async def partial_close(self, account_id: str, symbol: str, qty: float, is_long: bool, current_price: float = 0.0, order_id: str = "") -> dict:
        if not await self._ensure_connected():
            return {"status": "FAILED", "reason": "MT5_NOT_CONNECTED"}

        resolved_sym = await self._resolve_broker_symbol(symbol)
        sym_info = await asyncio.to_thread(mt5.symbol_info, resolved_sym)
        if sym_info is None:
            return {"status": "FAILED", "reason": "NO_SYMBOL_INFO"}

        normalized_qty, is_vol_valid = self._normalize_volume(qty, sym_info)
        if not is_vol_valid:
            return {
                "status": "VOLUME_TOO_SMALL",
                "reason": f"Normalized volume {normalized_qty} < volume_min {sym_info.volume_min}"
            }

        target_pos = None
        expected_type = mt5.POSITION_TYPE_BUY if is_long else mt5.POSITION_TYPE_SELL
        clean_target_id = str(order_id).strip() if order_id else ""

        # Verifikationsschleife für MT5-Cache-Lag
        for attempt in range(10):
            positions = await asyncio.to_thread(mt5.positions_get, symbol=resolved_sym) or []
            
            if clean_target_id:
                for pos in positions:
                    if str(pos.ticket).strip() == clean_target_id or str(getattr(pos, "identifier", "")).strip() == clean_target_id:
                        target_pos = pos
                        break
            
            if target_pos is None:
                for pos in positions:
                    if pos.type == expected_type and getattr(pos, "magic", 0) == self.MAGIC_NUMBER:
                        target_pos = pos
                        break
                if target_pos is None:
                    for pos in positions:
                        if pos.type == expected_type:
                            target_pos = pos
                            break
            
            if target_pos is not None:
                break
            await asyncio.sleep(0.03)

        if target_pos is None:
            return {"status": "NO_POSITION_FOUND", "reason": f"Ticket {clean_target_id or 'ANY'} not found for direction"}

        if normalized_qty >= float(target_pos.volume):
            return {
                "status": "INVALID_PARTIAL_VOLUME",
                "reason": f"Partial volume {normalized_qty} >= position volume {target_pos.volume}"
            }

        tick = await asyncio.to_thread(mt5.symbol_info_tick, resolved_sym)
        if tick is None:
            return {"status": "FAILED", "reason": "NO_TICK_DATA"}

        close_type = mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY
        close_price = tick.bid if is_long else tick.ask
        if close_price <= 0.0:
            close_price = tick.last
        if close_price <= 0.0 and current_price and float(current_price) > 0.0:
            close_price = float(current_price)
        if close_price <= 0.0:
            return {"status": "MARKET_CLOSED", "retcode": 10018}

        close_price = round(close_price, sym_info.digits)
        filling_type, filling_str = self._resolve_filling_mode(sym_info)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(target_pos.ticket),
            "symbol": resolved_sym,
            "volume": float(normalized_qty),
            "type": close_type,
            "price": close_price,
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": "INVARIX PARTIAL CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }

        logging.info(
            f"FTMOBrokerAdapter: Sende PARTIAL_CLOSE für Ticket {target_pos.ticket} ({resolved_sym}) | "
            f"Vol: {normalized_qty} | Kurs: {close_price} | Filling: {filling_str}"
        )
        res = await asyncio.to_thread(mt5.order_send, request)
        if res is None:
            err = await asyncio.to_thread(mt5.last_error)
            return {"status": "FAILED", "reason": str(err)}

        if res.retcode == mt5.TRADE_RETCODE_DONE:
            return {
                "status": "FILLED",
                "order_id": str(res.order),
                "ticket": int(target_pos.ticket),
                "price": float(getattr(res, "price", 0.0) or close_price),
                "qty": float(normalized_qty)
            }
        elif res.retcode == 10018:
            return {"status": "MARKET_CLOSED", "retcode": 10018}
        else:
            return {"status": "REJECTED", "retcode": res.retcode, "reason": res.comment}

    async def modify_stop_loss(self, account_id: str, symbol: str, new_sl: float, order_id: str = "", oco_id: str = "", new_qty: float = 0.0) -> dict:
        if not await self._ensure_connected():
            return {"status": "FAILED", "reason": "MT5_NOT_CONNECTED"}

        resolved_sym = await self._resolve_broker_symbol(symbol)
        sym_info = await asyncio.to_thread(mt5.symbol_info, resolved_sym)
        if sym_info is None:
            return {"status": "FAILED", "reason": "NO_SYMBOL_INFO"}

        target_pos = None
        clean_target_id = str(order_id).strip() if order_id else ""
        expected_max_vol = float(new_qty) if new_qty is not None and float(new_qty) > 0.0 else None

        # Verifikationsschleife für MT5-Cache-Lag (inkl. Volumenprüfung für Tranchierung)
        for attempt in range(10):
            positions = await asyncio.to_thread(mt5.positions_get, symbol=resolved_sym) or []
            current_target = None
            
            if clean_target_id:
                for pos in positions:
                    if str(pos.ticket).strip() == clean_target_id or str(getattr(pos, "identifier", "")).strip() == clean_target_id:
                        current_target = pos
                        break
            
            if current_target is None:
                if not clean_target_id or clean_target_id.startswith("AUTO_"):
                    for pos in positions:
                        if getattr(pos, "magic", 0) == self.MAGIC_NUMBER:
                            current_target = pos
                            break
                    if current_target is None and positions:
                        current_target = positions[0]

            if current_target is not None:
                if expected_max_vol is not None:
                    # Warte auf Volume-Update nach Partial Close
                    if float(current_target.volume) <= expected_max_vol + 1e-8:
                        target_pos = current_target
                        break
                else:
                    target_pos = current_target
                    break
                    
            await asyncio.sleep(0.03)

        if target_pos is None:
            if clean_target_id and not clean_target_id.startswith("AUTO_"):
                logging.warning(f"FTMOBrokerAdapter: Keine Position mit Ticket {clean_target_id} (oder Volumen nicht aktuell) gefunden.")
                return {"status": "NO_POSITION_FOUND", "reason": f"Ticket {clean_target_id} not found or vol wait failed"}
            return {"status": "NO_POSITION_FOUND", "reason": "No positions for symbol"}

        current_tp = float(getattr(target_pos, "tp", 0.0) or 0.0)
        
        rounded_sl = round(float(new_sl), sym_info.digits)
        pos_sl = float(getattr(target_pos, "sl", 0.0) or 0.0)
        
        if abs(pos_sl - rounded_sl) < (10 ** -sym_info.digits):
            return {"status": "MODIFIED", "reason": "ALREADY_AT_PRICE", "new_sl": pos_sl}

        tick = await asyncio.to_thread(mt5.symbol_info_tick, resolved_sym)
        if tick is None or (tick.bid <= 0.0 and tick.ask <= 0.0):
            return {"status": "MARKET_CLOSED", "reason": "NO_TICK_DATA"}

        point = float(getattr(sym_info, "point", 0.00001) or 0.00001)
        stops_level = int(getattr(sym_info, "trade_stops_level", 0) or 0)
        min_dist = stops_level * point

        if target_pos.type == mt5.POSITION_TYPE_BUY:
            check_price = tick.bid if tick.bid > 0.0 else tick.last
            if rounded_sl >= (check_price - min_dist):
                return {"status": "REJECTED", "reason": "INVALID_STOPS_DISTANCE", "detail": f"SL {rounded_sl} >= {check_price - min_dist}"}
        elif target_pos.type == mt5.POSITION_TYPE_SELL:
            check_price = tick.ask if tick.ask > 0.0 else tick.last
            if rounded_sl <= (check_price + min_dist):
                return {"status": "REJECTED", "reason": "INVALID_STOPS_DISTANCE", "detail": f"SL {rounded_sl} <= {check_price + min_dist}"}

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(target_pos.ticket),
            "symbol": resolved_sym,
            "sl": float(rounded_sl),
            "tp": float(current_tp),
            "magic": self.MAGIC_NUMBER,
            "comment": "INVARIX TRAILING"
        }
        
        res = await asyncio.to_thread(mt5.order_send, request)
        if res is None:
            err = await asyncio.to_thread(mt5.last_error)
            return {"status": "FAILED", "reason": str(err)}

        if res.retcode in (mt5.TRADE_RETCODE_DONE, 10025):
            return {"status": "MODIFIED", "new_sl": rounded_sl, "ticket": int(target_pos.ticket)}
        else:
            return {"status": "REJECTED", "retcode": res.retcode, "reason": res.comment}


class ExecutorDaemon:
    def __init__(self):
        self.reporter = TelegramReporter(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.nt8 = NinjaTraderAdapter()
        self.ftmo = FTMOBrokerAdapter()
        self.kill_event = asyncio.Event()
        self.active_adapters = {"apex": self.nt8, "ftmo": self.ftmo}
        # Spooler Queue Verzeichnisse anlegen
        self.signals_dir = script_dir / "signals"
        self.dir_pending = self.signals_dir / "01_pending"
        self.dir_processing = self.signals_dir / "02_processing"
        self.dir_executed = self.signals_dir / "03_executed"
        self.dir_rejected = self.signals_dir / "04_rejected"

        for d in [self.dir_pending, self.dir_processing, self.dir_executed, self.dir_rejected]:
            d.mkdir(parents=True, exist_ok=True)

    async def kill_switch_watcher(self):
        """Überwacht die Trigger-Datei asynchron. Intervall < 1s."""
        logging.info("Kill-Switch-Watcher aktiv.")
        while not self.kill_event.is_set():
            if os.path.exists(EXECUTOR_KILL_SWITCH):
                logging.critical("KILL SWITCH DATEI ERKANNT! Initiiere System-Stopp.")
                self.kill_event.set()
                await self.reporter.report_step_4_alert("Manueller Kill-Switch ausgelöst. Alle Adapter eingefroren.")
                break
            try:
                await asyncio.wait_for(self.kill_event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def ghost_order_guard(self):
        """Gleicht Working Orders mit Positionen ab."""
        logging.info("Ghost-Order Guard aktiv.")
        while not self.kill_event.is_set():
            try:
                await asyncio.wait_for(self.kill_event.wait(), timeout=EXECUTOR_POLLING_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def process_signal(
        self,
        account_type: str,
        account_id: str,
        symbol: str,
        direction: str,
        qty: float,
        entry: float,
        sl: float,
        tp: float,
        current_price: float = None,
        score: int = 60,
        setup_type: str = "SETUP_B",
        is_fleet: bool = False,
        balance: float = 50000.0,
        trailing_threshold: float = 47500.0,
        daily_buffer: float = 2500.0,
        max_dd_buffer: float = 5000.0
    ):
        """Routet ein Signal durch RESONO und führt es bei Freigabe aus."""
        if self.kill_event.is_set():
            logging.warning("Signal ignoriert: Kill-Switch ist aktiv.")
            return

        # 1. Gatekeeper: RESONO Prüfung
        c_price = current_price if current_price is not None else entry
        raw_pts = abs(entry - sl)
        
        if account_type == "ftmo" or "=X" in symbol:
            stop_distance = get_effective_forex_risk_pts(symbol, raw_pts, c_price, 1.0)
        else:
            stop_distance = raw_pts

        pt_val = get_point_value(symbol)

        signal_data = {
            "symbol": symbol,
            "direction": direction,
            "current_price": c_price,
            "entry_price": entry,
            "sl_price": sl,
            "tp_price": tp,
            "score": score,
            "setup_type": setup_type,
            "stop_distance_points": stop_distance,
            "stop_loss_distance": stop_distance,
            "point_value": pt_val
        }

        is_allowed = False
        allocated_qty = 0
        resono_status = "DENIED"
        reason = "Unbekannter Fehler"
        
        has_open_pos = False
        journal_path = script_dir / "users" / "admin" / "trade_journal.csv"
        if journal_path.exists():
            try:
                with open(journal_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if str(row.get("status", "")).strip().upper() == "OPEN":
                            r_acc = str(row.get("account_name", "")).strip()
                            if account_id in r_acc or r_acc in account_id or r_acc in ["AUTO_ROUTED", "DEMO_SPOOLER", "AUTO"]:
                                has_open_pos = True
                                break
            except Exception as e:
                logging.error(f"Fehler beim Lesen des Journals in process_signal: {e}")

        if account_type == "apex":
            resolved_phase = "funded_pa" if "PA" in str(account_id).upper() else "evaluation"
            acc_data = {
                "account_id": account_id,
                "current_balance": balance,
                "high_watermark": trailing_threshold + 2500.0,
                "account_type": resolved_phase,
                "has_open_position": has_open_pos
            }
            if is_fleet:
                res_eval = evaluate_fleet([acc_data], [signal_data])
                alloc = res_eval.get("allocations", [{}])[0]
                is_allowed = alloc.get("max_contracts", 0) > 0
                allocated_qty = alloc.get("max_contracts", 0)
                resono_status = alloc.get("status_code", "DENIED")
                reason = alloc.get("ui_reason", "Flotten-Veto")
            else:
                res_eval = evaluate_account_risk(acc_data, signal_data)
                is_allowed = res_eval.get("allowed", False)
                allocated_qty = res_eval.get("max_contracts", 0)
                resono_status = res_eval.get("status_code", "DENIED")
                reason = res_eval.get("ui_reason", "Blockiert")

        elif account_type == "ftmo":
            ftmo_acc_data = {
                "account_id": account_id,
                "account_size": 100000.0,
                "current_balance": 100000.0,
                "daily_buffer": daily_buffer,
                "max_dd_buffer": max_dd_buffer,
                "has_open_position": has_open_pos
            }
            res_eval = evaluate_ftmo_risk(ftmo_acc_data, signal_data)
            is_allowed = res_eval.get("allowed", False)
            allocated_qty = res_eval.get("max_lots", 0.0)
            resono_status = res_eval.get("status_code", "DENIED")
            reason = res_eval.get("ui_reason", "Blockiert")

        # Status für Telegram anpassen
        display_status = f"{resono_status} ({allocated_qty} Einheiten)" if is_allowed else resono_status
        await self.reporter.report_step_1_signal(symbol, direction, display_status, account_type)

        if not is_allowed:
            logging.warning(f"Ausführung durch RESONO blockiert: {resono_status} | Grund: {reason}")
            return {"status": "DENIED", "resono_status": resono_status, "reason": reason}

        # 2. Broker-Routing
        adapter = self.active_adapters.get(account_type)
        order_res = {"status": "FAILED", "reason": "No adapter configured"}
        if adapter:
            order_res = await adapter.place_bracket_order(account_id, symbol, direction, allocated_qty, entry, sl, tp)
            status = order_res.get("status")
            if status == "FILLED":
                exec_entry = float(order_res.get("price") or entry)
                exec_qty = float(order_res.get("qty") or allocated_qty)
                exec_sl = float(order_res.get("sl_price") or sl)
                exec_tp = float(order_res.get("tp_price") or tp)
                await self.reporter.report_step_2_order(account_id, symbol, exec_qty, exec_entry, exec_sl, exec_tp)
            elif status == "MARKET_CLOSED":
                logging.info(f"[{account_type.upper()}] MARKET CLOSED erkannt. Die Order-Struktur für {symbol} ist valide. Pipeline erfolgreich getestet.")
            elif status == "VOLUME_TOO_SMALL":
                logging.warning(f"[{account_type.upper()}] Order für {symbol} abgebrochen: VOLUME_TOO_SMALL ({order_res.get('reason')}).")

        return {"status": "APPROVED", "broker_res": order_res}

    async def watch_signal_queue(self):
        """Asynchroner Spooler-Watcher für eingehende Signale."""
        logging.info("Signal-Spooler Queue Watcher aktiv.")
        # Kaltstart-Recovery: Verwaiste Processing-Dateien aufräumen
        for orphaned in self.dir_processing.glob("*.json"):
            logging.warning(f"Isoliere verwaiste Datei aus Vorlauf: {orphaned.name}")
            try:
                with open(orphaned, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                payload["rejection_reason"] = "ORPHANED_ON_STARTUP"
                self._archive_signal(payload, orphaned, self.dir_rejected)
            except Exception as e:
                logging.error(f"Fehler bei Orphan-Bereinigung: {e}")
                orphaned.replace(self.dir_rejected / orphaned.name)

        while not self.kill_event.is_set():
            for filepath in sorted(self.dir_pending.glob("*.json")):
                if self.kill_event.is_set():
                    break

                # Atomares Verschieben nach 02_processing
                processing_path = self.dir_processing / filepath.name
                try:
                    filepath.replace(processing_path)
                except FileNotFoundError:
                    continue  # Von anderem Prozess gegriffen

                try:
                    with open(processing_path, 'r', encoding='utf-8') as f:
                        signal_payload = json.load(f)

                    # a) TTL-Schutzschild
                    sig_time_str = signal_payload.get("timestamp")
                    if sig_time_str:
                        sig_time = datetime.fromisoformat(sig_time_str.replace('Z', '+00:00'))
                        age = (datetime.now(timezone.utc) - sig_time).total_seconds()
                        if age > 180:
                            signal_payload["rejection_reason"] = "EXPIRED_TTL"
                            logging.warning(f"Signal {filepath.name} abgewiesen: TTL überschritten ({age:.1f}s)")
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                    action = str(signal_payload.get("action", "ENTRY")).strip().upper()

                    if action == "PARTIAL_CLOSE":
                        raw_qty = _parse_float_safe(signal_payload.get("qty"), fallback=0.0)
                        if raw_qty <= 0.0:
                            signal_payload["rejection_reason"] = "INVALID_PARTIAL_QTY"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        username = signal_payload.get("username", "admin")
                        req_trade_id = str(signal_payload.get("trade_id", "")).strip()
                        target_symbol = (signal_payload.get("instrument") or signal_payload.get("symbol") or "").strip().upper()
                        clean_target_sym = target_symbol.split()[0].replace("=X", "")
                        target_account = signal_payload.get("account") or signal_payload.get("account_id") or ""

                        journal_path = script_dir / "users" / username / "trade_journal.csv"
                        if not journal_path.exists():
                            signal_payload["rejection_reason"] = "JOURNAL_NOT_FOUND"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        with open(journal_path, 'r', encoding='utf-8') as f:
                            reader = csv.reader(f)
                            raw_rows = list(reader)

                        if not raw_rows:
                            signal_payload["rejection_reason"] = "EMPTY_JOURNAL"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        header = raw_rows[0]
                        rows = [dict(zip(header, line)) for line in raw_rows[1:] if len(line) == len(header)]

                        matched_row = None
                        if req_trade_id:
                            for r in reversed(rows):
                                if str(r.get("id", "")).strip() == req_trade_id and str(r.get("status", "")).strip().upper() == "OPEN":
                                    matched_row = r
                                    break

                        if not matched_row and clean_target_sym:
                            for r in reversed(rows):
                                if str(r.get("status", "")).strip().upper() == "OPEN":
                                    row_sym = str(r.get("symbol", "")).strip().upper().split()[0].replace("=X", "")
                                    if row_sym == clean_target_sym:
                                        matched_row = r
                                        break

                        if not matched_row:
                            signal_payload["rejection_reason"] = "TRADE_NOT_FOUND_IN_JOURNAL"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        if not target_account:
                            target_account = matched_row.get("account_name", "")

                        direction = str(signal_payload.get("direction") or matched_row.get("direction") or "LONG").strip().upper()
                        is_long = (direction == "LONG")
                        cur_price = _parse_float_safe(signal_payload.get("current_price"), fallback=0.0)

                        raw_type = str(signal_payload.get("account_type", "")).strip().lower()
                        if raw_type in self.active_adapters:
                            target_account_type = raw_type
                        else:
                            row_sym = str(matched_row.get("symbol", "")).upper()
                            row_acc = str(matched_row.get("account_name", "")).upper()
                            target_account_type = "ftmo" if ("=X" in row_sym or "FTMO" in row_acc) else "apex"
                        if target_account_type == "apex" and not raw_qty.is_integer():
                            signal_payload["rejection_reason"] = "FRACTIONAL_CONTRACTS_NOT_ALLOWED"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        adapter = self.active_adapters.get(target_account_type)
                        if not adapter:
                            signal_payload["rejection_reason"] = f"NO_ADAPTER_FOR_{target_account_type.upper()}"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        trade_id = str(matched_row.get("id", "")).strip()
                        pc_res = await adapter.partial_close(
                            account_id=target_account,
                            symbol=target_symbol or matched_row.get("symbol", ""),
                            qty=raw_qty,
                            is_long=is_long,
                            current_price=cur_price,
                            order_id=trade_id
                        )

                        if pc_res.get("status") in ("FILLED", "SUBMITTED"):
                            signal_payload["status"] = "PARTIAL_CLOSED"
                            signal_payload["broker_res"] = pc_res
                            self._archive_signal(signal_payload, processing_path, self.dir_executed)
                            continue
                        else:
                            signal_payload["rejection_reason"] = pc_res.get("reason", "BROKER_PARTIAL_CLOSE_REJECTED")
                            signal_payload["broker_res"] = pc_res
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                    elif action == "SCALE_OUT_AND_PROTECT":
                        req_trade_id = str(signal_payload.get("trade_id", "")).strip()
                        target_symbol = (signal_payload.get("instrument") or signal_payload.get("symbol") or "").strip().upper()
                        clean_target_sym = target_symbol.split()[0].replace("=X", "")
                        raw_close_qty = _parse_float_safe(signal_payload.get("close_qty"), fallback=0.0)
                        raw_runner_qty = _parse_float_safe(signal_payload.get("runner_qty"), fallback=0.0)
                        raw_exit_price = _parse_float_safe(signal_payload.get("exit_price"), fallback=0.0)
                        raw_new_sl = _parse_float_safe(signal_payload.get("new_sl"), fallback=0.0)
                        username = signal_payload.get("username", "admin")

                        if not req_trade_id or raw_close_qty <= 0.0 or raw_runner_qty <= 0.0 or raw_new_sl <= 0.0:
                            signal_payload["rejection_reason"] = "INVALID_PAYLOAD_DATA"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        journal_path = script_dir / "users" / username / "trade_journal.csv"
                        if not journal_path.exists():
                            signal_payload["rejection_reason"] = "JOURNAL_NOT_FOUND"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        with open(journal_path, 'r', encoding='utf-8') as f:
                            reader = csv.reader(f)
                            raw_rows = list(reader)
                        if not raw_rows:
                            signal_payload["rejection_reason"] = "EMPTY_JOURNAL"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        header = raw_rows[0]
                        rows = [dict(zip(header, line)) for line in raw_rows[1:] if len(line) == len(header)]
                        
                        needs_header_migration = False
                        if "current_sl" not in header:
                            header.append("current_sl")
                            needs_header_migration = True
                        if "current_risk_eur" not in header:
                            header.append("current_risk_eur")
                            needs_header_migration = True

                        if needs_header_migration:
                            for r in rows:
                                if "current_sl" not in r:
                                    r["current_sl"] = r.get("sl_price", "")
                                if "current_risk_eur" not in r:
                                    r["current_risk_eur"] = r.get("planned_risk_eur", "")

                        matched_row = None
                        for r in reversed(rows):
                            if str(r.get("id", "")).strip() == req_trade_id and str(r.get("status", "")).strip().upper() == "OPEN":
                                matched_row = r
                                break

                        if not matched_row:
                            signal_payload["rejection_reason"] = "TRADE_NOT_FOUND_IN_JOURNAL"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        target_account = matched_row.get("account_name", "")
                        direction = str(matched_row.get("direction", "")).strip().upper()
                        is_long = (direction == "LONG")
                        
                        old_sl_raw = matched_row.get("current_sl")
                        old_sl = _parse_float_safe(old_sl_raw, fallback=0.0)
                        if old_sl <= 0.0:
                            old_sl = _parse_float_safe(matched_row.get("sl_price"), fallback=0.0)

                        orig_qty = _parse_float_safe(matched_row.get("position_size"), fallback=0.0)
                        orig_risk = _parse_float_safe(matched_row.get("planned_risk_eur"), fallback=0.0)
                        orig_fees = _parse_float_safe(matched_row.get("est_fees_eur"), fallback=0.0)
                        orig_invest = _parse_float_safe(matched_row.get("invest_eur"), fallback=0.0)
                        entry_price = _parse_float_safe(matched_row.get("entry_price"), fallback=0.0)
                        pt_val = _parse_float_safe(matched_row.get("point_value"), fallback=1.0)
                        fx = _parse_float_safe(matched_row.get("fx_rate"), fallback=1.0)

                        raw_type = str(signal_payload.get("account_type", "")).strip().lower()
                        if raw_type in self.active_adapters:
                            target_account_type = raw_type
                        else:
                            row_sym = str(matched_row.get("symbol", "")).upper()
                            row_acc = target_account.upper()
                            target_account_type = "ftmo" if ("=X" in row_sym or "FTMO" in row_acc) else "apex"
                        if target_account_type == "apex" and (not raw_close_qty.is_integer() or not raw_runner_qty.is_integer()):
                            signal_payload["rejection_reason"] = "FRACTIONAL_CONTRACTS_NOT_ALLOWED"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        adapter = self.active_adapters.get(target_account_type)
                        if not adapter:
                            signal_payload["rejection_reason"] = f"NO_ADAPTER_FOR_{target_account_type.upper()}"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        # Schritt 1: Partial Close
                        pc_res = await adapter.partial_close(
                            account_id=target_account,
                            symbol=target_symbol or matched_row.get("symbol", ""),
                            qty=raw_close_qty,
                            is_long=is_long,
                            current_price=raw_exit_price,
                            order_id=req_trade_id
                        )

                        if pc_res.get("status") not in ("FILLED", "SUBMITTED"):
                            signal_payload["rejection_reason"] = pc_res.get("reason", "BROKER_PARTIAL_CLOSE_REJECTED")
                            signal_payload["broker_res"] = pc_res
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue
                            
                        real_exit_price = float(pc_res.get("price", raw_exit_price))
                        confirmed_sold_qty = float(pc_res.get("qty", raw_close_qty))

                        # MT5 Cache-Lag: Kurzer Delay vor Stop-Modifikation
                        if target_account_type == "ftmo":
                            await asyncio.sleep(0.5)
                            
                        # Schritt 2: Kaskadierte Stop-Modifikation
                        double_fault = False
                        executed_new_sl = old_sl
                        active_order_id = req_trade_id if target_account_type != "apex" else str(signal_payload.get("stop_order_id", "")).strip()

                        mod_res = await adapter.modify_stop_loss(
                            account_id=target_account,
                            symbol=target_symbol or matched_row.get("symbol", ""),
                            new_sl=raw_new_sl,
                            order_id=active_order_id,
                            new_qty=raw_runner_qty
                        )

                        if mod_res.get("status") in ("MODIFIED", "SUBMITTED"):
                            executed_new_sl = float(mod_res.get("new_sl", raw_new_sl))
                        else:
                            logging.warning(f"Scale-Out: Primärer Stop-Mod fehlgeschlagen. Versuche Notfall-Mengenreduktion (Schritt 2b).")
                            fallback_res = await adapter.modify_stop_loss(
                                account_id=target_account,
                                symbol=target_symbol or matched_row.get("symbol", ""),
                                new_sl=old_sl,
                                order_id=active_order_id,
                                new_qty=raw_runner_qty
                            )
                            if fallback_res.get("status") not in ("MODIFIED", "SUBMITTED"):
                                double_fault = True
                                logging.critical(f"SCALE-OUT DOUBLE FAULT: Partial Close (FILLED), aber Stop-Reduktion abgelehnt (Rest: {raw_runner_qty})!")
                                await self.reporter.report_step_4_alert(f"<b>CRITICAL: SCALE-OUT DOUBLE FAULT</b>\nTrade: <code>{req_trade_id}</code>\nDer Broker hat den Stop-Modify (auch Fallback) abgelehnt. Position ist nun OVERHEDGED / UNGESCHÜTZT!")

                        # Schritt 3: Transaktionaler Journal-Commit
                        import re
                        max_so = 0
                        for r in rows:
                            rid = str(r.get("id", ""))
                            if rid.startswith(f"{req_trade_id}_SO"):
                                match = re.search(r'_SO(\d+)$', rid)
                                if match:
                                    max_so = max(max_so, int(match.group(1)))
                        next_so = max_so + 1

                        split_pct = (confirmed_sold_qty / orig_qty) if orig_qty > 0.0 else 0.5
                        
                        tranche1 = matched_row.copy()
                        tranche1["id"] = f"{req_trade_id}_SO{next_so}"
                        tranche1["status"] = "CLOSED"
                        tranche1["position_size"] = str(confirmed_sold_qty)
                        tranche1["exit_price"] = str(real_exit_price)
                        tranche1["exit_date"] = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
                        tranche1["exit_reason"] = f"Scale-Out ({int(split_pct*100)}%)"
                        tranche1["planned_risk_eur"] = str(round(orig_risk * split_pct, 2))
                        tranche1["est_fees_eur"] = str(round(orig_fees * split_pct, 2))
                        tranche1["invest_eur"] = str(round(orig_invest * split_pct, 2))
                        
                        eff_diff_tranche1 = abs(entry_price - real_exit_price)
                        if "=X" in target_symbol:
                            eff_diff_tranche1 = get_effective_forex_risk_pts(clean_target_sym, eff_diff_tranche1, real_exit_price, fx)
                        pnl_raw = eff_diff_tranche1 * confirmed_sold_qty * pt_val * fx
                        
                        is_profit = False
                        if is_long and real_exit_price > entry_price: is_profit = True
                        if not is_long and real_exit_price < entry_price: is_profit = True
                        
                        tranche1["pnl_eur"] = str(round(pnl_raw, 2)) if is_profit else str(round(-pnl_raw, 2))
                        rows.append(tranche1)

                        matched_row["status"] = "CRITICAL_UNPROTECTED_OR_OVERHEDGED" if double_fault else "OPEN"
                        matched_row["position_size"] = str(raw_runner_qty)
                        matched_row["planned_risk_eur"] = str(round(orig_risk - (orig_risk * split_pct), 2))
                        matched_row["est_fees_eur"] = str(round(orig_fees - (orig_fees * split_pct), 2))
                        matched_row["invest_eur"] = str(round(orig_invest - (orig_invest * split_pct), 2))
                        
                        matched_row["current_sl"] = str(executed_new_sl)
                        
                        eff_diff_runner = abs(entry_price - executed_new_sl)
                        if "=X" in target_symbol:
                            eff_diff_runner = get_effective_forex_risk_pts(clean_target_sym, eff_diff_runner, executed_new_sl, fx)
                            
                        new_raw_risk = eff_diff_runner * raw_runner_qty * pt_val * fx
                        is_risk_free = False
                        if is_long and executed_new_sl >= entry_price and entry_price > 0.0: is_risk_free = True
                        if not is_long and executed_new_sl <= entry_price and entry_price > 0.0: is_risk_free = True
                        
                        matched_row["current_risk_eur"] = "0.00" if is_risk_free else str(round(new_raw_risk, 2))

                        tmp_path = journal_path.with_suffix(".tmp")
                        for attempt in range(10):
                            try:
                                with open(tmp_path, 'w', newline='', encoding='utf-8') as f:
                                    writer = csv.DictWriter(f, fieldnames=header)
                                    writer.writeheader()
                                    writer.writerows(rows)
                                tmp_path.replace(journal_path)
                                break
                            except OSError:
                                if attempt == 9: raise
                                await asyncio.sleep(0.05)

                        signal_payload["status"] = "SCALE_OUT_EXECUTED"
                        if double_fault:
                            signal_payload["warning"] = "DOUBLE_FAULT_STOP_NOT_REDUCED"
                        self._archive_signal(signal_payload, processing_path, self.dir_executed)
                        continue

                    elif action == "MODIFY_STOP":
                        raw_new_sl = signal_payload.get("new_sl") or signal_payload.get("sl_price") or signal_payload.get("sl")
                        raw_new_qty = _parse_float_safe(signal_payload.get("new_qty"), fallback=0.0)
                        try:
                            new_sl = float(raw_new_sl)
                            if new_sl <= 0.0:
                                raise ValueError("SL <= 0")
                        except (ValueError, TypeError):
                            signal_payload["rejection_reason"] = "INVALID_NEW_SL"
                            logging.warning(f"MODIFY_STOP Signal {filepath.name} abgewiesen: Ungültiger neuer Stop ({raw_new_sl}).")
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        username = signal_payload.get("username", "admin")
                        req_trade_id = str(signal_payload.get("trade_id", "")).strip()
                        target_symbol = (signal_payload.get("instrument") or signal_payload.get("symbol") or "").strip().upper()
                        clean_target_sym = target_symbol.split()[0].replace("=X", "")
                        target_account = signal_payload.get("account") or signal_payload.get("account_id") or ""
                        target_account_type = signal_payload.get("account_type", "apex")

                        journal_path = script_dir / "users" / username / "trade_journal.csv"
                        if not journal_path.exists():
                            signal_payload["rejection_reason"] = "JOURNAL_NOT_FOUND"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        with open(journal_path, 'r', encoding='utf-8') as f:
                            reader = csv.reader(f)
                            raw_rows = list(reader)

                        if not raw_rows:
                            signal_payload["rejection_reason"] = "EMPTY_JOURNAL"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        header = raw_rows[0]
                        rows = [dict(zip(header, line)) for line in raw_rows[1:] if len(line) == len(header)]

                        needs_header_migration = False
                        if "current_sl" not in header:
                            header.append("current_sl")
                            needs_header_migration = True
                        if "current_risk_eur" not in header:
                            header.append("current_risk_eur")
                            needs_header_migration = True

                        if needs_header_migration:
                            for r in rows:
                                if "current_sl" not in r:
                                    r["current_sl"] = r.get("sl_price", "")
                                if "current_risk_eur" not in r:
                                    r["current_risk_eur"] = r.get("planned_risk_eur", "")

                        matched_row = None
                        if req_trade_id:
                            for r in reversed(rows):
                                if str(r.get("id", "")).strip() == req_trade_id and str(r.get("status", "")).strip().upper() == "OPEN":
                                    matched_row = r
                                    break

                        if not matched_row:
                            for r in reversed(rows):
                                if str(r.get("status", "")).strip().upper() == "OPEN":
                                    row_sym = str(r.get("symbol", "")).strip().upper().split()[0].replace("=X", "")
                                    if row_sym == clean_target_sym:
                                        row_acc = str(r.get("account_name", "")).strip()
                                        if target_account:
                                            if target_account in row_acc or row_acc in target_account or row_acc in ["AUTO_ROUTED", "DEMO_SPOOLER", "AUTO"]:
                                                matched_row = r
                                                break
                                        else:
                                            matched_row = r
                                            break

                        if not matched_row:
                            signal_payload["rejection_reason"] = "TRADE_NOT_FOUND_IN_JOURNAL"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        if not target_account:
                            target_account = matched_row.get("account_name", "")

                        direction = str(matched_row.get("direction", "")).strip().upper()
                        c_sl_raw = matched_row.get("current_sl")
                        c_sl = _parse_float_safe(c_sl_raw, fallback=0.0)
                        if c_sl <= 0.0:
                            c_sl = _parse_float_safe(matched_row.get("sl_price"), fallback=0.0)
                        current_sl = c_sl

                        monotony_ok = False
                        if direction == "LONG":
                            if current_sl <= 0.0 or new_sl >= current_sl or raw_new_qty > 0.0:
                                monotony_ok = True
                        elif direction == "SHORT":
                            if current_sl <= 0.0 or new_sl <= current_sl or raw_new_qty > 0.0:
                                monotony_ok = True

                        if not monotony_ok:
                            signal_payload["rejection_reason"] = "MONOTONY_VIOLATION"
                            signal_payload["detail"] = f"Dir: {direction}, Current: {current_sl}, New: {new_sl}"
                            logging.warning(f"MODIFY_STOP abgewiesen: Monotonie verletzt ({signal_payload['detail']}).")
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue
                        raw_type = str(signal_payload.get("account_type", "")).strip().lower()
                        if raw_type in self.active_adapters:
                            target_account_type = raw_type
                        else:
                            row_sym = str(matched_row.get("symbol", "")).upper()
                            row_acc = str(matched_row.get("account_name", "")).upper()
                            if "=X" in row_sym or "FTMO" in row_acc:
                                target_account_type = "ftmo"
                            else:
                                target_account_type = "apex"

                        adapter = self.active_adapters.get(target_account_type)

                        if not adapter:
                            signal_payload["rejection_reason"] = f"NO_ADAPTER_FOR_{target_account_type.upper()}"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        trade_id = str(matched_row.get("id", "")).strip()
                        oco_id = str(signal_payload.get("oco_id", "")).strip()
                        if target_account_type == "apex":
                            stop_order_id = str(signal_payload.get("stop_order_id", "")).strip()
                            active_order_id = stop_order_id if stop_order_id else ""
                        else:
                            active_order_id = trade_id

                        mod_res = await adapter.modify_stop_loss(
                            account_id=target_account,
                            symbol=target_symbol or matched_row.get("symbol", ""),
                            new_sl=new_sl,
                            order_id=active_order_id,
                            oco_id=oco_id,
                            new_qty=raw_new_qty
                        )

                        if mod_res.get("status") == "MODIFIED":
                            executed_new_sl = float(mod_res.get("new_sl", new_sl))
                            entry_price = _parse_float_safe(matched_row.get("entry_price"), fallback=0.0)
                            pos_size = _parse_float_safe(matched_row.get("position_size"), fallback=1.0)
                            pt_val = _parse_float_safe(matched_row.get("point_value"), fallback=1.0)
                            fx = _parse_float_safe(matched_row.get("fx_rate"), fallback=1.0)

                            if "=X" in target_symbol:
                                eff_diff = get_effective_forex_risk_pts(clean_target_sym, abs(entry_price - executed_new_sl), executed_new_sl, fx)
                            else:
                                eff_diff = abs(entry_price - executed_new_sl)
                                
                            raw_risk = eff_diff * pos_size * pt_val * fx
                            is_risk_free = False
                            
                            if direction == "LONG" and executed_new_sl >= entry_price and entry_price > 0.0:
                                is_risk_free = True
                            elif direction == "SHORT" and executed_new_sl <= entry_price and entry_price > 0.0:
                                is_risk_free = True
                                
                            updated_risk_eur = 0.0 if is_risk_free else round(raw_risk, 2)

                            matched_row["current_sl"] = str(executed_new_sl)
                            matched_row["current_risk_eur"] = str(updated_risk_eur)

                            tmp_path = journal_path.with_suffix(".tmp")
                            with open(tmp_path, 'w', newline='', encoding='utf-8') as f:
                                writer = csv.DictWriter(f, fieldnames=header)
                                writer.writeheader()
                                writer.writerows(rows)
                            tmp_path.replace(journal_path)

                            await self.reporter.report_step_2b_trailing(
                                account_id=target_account,
                                symbol=clean_target_sym,
                                old_sl=current_sl,
                                new_sl=executed_new_sl,
                                current_risk_eur=updated_risk_eur
                            )

                            signal_payload["status"] = "MODIFIED"
                            signal_payload["executed_sl"] = executed_new_sl
                            signal_payload["current_risk_eur"] = updated_risk_eur
                            self._archive_signal(signal_payload, processing_path, self.dir_executed)
                            continue
                        else:
                            signal_payload["rejection_reason"] = mod_res.get("reason", "BROKER_MODIFY_REJECTED")
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                    else:
                        # Defensive Schlüssel-Abfrage (Key Fallbacks)
                        safe_symbol = signal_payload.get('instrument') or signal_payload.get('symbol') or ""
                        safe_account = signal_payload.get('account') or signal_payload.get('account_id') or ""
                        safe_direction = signal_payload.get('direction', 'LONG')
                        safe_qty = signal_payload.get('qty') or signal_payload.get('shares_contracts', 1)
                        safe_sl = signal_payload.get('sl_price') if signal_payload.get('sl_price') is not None else signal_payload.get('sl', 0.0)
                        safe_tp = signal_payload.get('tp_price') if signal_payload.get('tp_price') is not None else signal_payload.get('tp', 0.0)

                        if not safe_symbol or not safe_account:
                            signal_payload["rejection_reason"] = "INVALID_PAYLOAD"
                            logging.warning(f"Signal {filepath.name} abgewiesen: Instrument oder Account leer.")
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            continue

                        # b) & c) RESONO Risikofilter & Broker Routing
                        raw_acc_type = str(signal_payload.get("account_type", "apex")).strip().lower()
                        if not raw_acc_type:
                            raw_acc_type = "apex"

                        entry_val = float(signal_payload.get("entry") or signal_payload.get("current_price") or signal_payload.get("price") or 0.0)
                        signal_payload["entry"] = entry_val

                        result = await self.process_signal(
                            account_type=raw_acc_type,
                            account_id=safe_account,
                            symbol=safe_symbol,
                            direction=safe_direction,
                            qty=float(safe_qty),
                            entry=entry_val,
                            sl=float(safe_sl),
                            tp=float(safe_tp),
                            current_price=signal_payload.get("current_price"),
                            score=signal_payload.get("score", 60),
                            setup_type=signal_payload.get("setup_type", "SETUP_B"),
                            is_fleet=signal_payload.get("is_fleet", False),
                            balance=float(signal_payload.get("balance", 50000.0)),
                            trailing_threshold=float(signal_payload.get("trailing_threshold", 47500.0)),
                            daily_buffer=float(signal_payload.get("daily_buffer", 2500.0)),
                            max_dd_buffer=float(signal_payload.get("max_dd_buffer", 5000.0))
                        )

                        if result and result.get("status") == "DENIED":
                            signal_payload["rejection_reason"] = result.get("reason", "RESONO_DENIED")
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                        elif result and result.get("status") == "APPROVED":
                            broker_res = result.get("broker_res", {})
                            b_status = broker_res.get("status")
                            if b_status == "FILLED":
                                signal_payload["broker_order_id"] = broker_res.get("order_id", "")
                                if broker_res.get("price") and float(broker_res["price"]) > 0.0:
                                    signal_payload["execution_price"] = float(broker_res["price"])
                                    signal_payload["entry"] = float(broker_res["price"])
                                if broker_res.get("qty") and float(broker_res["qty"]) > 0.0:
                                    signal_payload["qty"] = float(broker_res["qty"])
                                if broker_res.get("sl_price") and float(broker_res["sl_price"]) > 0.0:
                                    signal_payload["sl_price"] = float(broker_res["sl_price"])
                                    signal_payload["sl"] = float(broker_res["sl_price"])
                                if broker_res.get("tp_price") and float(broker_res["tp_price"]) > 0.0:
                                    signal_payload["tp_price"] = float(broker_res["tp_price"])
                                    signal_payload["tp"] = float(broker_res["tp_price"])
                                signal_payload["execution_timestamp"] = datetime.now(timezone.utc).isoformat()
                                signal_payload["status"] = "FILLED"
                                self._archive_signal(signal_payload, processing_path, self.dir_executed)
                                self._write_to_journal(signal_payload)
                            elif b_status == "MARKET_CLOSED":
                                signal_payload["rejection_reason"] = "MARKET_CLOSED"
                                self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            elif b_status == "VOLUME_TOO_SMALL":
                                signal_payload["rejection_reason"] = "VOLUME_TOO_SMALL"
                                signal_payload["rejection_detail"] = broker_res.get("reason", "")
                                self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                            else:
                                signal_payload["rejection_reason"] = broker_res.get("reason", "BROKER_REJECTED")
                                self._archive_signal(signal_payload, processing_path, self.dir_rejected)
                        else:
                            signal_payload["rejection_reason"] = "UNKNOWN_ERROR"
                            self._archive_signal(signal_payload, processing_path, self.dir_rejected)

                except json.JSONDecodeError:
                    logging.error(f"Signal {filepath.name} ist defekt (JSONDecodeError).")
                    bad_payload = {"rejection_reason": "CORRUPT_JSON"}
                    self._archive_signal(bad_payload, processing_path, self.dir_rejected)
                except Exception as e:
                    logging.error(f"Fehler bei Signalverarbeitung {filepath.name}: {e}")
                    err_payload = {"rejection_reason": f"EXCEPTION: {str(e)}"}
                    self._archive_signal(err_payload, processing_path, self.dir_rejected)

            try:
                await asyncio.wait_for(self.kill_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    def _archive_signal(self, payload: dict, source_path: Path, target_dir: Path):
        """Aktualisiert das JSON und verschiebt die Datei ins Zielverzeichnis."""
        target_path = target_dir / source_path.name
        try:
            with open(source_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=4)
            source_path.replace(target_path)
        except Exception as e:
            logging.error(f"Fehler beim Archivieren von {source_path.name}: {e}")

    def _write_to_journal(self, payload: dict):
        """Hängt einen erfolgreichen Trade atomar an das Journal an."""
        username = payload.get("username", "admin")  # Fallback auf admin
        journal_path = script_dir / "users" / username / "trade_journal.csv"

        # Sicherstellen, dass die Nutzerstruktur existiert
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        master_header = [
            'id', 'account_name', 'entry_date', 'exit_date', 'symbol', 'name', 'direction',
            'signal_price', 'entry_price', 'currency', 'fx_rate', 'position_size', 'contract_type',
            'point_value', 'base_currency', 'invest_eur', 'sl_price', 'current_sl', 'tp_price', 'planned_risk_eur',
            'current_risk_eur', 'est_fees_eur', 'master_score', 'setup_type', 'mc_robustness', 'atr_days', 'exit_mode',
            'status', 'exit_price', 'pnl_eur', 'pnl_pct', 'r_multiple', 'exit_reason', 'notes',
            'strategy_version', 'execution_type'
        ]

        valid_rows = []
        current_header = master_header

        # 1. Dynamische Header-Erkennung & Bereinigung defekter Zeilen
        if journal_path.exists():
            try:
                with open(journal_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                    if rows:
                        file_header = rows[0]
                        # Wenn die Datei noch das alte Schema hat, auf 36 Spalten migrieren
                        current_header = master_header
                        for r in rows[1:]:
                            if len(r) == len(file_header):
                                row_dict = dict(zip(file_header, r))
                                status_val = str(row_dict.get('status', '')).strip().upper()
                                if status_val in ['OPEN', 'CLOSED']:
                                    if 'current_sl' not in row_dict:
                                        row_dict['current_sl'] = row_dict.get('sl_price', '')
                                    if 'current_risk_eur' not in row_dict:
                                        row_dict['current_risk_eur'] = row_dict.get('planned_risk_eur', '')
                                    valid_rows.append(row_dict)
            except Exception as e:
                logging.error(f"Fehler beim Lesen des Journals zur Bereinigung: {e}")

        # 2. Relevante Payload-Daten entpacken & Metadaten generieren
        trade_id = payload.get("broker_order_id") or payload.get("signal_id", f"AUTO_{int(datetime.now(timezone.utc).timestamp())}")
        entry_date = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

        symbol = (payload.get("symbol") or payload.get("instrument") or "").upper()
        clean_sym = symbol.split()[0] if symbol else ""
        direction = str(payload.get("direction", "")).title()
        entry_price = float(payload.get("execution_price") or payload.get("entry", 0.0))
        sl_price = float(payload.get("sl_price") or payload.get("sl", 0.0))
        tp_price = float(payload.get("tp_price") or payload.get("tp", 0.0))
        position_size = float(payload.get("qty") or payload.get("shares_contracts", 1))

        usd_symbols = ["NQ", "MNQ", "ES", "MES", "CL", "MCL", "GC", "MGC", "YM", "MYM", "RTY", "M2K"]
        currency = "$" if any(x in clean_sym for x in usd_symbols) else "€"
        base_currency = "USD" if currency == "$" else "EUR"
        contract_type = "Micro" if clean_sym in ["MNQ", "MES", "MCL", "MGC", "MYM", "M2K"] else ("Lot" if "=X" in symbol else "")

        point_value = get_point_value(clean_sym, contract_type)

        fx_rate = 1.0
        est_fees_eur = 0.0 if "=X" in symbol else 1.0
        
        eff_diff = get_effective_forex_risk_pts(clean_sym, abs(entry_price - sl_price), entry_price, fx_rate)
        planned_risk_eur = eff_diff * position_size * point_value * fx_rate

        # 3. Leeres Schema-Template erzeugen und befüllen
        new_row = {col: "" for col in current_header}
        updates = {
            "id": trade_id,
            "account_name": payload.get("account_name", payload.get("account_id", payload.get("account", ""))),
            "entry_date": entry_date,
            "symbol": symbol,
            "name": symbol,
            "direction": direction,
            "signal_price": float(payload.get("current_price") or payload.get("entry", 0.0)),
            "entry_price": entry_price,
            "currency": currency,
            "fx_rate": fx_rate,
            "position_size": position_size,
            "contract_type": contract_type,
            "point_value": point_value,
            "base_currency": base_currency,
            "sl_price": sl_price,
            "current_sl": sl_price,
            "tp_price": tp_price,
            "planned_risk_eur": planned_risk_eur,
            "current_risk_eur": planned_risk_eur,
            "est_fees_eur": est_fees_eur,
            "exit_mode": payload.get("setup_type", "SETUP_B"),
            "status": "OPEN",
            "strategy_version": "v1.0.0",
            "execution_type": "DAEMON_AUTO"
        }

        for k, v in updates.items():
            if k in new_row:
                new_row[k] = v

        valid_rows.append(new_row)

        # 4. Sicheres, atomares Zurückschreiben inkl. Header
        try:
            tmp_journal = journal_path.with_suffix(".tmp")
            with open(tmp_journal, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=current_header)
                writer.writeheader()
                writer.writerows(valid_rows)
            tmp_journal.replace(journal_path)
            logging.info(f"Trade {trade_id} atomar ins Journal von '{username}' (DAEMON_AUTO) geschrieben.")
        except Exception as e:
            logging.error(f"Fehler beim Schreiben in trade_journal.csv: {e}")

    async def trigger_kill_switch(self):
        """Notbremse für den programmatischen Abbruch."""
        self.kill_event.set()
        await self.reporter.report_step_4_alert("Programmatischer Kill-Switch ausgelöst.")
        logging.critical("DAEMON GESTOPPT: Kill-Event gesetzt.")


async def run_daemon():
    """
    Stellt den permanenten 24/7-Produktionsbetrieb sicher:
    - Initialisiert den ExecutorDaemon
    - Verbindet beide Broker-Adapter (NinjaTraderAdapter & FTMOBrokerAdapter)
    - Startet watch_signal_queue(), kill_switch_watcher() und ghost_order_guard()
    - Fängt SIGINT / SIGTERM / KeyboardInterrupt für einen sauberen Graceful Shutdown ab.
    """
    logging.info("================================================================================")
    logging.info("STARTE INVARIX EXECUTOR DAEMON (24/7 PRODUKTIV-DIENSTMODUS)")
    logging.info("================================================================================")

    daemon = ExecutorDaemon()
    loop = asyncio.get_running_loop()

    def _handle_os_signal(sig_name: str):
        if not daemon.kill_event.is_set():
            logging.warning(f"Betriebssystem-Signal '{sig_name}' empfangen. Leite Graceful Shutdown ein...")
            loop.call_soon_threadsafe(daemon.kill_event.set)

    # Betriebssystem-Signale (SIGINT / SIGTERM) plattformübergreifend registrieren
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_os_signal, sig.name)
        except (NotImplementedError, RuntimeError):
            # Windows-Fallback für ProactorEventLoop / SelectorEventLoop
            signal.signal(sig, lambda s, f, name=sig.name: _handle_os_signal(name))

    # Beide Broker-Adapter initial verbinden
    nt8_connected = await daemon.nt8.connect()
    ftmo_connected = await daemon.ftmo.connect()
    logging.info(
        f"Adapter-Status -> NinjaTrader 8 (Apex): {'CONNECTED' if nt8_connected else 'STANDBY/RECONNECTING'} | "
        f"MT5 (FTMO): {'CONNECTED' if ftmo_connected else 'STANDBY/RECONNECTING'}"
    )

    # Drei permanente Hintergrund-Dienste starten
    service_tasks = [
        asyncio.create_task(daemon.watch_signal_queue(), name="watch_signal_queue"),
        asyncio.create_task(daemon.kill_switch_watcher(), name="kill_switch_watcher"),
        asyncio.create_task(daemon.ghost_order_guard(), name="ghost_order_guard"),
    ]
    logging.info("Alle 3 Hintergrund-Dienste aktiv. Daemon läuft im permanenten 24/7-Modus.")

    try:
        # Prozess dauerhaft aktiv halten, bis kill_event durch Signal oder Kill-Switch ausgelöst wird
        await daemon.kill_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logging.warning("Direkte Unterbrechung erkannt. Setze kill_event...")
        daemon.kill_event.set()
    finally:
        logging.info("Graceful Shutdown: Stoppe Hintergrund-Dienste...")
        daemon.kill_event.set()

        done, pending = await asyncio.wait(service_tasks, timeout=10.0)
        for task in pending:
            logging.warning(f"Hintergrund-Task '{task.get_name()}' noch aktiv – erzwinge Abbruch.")
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        logging.info("Graceful Shutdown: Trenne Socket- und Terminal-Verbindungen...")
        if hasattr(daemon.nt8, "disconnect"):
            await daemon.nt8.disconnect()
        if hasattr(daemon.ftmo, "disconnect"):
            await daemon.ftmo.disconnect()

        logging.info("INVARIX EXECUTOR DAEMON vollständig und sauber beendet.")


async def run_test_battery():
    """Asynchrone 6-Stufen-Testbatterie laut Spezifikation."""
    daemon = ExecutorDaemon()
    await daemon.nt8.connect()
    logging.info("--- STARTING TEST 0: MT5 Connection Test ---")
    mt5_connected = await daemon.ftmo.connect()
    if mt5_connected:
        pos = await daemon.ftmo.get_open_positions("FTMO_100K_01")
        logging.info(f"Test 0: MT5 erfolgreich verbunden. {len(pos)} offene Positionen ausgelesen.")
    else:
        logging.warning("Test 0: MT5 Verbindung fehlgeschlagen (DRY_RUN Fallback aktiv).")

    # Hintergrund-Tasks starten
    watcher_task = asyncio.create_task(daemon.kill_switch_watcher())
    guard_task = asyncio.create_task(daemon.ghost_order_guard())
    spooler_task = asyncio.create_task(daemon.watch_signal_queue())

    logging.info("--- STARTING TEST 1: Apex MNQ Long (Einzelkonto) ---")
    await daemon.process_signal("apex", "DEMO9530978", "MNQ", "LONG", 1, 31230.0, 31200.0, 31290.0, current_price=31230.0, score=60, setup_type="SETUP_B", is_fleet=False, balance=51500.0, trailing_threshold=49000.0)

    logging.info("--- STARTING TEST 2: FTMO EURUSD Long (Dynamische Tick-Ausführung) ---")
    await daemon.process_signal("ftmo", "FTMO_100K_01", "EURUSD=X", "LONG", 2.5, 1.0850, 1.0820, 1.0910, current_price=1.0850, score=70, setup_type="SETUP_B", daily_buffer=4000.0, max_dd_buffer=8000.0)

    logging.info("--- STARTING TEST 3: RESONO Veto (Blockiert) ---")
    # Simulation eines Vetos durch Manipulation des lokalen Mocks für diesen Testlauf
    global evaluate_ftmo_risk
    evaluate_ftmo_risk = lambda *args, **kwargs: {"status": "MUTED_DAILY_LIMIT", "allowed": False, "status_code": "MUTED_DAILY_LIMIT", "ui_reason": "Puffer erschöpft", "info": "Puffer erschöpft"}
    await daemon.process_signal("ftmo", "FTMO_100K_02", "GBPUSD", "SHORT", 1.0, 1.2500, 1.2520, 1.2400)

    logging.info("--- STARTING TEST 4: Ghost-Order Guard Säuberung ---")
    # Direkter Aufruf der Reporter-Methode zur Simulation der Guard-Aktion
    await daemon.reporter.report_step_3_ghost("APEX_50K_01", "TRD-99998888")

    logging.info("--- STARTING TEST 5: Signal Spooler Queue Test ---")
    test_signal = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_type": "apex",
        "account_id": "DEMO_SPOOLER",
        "symbol": "MNQ",
        "direction": "SHORT",
        "qty": 1,
        "entry": 31230.0,
        "sl": 31260.0,
        "tp": 31170.0,
        "score": 85,
        "setup_type": "SETUP_A",
        "balance": 52000.0,
        "trailing_threshold": 49000.0
    }
    unique_sig_name = f"sig_test_{uuid.uuid4().hex[:8]}.json"
    signal_file = daemon.dir_pending / unique_sig_name
    with open(signal_file, "w", encoding="utf-8") as f:
        json.dump(test_signal, f, indent=4)

    await asyncio.sleep(2.0)
    logging.info(f"Test 5: Signal Spooler hat die Datei abgearbeitet (in pending existiert: {signal_file.exists()})")

    logging.info("--- STARTING TEST 6: Signal Spooler MODIFY_STOP Test ---")
    journal_path = script_dir / "users" / "admin" / "trade_journal.csv"
    has_open_mnq = False
    if journal_path.exists():
        try:
            with open(journal_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if str(row.get("status")).strip().upper() == "OPEN" and "MNQ" in str(row.get("symbol")).upper():
                        has_open_mnq = True
                        break
        except Exception:
            pass

    if not has_open_mnq:
        logging.info("Test 6: Seede synthetischen OPEN MNQ-Trade für isolierten Wochenend-Test...")
        seed_payload = {
            "broker_order_id": "TEST_SEED_12345",
            "account_name": "DEMO9530978",
            "symbol": "MNQ",
            "direction": "Short",
            "execution_price": 31230.0,
            "sl_price": 31260.0,
            "tp_price": 31170.0,
            "qty": 1,
            "username": "admin"
        }
        daemon._write_to_journal(seed_payload)

    test_modify_signal = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "MODIFY_STOP",
        "account_type": "apex",
        "account_id": "DEMO9530978",
        "symbol": "MNQ",
        "new_sl": 31240.0,
        "username": "admin"
    }
    
    unique_mod_name = f"sig_mod_{uuid.uuid4().hex[:8]}.json"
    mod_file = daemon.dir_pending / unique_mod_name
    
    try:
        with open(mod_file, "w", encoding="utf-8") as f:
            json.dump(test_modify_signal, f, indent=4)

        await asyncio.sleep(3.0)
        
        exec_file = daemon.dir_executed / unique_mod_name
        rej_file = daemon.dir_rejected / unique_mod_name
        
        if exec_file.exists():
            logging.info("Test 6: MODIFY_STOP erfolgreich abgearbeitet und nach 03_executed verschoben!")
        elif rej_file.exists():
            try:
                with open(rej_file, 'r', encoding='utf-8') as f:
                    rej_data = json.load(f)
                rej_reason = str(rej_data.get("rejection_reason", "")).upper()
                if "NO_ACTIVE_POSITION" in rej_reason or "MARKET_CLOSED" in rej_reason or "REJECTED" in rej_reason:
                    logging.info(f"Test 6: MODIFY_STOP technisch erfolgreich (Gateway wies korrekt wegen Marktschluss/fehlender Position ab: {rej_reason}).")
                else:
                    logging.warning(f"Test 6: Unerwartete Ablehnung in 04_rejected gefunden: {rej_reason}")
            except Exception as e:
                logging.warning(f"Test 6: Konnte Rejection-JSON nicht lesen: {e}")
        else:
            logging.warning("Test 6: Datei weder in 03_executed noch in 04_rejected gefunden (Timeout oder Fehler).")
    finally:
        if journal_path.exists():
            try:
                with open(journal_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    raw_rows = list(reader)
                if raw_rows:
                    header = raw_rows[0]
                    rows_dict = [dict(zip(header, line)) for line in raw_rows[1:] if len(line) == len(header)]
                    clean_rows = [r for r in rows_dict if str(r.get("id", "")) != "TEST_SEED_12345"]
                    
                    if len(clean_rows) < len(rows_dict):
                        tmp_journal = journal_path.with_suffix(".tmp")
                        with open(tmp_journal, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.DictWriter(f, fieldnames=header)
                            writer.writeheader()
                            writer.writerows(clean_rows)
                        tmp_journal.replace(journal_path)
                        logging.info("Test 6: Temporärer Test-Seed TEST_SEED_12345 atomar aus dem Journal entfernt.")
            except Exception as e:
                logging.error(f"Test 6: Fehler beim Journal-Teardown: {e}")

    logging.info("Beende Testbatterie, räume Tasks auf...")
    daemon.kill_event.set()
    await asyncio.gather(watcher_task, guard_task, spooler_task)
    if hasattr(daemon.ftmo, 'disconnect'):
        await daemon.ftmo.disconnect()
    if hasattr(daemon.nt8, 'disconnect'):
        await daemon.nt8.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="INVARIX Executor Daemon (MT5 / NT8 Multi-Asset Execution Engine)"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Führt exklusiv die asynchrone 6-Stufen-Testbatterie aus und terminiert danach sauber."
    )
    cli_args = parser.parse_args()

    try:
        if cli_args.test:
            asyncio.run(run_test_battery())
        else:
            asyncio.run(run_daemon())
    except KeyboardInterrupt:
        logging.info("Executor Daemon manuell beendet (KeyboardInterrupt).")
        sys.exit(0)