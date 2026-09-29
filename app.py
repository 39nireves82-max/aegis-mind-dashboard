#region IMPORTS & CONFIG
import os
import json
import subprocess
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf
import uuid
import datetime
import backtest_engine as bte
import hashlib
import shutil
import re
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import secrets
import base64
import time
try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore
st.set_page_config(layout="wide", page_title="AEGIS MIND — Rule-Based Trading Desk")
_hdr_base = os.path.dirname(os.path.abspath(__file__))
_icon_path = os.path.join(_hdr_base, "assets", "aegis_icon.png")
if not os.path.exists(_icon_path):
    _icon_path = os.path.join(_hdr_base, "assets", "aegis_mind_logo.png")

c_hdr_icon, c_hdr_title = st.columns([0.045, 0.955], vertical_alignment="center")
with c_hdr_icon:
    if os.path.exists(_icon_path):
        st.image(_icon_path, width=48)
with c_hdr_title:
    st.markdown("<h2 style='margin: 0; padding: 0; line-height: 1.2;'>AEGIS MIND — Rule-Based Trading Desk</h2>", unsafe_allow_html=True)
st.markdown("""
<style>
    .stApp, div[data-testid="stAppViewContainer"] {
        background-color: #000000 !important;
        background-image: none !important;
    }
    div[data-testid="stHeader"] {
        background: transparent !important;
    }
    .block-container {
        padding-top: 7.2rem !important;
        padding-bottom: 0rem !important;
    }
    h1, h2, h3, .stTitle { color: #ECE8E1 !important; font-weight: 600 !important; }
    p, span, label { color: #CBD5E1 !important; }
    div[data-testid="stCaptionContainer"] { color: #94A3B8 !important; }
    div[data-baseweb="input"] > div {
        background-color: #131822 !important;
        border: 1px solid #D97706 !important;
        border-radius: 6px !important;
    }
    div[data-baseweb="input"] input {
        color: #ECE8E1 !important;
    }
    div[data-baseweb="input"]:focus-within > div {
        border: 1px solid #F59E0B !important;
        box-shadow: 0 0 8px rgba(217, 119, 6, 0.4) !important;
    }
    input[type="password"], input[autocomplete="new-password"] {
        autocomplete: new-password !important;
    }
    input::-webkit-contacts-auto-fill-button,
    input::-webkit-credentials-auto-fill-button {
        visibility: hidden !important;
        display: none !important;
        pointer-events: none !important;
    }
    div[data-testid="stSidebar"] input[type="password"]::-ms-reveal,
    div[data-testid="stSidebar"] input[type="password"]::-ms-clear {
        display: none !important;
    }
    div[data-testid="stSidebar"] input {
        autocomplete: off !important;
    }
</style>
<script>
    const inputs = window.parent.document.querySelectorAll('input');
    inputs.forEach(input => {
        input.setAttribute('autocomplete', 'new-password');
        input.setAttribute('autocorrect', 'off');
        input.setAttribute('spellcheck', 'false');
    });
</script>
""", unsafe_allow_html=True)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
BOT_DIR = os.path.join(PARENT_DIR, "RSI Bot")
CONFIG_FILE = os.path.join(BOT_DIR, "ticker_config.json")
MEGA_LISTS_DIR = os.path.join(BOT_DIR, "mega_lists")
JOURNAL_FILE = os.path.join(BOT_DIR, "trade_journal.csv")
#endregion
USERS_DIR = os.path.join(BASE_DIR, "users")
AUTH_FILE = os.path.join(USERS_DIR, "auth_credentials.json")

def hash_password(plain_text: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', plain_text.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"pbkdf2:sha256:100000${salt}${key.hex()}"

def verify_password(plain_text: str, stored_hash: str) -> tuple[bool, bool]:
    if not stored_hash:
        return False, False
    if stored_hash.startswith("pbkdf2:sha256:"):
        try:
            parts = stored_hash.split("$")
            if len(parts) == 3:
                _, salt, expected_hash = parts
                key = hashlib.pbkdf2_hmac('sha256', plain_text.encode('utf-8'), salt.encode('utf-8'), 100000)
                return secrets.compare_digest(key.hex(), expected_hash), False
        except Exception:
            return False, False
    # Abwärtskompatibilität für altes simples SHA-256 (64 Hex-Zeichen)
    legacy_hash = hashlib.sha256(plain_text.encode('utf-8')).hexdigest()
    if secrets.compare_digest(legacy_hash, stored_hash):
        return True, True  # Passwort stimmt, benötigt Re-Hash auf PBKDF2
    return False, False

def init_auth_system():
    os.makedirs(USERS_DIR, exist_ok=True)
    admin_dir = os.path.join(USERS_DIR, "admin")
    
    # 1. Credentials anlegen falls nicht existent (Standard: admin / admin)
    if not os.path.exists(AUTH_FILE):
        default_pw_hash = hash_password("admin")
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({"admin": default_pw_hash}, f, indent=4)
            
    # 2. Admin Silo anlegen und alte Daten migrieren falls vorhanden
    if not os.path.exists(admin_dir):
        os.makedirs(admin_dir, exist_ok=True)
        old_config = os.path.join(BOT_DIR, "ticker_config.json")
        if os.path.exists(old_config):
            shutil.move(old_config, os.path.join(admin_dir, "ticker_config.json"))
        old_journal = os.path.join(BOT_DIR, "trade_journal.csv")
        if os.path.exists(old_journal):
            shutil.move(old_journal, os.path.join(admin_dir, "trade_journal.csv"))
        with open(os.path.join(admin_dir, "user_profile.json"), "w", encoding="utf-8") as f:
            json.dump({"role": "admin", "telegram_chat_id": ""}, f, indent=4)

init_auth_system()

if "username" not in st.session_state:
    st.session_state.username = None
    st.session_state.role = None

if st.session_state.username is None:
    c_login, c_hero = st.columns([0.44, 0.56], gap="large", vertical_alignment="center")
    with c_login:
        env_path = os.path.join(BOT_DIR, ".env")
        load_dotenv(env_path, override=True)
        REG_CODE = os.getenv("REGISTRATION_CODE", "TRADING_ALPHA_2026")
        MASTER_RESET_KEY = os.getenv("MASTER_RESET_KEY", "").strip()
        
        st.markdown("""
        <style>
            div[data-testid="stForm"] {
                background-color: #111827ee !important;
                border: 1px solid rgba(217, 119, 6, 0.45) !important;
                border-radius: 12px !important;
                backdrop-filter: blur(10px) !important;
                -webkit-backdrop-filter: blur(10px) !important;
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.6) !important;
            }
        </style>
        """, unsafe_allow_html=True)
        
        show_pwd = st.checkbox("👁️ Passwörter anzeigen")
        pwd_type = "default" if show_pwd else "password"
        
        tab_login, tab_register, tab_forgot = st.tabs(["🔐 Login", "📝 Registrierung", "❓ Passwort vergessen"])
        
        with tab_login:
            with st.form("login_form", border=True):
                in_user_raw = st.text_input("Benutzername")
                in_pw = st.text_input("Passwort", type=pwd_type)
                if st.form_submit_button("Login", use_container_width=True):
                    in_user = str(in_user_raw).strip().lower()
                    if not re.match(r"^[a-z0-9_]{3,20}$", in_user):
                        time.sleep(1.0)
                        st.error("Falscher Benutzername oder Passwort.")
                        st.stop()
                        
                    with open(AUTH_FILE, "r", encoding="utf-8") as f:
                        creds = json.load(f)
                        
                    stored_hash = creds.get(in_user, "")
                    is_correct, needs_rehash = verify_password(in_pw, stored_hash)
                    
                    if is_correct:
                        if needs_rehash:
                            creds[in_user] = hash_password(in_pw)
                            with open(AUTH_FILE, "w", encoding="utf-8") as f:
                                json.dump(creds, f, indent=4)
                                
                        profile_path = os.path.join(USERS_DIR, in_user, "user_profile.json")
                        role = "user"
                        is_active = True
                        
                        if os.path.exists(profile_path):
                            with open(profile_path, "r", encoding="utf-8") as pf:
                                p_data = json.load(pf)
                                role = p_data.get("role", "user")
                                is_active = p_data.get("is_active", True)
                                
                        if not is_active:
                            st.error("⛔ Dein Zugang wurde temporär deaktiviert. Bitte wende dich an den Admin.")
                            st.stop()
                            
                        st.session_state.username = in_user
                        st.session_state.role = role
                        st.rerun()
                    else:
                        time.sleep(1.0)
                        st.error("Falscher Benutzername oder Passwort.")
                        
        with tab_register:
            st.markdown("### 📝 Neuen Zugang anlegen")
            with st.form("register_form", border=True):
                new_user = st.text_input("Benutzername", help="3–20 Zeichen, nur Kleinbuchstaben, Zahlen und Unterstrich")
                new_code = st.text_input("Einladungscode", type=pwd_type)
                new_pw1 = st.text_input("Neues Passwort", type=pwd_type)
                new_pw2 = st.text_input("Passwort wiederholen", type=pwd_type)
                
                if st.form_submit_button("Registrieren", use_container_width=True):
                    new_user_clean = new_user.strip().lower()
                    
                    with open(AUTH_FILE, "r", encoding="utf-8") as f:
                        creds = json.load(f)
                        
                    if not re.match(r"^[a-z0-9_]{3,20}$", new_user_clean):
                        st.error("⚠️ Ungültiger Benutzername! Bitte 3-20 Zeichen (nur a-z, 0-9, _).")
                    elif new_code != REG_CODE:
                        st.error("⚠️ Falscher Einladungscode!")
                    elif len(new_pw1) < 6:
                        st.error("⚠️ Das Passwort muss mindestens 6 Zeichen lang sein.")
                    elif new_pw1 != new_pw2:
                        st.error("⚠️ Die Passwörter stimmen nicht überein.")
                    elif new_user_clean in creds or os.path.exists(os.path.join(USERS_DIR, new_user_clean)):
                        st.error("⚠️ Dieser Benutzername existiert bereits.")
                    else:
                        creds[new_user_clean] = hash_password(new_pw1)
                        with open(AUTH_FILE, "w", encoding="utf-8") as f:
                            json.dump(creds, f, indent=4)
                            
                        user_dir = os.path.join(USERS_DIR, new_user_clean)
                        os.makedirs(user_dir, exist_ok=True)
                        
                        with open(os.path.join(user_dir, "user_profile.json"), "w", encoding="utf-8") as f:
                            json.dump({"role": "user", "telegram_chat_id": "", "tos_accepted_at": None}, f, indent=4)
                            
                        default_config = {
                            "global_settings": {"rsi_defensiv": 35.0, "rsi_aggressiv": 30.0, "rsi_sell_defensiv": 70.0, "rsi_sell_aggressiv": 80.0, "ema_trend_default": 200.0, "custom_sectors": [], "risk_mode": "Festes Euro-Risiko (€)", "account_size": 10000.0, "risk_eur": 100.0, "risk_pct": 1.0, "fixed_investment": 1000.0, "currency_view": "Duale Ansicht (Original & EUR)", "dynamic_risk_scaling": False, "fee_mode": "Keine Gebühren / Raw", "tax_jurisdiction": "DE"},
                            "pro_mode_settings": {"ema200_killer": "Aktiv", "rsi_aktiv": "Aktiv", "bollinger_aktiv": "Aktiv", "macd_aktiv": "Aktiv", "volumen_aktiv": "Aktiv", "keltner_aktiv": "Aktiv", "plateau_aktiv": "Inaktiv"},
                            "esg_blacklist": {"aktiv": False, "tickers": ["NESN.SW", "GLEN.L", "RHM.DE"]}, 
                            "tab2_settings": {"tf": "1d", "rsi_buy": 30.0, "rsi_sell": 70.0},
                            "tab3_settings": {"tf_futures": "1h", "tf_forex": "4h", "rsi_short_entry": 70.0, "rsi_long_entry": 30.0},
                            "tickers": [], 
                            "screener_tickers": [], 
                            "futures_tickers": [{"symbol": "NQ=F", "name": "Nasdaq 100"}],
                            "lab_accounts": {
                                "default": {
                                    "id": "default", "name": "Privatkonto (10k)", "account_size": 10000.0, "risk_pct": 1.0, 
                                    "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Bitpanda Fusion (0.10% / 0.05%)", 
                                    "min_score": 70, "years": 5, "tickers": [], "last_backtest": None, "tax_category": "private", "exit_profile": "private_alpha"
                                },
                                "apex": {
                                    "id": "apex", "name": "Apex 50k Demo", "account_size": 50000.0, "risk_pct": 1.0, 
                                    "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Apex / CME Futures (Insti-Rate)", 
                                    "min_score": 60, "years": 2, "tickers": ["NQ=F"], "last_backtest": None, "tax_category": "prop_firm", "exit_profile": "apex_lock"
                                },
                                "ftmo": {
                                    "id": "ftmo", "name": "FTMO 50k Demo", "account_size": 50000.0, "risk_pct": 1.0, 
                                    "compounding": "inactive", "trailing_stop": "active", "broker_profile": "FTMO / Forex (Raw Spread)", 
                                    "min_score": 60, "years": 2, "tickers": ["USDJPY=X", "GBPUSD=X"], "last_backtest": None, "tax_category": "prop_firm", "exit_profile": "ftmo_swing"
                                }
                            },
                            "scan_universes": {}
                        }
                        with open(os.path.join(user_dir, "ticker_config.json"), "w", encoding="utf-8") as f:
                            json.dump(default_config, f, indent=4)
                            
                        cols = ['id', 'account_name', 'entry_date', 'exit_date', 'symbol', 'name', 'direction', 'signal_price', 'entry_price', 'currency', 'fx_rate', 'position_size', 'contract_type', 'point_value', 'base_currency', 'invest_eur', 'sl_price', 'tp_price', 'planned_risk_eur', 'est_fees_eur', 'master_score', 'setup_type', 'mc_robustness', 'atr_days', 'exit_mode', 'status', 'exit_price', 'pnl_eur', 'pnl_pct', 'r_multiple', 'exit_reason', 'notes', 'strategy_version', 'execution_type']
                        pd.DataFrame(columns=cols).to_csv(os.path.join(user_dir, "trade_journal.csv"), index=False)
                        
                        with open(os.path.join(user_dir, "alert_state.json"), "w", encoding="utf-8") as f:
                            json.dump({}, f)
                            
                        st.session_state.username = new_user_clean
                        st.session_state.role = "user"
                        st.rerun()

        with tab_forgot:
            st.markdown("### ❓ Passwort zurücksetzen")
            st.caption("Nutze deinen hinterlegten Telegram-Kanal oder den Admin-Master-Sicherheitscode.")
            
            with st.form("forgot_pw_form", border=True):
                f_user = st.text_input("Benutzername").strip().lower()
                f_code = st.text_input("Sicherheitscode (6-stelliger Telegram-PIN ODER Admin-Master-Key)", type=pwd_type)
                f_new_pw1 = st.text_input("Neues Passwort", type=pwd_type)
                f_new_pw2 = st.text_input("Neues Passwort wiederholen", type=pwd_type)
                
                c_f1, c_f2 = st.columns(2)
                with c_f1:
                    request_tg = st.form_submit_button("📲 Telegram-PIN anfordern", use_container_width=True)
                with c_f2:
                    submit_reset = st.form_submit_button("🔑 Passwort neu setzen", use_container_width=True)
                    
            if request_tg:
                if not f_user or not re.match(r"^[a-z0-9_]{3,20}$", f_user):
                    st.error("Bitte gib einen gültigen Benutzernamen ein.")
                else:
                    pf_path = os.path.join(USERS_DIR, f_user, "user_profile.json")
                    if not os.path.exists(pf_path):
                        st.error("Benutzer nicht gefunden.")
                    else:
                        with open(pf_path, "r", encoding="utf-8") as pf:
                            p_data = json.load(pf)
                            chat_id = p_data.get("telegram_chat_id", "").strip()
                            
                        tg_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
                        
                        if not chat_id or not tg_token:
                            st.warning("⚠️ Keine Telegram Chat-ID für diesen Account hinterlegt. Bitte den Admin-Master-Key nutzen.")
                        else:
                            pin = f"{secrets.randbelow(900000) + 100000}"
                            expires_at = (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
                            p_data["reset_otp"] = hashlib.sha256(pin.encode()).hexdigest()
                            p_data["reset_otp_expires"] = expires_at
                            with open(pf_path, "w", encoding="utf-8") as pf:
                                json.dump(p_data, pf, indent=4)
                                
                            try:
                                url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                                resp = requests.post(url, json={"chat_id": chat_id, "text": f"🔐 Dein 6-stelliger Trading Dashboard Reset-Code: *{pin}*\n\n(Gültig für 10 Minuten)", "parse_mode": "Markdown"}, timeout=5)
                                if resp.status_code == 200:
                                    st.success(f"✅ Reset-PIN per Telegram an Chat-ID {chat_id} gesendet (10 Min. gültig)!")
                                else:
                                    st.error("Fehler beim Senden via Telegram.")
                            except Exception as ex:
                                st.error(f"Telegram-Fehler: {ex}")
                                
            if submit_reset:
                with open(AUTH_FILE, "r", encoding="utf-8") as f:
                    creds = json.load(f)
                    
                code_valid = False
                pf_path = os.path.join(USERS_DIR, f_user, "user_profile.json")
                p_data = {}
                
                # 1. Master-Reset-Key Prüfung (nur wenn in .env definiert und nicht leer)
                if MASTER_RESET_KEY and secrets.compare_digest(f_code, MASTER_RESET_KEY):
                    code_valid = True
                    if os.path.exists(pf_path):
                        with open(pf_path, "r", encoding="utf-8") as pf:
                            p_data = json.load(pf)
                # 2. Telegram-OTP Prüfung
                elif os.path.exists(pf_path):
                    with open(pf_path, "r", encoding="utf-8") as pf:
                        p_data = json.load(pf)
                    stored_otp_hash = p_data.get("reset_otp", "")
                    expires_str = p_data.get("reset_otp_expires", "")
                    input_otp_hash = hashlib.sha256(f_code.encode()).hexdigest()
                    
                    if stored_otp_hash and expires_str and secrets.compare_digest(input_otp_hash, stored_otp_hash):
                        try:
                            exp_dt = datetime.datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S")
                            if datetime.datetime.now() < exp_dt:
                                code_valid = True
                            else:
                                st.error("⚠️ Dieser PIN ist bereits abgelaufen (Gültigkeit: 10 Minuten). Bitte fordere einen neuen an.")
                        except Exception:
                            code_valid = False
                
                if f_user not in creds:
                    time.sleep(1.0)
                    st.error("Benutzer nicht gefunden.")
                elif not code_valid:
                    time.sleep(1.0)
                    st.error("⚠️ Ungültiger Sicherheitscode oder abgelaufener PIN.")
                elif len(f_new_pw1) < 6:
                    st.error("⚠️ Das neue Passwort muss mindestens 6 Zeichen lang sein.")
                elif f_new_pw1 != f_new_pw2:
                    st.error("⚠️ Die Passwörter stimmen nicht überein.")
                else:
                    creds[f_user] = hash_password(f_new_pw1)
                    with open(AUTH_FILE, "w", encoding="utf-8") as f:
                        json.dump(creds, f, indent=4)
                        
                    # OTP restlos tilgen
                    if os.path.exists(pf_path):
                        p_data.pop("reset_otp", None)
                        p_data.pop("reset_otp_expires", None)
                        with open(pf_path, "w", encoding="utf-8") as pf:
                            json.dump(p_data, pf, indent=4)
                            
                    st.success("✅ Passwort erfolgreich neu gesetzt! Du kannst dich jetzt im ersten Tab anmelden.")
    with c_hero:
        logo_path = os.path.join(BASE_DIR, "assets", "aegis_mind_logo.png")
        if os.path.exists(logo_path):
            _, c_img_center, _ = st.columns([0.14, 0.72, 0.14])
            with c_img_center:
                st.image(logo_path, use_container_width=True)
    st.stop()

# Helfer für dynamische Pfade auf Basis des aktuellen Nutzers
def get_user_file(filename):
    clean_user = re.sub(r'[^a-z0-9_]', '', str(st.session_state.username).strip().lower())
    target_path = os.path.abspath(os.path.join(USERS_DIR, clean_user, os.path.basename(filename)))
    users_root = os.path.abspath(USERS_DIR)
    if not target_path.startswith(users_root):
        raise PermissionError("Path traversal attempt detected!")
    return target_path

# 🔐 DATA AT-REST: VERSCHLÜSSELUNG FÜR API-KEYS
env_path = os.path.join(BOT_DIR, ".env")
load_dotenv(env_path, override=True)
ENC_KEY = os.getenv("ENCRYPTION_KEY")

if not ENC_KEY:
    fallback_key = Fernet.generate_key()
    st.error(f"🚨 **Sicherheitswarnung:** Kein `ENCRYPTION_KEY` in der `.env` Datei gefunden!\n\nBitte erstelle/öffne die `.env` Datei im Projektverzeichnis und trage folgenden Schlüssel ein (Kopieren & Speichern):\n\n`ENCRYPTION_KEY={fallback_key.decode()}`\n\nStarte die App danach neu.")
    st.stop()

fernet = Fernet(ENC_KEY.encode() if isinstance(ENC_KEY, str) else ENC_KEY)

def encrypt_secret(plain_text: str) -> str:
    if not plain_text: return ""
    try:
        # Prüfen, ob der String bereits das typische Fernet-Format hat
        if plain_text.startswith("gAAAAA"): return plain_text 
        return fernet.encrypt(plain_text.encode()).decode()
    except Exception:
        return plain_text

def decrypt_secret(cipher_text: str) -> str:
    if not cipher_text: return ""
    try:
        return fernet.decrypt(cipher_text.encode()).decode()
    except Exception:
        return cipher_text

# 🛡️ RECHTLICHE FIREWALL: TOS CHECK (OPT-IN)
user_profile_path = get_user_file("user_profile.json")
user_profile_data = {}
if os.path.exists(user_profile_path):
    with open(user_profile_path, "r", encoding="utf-8") as f:
        user_profile_data = json.load(f)

if not user_profile_data.get("tos_accepted_at"):
    st.markdown("---")
    st.markdown("## ⚖️ Nutzungsbedingungen & Haftungsausschluss")
    st.warning("⚠️ **Wichtiger rechtlicher Hinweis**\n\nDas RSI Trading Management-System AEGIS MIND dient **ausschließlich der Marktbeobachtung und dem persönlichen Risikomanagement**. Es stellt **keine Anlageberatung oder Handelsempfehlung** dar.\n\nDer Betreiber übernimmt **keinerlei Haftung** für finanzielle Verluste, Verzögerungen, API-Ausfälle oder Softwarefehler. Jeder Trade wird vom Nutzer vollständig **eigenverantwortlich** platziert.")
    tos1 = st.checkbox("Ich habe die Bedingungen gelesen und verstanden.")
    tos2 = st.checkbox("Ich handle auf mein eigenes, vollständiges Risiko.")
    tos3 = st.checkbox("Ich erkenne den vollständigen Haftungsausschluss an.")
    
    st.write("")
    if st.button("Akzeptieren & Dashboard freischalten", disabled=not (tos1 and tos2 and tos3), type="primary"):
        user_profile_data["tos_accepted_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(user_profile_path, "w", encoding="utf-8") as f:
            json.dump(user_profile_data, f, indent=4)
        st.rerun()
    st.stop()
st.info("👈 **Tipp:** Klappe die linke Seitenleiste auf (Pfeil-Symbol oben links), um zum **Risikomanagement & Broker-Order-Desk** zu gelangen.")

#region DATA MANAGEMENT
def load_trade_journal():
    cols = ['id', 'account_name', 'entry_date', 'exit_date', 'symbol', 'name', 'direction', 'signal_price', 'entry_price', 'currency', 'fx_rate', 'position_size', 'contract_type', 'point_value', 'base_currency', 'invest_eur', 'sl_price', 'tp_price', 'planned_risk_eur', 'est_fees_eur', 'master_score', 'setup_type', 'mc_robustness', 'atr_days', 'exit_mode', 'status', 'exit_price', 'pnl_eur', 'pnl_pct', 'r_multiple', 'exit_reason', 'notes', 'strategy_version', 'execution_type']
    user_journal = get_user_file("trade_journal.csv")
    if os.path.exists(user_journal):
        try:
            df = pd.read_csv(user_journal)
            for c in cols:
                if c not in df.columns:
                    if c == 'point_value': df[c] = 1.0
                    elif c == 'base_currency': df[c] = 'EUR'
                    elif c == 'contract_type': df[c] = ''
                    elif c == 'strategy_version': df[c] = 'v1.0.0'
                    elif c == 'execution_type': df[c] = 'COPILOT_MANUAL'
                    elif c == 'signal_price': df[c] = df['entry_price'] if 'entry_price' in df.columns else None
                    else: df[c] = None
                else:
                    if c == 'strategy_version': df[c] = df[c].fillna('v1.0.0')
                    elif c == 'execution_type': df[c] = df[c].fillna('COPILOT_MANUAL')
                    elif c == 'signal_price' and 'entry_price' in df.columns: df[c] = df[c].fillna(df['entry_price'])
            return df[cols]
        except Exception:
            return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_trade_journal(df):
    cols = ['id', 'account_name', 'entry_date', 'exit_date', 'symbol', 'name', 'direction', 'signal_price', 'entry_price', 'currency', 'fx_rate', 'position_size', 'contract_type', 'point_value', 'base_currency', 'invest_eur', 'sl_price', 'tp_price', 'planned_risk_eur', 'est_fees_eur', 'master_score', 'setup_type', 'mc_robustness', 'atr_days', 'exit_mode', 'status', 'exit_price', 'pnl_eur', 'pnl_pct', 'r_multiple', 'exit_reason', 'notes', 'strategy_version', 'execution_type']
    for c in cols:
        if c not in df.columns:
            if c == 'strategy_version': df[c] = 'v1.0.0'
            elif c == 'execution_type': df[c] = 'COPILOT_MANUAL'
            else: df[c] = None
    user_dir = os.path.join(USERS_DIR, st.session_state.username)
    os.makedirs(user_dir, exist_ok=True)
    df[cols].to_csv(get_user_file("trade_journal.csv"), index=False)
def push_to_github():
    try:
        subprocess.run(["git", "add", "."], cwd=BOT_DIR, check=True, capture_output=True, text=True)
        commit_res = subprocess.run(["git", "commit", "-m", "Dashboard Update"], cwd=BOT_DIR, capture_output=True, text=True)
        if "nothing to commit" in commit_res.stdout or "nothing to commit" in commit_res.stderr: return True, "ℹ️ Keine Änderungen."
        subprocess.run(["git", "push"], cwd=BOT_DIR, check=True, capture_output=True, text=True)
        return True, "✅ Erfolgreich auf GitHub aktualisiert!"
    except Exception as e: return False, f"❌ Fehler: {str(e)}"

def load_config():
    config = {
        "global_settings": {"rsi_defensiv": 35.0, "rsi_aggressiv": 30.0, "rsi_sell_defensiv": 70.0, "rsi_sell_aggressiv": 80.0, "ema_trend_default": 200.0, "custom_sectors": [], "risk_mode": "Festes Euro-Risiko (€)", "account_size": 10000.0, "risk_eur": 100.0, "risk_pct": 1.0, "fixed_investment": 1000.0, "currency_view": "Duale Ansicht (Original & EUR)", "dynamic_risk_scaling": False, "fee_mode": "Keine Gebühren / Raw", "tax_jurisdiction": "DE"},
        "pro_mode_settings": {"ema200_killer": "Aktiv", "rsi_aktiv": "Aktiv", "bollinger_aktiv": "Aktiv", "macd_aktiv": "Aktiv", "volumen_aktiv": "Aktiv", "keltner_aktiv": "Aktiv", "plateau_aktiv": "Inaktiv"},
        "esg_blacklist": {"aktiv": False, "tickers": ["NESN.SW", "GLEN.L", "RHM.DE"]}, 
        "tab2_settings": {"tf": "1d", "rsi_buy": 30.0, "rsi_sell": 70.0},
        "tab3_settings": {"tf": "1h", "rsi_short_entry": 70.0, "rsi_take_profit": 30.0},
        "tickers": [], 
        "screener_tickers": [], 
        "futures_tickers": [{"symbol": "NQ=F", "name": "Nasdaq 100"}],
        "lab_accounts": {
            "default": {
                "id": "default", "name": "Privatkonto (10k)", "account_size": 10000.0, "risk_pct": 1.0, 
                "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Bitpanda Fusion (0.10% / 0.05%)", 
                "min_score": 70, "years": 5, "tickers": [], "last_backtest": None, "tax_category": "private", "exit_profile": "private_alpha"
            },
            "apex": {
                "id": "apex", "name": "Apex 50k Demo", "account_size": 50000.0, "risk_pct": 1.0, 
                "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Apex / CME Futures (Insti-Rate)", 
                "min_score": 60, "years": 2, "tickers": ["NQ=F"], "last_backtest": None, "tax_category": "prop_firm", "exit_profile": "apex_lock"
            },
            "ftmo": {
                "id": "ftmo", "name": "FTMO 50k Demo", "account_size": 50000.0, "risk_pct": 1.0, 
                "compounding": "inactive", "trailing_stop": "active", "broker_profile": "FTMO / Forex (Raw Spread)", 
                "min_score": 60, "years": 2, "tickers": ["USDJPY=X", "GBPUSD=X"], "last_backtest": None, "tax_category": "prop_firm", "exit_profile": "ftmo_swing"
            }
        },
        "scan_universes": {}
    }
    
    user_config = get_user_file("ticker_config.json")
    if os.path.exists(user_config):
        try:
            with open(user_config, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    for k in config.keys():
                        if k in loaded and isinstance(loaded[k], dict):
                            config[k].update(loaded[k])
                        elif k in loaded:
                            config[k] = loaded[k]
        except Exception: pass

    os.makedirs(MEGA_LISTS_DIR, exist_ok=True)
    tag_universes = {}
    
    # 1. Alle JSON-Dateien im Ordner durchsuchen
    for filename in os.listdir(MEGA_LISTS_DIR):
        if filename.endswith(".json"):
            try:
                with open(os.path.join(MEGA_LISTS_DIR, filename), "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    # Abwärtskompatibilität: Dateiname als Standard-Tag
                    default_tag = filename.replace(".json", "").replace("_", " ").title()
                    
                    for ticker in file_data:
                        # Tags sammeln, falls nicht vorhanden: Standard-Tag nutzen
                        tags = ticker.get("tags", [default_tag])
                        if not tags: tags = [default_tag]
                        
                        for tag in tags:
                            if tag not in tag_universes:
                                tag_universes[tag] = {}
                            # Deduplizierung über Dictionary-Key (Symbol)
                            tag_universes[tag][ticker["symbol"]] = {
                                "symbol": ticker["symbol"], 
                                "name": ticker.get("name", ticker["symbol"])
                            }
            except Exception: 
                pass 

    # 2. Gesammelte Tag-Universen in die globale Config übernehmen
    config["scan_universes"] = {}
    for tag, tickers_dict in tag_universes.items():
        config["scan_universes"][tag] = {
            "is_premium": False,
            "tickers": list(tickers_dict.values())
        }
    return config

def save_config(config):
    user_dir = os.path.join(USERS_DIR, st.session_state.username)
    os.makedirs(user_dir, exist_ok=True)
    with open(get_user_file("ticker_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

if "config" not in st.session_state: 
    st.session_state.config = load_config()
def get_currency_symbol(ticker):
    sym = str(ticker).upper()
    if sym.endswith(".SW"): return "CHF"
    elif sym.endswith(".L"): return "£"
    elif sym.endswith(".DE") or sym.endswith(".F") or sym.endswith(".MU") or sym.endswith(".AS"): return "€"
    elif "-" in sym: return "USD" # Kryptowährungen
    elif sym.endswith("=X") and len(sym) >= 5: return sym[-5:-2] # e.g. EURUSD=X -> USD
    elif sym.endswith("=F"): return "$"
    else: return "$"

POINT_VALUES = {
    "MNQ": 2.0, "NQ=F": 2.0,
    "MES": 5.0, "ES=F": 5.0,
    "MYM": 0.5, "YM=F": 0.5,
    "M2K": 5.0, "RTY=F": 5.0,
    "MGC": 10.0, "GC=F": 10.0,
    "SIL": 10.0, "SI=F": 10.0,
    "MCL": 10.0, "CL=F": 10.0,
    "QG": 2500.0, "NG=F": 2500.0,
    "MHG": 250.0, "HG=F": 250.0,
    "Lot": 100000.0
}

def get_point_value(symbol, contract=""):
    if contract in POINT_VALUES: return POINT_VALUES[contract]
    if symbol in POINT_VALUES: return POINT_VALUES[symbol]
    return 1.0    
#endregion
#region CALC CORE
def is_market_open_mez(symbol, category_hint=""):
    sym_u = str(symbol).upper().strip()
    cat_u = str(category_hint).upper()
    
    # 1. Krypto: 24/7 geöffnet
    if any(ext in sym_u for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]) or "KRYPTO" in cat_u:
        return True
        
    # Lokale deutsche Zeit ermitteln (unabhängig von der Server-Zeitzone)
    try:
        berlin_tz = zoneinfo.ZoneInfo("Europe/Berlin")
        now_dt = datetime.datetime.now(berlin_tz)
    except Exception:
        now_dt = datetime.datetime.now()
        
    wd = now_dt.weekday()  # 0 = Montag ... 4 = Freitag, 5 = Samstag, 6 = Sonntag
    hr = now_dt.hour
    
    # 2. Forex Majors: Geschlossen Fr 23:00 bis So 23:00 Uhr MEZ
    if any(ext in sym_u for ext in ["=X", "DX-Y"]) or "FOREX" in cat_u:
        if (wd == 4 and hr >= 23) or (wd == 5) or (wd == 6 and hr < 23):
            return False
        return True
        
    # 3. CME Futures / Rohstoffe: Geschlossen Fr 23:00 bis So 24:00 Uhr MEZ sowie täglich 23:00 bis 00:00 Uhr MEZ (Maintenance)
    if "=F" in sym_u or any(x in cat_u for x in ["FUTURES", "ROHSTOFFE"]):
        # Freitag ab 23 Uhr zu
        if wd == 4 and hr >= 23:
            return False
        # Samstag ganztägig zu
        if wd == 5:
            return False
        # Sonntag ganztägig bis Mitternacht zu (Öffnung Montag 00:00 Uhr MEZ)
        if wd == 6:
            return False
        # Tägliche 60-Minuten-Wartungspause von 23:00 bis 00:00 Uhr MEZ (Mo-Do)
        if hr == 23:
            return False
        return True
        
    # 4. Aktien / ETFs: Geschlossen Sa/So sowie werktags vor 09:00 Uhr bzw. ab 22:00 Uhr MEZ
    if wd in [5, 6] or hr < 9 or hr >= 22:
        return False
        
    return True

@st.cache_data(ttl=3600, show_spinner=False)
def get_fx_rate(from_curr, to_curr="EUR"):
    if from_curr == "€" or from_curr == "EUR": return 1.0
    
    curr_map = {"$": "USD", "CHF": "CHF", "£": "GBP"}
    from_iso = curr_map.get(from_curr, from_curr)
    
    if from_iso == to_curr: return 1.0
    
    try:
        pair = f"{from_iso}{to_curr}=X"
        df = yf.download(pair, period="1d", interval="1m", progress=False)
        if not df.empty and "Close" in df.columns:
            val = df["Close"].iloc[-1]
            if isinstance(val, pd.Series): val = val.iloc[-1]
            return float(val)
    except:
        pass
        
    # Robust Fallback bei API-Ausfall
    fallbacks = {"USD": 0.92, "CHF": 1.05, "GBP": 1.17}
    return fallbacks.get(from_iso, 1.0)

@st.cache_data(ttl=3600)
def get_economic_calendar():
    today = datetime.date.today()
    
    # 1. NFP (Non-Farm Payrolls): Meistens der erste Freitag im Monat
    is_first_friday = today.weekday() == 4 and 1 <= today.day <= 7
    if is_first_friday:
        return True, "US Non-Farm Payrolls (NFP)", "14:30 Uhr", "Gefahr unkontrollierter Slippage bei Futures & Indizes. Mindestens 10 Minuten vor und nach dem Event Handelsstopp empfohlen!"
        
    # 2. Statische Fallbacks für bekannte Cluster (Mitte des Monats = oft CPI / FOMC)
    if today.day in [10, 11, 12] and today.weekday() in [1, 2, 3]: 
        return True, "US CPI Inflationsdaten", "14:30 Uhr", "Gefahr extremer Volatilität. Handelsstopp empfohlen!"
    if today.day in [16, 17, 18] and today.weekday() == 2:
        return True, "FOMC Zinsentscheid (Fed)", "20:00 Uhr", "Märkte spielen verrückt. Absolutes Trading-Verbot 15 Min davor/danach!"
        
    return False, "Keine High-Impact US-Events", "", "Reguläres Marktumfeld."

@st.cache_data(ttl=3600)
def get_macro_status():
    tickers = {"S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "SMI": "^SSMI", "DAX": "^GDAXI", "Bitcoin": "BTC-USD"}
    results = {}
    bullish_count = 0
    
    try:
        b_df = yf.download(list(tickers.values()), period="1y", interval="1d", group_by="ticker", progress=False)
        
        for name, sym in tickers.items():
            if isinstance(b_df.columns, pd.MultiIndex):
                df = b_df[sym].copy() if sym in b_df.columns.levels[0] else pd.DataFrame()
            else:
                df = b_df.copy()
                
            df = df.dropna(subset=["Close"])
            
            if len(df) < 200:
                results[name] = {"price": 0.0, "is_bullish": False, "trend": "⚪ N/A"}
                continue
                
            c_p = df["Close"].iloc[-1]
            ema_200 = df["Close"].ewm(span=200, adjust=False).mean().iloc[-1]
            is_bull = c_p > ema_200
            
            if is_bull: bullish_count += 1
            
            results[name] = {
                "price": c_p,
                "is_bullish": is_bull,
                "trend": "🟢 Bullisch" if is_bull else "🔴 Bärisch"
            }
    except Exception as e:
        return None, 0, "⛅ Ladefehler", "warning", f"API-Fehler: {e}"

    if bullish_count >= 4:
        return results, bullish_count, "☀️ Sonnig (Starker Rückenwind)", "success", "Voller Rückenwind für Rebound- & Long-Setups."
    elif bullish_count >= 2:
        return results, bullish_count, "⛅ Wechselhaft (Gemischte Märkte)", "warning", "Gemischtes Bild. Normale Positionsgrößen, selektive Setups."
    else:
        return results, bullish_count, "🌧️ Sturm (Bärenmarkt)", "error", "Positionen halbieren. Hohe Vorsicht bei Long-Setups."

def validate_price_sanity(current_price, hist_df):
    df_clean = hist_df.dropna(subset=["Close"])
    if len(df_clean) < 5: return current_price, ""
    
    median_5d = df_clean["Close"].tail(5).median()
    if current_price <= 0 or abs(current_price - median_5d) / median_5d > 0.3:
        valid_prices = df_clean["Close"].tail(5)
        valid_prices = valid_prices[abs(valid_prices - median_5d) / median_5d <= 0.3]
        valid_price = valid_prices.iloc[-1] if not valid_prices.empty else median_5d
        return valid_price, "⚠️"
        
    return current_price, ""

@st.cache_data(ttl=3600, show_spinner=False)
def get_benchmark_data(symbol):
    df = yf.download(symbol, period="1y", interval="1d", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=900, show_spinner=False)
def fetch_market_data(tickers, period, interval):
    if not tickers: return pd.DataFrame()
    return yf.download(tickers, period=period, interval=interval, group_by="ticker", progress=False)

def calc_relative_strength(ticker_symbol, ticker_df, timeframe_days=20):
    if len(ticker_df) < timeframe_days: return None
    
    sym = str(ticker_symbol)
    
    # Multi-Asset Fallback für Futures & Forex
    if sym.endswith("=F") or sym.endswith("=X") or sym == "DX-Y.NYB":
        return 1.0
        
    tech_tickers = ["NFLX", "NVDA", "PLTR", "XPEV", "PANW", "CRWD"]
    
    if sym.endswith(".SW"): bench = "^SSMI"
    elif sym.endswith(".DE") or sym.endswith(".F") or sym.endswith(".MU"): bench = "^GDAXI"
    elif sym in tech_tickers: bench = "^NDX"
    else: bench = "^GSPC"
    
    bench_df = get_benchmark_data(bench)
    bench_df = bench_df.dropna(subset=["Close"])
    
    if bench_df.empty or len(bench_df) < timeframe_days: return None
    
    perf_aktie = (ticker_df["Close"].iloc[-1] / ticker_df["Close"].iloc[-timeframe_days]) - 1
    perf_bench = (bench_df["Close"].iloc[-1] / bench_df["Close"].iloc[-timeframe_days]) - 1
    
    return (1 + perf_aktie) / (1 + perf_bench)

def calculate_master_score(details, crv_rating, rs_ratio, latest_rsi, rsi_buy, direction="Long", is_multi_asset=False):
    pts_saeulen = details.get("pts_saeulen", 0)
    pts_signal = details.get("pts_signal", 0)
    setup_type = details.get("setup_type", "A")
    asset_cls = details.get("asset_class", "EQUITY")
    vol_missing = details.get("vol_missing", False)

    pts_crv = 0
    if "Top" in crv_rating: pts_crv = 20 if setup_type == "B" else 30
    elif "Passabel" in crv_rating: pts_crv = 10 if setup_type == "B" else 15
    max_crv = 20 if setup_type == "B" else 30

    max_saeulen = 35 if setup_type == "B" else 45
    if vol_missing or asset_cls == "FOREX": max_saeulen -= 10

    max_signal = 15 if setup_type == "B" else 25

    pts_rs = 0
    max_rs = 0
    if setup_type == "B" and asset_cls == "EQUITY" and rs_ratio is not None:
        max_rs = 30
        if rs_ratio >= 1.05: pts_rs = 30
        elif rs_ratio >= 0.95: pts_rs = 15

    achieved = pts_saeulen + pts_crv + pts_rs + pts_signal
    achievable = max_saeulen + max_crv + max_rs + max_signal
    total = int((achieved / achievable) * 100) if achievable > 0 else 0

    if direction == "Long" and ("Zu teuer" in details.get("ampel", "") or latest_rsi >= 70): total = min(total, 45)
    elif direction == "Short" and ("Zu billig" in details.get("ampel", "") or latest_rsi <= 30): total = min(total, 45)

    if not is_multi_asset and "Defensiv" in details.get("dna", ""):
        details["ampel"] = "⚪ Kein Swing-Setup (Low Volatility)"
        return 0, "⚪ N/A (Defensiv)", "Säulen:0 CRV:0 RS:0 Sig:0"

    icon = "🚀" if total >= 75 else ("🟢" if total >= 60 else ("🟡" if total >= 40 else "🔴"))
    breakdown_str = f"Säulen:{int(pts_saeulen)} CRV:{int(pts_crv)} RS:{int(pts_rs)} Sig:{int(pts_signal)}"
    return total, f"{icon} {total}/100", breakdown_str
def calc_rsi_and_targets(df_ticker, t_buy, t_sell, strategy_mode="5_saeulen_core", is_dynamic=False, z_buy=-2.0, z_sell=2.0, ticker=""):
    df = df_ticker.dropna(subset=["Close"]).copy()
    if len(df) < 20: return None 

    close = df["Close"]
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    df["EMA_20"] = close.ewm(span=20, adjust=False).mean()
    df["SMA_50"] = close.rolling(window=50).mean()
    df["EMA_200"] = close.ewm(span=200, adjust=False).mean()

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    if "Volume" in df.columns:
        df["Vol_SMA_20"] = df["Volume"].rolling(window=20).mean()

    sma_20_bb = close.rolling(window=20).mean()
    std_20_bb = close.rolling(window=20).std()
    df["BB_lower"] = sma_20_bb - (std_20_bb * 2)
    
    # --- START NEU: Z-Score Berechnung ---
    df["Z_Score"] = (close - sma_20_bb) / std_20_bb
    latest_z = df["Z_Score"].iloc[-1] if not pd.isna(df["Z_Score"].iloc[-1]) else 0.0
    # --- ENDE NEU ---

    if "High" in df.columns and "Low" in df.columns:
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - close.shift()).abs()
        low_close = (df["Low"] - close.shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(window=14).mean()
        latest_atr = df["ATR"].iloc[-1] if not pd.isna(df["ATR"].iloc[-1]) else 0.0
    else:
        latest_atr = 0.0
    if "ATR" in df.columns:
        df["KC_upper"] = df["EMA_20"] + (2 * df["ATR"])
        df["KC_lower"] = df["EMA_20"] - (2 * df["ATR"])
    else:
        df["KC_upper"] = df["EMA_20"]
        df["KC_lower"] = df["EMA_20"]

    latest_close = close.iloc[-1]
    # Asset-Klassifizierung
    sym_u = str(ticker).upper() if ticker else str(df.columns.name if hasattr(df.columns, 'name') and df.columns.name else "").upper()

    if any(ext in sym_u for ext in ["=X", "DX-Y"]): asset_class = "FOREX"
    elif "=F" in sym_u: asset_class = "FUTURES"
    elif any(ext in sym_u for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]): asset_class = "CRYPTO"
    else: asset_class = "EQUITY"
    latest_ag = avg_gain.iloc[-1]
    latest_al = avg_loss.iloc[-1]
    latest_rsi = df["RSI"].iloc[-1]
    
    is_buy_zone = (latest_z <= z_buy) if is_dynamic else (latest_rsi <= t_buy)
    is_sell_zone = (latest_z >= z_sell) if is_dynamic else (latest_rsi >= t_sell)
    
    p_sell = latest_close + max(0, (t_sell / (100 - t_sell) * (latest_al * 13 / 14) * 14) - (latest_ag * 13))
    p_buy = latest_close - max(0, ((((latest_ag * 13 / 14) * 14) / (t_buy / (100 - t_buy))) - (latest_al * 13)))
    atr_pct = (latest_atr / latest_close) * 100 if latest_close > 0 else 0.0
    if atr_pct >= 2.5: dna = "🚀 High-Beta Growth"
    elif atr_pct >= 1.8: dna = "⚖️ Balanced Core"
    else: dna = "🛡️ Low-Beta Defensiv"

    dna = f"[{asset_class}] " + dna
    vol_val = df["Volume"].iloc[-1] if "Volume" in df.columns else 0
    vol_sma = df["Vol_SMA_20"].iloc[-1] if "Vol_SMA_20" in df.columns else 0
    vol_missing = True if (pd.isna(vol_val) or pd.isna(vol_sma) or vol_sma <= 0) else False
        
    details = {"score": 0, "score_max": 5, "ampel": "🟡 Warten", "strategy": strategy_mode, "breakdown": "", "is_dynamic": is_dynamic, "z_score": latest_z, "plateau": "⚪ N/A", "atr": latest_atr, "atr_pct": atr_pct, "dna": dna, "asset_class": asset_class, "vol_missing": vol_missing}
    # Asset-spezifische Schwellenwerte
    if asset_class == "CRYPTO":
        pb_low, pb_high = 42.0, 58.0
        eff_t_buy = t_buy if t_buy != 30.0 else 25.0
        eff_z_buy = z_buy if is_dynamic else min(-2.2, z_buy)
    else:
        pb_low, pb_high = 38.0, 52.0
        eff_t_buy = t_buy
        eff_z_buy = z_buy

    if strategy_mode == "5_saeulen_core":
        # Setup-Erkennung
        trend_ok = (latest_close > df["EMA_200"].iloc[-1]) if asset_class != "FOREX" else True
        is_pullback = False
        if asset_class != "FOREX" and trend_ok and (pb_low <= latest_rsi <= pb_high):
            if abs(latest_close - df["EMA_20"].iloc[-1]) / df["EMA_20"].iloc[-1] <= 0.015:
                is_pullback = True

        is_setup_a = (latest_rsi <= eff_t_buy) or (latest_z <= eff_z_buy) or (latest_close <= df["KC_lower"].iloc[-1])
            
        if is_pullback:
            details["setup_type"] = "B"
            p1 = 15 if (latest_close > df["EMA_200"].iloc[-1] or asset_class == "FOREX") else 0
            p2 = 10 if df["MACD_Hist"].iloc[-1] > 0 else 0
            p3 = 10 if (not vol_missing and vol_val > vol_sma) else 0
            details["pts_saeulen"] = p1 + p2 + p3
            details["pts_signal"] = 15
            details["breakdown"] = f"EMA200:{p1} MACD:{p2} Vol:{p3}" if not vol_missing else f"EMA200:{p1} MACD:{p2} Vol:N/A"
            details["ampel"] = "🟢 ⚡ Long (Trend)"
        else:
            details["setup_type"] = "A"
            p1 = 15 if latest_rsi <= eff_t_buy else 0
            p2 = 10 if latest_close <= df["BB_lower"].iloc[-1] else 0
            p3 = 10 if latest_close <= df["KC_lower"].iloc[-1] else 0
            p4 = 10 if (not vol_missing and vol_val > vol_sma) else 0
            details["pts_saeulen"] = p1 + p2 + p3 + p4
            
            sig_trend = 15 if (latest_close > df["EMA_200"].iloc[-1] or asset_class == "FOREX") else (10 if latest_close > df["EMA_20"].iloc[-1] else 0)
            sig_ext = 10 if is_setup_a else 0
            details["pts_signal"] = sig_trend + sig_ext
            details["breakdown"] = f"RSI:{p1} BB:{p2} KC:{p3} Vol:{p4}" if not vol_missing else f"RSI:{p1} BB:{p2} KC:{p3} Vol:N/A"
            
            if (latest_close > df["EMA_200"].iloc[-1] or asset_class == "FOREX") and sig_ext > 0: details["ampel"] = "🟢 🔄 Long (Reversal)"
            elif latest_close > df["EMA_20"].iloc[-1] and sig_ext > 0: details["ampel"] = "🟡 🔄 Long (Rebound/Risk)"
            elif is_sell_zone: details["ampel"] = "🔴 Zu teuer"
            elif not (latest_close > df["EMA_200"].iloc[-1] or latest_close > df["EMA_20"].iloc[-1] or asset_class == "FOREX"): details["ampel"] = "🔴 Trend blockiert (unter EMA 200)"
            
        pro_mode = st.session_state.config.get("pro_mode_settings", {})
        if pro_mode.get("plateau_aktiv", "Inaktiv") == "Aktiv" and (is_buy_zone or is_sell_zone):
            hits = 0
            for p in [12, 13, 15, 16]:
                if is_dynamic:
                    z_p = (close - close.rolling(window=p).mean()) / close.rolling(window=p).std()
                    if (is_buy_zone and z_p.iloc[-1] <= z_buy) or (is_sell_zone and z_p.iloc[-1] >= z_sell): hits += 1
                else:
                    rs_p = gain.ewm(alpha=1/p, adjust=False).mean() / loss.ewm(alpha=1/p, adjust=False).mean()
                    rsi_p = 100 - (100 / (1 + rs_p))
                    if (is_buy_zone and rsi_p.iloc[-1] <= t_buy) or (is_sell_zone and rsi_p.iloc[-1] >= t_sell): hits += 1
            details["plateau"] = "⛰️ Robust" if hits >= 3 else "⚠️ Instabil"

    return latest_rsi, p_buy, p_sell, df, details

def calculate_sl_tp_crv(df, current_price, p_sell, tab_mode):
    sl = tp = 0.0
    is_short = False
    
    if tab_mode == "tab1":
        ema200_sl = df["EMA_200"].iloc[-1] * 0.97
        low_20 = df["Low"].tail(20).min() if "Low" in df.columns else current_price * 0.95
        sl = max(ema200_sl, low_20)
        tp = p_sell
        
        # NEU: Zwingende SL-Regel für Long-Trades
        if sl >= current_price:
            sl = current_price * 0.95
            
    elif tab_mode == "tab2":
        ema20_sl = df["EMA_20"].iloc[-1] * 0.98
        sl = max(current_price * 0.95, ema20_sl)
        
        # NEU: Zwingende SL-Regel für Long-Trades
        if sl >= current_price:
            sl = current_price * 0.95
            
        ema200 = df["EMA_200"].iloc[-1]
        atr = df["ATR"].iloc[-1] if "ATR" in df.columns and not pd.isna(df["ATR"].iloc[-1]) else 0
        if current_price < ema200 and ema200 < current_price * 1.15:
            tp = ema200
        else:
            tp = current_price + (2.0 * atr) if atr > 0 else current_price * 1.08
            
    elif tab_mode == "tab3":
        sl = df["High"].tail(24).max() if "High" in df.columns else current_price * 1.02
        # NEU: Zwingende SL-Regel für Short-Trades
        if sl <= current_price:
            sl = current_price * 1.02
        tp = df["Low"].tail(24).min() if "Low" in df.columns else current_price * 0.98
        is_short = True
        
    if is_short:
        risk = sl - current_price
        reward = current_price - tp
    else:
        risk = current_price - sl
        reward = tp - current_price
        
    # NEU: Logische Abfrage im CRV (Reward muss positiv sein)
    if reward <= 0:
        crv_rating = "🔴 Kein Upside"
    else:
        crv = (reward / risk) if risk > 0 else 0
        
        if crv >= 2.0: crv_rating = f"🟢 Top CRV (1:{crv:.1f})"
        elif crv >= 1.5: crv_rating = f"🟡 Passabel (1:{crv:.1f})"
        else: crv_rating = f"🔴 Unattraktiv (1:{crv:.1f})"
            
    return sl, tp, crv_rating
def calculate_trailing_stop(current_price, entry_price, initial_sl, tp_price, atr_val, ema20_val=0, exit_mode="PROP_DEFENSIVE", is_crypto=False, direction="Long"):
    risk = abs(entry_price - initial_sl)
    if risk <= 0: return initial_sl, "⚪ N/A"
    dir_m = 1 if direction == "Long" else -1
    open_profit = (current_price - entry_price) if direction == "Long" else (entry_price - current_price)
    current_r = open_profit / risk if risk > 0 else 0
    
    if exit_mode == "DEFENSIVE_EMERGENCY":
        if current_r < 0.75:
            return initial_sl, "🚨 Slippage-Notfallmodus (Frühes BE ab +0.75 R)"
        elif current_r < 1.5:
            new_sl = max(initial_sl, entry_price) if direction == "Long" else min(initial_sl, entry_price)
            return new_sl, "🚨 Notfall-BE aktiv (50% Scale-Out & Netto-BE ab +0.75 R)"
        else:
            trail_base = current_price - (1.5 * atr_val * dir_m)
            new_sl = max(entry_price, trail_base) if direction == "Long" else min(entry_price, trail_base)
            return new_sl, "🚨 Notfall-Trail aktiv (Enger 1.5x ATR Schutz)"

    if is_crypto:
        if current_r < 1.5:
            return initial_sl, "🛡️ Initial-Schutz (Krypto-DNA: Kein frühes BE)"
        else:
            trend_trail = current_price - (3.5 * atr_val * dir_m)
            new_target_sl = max(entry_price, trend_trail) if direction == "Long" else min(entry_price, trend_trail)
            if ema20_val > 0:
                new_target_sl = max(new_target_sl, ema20_val * 0.98) if direction == "Long" else min(new_target_sl, ema20_val * 1.02)
            return new_target_sl, "🪙 Krypto-Trail aktiv (3.5x ATR, BE ab +1.5R)"
    
    if exit_mode == "TARGET_LOCKED":
        peak_protection = entry_price + (open_profit * 0.80 * dir_m)
        if current_r < 1.0:
            return initial_sl, "🛡️ Initial-Schutz"
        else:
            new_sl = max(initial_sl, peak_protection) if direction == "Long" else min(initial_sl, peak_protection)
            return new_sl, "🛡️ Apex Tightening ab +1.0 R (80% Peak Protection)"
            
    elif exit_mode == "ALPHA_CASHFLOW":
        tp_distance = abs(tp_price - entry_price)
        tight_trigger_profit = 0.9 * tp_distance
        
        if current_r < 1.0:
            return initial_sl, "🛡️ Initial-Schutz"
        elif current_r < 1.5:
            new_sl = max(initial_sl, entry_price) if direction == "Long" else min(initial_sl, entry_price)
            return new_sl, "⚖️ Scale-Out 30% & Netto-BE ab +1.0 R"
            
        new_target_sl = entry_price
        msg = "📈 Trail-Modus aktiv"
        
        if open_profit >= tight_trigger_profit:
            trail_base = current_price - (0.5 * atr_val * dir_m)
            new_target_sl = max(new_target_sl, trail_base) if direction == "Long" else min(new_target_sl, trail_base)
            msg = "🔥 90% Tightening aktiv"
        else:
            trail_base = current_price - (2.5 * atr_val * dir_m)
            new_target_sl = max(new_target_sl, trail_base) if direction == "Long" else min(new_target_sl, trail_base)
            msg = "📈 Trail-Modus aktiv (2.5x ATR)"
            
        if current_r >= 6.0:
            peak_floor = entry_price + (open_profit * 0.50 * dir_m)
            new_target_sl = max(new_target_sl, peak_floor) if direction == "Long" else min(new_target_sl, peak_floor)
            msg = "🚀 Home-Run Stufe 3 aktiv (+6.0R Peak Protection 50%)"
        elif current_r >= 4.0:
            r4_floor = entry_price + (2.5 * risk * dir_m)
            new_target_sl = max(new_target_sl, r4_floor) if direction == "Long" else min(new_target_sl, r4_floor)
            msg = "🚀 Home-Run Stufe 2 aktiv (+4.0R gesichert auf +2.5R)"
        elif current_r >= 2.5:
            r25_floor = entry_price + (1.0 * risk * dir_m)
            new_target_sl = max(new_target_sl, r25_floor) if direction == "Long" else min(new_target_sl, r25_floor)
            msg = "🚀 Home-Run Stufe 1 aktiv (+2.5R gesichert auf +1.0R)"
            
        return new_target_sl, msg
            
    elif exit_mode == "HOME_RUN_TREND":
        trend_trail = current_price - (3.0 * atr_val * dir_m)
        if ema20_val > 0:
            trend_trail = max(trend_trail, ema20_val * 0.98) if direction == "Long" else min(trend_trail, ema20_val * 1.02)
            
        new_target_sl = trend_trail
        if current_r >= 6.0:
            peak_floor = entry_price + (open_profit * 0.50 * dir_m)
            new_target_sl = max(trend_trail, peak_floor) if direction == "Long" else min(trend_trail, peak_floor)
            return new_target_sl, "🚀 Home-Run aktiv (+6.0R Peak Protection 50%)"
        elif current_r >= 4.0:
            r4_floor = entry_price + (2.5 * risk * dir_m)
            new_target_sl = max(trend_trail, r4_floor) if direction == "Long" else min(trend_trail, r4_floor)
            return new_target_sl, "🚀 Home-Run aktiv (+4.0R gesichert auf +2.5R)"
        elif current_r >= 2.5:
            r25_floor = entry_price + (1.0 * risk * dir_m)
            new_target_sl = max(trend_trail, r25_floor) if direction == "Long" else min(trend_trail, r25_floor)
            return new_target_sl, "🚀 Home-Run aktiv (+2.5R gesichert auf +1.0R)"
        elif current_r >= 1.5:
            new_target_sl = max(trend_trail, entry_price) if direction == "Long" else min(trend_trail, entry_price)
            return new_target_sl, "🚀 Home-Run aktiv (Netto-BE ab +1.5R)"
        else:
            return initial_sl, "🛡️ Initial-Schutz (Trend)"
            
    else: # PROP_DEFENSIVE
        if current_r < 1.0:
            return initial_sl, "🛡️ Initial-Schutz"
        elif current_r < 1.5:
            new_sl = max(initial_sl, entry_price) if direction == "Long" else min(initial_sl, entry_price)
            return new_sl, "⚖️ Scale-Out 50% & Netto-BE ab +1.0 R"
        else:
            trail_base = current_price - (2.0 * atr_val * dir_m)
            new_sl = max(entry_price, trail_base) if direction == "Long" else min(entry_price, trail_base)
            return new_sl, "📈 Trail-Modus aktiv (2.0x ATR)"
def run_monte_carlo_test(current_price, sl_price, tp_price, iterations=100):
    if current_price <= 0 or sl_price <= 0 or tp_price <= 0: return 0.0, "⚪ N/A"
    passes = 0
    for _ in range(iterations):
        # Slippage & Rauschen: Einstieg teurer, SL tiefer, TP tiefer
        sim_entry = current_price * (1 + np.random.uniform(0.001, 0.008))
        sim_sl = sl_price * (1 - np.random.uniform(0.002, 0.010))
        sim_tp = tp_price * (1 - np.random.uniform(0.002, 0.005))
        
        risk = sim_entry - sim_sl
        reward = sim_tp - sim_entry
        
        if risk > 0 and (reward / risk) >= 1.2:
            passes += 1
            
    mc_ratio = (passes / iterations) * 100
    if mc_ratio >= 80: label = f"🟢 Robust ({int(mc_ratio)}%)"
    elif mc_ratio >= 50: label = f"🟡 Fragil ({int(mc_ratio)}%)"
    else: label = f"🔴 Instabil ({int(mc_ratio)}%)"
    
    return mc_ratio, label

def calculate_position_size(entry_price, sl_price, tp_price, config, fx_rate=1.0):
    gs = config.get("global_settings", {})
    mode = gs.get("risk_mode", "Festes Euro-Risiko (€)")
    acc_size = float(gs.get("account_size", 10000.0))
    risk_eur = float(gs.get("risk_eur", 100.0))
    risk_pct = float(gs.get("risk_pct", 1.0))
    fixed_inv = float(gs.get("fixed_investment", 1000.0))
    dyn_scaling = gs.get("dynamic_risk_scaling", False)
    prop_guard = gs.get("prop_guard", True)
    fee_mode = gs.get("fee_mode", "Keine Gebühren / Raw")
    
    entry_eur = entry_price * fx_rate
    sl_eur = sl_price * fx_rate
    tp_eur = tp_price * fx_rate if tp_price else None
    
    risk_per_share_eur = abs(entry_eur - sl_eur)
    if entry_eur <= 0:
        return 0.0, 0.0, 0.0, 0.0, ""
        
    max_possible_shares = acc_size / entry_eur
    target_risk_base = acc_size * (risk_pct / 100.0) if mode == "Prozentuales Konto-Risiko (%)" else risk_eur
    
    modifier = 1.0
    status_msg = f"⚙️ Smart Sizing: Inaktiv (Strikte 1.0x Basis = {target_risk_base:.2f} €)"
    
    if mode != "Feste Investition (€)" and dyn_scaling and tp_eur is not None and risk_per_share_eur > 0:
        reward_per_share_eur = abs(tp_eur - entry_eur)
        crv = reward_per_share_eur / risk_per_share_eur
        
        if crv >= 2.0:
            modifier = 1.0 if prop_guard else 1.2
            if prop_guard:
                status_msg = f"🛡️ Smart Sizing: Aktiv (Auf 1.0x / {target_risk_base:.2f} € gedeckelt durch Prop-Firm Guard)"
            else:
                status_msg = f"⚡ Smart Sizing: Aktiv (+20% Skalierung auf {target_risk_base * 1.2:.2f} €)"
        elif crv < 1.5:
            modifier = 0.5
            status_msg = f"⚠️ Smart Sizing: Aktiv (Defensiv halbiert auf {target_risk_base * 0.5:.2f} €)"
        else:
            status_msg = f"⚙️ Smart Sizing: Aktiv (Normales CRV, 1.0x Basis = {target_risk_base:.2f} €)"
    fee_rate_pct = 0.0
    flat_fee_eur = 0.0
    if "1.49% Spread" in fee_mode or "Bitpanda Retail" in fee_mode:
        fee_rate_pct = 0.0199  # 1.49% Spread + 0.5% FX/Slippage (Pauschale 1.99%)
    elif "Bitpanda Fusion" in fee_mode or "0.10%" in fee_mode:
        fee_rate_pct = 0.0010
    elif "0.25% Gebühr" in fee_mode:
        fee_rate_pct = 0.0025
    elif "0.06%" in fee_mode or "Bybit" in fee_mode:
        fee_rate_pct = 0.0006
    elif "Apex" in fee_mode or "Tradovate" in fee_mode:
        fee_rate_pct = 0.00005 + 0.0001  # 0.005% Fee + 0.01% Slippage
    elif "FTMO" in fee_mode or "MetaTrader" in fee_mode:
        fee_rate_pct = 0.00003 + 0.00002  # 0.003% Fee + 0.002% Slippage
    elif "Aktien Broker" in fee_mode or "Interactive" in fee_mode or "Flatex" in fee_mode:
        flat_fee_eur = 2.00
    
    if mode == "Feste Investition (€)":
        target_inv = min(fixed_inv, acc_size) 
        if flat_fee_eur > 0: target_inv = max(0, target_inv - flat_fee_eur)
        position_size = round(target_inv / (entry_eur * (1 + fee_rate_pct)), 4)
        status_msg = f"⚙️ Smart Sizing: Inaktiv (Feste Investition)"
    else:
        target_risk = target_risk_base * modifier
        if flat_fee_eur > 0:
            adjusted_target_risk = max(0, target_risk - flat_fee_eur)
            loss_per_share = risk_per_share_eur
        else:
            adjusted_target_risk = target_risk
            loss_per_share = risk_per_share_eur + (entry_eur + sl_eur) * fee_rate_pct
            
        position_size = round(adjusted_target_risk / loss_per_share, 4) if loss_per_share > 0 else 0.0
        
        if position_size > max_possible_shares:
            position_size = round(max_possible_shares, 4)
            
    total_capital_eur = position_size * entry_eur
    pure_risk_eur = position_size * risk_per_share_eur
    if "1.49% Spread" in fee_mode or "Bitpanda Retail" in fee_mode:
        fee_roundtrip_eur = max(2.00, (position_size * entry_eur + position_size * sl_eur) * fee_rate_pct)
    else:
        fee_roundtrip_eur = flat_fee_eur if flat_fee_eur > 0 else (position_size * entry_eur + position_size * sl_eur) * fee_rate_pct
    
    return position_size, total_capital_eur, pure_risk_eur, fee_roundtrip_eur, status_msg
            
def calculate_smart_proposal(entry_price, sl_price, tp_price, max_r_eur, config, expected_days=0, is_short=False):
    if entry_price <= 0 or sl_price <= 0: return None
    
    # Abfangen unlogischer Trades je nach Richtung (Long vs. Short)
    if is_short and tp_price >= entry_price: return None
    if not is_short and tp_price <= entry_price: return None
    
    gs = config.get("global_settings", {})
    is_strict = gs.get("prop_guard", True)
    acc_size = float(gs.get("account_size", 10000.0))
    
    risk_per_share = abs(entry_price - sl_price)
    if risk_per_share <= 0: return None
    
    reward_per_share = abs(tp_price - entry_price)
    crv = reward_per_share / risk_per_share
    
    # Dynamische Skalierung über das CRV-Rating
    if crv >= 2.0:
        modifier = 1.2
        reason = "🔥 **Top-Setup (CRV ≥ 2.0):** "
    elif crv >= 1.5:
        modifier = 1.0
        reason = "⚖️ **Solides Setup:** "
    else:
        modifier = 0.5
        reason = "⚠️ **Schwaches CRV:** "
        
    # Prop-Firm Compliance Check & Kappung
    if is_strict and modifier > 1.0:
        modifier = 1.0
        reason += "Risiko laut Prop-Firm Modus strikt auf Limit gedeckelt."
    elif not is_strict and modifier > 1.0:
        reason += "Risiko um 20% erhöht (Gewinnmaximierung erlaubt)."
    elif modifier < 1.0:
        reason += "Positionsgröße halbiert (Kapitalschutz geht vor)."
    else:
        reason += "Standard-Risiko empfohlen."
        
    if expected_days > 0:
        reason += f" Aufgrund der ATR (ca. {int(expected_days)} Tage) wird von einem {'kurzfristigen' if expected_days <= 7 else 'mittelfristigen'} Swing-Trade ausgegangen."
        
    smart_risk = max_r_eur * modifier
    smart_pos = round(smart_risk / risk_per_share, 4)
    
    if smart_pos * entry_price > acc_size:
        smart_pos = round(acc_size / entry_price, 4)
        reason += " (Stückzahl durch Kontoguthaben limitiert)."
        
    return {
        "pos": smart_pos, "inv": smart_pos * entry_price, 
        "profit": smart_pos * reward_per_share, "risk": smart_pos * risk_per_share, 
        "reason": reason
    }
def calc_tax_report(df_journal, selected_year, jurisdiction, account_filter, accounts_config):
    df = df_journal[df_journal['status'] == 'CLOSED'].copy()
    if df.empty: return pd.DataFrame(), {}
    
    def parse_year(d_str):
        try: return datetime.datetime.strptime(str(d_str), "%d/%m/%Y %H:%M").year
        except: 
            try: return datetime.datetime.strptime(str(d_str), "%Y-%m-%d %H:%M").year
            except: return 0
            
    df['year'] = df['exit_date'].apply(parse_year)
    df = df[df['year'] == int(selected_year)]
    
    if account_filter != "Alle Konten":
        df = df[df['account_name'] == account_filter]
        
    report_lines = []
    metrics = {"brutto_gewinn": 0.0, "brutto_verlust": 0.0, "fees": 0.0, "payouts": 0.0, "challenge_fees": 0.0, "is_prop": False}
    
    for _, row in df.iterrows():
        is_cashflow = str(row.get('setup_type', '')) in ['DEPOSIT', 'WITHDRAWAL'] or str(row.get('direction', '')) in ['DEPOSIT', 'WITHDRAWAL']
        if is_cashflow:
            continue
        acc_name = row.get('account_name', '')
        tax_cat = "private"
        for acc in accounts_config.values():
            if acc["name"] == acc_name:
                tax_cat = acc.get("tax_category", "private")
                break
                
        is_payout = str(row.get('direction', '')) == 'PAYOUT' or str(row.get('setup_type', '')) == 'PAYOUT'
        is_fee = str(row.get('direction', '')) == 'CHALLENGE_FEE' or str(row.get('setup_type', '')) == 'CHALLENGE_FEE'
        
        if tax_cat == "prop_firm":
            metrics["is_prop"] = True
            if is_payout:
                amt = float(row.get('pnl_eur', 0.0))
                metrics["payouts"] += amt
                report_lines.append(row)
            elif is_fee:
                amt = abs(float(row.get('pnl_eur', 0.0)))
                metrics["challenge_fees"] += amt
                report_lines.append(row)
        else: # Private
            if is_payout or is_fee: continue 
            
            pnl = float(row.get('pnl_eur', 0.0))
            fee = float(row.get('est_fees_eur', 0.0))
            metrics["fees"] += fee
            
            sym = str(row.get('symbol', ''))
            is_termingeschaeft = sym.endswith('=F') or sym.endswith('=X') or str(row.get('contract_type')) in ['MNQ', 'MES', 'MYM', 'M2K', 'Lot', 'Micro']
            
            # Bei DE & Termingeschäften greifen Verlustverrechnungsbeschränkungen
            if pnl >= 0: metrics["brutto_gewinn"] += pnl
            else: metrics["brutto_verlust"] += abs(pnl)
            
            report_lines.append(row)
            
    metrics["netto"] = (metrics["brutto_gewinn"] - metrics["brutto_verlust"]) + metrics["payouts"] - metrics["challenge_fees"]
    return pd.DataFrame(report_lines), metrics
PROFILE_DISPLAY_NAMES = {
    "apex_lock": "Target-Lock Intraday (Apex)",
    "ftmo_swing": "Forex Swing-Runner (FTMO)",
    "private_alpha": "Home-Run Trend (Maximal-Alpha)",
    "commodity_scale": "Scale-Out Defensiv (Rohstoff-Swing)",
    "apex_commodity_scale": "Scale-Out Defensiv (Rohstoff-Swing)",
    "commodity_alpha": "Rohstoff-Runner (Privat-Alpha)",
    "defensive_swing": "Defensiv-Swing (Teilgewinn ab +1.0 R)",
    "prop_guard": "Defensiv-Swing (Teilgewinn ab +1.0 R)",
    "sandbox": "Sandbox-Demo (Manuell)"
}

def get_profile_display_name(prof_key):
    return PROFILE_DISPLAY_NAMES.get(str(prof_key).strip(), str(prof_key))

def get_asset_strategy_recommendation(symbol):
    sym = str(symbol).upper().strip()
    if sym == 'NQ=F':
        return {"label": "🟢 Validierter Prop-Leader", "konto_typ": "Apex Prop-Desk (50k)", "profil": "Target-Lock Intraday (Apex)", "valid_profiles": ["apex_lock"], "timeframe": "1h (RTH 15:30–21:30 MEZ)", "hinweis": "Striktes Apex Target-Lock (+2.0 R). EOD-Glattstellung vor 22:00 Uhr MEZ zwingend. Im Privatdepot ab 15.000 € Kontogröße zulässig."}
    elif sym in ['USDJPY=X', 'GBPUSD=X']:
        return {"label": "🟢 Validierter Forex-Swing", "konto_typ": "FTMO Prop-Desk (50k)", "profil": "Forex Swing-Runner (FTMO)", "valid_profiles": ["ftmo_swing"], "timeframe": "4h", "hinweis": "Strikte 5% Sizing-Regel vom Daily Loss. Freier Trendauslauf (kein starres Apex-EOD)."}
    elif sym == 'EURUSD=X':
        return {"label": "🟢 Validierter London/NY Overlap", "konto_typ": "FTMO Prop-Desk (50k)", "profil": "Forex Swing-Runner (FTMO)", "valid_profiles": ["ftmo_swing"], "timeframe": "1h (13:00–18:00 MEZ)", "hinweis": "Nur im 1h-Takt während der Überlappung handeln (4h empirisch ungeeignet)."}
    elif sym == 'CL=F':
        return {"label": "🟢 Validierter Privater Rohstoff-Bulle (4h)", "konto_typ": "Privates Vermögenskonto (IBKR / Depot)", "profil": "Scale-Out Defensiv (Rohstoff-Swing)", "valid_profiles": ["commodity_scale", "apex_commodity_scale"], "timeframe": "4h (Pit-Session 14:30–20:30 MEZ)", "hinweis": "50% Scale-Out ab +1.0 R, freie Mehrtages-Haltedauer. Für Apex wegen des strikten Overnight-Verbots gesperrt!"}
    elif sym == 'GC=F':
        return {"label": "⚖️ Privater Edelmetall-Swing", "konto_typ": "Privates Vermögenskonto", "profil": "Rohstoff-Runner (Privat-Alpha)", "valid_profiles": ["commodity_alpha"], "timeframe": "1h (London-Session 09:00–18:00 MEZ)", "hinweis": "Freier Trendlauf ohne Scale-Out. Für Prop-Challenges ungeeignet."}
    elif any(ext in sym for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]):
        return {"label": "🪙 Krypto-DNA (Volatilitäts-Modus)", "konto_typ": "Privates Krypto-Portfolio (Bybit/IBKR)", "profil": "Home-Run Trend (Maximal-Alpha)", "valid_profiles": ["private_alpha"], "timeframe": "1d", "hinweis": "Streng für Prop-Trading verboten! Kein BE vor +1.5 R, weiter 3.5x ATR Trailing-Stop."}
    elif not sym.endswith("=F") and not sym.endswith("=X") and not sym.startswith("^"):
        return {"label": "🚀 Asymmetric Alpha (Home-Run)", "konto_typ": "Privates Vermögenskonto", "profil": "Defensiv-Swing (Teilgewinn ab +1.0 R)", "valid_profiles": ["defensive_swing", "prop_guard", "private_alpha"], "timeframe": "4h (RTH 15:30–22:00 MEZ)", "hinweis": "Setup B Trend-Pullback über EMA 200. 50% Teilgewinn ab +1.0 R zur Kapitalsicherung empfohlen."}
    else:
        return {"label": "⚪ Nicht im v1.0.0 Kernkader validiert", "konto_typ": "Beliebig / Sandbox", "profil": "Defensiv-Swing (Teilgewinn ab +1.0 R)", "valid_profiles": ["defensive_swing", "prop_guard"], "timeframe": "1d", "hinweis": "Setup nicht Teil der Kernvalidierung. Nur mit Vorsicht im Demomodus testen."}

def get_action_guideline(sym, score, a_class=""):
    sym_u = str(sym).upper().strip()
    a_cls_u = str(a_class).upper().strip()
    try:
        sc = float(score)
    except Exception:
        sc = 0.0

    if sym_u == "NQ=F":
        if sc >= 70:
            return "🛑 Überdehnungsfalle: Kein Blindkauf! Rechnerisch droht ein Panik-/Crash-Abverkauf (PF bricht historisch auf 0.91 ein). Aktion: Warten, bis der Score in den Korridor 60–65 abkühlt oder eine Kerze über dem Paniktief schließt."
        elif 60 <= sc < 70:
            return "🟢 Im Ziel-Korridor: Gesunder Pullback im Aufwärtstrend. Setup regelkonform handelbar."
        else:
            return "⚪ Kein Setup: Warten auf Korrektur in den Korridor 60–65."
    elif sym_u == "GC=F":
        if sc >= 70:
            return "ℹ️ Hohe Überdehnung: Bei Gold oft starke V-Rebounds. Aktion: Prüfen, ob Makro-Filter (EMA 200) intakt und Session aktiv (09:00–18:00 MEZ). Wenn ja -> Rebound-Chance mit engem Stop."
        elif 60 <= sc < 70:
            return "🟢 Im Ziel-Korridor: Setup regelkonform handelbar."
        else:
            return "⚪ Kein Setup: Markt neutral oder im Momentum. Auf Pullback warten."
    elif sym_u in ["CL=F", "MCL"]:
        if 65 <= sc <= 70:
            return "🟢 Im Ziel-Korridor: Sweet Spot für Mehrtages-Swing (Scale-Out Defensiv)."
        elif sc > 70:
            return "⚠️ Obere Grenze: Rebound weit gelaufen, nicht über 75 hinterherkaufen."
        else:
            return "⚪ Kein Setup: Warten auf Pullback in den Ziel-Korridor 65–70."
    elif sym_u in ["USDJPY=X", "GBPUSD=X", "EURUSD=X"] or "FOREX" in a_cls_u or sym_u.endswith("=X"):
        low_b, high_b = (65, 75) if sym_u == "EURUSD=X" else (60, 70)
        if low_b <= sc <= high_b:
            return "🟢 Im Ziel-Korridor: Range-/Trend-Pullback handelbar."
        elif sc > high_b:
            return "⚠️ Range-Ende: Nur mit Session-Bestätigung agieren."
        else:
            return "⚪ Kein Setup: Warten auf klares Signal."
    elif not ("=F" in sym_u or "=X" in sym_u or "DX-Y" in sym_u or any(ext in sym_u for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]) or a_cls_u in ["FUTURES", "ROHSTOFFE", "FOREX", "KRYPTO", "CRYPTO"]):
        if 65 <= sc <= 75:
            return "🟢 Im Ziel-Korridor (65–75): Gesunder Pullback an EMA 20 im Aufwärtstrend (Setup B)."
        elif sc < 65:
            return "⚪ Unter Ziel-Korridor (< 65): Warten auf klaren Pullback im Trend."
        else:
            return "🟢 Hohe Relative Stärke: Institutioneller Kaufdruck, Trendfolge ideal."
    else:
        if sc >= 60:
            return "🟢 Im Setup-Bereich."
        else:
            return "⚪ Kein Signal: Neutral."
#endregion

#region UI COMPONENTS
def render_currency_metric(col, label, val, curr, fx, view_mode):
    if curr == "€" or curr == "EUR":
        col.metric(label, f"{val:.2f} €")
        return

    val_orig = f"{val:.2f} {curr}"
    val_eur = f"{val * fx:.2f} €"

    if view_mode == "Nur Bitpanda EUR (€)":
        col.metric(label, val_eur)
    elif view_mode == "Nur Original":
        col.metric(label, val_orig)
    else: # Duale Ansicht
        col.metric(label, val_orig, f"💶 ≈ {val_eur}", delta_color="off")
def render_dynamic_settings(title, config_section, fields_config, key_prefix="", expanded=False, reset_label=None, defaults_to_reset=None, extra_resets=None):
    with st.expander(f"⚙️ {title}", expanded=expanded):
        counter_key = f"counter_{key_prefix}{config_section}"
        if counter_key not in st.session_state: st.session_state[counter_key] = 0
        current_counter = st.session_state[counter_key]
        
        with st.form(key=f"form_{key_prefix}{config_section}_{current_counter}", border=False):
            cols = st.columns(len(fields_config))
            new_values = {}
            for i, field in enumerate(fields_config):
                with cols[i]:
                    current_val = st.session_state.config[config_section].get(field["key"], field["default"])
                    w_key = f"{key_prefix}{field['key']}_{current_counter}"
                    if field["type"] == "number":
                        new_values[field["key"]] = st.number_input(field["label"], value=float(current_val), step=field.get("step", 1.0), key=w_key, help=field.get("help"))
                    elif field["type"] == "radio":
                        new_values[field["key"]] = st.radio(field["label"], field["options"], index=field["options"].index(current_val) if current_val in field["options"] else 0, horizontal=True, key=w_key, help=field.get("help"))
            
            submit_btn = st.form_submit_button(f"💾 {title} speichern", use_container_width=True)
            if submit_btn:
                st.session_state.config[config_section].update(new_values)
                save_config(st.session_state.config)
                st.success("Gespeichert!")
                st.rerun()

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("❌ Änderungen verwerfen", key=f"discard_{key_prefix}{config_section}", use_container_width=True):
                st.session_state[counter_key] += 1
                st.rerun()
        with col_b2:
            if reset_label and defaults_to_reset is not None:
                if st.button(reset_label, key=f"reset_{key_prefix}{config_section}", use_container_width=True):
                    st.session_state.config[config_section] = defaults_to_reset.copy()
                    if extra_resets:
                        for ex_key, ex_val in extra_resets.items(): st.session_state.config[ex_key] = ex_val.copy()
                    save_config(st.session_state.config)
                    st.session_state[counter_key] += 1
                    st.rerun()

def render_management_panel(target_list_key, show_sectors=False):
    st.subheader("🛠️ Verwaltung" + (" & Sektoren" if show_sectors else " der Watchlist"))
    col_v1, col_v2 = st.columns(2) if show_sectors else (None, st.columns(1)[0])
    
    if show_sectors:
        with col_v1:
            with st.expander("📂 Sektoren verwalten", expanded=False):
                new_sec = st.text_input("Neuer Sektor (Freitext):")
                if st.button("➕ Sektor hinzufügen") and new_sec:
                    if new_sec not in st.session_state.config["global_settings"].get("custom_sectors", []):
                        st.session_state.config["global_settings"].setdefault("custom_sectors", []).append(new_sec)
                        save_config(st.session_state.config); st.rerun()
                cust_secs = st.session_state.config["global_settings"].get("custom_sectors", [])
                del_sec = st.selectbox("Sektor löschen:", ["- Auswählen -"] + cust_secs)
                if st.button("🗑️ Sektor löschen") and del_sec != "- Auswählen -":
                    st.session_state.config["global_settings"]["custom_sectors"].remove(del_sec)
                    save_config(st.session_state.config); st.rerun()

    target_col = col_v2 if show_sectors else col_v1
    with target_col if target_col else st.container():
        with st.expander("🗑️ Ticker aus Liste entfernen", expanded=False):
            if st.session_state.config[target_list_key]:
                del_opt = {f"{t['symbol']} ({t['name']})": t['symbol'] for t in st.session_state.config[target_list_key]}
                to_delete = st.multiselect("Wähle Wertpapiere:", list(del_opt.keys()), key=f"del_{target_list_key}")
                if st.button("🗑️ Ausgewählte löschen", type="primary", key=f"btn_del_{target_list_key}") and to_delete:
                    syms_del = [del_opt[i] for i in to_delete]
                    st.session_state.config[target_list_key] = [t for t in st.session_state.config[target_list_key] if t["symbol"] not in syms_del]
                    save_config(st.session_state.config); st.rerun()

def render_search_bar(config_key, is_tab1=False):
    st.subheader("🔍 Neues Wertpapier hinzufügen")
    c_search, c_btn = st.columns([3, 1])
    with c_search: sq = st.text_input("Name, Stichwort oder Ticker eingeben:", key=f"search_{config_key}")
    suggestions = []
    if sq and len(sq.strip()) >= 2:
        sq_clean = sq.lower().replace(" ", "")
        
        # 1. Lokale Sektoren/Universen durchsuchen (z.B. "Cybersecurity")
        for tag, tag_data in st.session_state.config.get("scan_universes", {}).items():
            if sq_clean in tag.lower().replace(" ", ""):
                suggestions.append((f"TAG:{tag}", f"Sektor: {tag}", f"📁 Ganze Liste: {tag} ({len(tag_data.get('tickers', []))} Ticker)"))
                
        # 2. Yahoo Finance Suche (Freitext, ISIN, Ticker)
        try:
            # Vollständiger Browser-Header, damit Yahoo die Anfrage nicht blockiert
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            resp = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={sq.strip()}&quotesCount=20", headers=headers, timeout=5)
            if resp.status_code == 200:
                seen = set()
                for q in resp.json().get("quotes", []):
                    sym = q.get("symbol")
                    if not sym or sym in seen: continue
                    seen.add(sym)
                    name = q.get("longname") or q.get("shortname") or sym
                    suggestions.append((sym, name, f"{name} ({sym}) — {q.get('exchDisp', '')}"))
        except: pass
            
    chosen_sym, chosen_name = None, None
    if suggestions:
        opt_dict = {lbl: (sym, name) for sym, name, lbl in suggestions}
        chosen_sym, chosen_name = opt_dict[st.selectbox("Treffer:", list(opt_dict.keys()), key=f"sel_{config_key}")]
        
    with c_btn:
        st.write(""); st.write("")
        if st.button("➕ Hinzufügen", use_container_width=True, key=f"add_{config_key}") and chosen_sym:
            if config_key not in st.session_state.config: st.session_state.config[config_key] = []
            
            if chosen_sym.startswith("TAG:"):
                tag_name = chosen_sym.replace("TAG:", "")
                tickers_to_add = st.session_state.config.get("scan_universes", {}).get(tag_name, {}).get("tickers", [])
                added = 0
                for t in tickers_to_add:
                    if not any(existing["symbol"] == t["symbol"] for existing in st.session_state.config[config_key]):
                        new_entry = {"symbol": t["symbol"], "name": t.get("name", t["symbol"])}
                        if is_tab1: new_entry.update({"sector": tag_name, "risk_class": "Wachstum/Aggressiv", "use_custom": False, "custom_rsi_buy": st.session_state.config["global_settings"]["rsi_aggressiv"], "custom_rsi_sell": st.session_state.config["global_settings"]["rsi_sell_aggressiv"]})
                        if config_key == "lab_tickers": new_entry.update({"account": 10000.0, "risk": 1.0})
                        st.session_state.config[config_key].append(new_entry)
                        added += 1
                if added > 0:
                    save_config(st.session_state.config)
                    st.success(f"✅ {added} Ticker aus '{tag_name}' hinzugefügt!")
                    st.rerun()
                else:
                    st.info("ℹ️ Alle Ticker dieser Liste sind bereits vorhanden.")
            else:
                if not any(t["symbol"] == chosen_sym for t in st.session_state.config[config_key]):
                    new_entry = {"symbol": chosen_sym, "name": chosen_name}
                    if is_tab1: new_entry.update({"sector": "Standard", "risk_class": "Wachstum/Aggressiv", "use_custom": False, "custom_rsi_buy": st.session_state.config["global_settings"]["rsi_aggressiv"], "custom_rsi_sell": st.session_state.config["global_settings"]["rsi_sell_aggressiv"]})
                    if config_key == "lab_tickers": new_entry.update({"account": 10000.0, "risk": 1.0})
                    st.session_state.config[config_key].append(new_entry)
                    save_config(st.session_state.config)
                    st.rerun()

def render_chart_system(res_dict, uid, selected_sector="Alle", show_trend_box=False):
    st.subheader("📈 Interaktives Trading-Chart System")
    c1, c2, c3 = st.columns([2, 1, 1])
    chart_opts = {f"[{v[4]}] {k} - {v[3]}" if v[4] != "N/A" else f"{k} - {v[3]}": k for k, v in res_dict.items() if selected_sector == "Alle" or v[4] == selected_sector}
    with c1: sel_sym = chart_opts.get(st.selectbox("Wertpapier auswählen:", list(chart_opts.keys()), key=f"c_sel_{uid}")) if chart_opts else None
    with c2: chart_type = st.selectbox("Kursdarstellung:", ["Kerzenchart", "Linie"], key=f"c_type_{uid}")
    with c3: sub_ind = st.selectbox("Indikator:", ["RSI", "MACD", "Volumen"], key=f"c_ind_{uid}")

    if sel_sym:
        df_p, t_low, t_high, t_name, t_sec = res_dict[sel_sym]
        if show_trend_box:
            c_price = df_p["Close"].iloc[-1]
            c_ema = df_p["EMA_200"].iloc[-1]
            c_rsi = df_p["RSI"].iloc[-1]
            if c_rsi <= t_low and c_price <= c_ema:
                st.warning("🟡 **Trend-Warnung:** RSI signalisiert Kauf, aber Kurs liegt unter dem EMA 200. Vorsicht vor fallenden Messern!")
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.65, 0.35], subplot_titles=(f"{sel_sym} - Kursverlauf", sub_ind))
        
        if chart_type == "Kerzenchart" and "Open" in df_p: fig.add_trace(go.Candlestick(x=df_p.index, open=df_p["Open"], high=df_p["High"], low=df_p["Low"], close=df_p["Close"], name="Kurs"), row=1, col=1)
        else: fig.add_trace(go.Scatter(x=df_p.index, y=df_p["Close"], name="Schlusskurs", line=dict(color="#1f77b4", width=2)), row=1, col=1)

        fig.add_trace(go.Scatter(x=df_p.index, y=df_p["EMA_20"], name="EMA 20", line=dict(color="orange")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_p.index, y=df_p["SMA_50"], name="SMA 50", line=dict(color="purple")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_p.index, y=df_p["EMA_200"], name="EMA 200", line=dict(color="red", dash="dot")), row=1, col=1)

        if sub_ind == "RSI":
            fig.add_trace(go.Scatter(x=df_p.index, y=df_p["RSI"], line=dict(color="#2ca02c")), row=2, col=1)
            fig.add_hline(y=t_high, line_dash="dash", line_color="red", annotation_text=f"{t_high}", row=2, col=1)
            fig.update_yaxes(range=[0, 100], row=2, col=1)
        elif sub_ind == "MACD":
            fig.add_trace(go.Scatter(x=df_p.index, y=df_p["MACD"], line=dict(color="blue")), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_p.index, y=df_p["MACD_Signal"], line=dict(color="orange")), row=2, col=1)
            fig.add_trace(go.Bar(x=df_p.index, y=df_p["MACD_Hist"], marker_color="gray"), row=2, col=1)
        elif sub_ind == "Volumen" and "Volume" in df_p:
            fig.add_trace(go.Bar(x=df_p.index, y=df_p["Volume"], marker_color="teal"), row=2, col=1)

        fig.update_layout(height=600, margin=dict(l=20, r=20, t=40, b=20), hovermode="x unified", xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

def render_macro_weather():
    with st.expander("🌍 Globales Marktwetter & Trend-Radar", expanded=False):
        res, b_count, sent, box_type, advice = get_macro_status()
        
        if not res:
            st.warning("Marktdaten konnten aktuell nicht geladen werden.")
            return
            
        cols = st.columns(5)
        for idx, (name, data) in enumerate(res.items()):
            with cols[idx]:
                st.metric(label=name, value=f"{data['price']:,.2f}", delta=data['trend'], delta_color="off")
        
        st.write("") # Kleiner Abstand
        has_news, news_title, news_time, news_warn = get_economic_calendar()
        if has_news:
            st.warning(f"⚠️ **Wirtschaftskalender-Alarm:** Heute um {news_time} – **{news_title}**! {news_warn}")
        else:
            st.caption(f"🟢 **Wirtschaftskalender:** {news_title} für heute gemeldet. {news_warn}")
        if box_type == "success": st.success(f"**Gesamt-Sentiment: {sent}** | {advice}")
        elif box_type == "warning": st.warning(f"**Gesamt-Sentiment: {sent}** | {advice}")
        else: st.error(f"**Gesamt-Sentiment: {sent}** | {advice}")

#endregion

# --- NEU: Marktwetter aufrufen ---
render_macro_weather()

with st.expander("📖 Schnellstart-Anleitung & Kader-Spickzettel", expanded=False):
    st.markdown("""
    ### 🚀 In 4 Schritten zum Trade
    * **Schritt 1:** Marktwetter & Wirtschaftskalender prüfen (Sperre/Pause bei High-Impact Events wie CPI/FOMC/NFP beachten).
    * **Schritt 2:** Signal im passenden Tab suchen (Ampel 🟢 = Handlungsfreigabe):
      * LONG: 🔵 🔄 Long (Reversal) [Setup A] | 🔷 ⚡ Long (Trend) [Setup B]
      * SHORT: 🟣 🔄 Short (Reversal) [Setup A] | 🟪 ⚡ Short (Trend) [Setup B]
    * **Schritt 3:** In der Tabelle die Checkbox '🛒 Order' aktivieren -> Stückzahl, Stop-Loss und Take-Profit in der linken Seitenleiste ablesen und manuell im Broker ausführen. *(Vor dem Einbuchen neuer Einzeltitel ins Depot ist ein 5-Jahres-Walk-Forward-Check im Strategie-Labor mit OOS-PF >= 1.40 Pflicht.)*
    * **Schritt 4:** Klick auf '📝 Trade einloggen' -> Die Überwachung der Position (Netto-BE, Trailing-Stop, Stufen-Chandelier) erfolgt vollautomatisch durch den Telegram-Copiloten.

    ---
    ### 📋 Master-Kader & Profil-Spickzettel (Welches Setup wohin gehört)
    **🏢 Fremdkapital / Prop-Challenges (tax_category: prop_firm):**
    * **Apex 50k:** Ticker `NQ=F` (1h, RTH 15:30–21:30 MEZ) | Profil: **Target-Lock Intraday (apex_lock)** mit 10% Daily-Loss Sizing.
    * **FTMO 50k:** Ticker `USDJPY=X` & `GBPUSD=X` (4h) | Profil: **Forex Swing-Runner (ftmo_swing)** mit 5% Daily-Loss Sizing.

    **👤 Privates Cashflow- & Alpha-Depot (tax_category: private):**
    * **High-Beta Tech & Growth (z.B. NVDA, PLTR, AAPL auf 4h, RTH 15:30–22:00 MEZ):** Ausschließlich Setup B Trend-Pullbacks über EMA 200. Profil: **Defensiv-Swing (defensive_swing)** für frühe Gewinnsicherung (+1.0 R) oder **Home-Run Trend (private_alpha)** für freie Mega-Trends.
    * **Träge Dividendentitel & Low-Beta (ATR < 1.8%):** Automatisch gesperrt. Binden totes Kapital und sind für unser Swing-System ungeeignet.
    * **Rohöl (CL=F auf 4h, Pit-Session 14:30–20:30 MEZ):** Profil **Scale-Out Defensiv (Rohstoff-Swing)** – Exklusiv für das private Depot (Für Apex wegen Overnight-Verbot gesperrt).
    * **Gold (GC=F auf 1h, London/NY 09:00–18:00 MEZ):** Profil **Rohstoff-Runner (Privat-Alpha)** (volle Swings, kein TP-Deckel).

    ⚠️ **Wichtiger Grundsatz zu Score-Werten (Ziel-Korridor-Disziplin):**
    Bei Index- und Rohstoff-Futures bedeutet ein höherer Score nicht automatisch mehr Sicherheit! Werte über dem Ziel-Korridor (z. B. NQ=F >= 70) deuten oft auf panikartige Überdehnungen / fallende Messer hin. Halte dich strikt an die validierten Ziel-Korridore.

    | Asset | Ziel-Korridor | Bei Score >= 70 | Markt-Bedeutung | Konkrete Aktion |
    | :--- | :--- | :--- | :--- | :--- |
    | **NQ=F (Nasdaq)** | **55 – 65** | 🛑 Zu heiß | Panik-Abverkauf / Crash-Gefahr | **Warten**, bis Kurs sich beruhigt |
    | **CL=F (Rohöl)** | **65 – 75** | 🟢 Sweet Spot | Mehrtages-Swing im Trend (4h) | **Einstieg mit 50% Scale-Out ab +1.0 R** |
    | **GC=F (Gold)** | **60 – 65** | ℹ️ Rebound | Flummi-Effekt nach oben möglich | Kaufen, wenn Makro-Ampel grün |
    | **Forex (4h)** | **60 – 70** | ⚠️ Band-Ende | Währung stößt an Grenzen | Vorsicht vor Rücksetzern |
    | **Aktien (4h)** | **65 – 75** | 🟢 Ideal! | Gesunder Trend-Pullback im Bullenmarkt (Setup B) | **Kauf-Signal mit Teilgewinn bei +1.0 R** |
    """)
    st.info("ℹ️ Krypto-DNA (BTC/ETH/SOL): Befindet sich für v1.0.0 im experimentellen Labor-Modus (Phase 7). Reiner Handelsempfehlungs-Fokus liegt auf Futures, Rohstoffen, Forex und US-Aktien.")
    with st.expander("ℹ️ Warum ein höherer Score nicht immer besser ist", expanded=False):
        st.caption("• Indizes & Rohstoffe besitzen keine 'Relative Stärke' gegen sich selbst. Ein Score über 70 entsteht hier nur durch extreme Panik-Verkäufe (fallende Messer).\n\n• Aktien hingegen erhalten bis zu 30 Bonuspunkte für Relative Stärke gegenüber dem Gesamtmarkt. Ein hoher Score beweist hier echtes institutionelles Kaufinteresse.")

#region SIDEBAR (Risk Management & Order Desk)
with st.sidebar:
    st.markdown(f"👤 **Eingeloggt als:** {st.session_state.username} ({st.session_state.role})")
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.username = None
        st.session_state.role = None
        st.rerun()
    st.markdown("---")
    with st.expander("👤 Kontosicherheit (Passwort ändern)", expanded=False):
        with st.form("pwd_change_form"):
            st.markdown("""
            <input style="display:none" type="text" name="fake_username"/>
            <input style="display:none" type="password" name="fake_password"/>
            """, unsafe_allow_html=True)
            
            show_pwd_sidebar = st.checkbox("👁️ Passwörter im Klartext anzeigen", key="show_pwd_sb")
            pw_input_type = "default" if show_pwd_sidebar else "password"
            
            old_pw = st.text_input("Aktuelles Passwort", type=pw_input_type)
            new_pw1 = st.text_input("Neues Passwort", type=pw_input_type)
            new_pw2 = st.text_input("Neues Passwort wiederholen", type=pw_input_type)
            
            if st.form_submit_button("💾 Passwort speichern", use_container_width=True):
                with open(AUTH_FILE, "r", encoding="utf-8") as f:
                    creds = json.load(f)
                
                stored_hash = creds.get(st.session_state.username, "")
                is_correct, _ = verify_password(old_pw, stored_hash)
                
                if not is_correct:
                    st.error("⚠️ Das aktuelle Passwort ist falsch.")
                elif len(new_pw1) < 6:
                    st.error("⚠️ Das neue Passwort muss mindestens 6 Zeichen lang sein.")
                elif new_pw1 != new_pw2:
                    st.error("⚠️ Die neuen Passwörter stimmen nicht überein.")
                else:
                    creds[st.session_state.username] = hash_password(new_pw1)
                    with open(AUTH_FILE, "w", encoding="utf-8") as f:
                        json.dump(creds, f, indent=4)
                    st.success("✅ Passwort erfolgreich geändert!")
    if st.session_state.role == "admin":
        admin_bypass = st.checkbox("🔓 Admin: Poka-Yoke Sperren umgehen", key="admin_poka_bypass", value=st.session_state.get("admin_poka_bypass", False))
        if admin_bypass:
            st.warning("⚠️ **Admin-Bypass aktiv:** Poka-Yoke Schutzschilde umgangen.")
    else:
        st.session_state["admin_poka_bypass"] = False
    has_news, news_title, news_time, news_warn = get_economic_calendar()
    if has_news:
        st.error(f"🛑 **Markt-Warnung:** Heute um {news_time} stehen '{news_title}' an. Erhöhtes Slippage-Risiko für alle Orders!")
    else:
        st.success("🟢 **Markt-Radar:** Keine High-Impact US-Termine heute.")

    st.markdown("---")
    
    # Helfer zum Abrufen der aktuellen Order-Daten (Tab-unabhängig)
    def get_global_order_data():
        if st.session_state.get("active_order_ticker"):
            sym = st.session_state.active_order_ticker
            if "scanner_results" in st.session_state and not st.session_state.scanner_results.empty:
                df = st.session_state.scanner_results
                if sym in df["Ticker"].values: return sym, df[df["Ticker"] == sym].iloc[0], "swing"
            if "watchlist_results" in st.session_state and not st.session_state.watchlist_results.empty:
                df_w = st.session_state.watchlist_results
                if sym in df_w["Ticker"].values: return sym, df_w[df_w["Ticker"] == sym].iloc[0], "swing"
        if st.session_state.get("active_futures_order"):
            sym = st.session_state.active_futures_order
            if st.session_state.get("futures_scan_results"):
                df = pd.DataFrame(st.session_state.futures_scan_results["tb_data"])
                if sym in df["Ticker"].values: return sym, df[df["Ticker"] == sym].iloc[0], "prop"
        return None, None, None

    active_sym, row_data, desk_type = get_global_order_data()
    if not desk_type:
        # ZUSTAND A: RUHEZUSTAND
        st.info("👈 Wähle in der Tabelle eines Scanners die Checkbox '🛒 Order' aus, um den automatischen Positions- und Risiko-Rechner zu laden.")
    
    elif desk_type == "swing":
        # ZUSTAND B: SWING-DESK (Aktien & Krypto)
        st.header("📋 Broker-Order-Desk (Aktien & Krypto)")
        if st.button("🗑️ Order-Desk leeren / Auswahl aufheben", use_container_width=True, key="global_clear_swing"):
            st.session_state.active_order_ticker = None
            st.session_state.active_futures_order = None
            st.toast("Order-Desk geleert.", icon="ℹ️")
            st.rerun()
            
        acc_opts_sidebar = {acc["name"]: acc_id for acc_id, acc in st.session_state.config.get("lab_accounts", {}).items()}
        if not acc_opts_sidebar: acc_opts_sidebar = {"Standard Portfolio": "default"}
        def_acc_id_sb = st.session_state.get("active_lab_account", list(acc_opts_sidebar.values())[0])
        def_acc_name_sb = next((n for n, idx in acc_opts_sidebar.items() if idx == def_acc_id_sb), list(acc_opts_sidebar.keys())[0])
        
        konto_options = list(acc_opts_sidebar.keys()) + ["[Manuell / Sandbox-Demo]"]
        if def_acc_name_sb not in konto_options: def_acc_name_sb = konto_options[0]
        sel_acc_name = st.selectbox("Ziel-Konto:", konto_options, index=konto_options.index(def_acc_name_sb), key=f"global_acc_swing_{active_sym}")
        
        temp_config = json.loads(json.dumps(st.session_state.config))
        is_sandbox_swing = (sel_acc_name == "[Manuell / Sandbox-Demo]")
        
        if is_sandbox_swing:
            st.warning("💡 **Sandbox-Modus:** Reine Kalkulation zur Demonstration. Das Einbuchen in Konten ist gesperrt.")
            c_sb1, c_sb2 = st.columns(2)
            sandbox_cap = c_sb1.number_input("Kontokapital (€)", value=10000.0, step=1000.0, key=f"sb_cap_swing_{active_sym}")
            sandbox_risk_mode = c_sb2.selectbox("Risiko-Modus", ["Festes Euro-Risiko (€)", "Prozentuales Konto-Risiko (%)", "Feste Investition (€)"], key=f"sb_mode_swing_{active_sym}")
            sandbox_risk_val = st.number_input("Wert (€ oder %)", value=100.0 if "Euro" in sandbox_risk_mode or "Investition" in sandbox_risk_mode else 1.0, step=10.0 if "Euro" in sandbox_risk_mode or "Investition" in sandbox_risk_mode else 0.1, key=f"sb_val_swing_{active_sym}")
            
            temp_config["global_settings"]["account_size"] = sandbox_cap
            temp_config["global_settings"]["risk_mode"] = sandbox_risk_mode
            if "Euro" in sandbox_risk_mode:
                temp_config["global_settings"]["risk_eur"] = sandbox_risk_val
            elif "Prozentual" in sandbox_risk_mode:
                temp_config["global_settings"]["risk_pct"] = sandbox_risk_val
            else:
                temp_config["global_settings"]["fixed_investment"] = sandbox_risk_val
            temp_config["global_settings"]["prop_guard"] = False
            acc_prof_sb = "sandbox"
        else:
            sel_acc_id = acc_opts_sidebar[sel_acc_name]
            sel_acc_data = st.session_state.config.get("lab_accounts", {}).get(sel_acc_id, {})
            acc_prof_sb = sel_acc_data.get("exit_profile", "prop_guard")
            start_cap = float(sel_acc_data.get("account_size", 10000.0))
            
            df_j_all = load_trade_journal()
            df_j_acc = df_j_all[df_j_all['account_name'] == sel_acc_name] if not df_j_all.empty else pd.DataFrame()
            df_j_closed_sb = df_j_acc[df_j_acc['status'] == 'CLOSED'] if not df_j_acc.empty else pd.DataFrame()
            deposits_sb = df_j_closed_sb[df_j_closed_sb['setup_type'] == 'DEPOSIT']['pnl_eur'].sum() if not df_j_closed_sb.empty else 0.0
            withdrawals_sb = abs(df_j_closed_sb[df_j_closed_sb['setup_type'] == 'WITHDRAWAL']['pnl_eur'].sum()) if not df_j_closed_sb.empty else 0.0
            effective_base_sb = start_cap + deposits_sb - withdrawals_sb
            realized_pnl = df_j_closed_sb[~df_j_closed_sb['setup_type'].isin(['DEPOSIT', 'WITHDRAWAL'])]['pnl_eur'].sum() if not df_j_closed_sb.empty else 0.0
            bound_capital = df_j_acc[df_j_acc['status'] == 'OPEN']['invest_eur'].sum() if not df_j_acc.empty else 0.0
            free_cash = max(0.0, effective_base_sb + realized_pnl - bound_capital)
            
            st.caption(f"🏦 Verfügbares freies Kapital: **{free_cash:,.2f} €** (Konto: {sel_acc_name} | Profil: {get_profile_display_name(acc_prof_sb)})")
            
            temp_config["global_settings"]["account_size"] = free_cash
            temp_config["global_settings"]["risk_pct"] = sel_acc_data.get("risk_pct", 1.0)
            temp_config["global_settings"]["prop_guard"] = (acc_prof_sb in ["prop_guard", "defensive_swing", "apex_lock"])
        profile_conflict_blocked_swing = False
        admin_bypass_swing = st.session_state.get("admin_poka_bypass", False)
        acc_tax_swing = "private" if is_sandbox_swing else sel_acc_data.get("tax_category", "private")
        is_prop_firm_swing = (acc_tax_swing == "prop_firm" or "apex" in sel_acc_name.lower() or "ftmo" in sel_acc_name.lower())

        empfehlung = get_asset_strategy_recommendation(active_sym)
        with st.container(border=True):
            st.markdown(f"**🔄 Aktive Order: {active_sym} | {empfehlung['label']}**")
            st.markdown(f"🎯 **Bestes Konto:** {empfehlung['konto_typ']} | ⏱️ **{empfehlung['timeframe']}**")
            st.caption(f"_{empfehlung['hinweis']}_")
            if acc_prof_sb in empfehlung.get("valid_profiles", [empfehlung["profil"]]):
                st.success("✅ Gewähltes Kontoprofil passt perfekt zum Setup.")
            else:
                acc_prof_disp_sb = get_profile_display_name(acc_prof_sb)
                if is_prop_firm_swing:
                    if admin_bypass_swing:
                        st.warning("⚠️ **Admin-Bypass aktiv:** Profil-Sperre aufgehoben.")
                    else:
                        st.error(f"🛑 **Prop-Guard:** Profil-Konflikt! Für {active_sym} ist ausschließlich '{empfehlung['profil']}' zugelassen. Gewählt ist '{acc_prof_disp_sb}'. Um Drawdown-Verstöße und Regelbrüche auszuschließen, ist das Einloggen gesperrt.")
                        profile_conflict_blocked_swing = True
                else:
                    st.warning(f"⚠️ **Profil-Abweichung:** Gewähltes Konto nutzt '{acc_prof_disp_sb}', validiert ist jedoch '{empfehlung['profil']}'!")
        
        einstieg_val = float(str(row_data.get('Kurs', '0')).split()[0])
        sl_val = float(row_data.get('SL', row_data.get('Stop Loss (SL)', 0)))
        tp_val = float(row_data.get('TP', row_data.get('Take Profit (TP)', 0)))
        atr_val = float(row_data.get('ATR', 0))
        
        is_multi = active_sym.endswith("=F") or any(ext in active_sym.upper() for ext in ["=X", "DX-Y"])
        is_setup_b = "⚡ Long" in str(row_data.get("Ampel", ""))
        
        if is_multi or acc_prof_sb == "apex_lock": expected_days = 0.5
        elif is_setup_b: expected_days = 15
        else:
            expected_days = (abs(tp_val - einstieg_val) / atr_val) if atr_val > 0 else 0
            expected_days = max(3, expected_days)

        time_stop = round(expected_days * 1.5)
        fx = get_fx_rate(get_currency_symbol(active_sym))
        dyn_pos_size, dyn_inv_cap, dyn_max_r, est_fees, smart_status = calculate_position_size(einstieg_val, sl_val, tp_val, temp_config, fx)
        pos_size_str = f"{dyn_pos_size:.2f}"
        gewinn_eur_brutto = (tp_val - einstieg_val) * dyn_pos_size * fx if tp_val > einstieg_val else 0.0
                
        gs = st.session_state.config.get("global_settings", {})
        fee_mode_str = gs.get("fee_mode", "Keine Gebühren / Raw")
        if "1.49% Spread" in fee_mode_str or "Bitpanda Retail" in fee_mode_str: tp_fees_eur = max(2.00, (einstieg_val + tp_val) * dyn_pos_size * fx * 0.0199)
        elif "Bitpanda Fusion" in fee_mode_str or "0.10%" in fee_mode_str: tp_fees_eur = (einstieg_val + tp_val) * dyn_pos_size * fx * 0.0010
        elif "0.25% Gebühr" in fee_mode_str: tp_fees_eur = (einstieg_val + tp_val) * dyn_pos_size * fx * 0.0025
        elif "Bybit" in fee_mode_str or "0.06%" in fee_mode_str: tp_fees_eur = (einstieg_val + tp_val) * dyn_pos_size * fx * 0.0006
        elif "Apex" in fee_mode_str or "Tradovate" in fee_mode_str: tp_fees_eur = (einstieg_val + tp_val) * dyn_pos_size * fx * (0.00005 + 0.0001)
        elif "FTMO" in fee_mode_str or "MetaTrader" in fee_mode_str: tp_fees_eur = (einstieg_val + tp_val) * dyn_pos_size * fx * (0.00003 + 0.00002)
        elif "Aktien Broker" in fee_mode_str or "Interactive" in fee_mode_str or "Flatex" in fee_mode_str: tp_fees_eur = 2.00
        else: tp_fees_eur = 0.0
                
        gewinn_eur_netto = max(0.0, gewinn_eur_brutto - tp_fees_eur)
        total_risk_eur = dyn_max_r + est_fees
        sort_score = row_data.get("Sort_Score", row_data.get("Master-Score", 0))
        if isinstance(sort_score, str):
            try: sort_score = float(sort_score.split()[1].split("/")[0])
            except: sort_score = 0
            
        if is_setup_b: rec_text = "🔵 Starkes Trend-Setup (Pullback im Bullenmarkt)"
        elif sort_score >= 75: rec_text = "🚀 Starkes Setup (Kaufzone)"
        elif sort_score >= 60: rec_text = "🟡 Auf der Watchlist beobachten (Reifendes Setup)"
        else: rec_text = "🔴 Aktuell kein Einstieg"
        
        if rec_text == "🔴 Aktuell kein Einstieg": smart_status = f"⚙️ Smart Sizing: Pausiert (Kein valides Setup)"
        status_msg = f"**Status:** {rec_text}\n\n{smart_status}"
        if expected_days == 0.5: status_msg += f"\n\n⏱️ Geplante Haltedauer: Intraday (< 1 Tag / Daytrade)"
        elif expected_days > 0: status_msg += f"\n\nAufgrund der ATR (ca. {int(expected_days)} Tage) wird von einem {'kurzfristigen' if expected_days <= 7 else 'mittelfristigen'} Swing-Trade ausgegangen."
        if "Defensiv" in str(row_data.get("DNA", "")): status_msg += "\n\n⚠️ Hinweis: Geringe Volatilität (ATR < 1.8%). Nicht optimal für kurzfristige Swings (Gefahr von Time-Stops)."   
        
        _, b_count, _, _, _ = get_macro_status()
        if b_count >= 4: st.info("💡 **Markt-Empfehlung:** Starker Bullenmarkt. Profil **Home-Run Trend (Maximal-Alpha)** empfohlen.")
        else: st.info("💡 **Markt-Empfehlung:** Defensives Marktumfeld. Profil **Defensiv-Swing / Prop-Guard** empfohlen.")
        
        # Sektor-Korrelationsschutz
        df_j_check = load_trade_journal()
        open_trades_check = df_j_check[df_j_check['status'] == 'OPEN']
        curr_sector = row_data.get('Kategorie', row_data.get('Sektor', 'Standard'))
        open_sectors = []
        for open_sym in open_trades_check['symbol'].tolist():
            s_cat = "Unbekannt"
            for tag, t_data in st.session_state.config.get("scan_universes", {}).items():
                if any(t["symbol"] == open_sym for t in t_data.get("tickers", [])):
                    s_cat = tag; break
            open_sectors.append(s_cat)
            
        same_sector_count = open_sectors.count(curr_sector)
        if same_sector_count >= 2: status_msg += f"\n\n⚠️ **Korrelations-Warnung:** Bereits {same_sector_count} offene Trades im Sektor '{curr_sector}'! Max. 2 empfohlen."
        elif same_sector_count == 1: status_msg += f"\n\nℹ️ **Diversifikation:** 1 offener Trade im Sektor '{curr_sector}'."
        else: status_msg += f"\n\n✅ **Grünes Licht:** Keine offenen Trades im Sektor '{curr_sector}'. Gute Diversifikation!" 
        
        st.info(f"Aktuelles Setup: **{active_sym}**\n\n{status_msg}")    
        
        c_order1, c_order2 = st.columns(2)
        curr = get_currency_symbol(active_sym)
        curr_view = st.session_state.config.get("global_settings", {}).get("currency_view", "Duale Ansicht (Original & EUR)")
        max_limit_price = (tp_val + 1.25 * sl_val) / 2.25
        render_currency_metric(c_order1, "Aktueller Kurs (Signal)", einstieg_val, curr, fx, curr_view)
        c_order2.metric("Stückzahl", pos_size_str)
        st.info(f"🎯 Empfohlenes Kauflimit: Maximal bis {max_limit_price:.2f} {curr} | Slippage-Schutz: Limit-Order im Broker platzieren!")
        c_order3, c_order4 = st.columns(2)
        render_currency_metric(c_order3, "Stop Loss", sl_val, curr, fx, curr_view)
        render_currency_metric(c_order4, "Take Profit", tp_val, curr, fx, curr_view)
        st.markdown(f"**Reines Kursrisiko:** {dyn_max_r:.2f} € | **Geschätzte Gebühren:** {est_fees:.2f} €")
        
        risk_per_share = einstieg_val - sl_val
        if risk_per_share > 0:
            be_mark = einstieg_val + risk_per_share
            trail_mark = einstieg_val + (1.5 * risk_per_share)
            fees_per_share = (est_fees / dyn_pos_size) if dyn_pos_size > 0 else 0
            net_be = einstieg_val + (fees_per_share / fx) if fx > 0 else einstieg_val
            
            def fmt_trail(v):
                if curr_view == "Nur Bitpanda EUR (€)": return f"{(v * fx):.2f} €"
                elif curr_view == "Nur Original": return f"{v:.2f} {curr}"
                else: return f"{v:.2f} {curr} (≈ {v * fx:.2f} €)"
                
            sym_str = str(active_sym).upper()
            is_crypto_asset = any(sym_str.endswith(ext) for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF"]) or "KRYPTO" in str(row_data.get('Kategorie', row_data.get('Sektor', ''))).upper()
            
            if is_crypto_asset: st.info(f"🪙 **Krypto-DNA Matrix:**\n\n**Kein frühes BE:** Initial-SL bleibt bis +1.5 R.\n\n**Trail-Start (3.5x ATR & Netto-BE):** {fmt_trail(trail_mark)} (+1.5 R)", icon="🪙")
            elif is_setup_b: st.info(f"🎯 **Asymmetric Alpha (Setup B):**\n\n**Home-Run (Kein Scale-Out, Kein TP):**\nAb {fmt_trail(trail_mark)} (+1.5 R) greift Netto-Break-Even und offener Trend-Trail.", icon="📈")
            else: st.info(f"🎯 **Asymmetric Alpha (Setup A):**\n\n**30% Scale-Out & Netto-BE ab:** {fmt_trail(be_mark)} (+1.0 R)\n\n**Trail-Start (2.5x ATR):** {fmt_trail(trail_mark)} (+1.5 R)", icon="ℹ️") 
        
        c_order5, c_order6 = st.columns(2)
        c_order5.metric("Effektives Gesamtrisiko", f"{total_risk_eur:.2f} €")
        render_currency_metric(c_order6, "Investition", dyn_inv_cap / fx if fx > 0 else dyn_inv_cap, curr, fx, curr_view)

        c_order7, c_order8 = st.columns(2)
        render_currency_metric(c_order7, "Möglicher Gewinn (Netto)", gewinn_eur_netto / fx if fx > 0 else gewinn_eur_netto, curr, fx, curr_view)
        st.markdown(f"**Reiner Kursgewinn:** {gewinn_eur_brutto:.2f} € | **Gebühren bei TP:** {tp_fees_eur:.2f} €")
                
        if atr_val > 0:
            st.markdown(f"⏱️ **Erwartete Haltedauer:** ca. {int(expected_days)} Handelstage")
            st.markdown("---")
            is_poka_blocked = False
            admin_bypass_swing = st.session_state.get("admin_poka_bypass", False)
            
            if not is_sandbox_swing and not admin_bypass_swing:
                sym_u_poka = str(active_sym).upper()
                is_crypto_poka = any(ext in sym_u_poka for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL"]) or "KRYPTO" in str(row_data.get('Kategorie', row_data.get('Sektor', ''))).upper()
                acc_tax = sel_acc_data.get("tax_category", "private")
                
                if is_crypto_poka and (acc_tax == "prop_firm" or acc_prof_sb in ["apex_lock", "ftmo_swing"]):
                    st.error("🛑 **Krypto-Guard:** Kryptowährungen sind für Prop-Firm Challenges gesperrt (Whipsaw-Risiko). Bitte ein privates Depot wählen.")
                    is_poka_blocked = True
                elif "apex" in acc_prof_sb.lower() or "apex" in sel_acc_name.lower():
                    st.error("🛑 **Apex-Guard:** Auf Apex-Konten sind ausschließlich CME-Futures zugelassen. Aktien- und Krypto-Swings sind gesperrt.")
                    is_poka_blocked = True
                elif "ftmo" in acc_prof_sb.lower() or "ftmo" in sel_acc_name.lower():
                    st.error("🛑 **FTMO-Guard:** Dieses Konto ist für Forex-Swings reserviert. Aktien- und Krypto-Buchungen sind gesperrt.")
                    is_poka_blocked = True
            
            btn_disabled = is_sandbox_swing or is_poka_blocked or profile_conflict_blocked_swing
            market_open_swing = is_market_open_mez(active_sym, row_data.get('Kategorie', row_data.get('Sektor', '')))
            if not market_open_swing:
                st.info("⏸️ Markt geschlossen (Wochenende / Außerbörslich). Kurse basieren auf dem letzten Schlusskurs.")
            btn_help_swing = None if market_open_swing else "Achtung: Ausführung und Fills erfolgen erst zur nächsten Marktöffnung."
            real_fill_swing = st.number_input("Tatsächlicher Fill-Preis (Broker)", value=float(einstieg_val), step=0.01, format="%.2f", key=f"fill_swing_{active_sym}", help="Übertrage hier nach der Broker-Ausführung deinen echten Kurs. Standardmäßig mit dem Signal-Kurs vorausgefüllt.")
            real_risk_swing = abs(real_fill_swing - sl_val)
            real_reward_swing = abs(tp_val - real_fill_swing)
            effective_crv_swing = (real_reward_swing / real_risk_swing) if real_risk_swing > 0 else 0.0

            if real_fill_swing != einstieg_val:
                if effective_crv_swing < 1.0:
                    st.error(f"🛑 Kritische Slippage! Reales CRV auf 1:{effective_crv_swing:.2f} eingebrochen. Risiko übersteigt Gewinnchance!")
                elif effective_crv_swing < 1.25:
                    st.warning(f"⚠️ Slippage-Warnung: Reales CRV auf 1:{effective_crv_swing:.2f} gefallen. Frühes Netto-Break-Even empfohlen.")
                else:
                    st.info(f"ℹ️ Reales CRV nach Fill: 1:{effective_crv_swing:.2f}")

            if st.button("📝 Trade einloggen (Snapshot)", key=f"global_log_swing_{active_sym}", use_container_width=True, disabled=btn_disabled, help=btn_help_swing):
                df_j = load_trade_journal()
                if acc_prof_sb in ["apex_lock", "prop_guard", "defensive_swing", "apex_commodity_scale", "commodity_scale"]: determined_exit_mode = "TARGET_LOCKED" if acc_prof_sb == "apex_lock" else "PROP_DEFENSIVE"
                else: determined_exit_mode = "HOME_RUN_TREND" if is_setup_b else "ALPHA_CASHFLOW"

                dyn_inv_cap_real = dyn_pos_size * real_fill_swing * fx
                dyn_risk_eur_real = dyn_pos_size * abs(real_fill_swing - sl_val) * fx
                trade_notes_swing = ""
                if effective_crv_swing < 1.25 and real_fill_swing != einstieg_val:
                    final_exit_mode_swing = "DEFENSIVE_EMERGENCY"
                    trade_notes_swing = f"Slippage-Alert: Signal {einstieg_val:.2f} vs Fill {real_fill_swing:.2f} (CRV: {effective_crv_swing:.2f})"
                else:
                    final_exit_mode_swing = determined_exit_mode

                new_trade = {
                    'id': str(uuid.uuid4())[:8], 'account_name': sel_acc_name,
                    'entry_date': datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                    'exit_date': "", 'symbol': active_sym, 'name': row_data.get('Name', active_sym),
                    'direction': 'Long', 'signal_price': einstieg_val, 'entry_price': real_fill_swing, 'currency': curr,
                    'fx_rate': fx, 'position_size': dyn_pos_size, 'invest_eur': dyn_inv_cap_real,
                    'sl_price': sl_val, 'tp_price': tp_val, 'planned_risk_eur': dyn_risk_eur_real,
                    'est_fees_eur': est_fees, 'master_score': sort_score, 'setup_type': row_data.get("Ampel", ""),
                    'mc_robustness': row_data.get("Monte-Carlo", ""), 'atr_days': expected_days,
                    'exit_mode': final_exit_mode_swing, 'status': 'OPEN', 'exit_price': None, 'pnl_eur': None, 'pnl_pct': None,
                    'r_multiple': None, 'exit_reason': "", 'notes': trade_notes_swing,
                    'strategy_version': 'v1.0.0', 'execution_type': 'COPILOT_MANUAL'
                }
                df_j = pd.concat([df_j, pd.DataFrame([new_trade])], ignore_index=True)
                save_trade_journal(df_j)
                st.toast("✅ Trade erfolgreich im Journal archiviert!", icon="📝")
                st.rerun()

    elif desk_type == "prop":
        # ZUSTAND C: PROP-DESK (Futures & Forex)
        st.header("🎯 Prop-Firm Order-Desk (Futures & Forex)")
        if st.button("🗑️ Order-Desk leeren / Auswahl aufheben", use_container_width=True, key="global_clear_prop"):
            st.session_state.active_order_ticker = None
            st.session_state.active_futures_order = None
            st.toast("Order-Desk geleert.", icon="ℹ️")
            st.rerun()
                            
        is_shrt = row_data.get('_raw_is_short', False)
        dir_icon = "🟣 Short" if is_shrt else "🔵 Long"
        c_type = row_data.get("Empf. Größe", "0 Kontrakt").split(" ")[1] if " " in str(row_data.get("Empf. Größe", "")) else "Kontrakt"
        
        st.subheader(f"{active_sym}")
        st.markdown(f"**{row_data.get('Klasse', 'N/A')} | {row_data.get('Name', 'N/A')}**\n\n**Richtung:** {dir_icon} | **Typ:** {c_type}")
        
        acc_opts_t3 = {acc["name"]: acc_name for acc_name, acc in st.session_state.config.get("lab_accounts", {}).items()}
        if not acc_opts_t3: acc_opts_t3 = {"Standard Portfolio": "default"}
        def_acc_id_t3 = st.session_state.get("active_lab_account", list(acc_opts_t3.values())[0])
        def_acc_name_t3 = next((n for n, idx in acc_opts_t3.items() if idx == def_acc_id_t3), list(acc_opts_t3.keys())[0])
        
        konto_options_pf = list(acc_opts_t3.keys()) + ["[Manuell / Sandbox-Demo]"]
        if def_acc_name_t3 not in konto_options_pf: def_acc_name_t3 = konto_options_pf[0]
        sel_pf_acc_name = st.selectbox("Ziel-Konto:", konto_options_pf, index=konto_options_pf.index(def_acc_name_t3), key=f"pf_acc_global_{active_sym}")
        
        is_sandbox_prop = (sel_pf_acc_name == "[Manuell / Sandbox-Demo]")
        
        if is_sandbox_prop:
            st.warning("💡 **Sandbox-Modus:** Reine Kalkulation zur Demonstration. Das Einbuchen in Konten ist gesperrt.")
            c_sbp1, c_sbp2 = st.columns(2)
            sandbox_cap_pf = c_sbp1.number_input("Kontokapital ($/€)", value=50000.0, step=1000.0, key=f"sb_cap_prop_{active_sym}")
            sandbox_risk_mode_pf = c_sbp2.selectbox("Risiko-Modus", ["Festes Risiko ($/€)", "Prozentuales Risiko (%)"], key=f"sb_mode_prop_{active_sym}")
            sandbox_risk_val_pf = st.number_input("Wert ($/€ oder %)", value=500.0 if "Fest" in sandbox_risk_mode_pf else 1.0, step=50.0 if "Fest" in sandbox_risk_mode_pf else 0.1, key=f"sb_val_prop_{active_sym}")
            
            free_cash_pf = sandbox_cap_pf
            is_apex_lock = False
            prof_name = "sandbox"
            dl = sandbox_cap_pf * 0.05
            mdd = sandbox_cap_pf * 0.10
            
            if "Fest" in sandbox_risk_mode_pf:
                dyn_max_risk = sandbox_risk_val_pf
            else:
                dyn_max_risk = sandbox_cap_pf * (sandbox_risk_val_pf / 100.0)
        else:
            sel_pf_acc_id = acc_opts_t3[sel_pf_acc_name]
            sel_pf_acc_data = st.session_state.config.get("lab_accounts", {}).get(sel_pf_acc_id, {})
            is_apex_lock = sel_pf_acc_data.get("exit_profile") == "apex_lock"
            start_cap_pf = float(sel_pf_acc_data.get("account_size", 50000.0))
            
            prof_name = sel_pf_acc_data.get("exit_profile", "prop_guard")
            if prof_name == "apex_lock": dl, mdd = start_cap_pf * 0.025, start_cap_pf * 0.05
            elif prof_name == "ftmo_swing": dl, mdd = start_cap_pf * 0.05, start_cap_pf * 0.10
            else: dl, mdd = start_cap_pf * 0.05, start_cap_pf * 0.10 # Fallback
            
            df_j_all = load_trade_journal()
            df_j_acc = df_j_all[df_j_all['account_name'] == sel_pf_acc_name] if not df_j_all.empty else pd.DataFrame()
            df_j_closed_pf = df_j_acc[df_j_acc['status'] == 'CLOSED'] if not df_j_acc.empty else pd.DataFrame()
            deposits_pf = df_j_closed_pf[df_j_closed_pf['setup_type'] == 'DEPOSIT']['pnl_eur'].sum() if not df_j_closed_pf.empty else 0.0
            withdrawals_pf = abs(df_j_closed_pf[df_j_closed_pf['setup_type'] == 'WITHDRAWAL']['pnl_eur'].sum()) if not df_j_closed_pf.empty else 0.0
            effective_base_pf = start_cap_pf + deposits_pf - withdrawals_pf
            realized_pnl_pf = df_j_closed_pf[~df_j_closed_pf['setup_type'].isin(['DEPOSIT', 'WITHDRAWAL'])]['pnl_eur'].sum() if not df_j_closed_pf.empty else 0.0
            bound_capital_pf = df_j_acc[df_j_acc['status'] == 'OPEN']['invest_eur'].sum() if not df_j_acc.empty else 0.0
            free_cash_pf = max(0.0, effective_base_pf + realized_pnl_pf - bound_capital_pf)
            
            st.caption(f"🏦 Verfügbares freies Kapital: **{free_cash_pf:,.2f} €** (Konto: {sel_pf_acc_name} | Profil: {get_profile_display_name(prof_name)})")
            
            pf_risk_pct = st.radio("Risiko pro Trade (% vom Daily Loss):", [5, 10, 15], index=1, horizontal=True, key=f"pf_risk_global_{active_sym}")
            dyn_max_risk = dl * (pf_risk_pct / 100.0)
        profile_conflict_blocked_prop = False
        admin_bypass_prop = st.session_state.get("admin_poka_bypass", False)
        acc_tax_prop = "private" if is_sandbox_prop else sel_pf_acc_data.get("tax_category", "prop_firm")
        is_prop_firm_prop = (acc_tax_prop == "prop_firm" or "apex" in sel_pf_acc_name.lower() or "ftmo" in sel_pf_acc_name.lower())

        is_apex_acc_prop = not is_sandbox_prop and ("apex" in sel_pf_acc_name.lower() or prof_name == "apex_lock" or (acc_tax_prop == "prop_firm" and "ftmo" not in sel_pf_acc_name.lower() and prof_name != "ftmo_swing"))

        empfehlung = get_asset_strategy_recommendation(active_sym)
        with st.container(border=True):
            st.markdown(f"**🔄 Aktive Order: {active_sym} | {empfehlung['label']}**")
            st.markdown(f"🎯 **Bestes Konto:** {empfehlung['konto_typ']} | ⏱️ **{empfehlung['timeframe']}**")
            st.caption(f"_{empfehlung['hinweis']}_")
            if is_apex_acc_prop:
                if active_sym == "CL=F":
                    if admin_bypass_prop:
                        st.warning("⚠️ **Admin-Bypass aktiv:** Profil-Sperre aufgehoben.")
                    else:
                        st.error("🛑 Apex-Guard: Mehrtages-Swings sind auf Apex verboten (Keine Overnight-Positionen). CL=F ist ausschließlich im Privatdepot zugelassen.")
                        profile_conflict_blocked_prop = True
                elif active_sym == "NQ=F" and prof_name == "apex_lock":
                    st.success("✅ Gewähltes Kontoprofil passt perfekt zum Setup.")
                else:
                    prof_disp_pf = get_profile_display_name(prof_name)
                    if admin_bypass_prop:
                        st.warning("⚠️ **Admin-Bypass aktiv:** Profil-Sperre aufgehoben.")
                    else:
                        st.error(f"🛑 **Prop-Guard:** Profil-Konflikt! Auf Apex-Konten ist ausschließlich 'NQ=F' mit 'Target-Lock Intraday (Apex)' zugelassen (Gewählt: {active_sym} mit '{prof_disp_pf}'). Um Drawdown-Verstöße und Regelbrüche auszuschließen, ist das Einloggen gesperrt.")
                        profile_conflict_blocked_prop = True
            elif prof_name in empfehlung.get("valid_profiles", [empfehlung["profil"]]):
                st.success("✅ Gewähltes Kontoprofil passt perfekt zum Setup.")
            else:
                prof_disp_pf = get_profile_display_name(prof_name)
                if is_prop_firm_prop:
                    if admin_bypass_prop:
                        st.warning("⚠️ **Admin-Bypass aktiv:** Profil-Sperre aufgehoben.")
                    else:
                        st.error(f"🛑 **Prop-Guard:** Profil-Konflikt! Für {active_sym} ist ausschließlich '{empfehlung['profil']}' zugelassen. Gewählt ist '{prof_disp_pf}'. Um Drawdown-Verstöße und Regelbrüche auszuschließen, ist das Einloggen gesperrt.")
                        profile_conflict_blocked_prop = True
                else:
                    st.warning(f"⚠️ **Profil-Abweichung:** Gewähltes Konto nutzt '{prof_disp_pf}', validiert ist jedoch '{empfehlung['profil']}'!")

        pt_val = get_point_value(active_sym, c_type)
        
        raw_cp = float(row_data.get('_raw_cp', str(row_data.get('Kurs', '0')).split()[0]))
        raw_sl = float(row_data.get('_raw_sl', row_data.get('Stop Loss', 0)))
        raw_tp = float(row_data.get('_raw_tp', row_data.get('Take Profit', 0)))
        risk_pts_dyn = abs(raw_cp - raw_sl)
        if dyn_max_risk > free_cash_pf:
            st.warning(f"⚠️ **Kapital-Warnung:** Das geplante Risiko (${dyn_max_risk:.2f}) übersteigt das freie Kapital. Sizing wird angepasst.")
            dyn_max_risk = free_cash_pf
        
        if is_apex_lock:
            apex_cap = mdd * 0.10
            if dyn_max_risk > apex_cap:
                dyn_max_risk = apex_cap
                st.warning(f"🛡️ **Apex Lock Aktiv:** Risiko auf max. ${apex_cap:.2f} (10% vom Trailing-DD) gedeckelt.")
                
        raw_qty_dyn = dyn_max_risk / (risk_pts_dyn * pt_val) if risk_pts_dyn > 0 else 0
        is_trade_blocked = False
        is_apex = "apex" in sel_pf_acc_name.lower() or is_apex_lock
        a_class = row_data.get('Klasse', 'Futures')
        is_forex_sym = a_class == "Forex" or active_sym.endswith("=X")
        
        admin_bypass = st.session_state.get("admin_poka_bypass", False)
        is_ftmo = "ftmo" in sel_pf_acc_name.lower() or prof_name == "ftmo_swing"
        is_crypto_sym = a_class == "Krypto"

        if is_apex and not (a_class in ["Futures", "Rohstoffe"] or "=F" in str(active_sym).upper() or str(active_sym).upper().strip() == "CL=F"):
            if admin_bypass:
                st.warning("⚠️ **Admin-Bypass aktiv:** Apex-Guard umgangen.")
            else:
                st.error("🛑 **Apex-Guard:** Erlaubt strikt nur CME-Futures. Forex und Krypto sind gesperrt!")
                is_trade_blocked, raw_qty_dyn = True, 0
        elif is_ftmo and not (a_class == "Forex" or "=X" in str(active_sym).upper()):
            if admin_bypass:
                st.warning("⚠️ **Admin-Bypass aktiv:** FTMO-Guard umgangen.")
            else:
                st.error("🛑 **FTMO-Guard:** Erlaubt strikt nur Forex Majors. Futures und Krypto sind gesperrt!")
                is_trade_blocked, raw_qty_dyn = True, 0
        elif is_crypto_sym and not admin_bypass:
            st.error("🛑 **Krypto-Guard:** Krypto ist auf Prop-Firm Challenges gesperrt (Whipsaw-Risiko).")
            is_trade_blocked, raw_qty_dyn = True, 0

        if a_class in ["Futures", "Rohstoffe"]:
            qty_dyn = int(raw_qty_dyn)
            if is_apex_lock and qty_dyn > 5:
                qty_dyn = 5
                st.warning("🛡️ **Apex Lock Aktiv:** Harter Cap auf max. 5 Kontrakte.")
            size_str_dyn = f"{qty_dyn} {c_type}" if qty_dyn >= 1 else "⚠️ SL zu weit"
            actual_risk_dyn = qty_dyn * risk_pts_dyn * pt_val
        else:
            qty_dyn = round(raw_qty_dyn, 2) if a_class == "Forex" else round(raw_qty_dyn, 4)
            size_str_dyn = f"{qty_dyn} {c_type}" if qty_dyn > 0 else "⚠️ SL zu weit"
            actual_risk_dyn = qty_dyn * risk_pts_dyn * pt_val
        if not is_sandbox_prop and acc_tax_prop == "private" and active_sym == "NQ=F":
            if qty_dyn < 1:
                if not admin_bypass:
                    profile_conflict_blocked_prop = True
                    st.error("🛑 Poka-Yoke Kapitalschutz: Das aktuelle Stop-Loss-Risiko für 1 Micro-Kontrakt (MNQ) übersteigt dein eingestelltes Risikobudget. Um CME-Futures im Privatkonto regeltreu (max. 1.0% Risiko) zu handeln, ist ein Kontokapital ab ca. 15.000 € (oder eine Risikoanpassung) erforderlich.")
            
        if is_trade_blocked: size_str_dyn, actual_risk_dyn = "🚫 Gesperrt", 0.0
        
        c_b1, c_b2 = st.columns(2)
        c_b1.metric("Einstieg", f"{raw_cp:.4f}")
        c_b2.metric("Größe", size_str_dyn)
        
        c_b3, c_b4 = st.columns(2)
        c_b3.metric("Stop Loss", f"{raw_sl:.4f}")
        c_b4.metric("Take Profit", f"{raw_tp:.4f}")
        if is_shrt:
            max_limit_prop = (raw_tp + 1.25 * raw_sl) / 2.25
        else:
            max_limit_prop = (raw_tp + 1.25 * raw_sl) / 2.25
        fmt = ".4f" if is_forex_sym else ".2f"
        st.caption(f"🎯 Max. Limit-Preis (CRV ≥ 1.25): {max_limit_prop:{fmt}} | Slippage-Schutz: Limit-Order empfohlen!")
        st.markdown(f"**Abstand:** {row_data.get('Abstand', 'N/A')}")
        st.markdown(f"**Punktwert:** ${pt_val:.2f} pro {c_type}")
        st.markdown(f"**Effektives Risiko:** ${actual_risk_dyn:.2f}" if actual_risk_dyn > 0 else "**Effektives Risiko:** N/A")
        
        if actual_risk_dyn > 0:
            risk_per_unit = risk_pts_dyn * pt_val
            st.caption(f"💡 **Formel:** {risk_pts_dyn:.4f} Abstand × ${pt_val:.2f} Punktwert = **${risk_per_unit:.2f}** Risiko pro {c_type}. Bei ${dyn_max_risk:.2f} Risikolimit ergibt das **{qty_dyn} {c_type}**.")
        st.markdown("---")
        is_multi_t3 = active_sym.endswith("=F") or any(ext in active_sym.upper() for ext in ["=X", "DX-Y"])
        if is_multi_t3 or is_apex_lock: exp_days_t3 = 0.5
        else: exp_days_t3 = 15 if "Trend" in str(row_data.get("Signal", "")) else 3
        
        if exp_days_t3 == 0.5: st.markdown("⏱️ **Geplante Haltedauer:** Intraday (< 1 Tag / Daytrade)")
        else: st.markdown(f"⏱️ **Erwartete Haltedauer:** ca. {exp_days_t3} Handelstage")

        _, b_count, _, _, _ = get_macro_status()
        if b_count >= 4: st.info("💡 **Markt-Empfehlung:** Starker Bullenmarkt. Profil **Home-Run Trend (Maximal-Alpha)** empfohlen.")
        else: st.info("💡 **Markt-Empfehlung:** Defensives Marktumfeld. Profil **Defensiv-Swing / Prop-Guard** empfohlen.")
        
        btn_disabled_prop = is_trade_blocked or is_sandbox_prop or profile_conflict_blocked_prop
        market_open_prop = is_market_open_mez(active_sym, row_data.get('Klasse', 'Futures'))
        if not market_open_prop:
            st.info("⏸️ Markt geschlossen (Wochenende / Außerbörslich). Kurse basieren auf dem letzten Schlusskurs.")
        btn_help_prop = None if market_open_prop else "Achtung: Ausführung und Fills erfolgen erst zur nächsten Marktöffnung."
        step_prop = 0.0001 if is_forex_sym else 0.25
        fmt_prop = "%.4f" if is_forex_sym else "%.2f"
        fmt_prop_str = ".4f" if is_forex_sym else ".2f"
        real_fill_prop = st.number_input("Tatsächlicher Fill-Preis (Broker)", value=float(raw_cp), step=step_prop, format=fmt_prop, key=f"fill_prop_{active_sym}", help="Übertrage hier nach der Broker-Ausführung deinen echten Kurs. Standardmäßig mit dem Signal-Kurs vorausgefüllt.")
        real_risk_prop = abs(real_fill_prop - raw_sl)
        real_reward_prop = abs(raw_tp - real_fill_prop)
        effective_crv_prop = (real_reward_prop / real_risk_prop) if real_risk_prop > 0 else 0.0

        if real_fill_prop != raw_cp:
            if effective_crv_prop < 1.0:
                st.error(f"🛑 Kritische Slippage! Reales CRV auf 1:{effective_crv_prop:.2f} eingebrochen. Risiko übersteigt Gewinnchance!")
            elif effective_crv_prop < 1.25:
                st.warning(f"⚠️ Slippage-Warnung: Reales CRV auf 1:{effective_crv_prop:.2f} gefallen. Frühes Netto-Break-Even empfohlen.")
            else:
                st.info(f"ℹ️ Reales CRV nach Fill: 1:{effective_crv_prop:.2f}")

        if st.button("📝 In Prop-Journal einloggen", type="primary", use_container_width=True, key=f"global_log_pf_{active_sym}", disabled=btn_disabled_prop, help=btn_help_prop):
            df_j = load_trade_journal()
            fx_usd_eur = get_fx_rate("$", "EUR")
            
            if prof_name in ["apex_lock", "prop_guard", "defensive_swing", "apex_commodity_scale", "commodity_scale"]: determined_exit_mode = "TARGET_LOCKED" if prof_name == "apex_lock" else "PROP_DEFENSIVE"
            else: determined_exit_mode = "HOME_RUN_TREND" if "Trend" in str(row_data.get("Signal", "")) else "ALPHA_CASHFLOW"

            actual_risk_real = qty_dyn * real_risk_prop * pt_val
            if effective_crv_prop < 1.25 and real_fill_prop != raw_cp:
                final_exit_mode_prop = "DEFENSIVE_EMERGENCY"
                trade_notes_prop = f"Prop-Desk ({size_str_dyn}) | Slippage-Alert: Signal {raw_cp:{fmt_prop_str}} vs Fill {real_fill_prop:{fmt_prop_str}} (CRV: {effective_crv_prop:.2f})"
            else:
                final_exit_mode_prop = determined_exit_mode
                trade_notes_prop = f"Prop-Desk ({size_str_dyn})"

            new_trade = {
                'id': str(uuid.uuid4())[:8], 'account_name': sel_pf_acc_name,
                'entry_date': datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                'exit_date': "", 'symbol': active_sym, 'name': row_data.get("_raw_name", active_sym),
                'direction': 'Short' if is_shrt else 'Long',
                'signal_price': raw_cp, 'entry_price': real_fill_prop, 'currency': get_currency_symbol(active_sym),
                'fx_rate': fx_usd_eur, 'position_size': qty_dyn,
                'contract_type': c_type, 'point_value': pt_val, 'base_currency': "USD",
                'invest_eur': 0, 'sl_price': raw_sl, 'tp_price': raw_tp, 
                'planned_risk_eur': actual_risk_real * fx_usd_eur, 'est_fees_eur': 0.0,
                'master_score': row_data.get("Sort_Score", 0), 'setup_type': row_data.get("Signal", ""),
                'mc_robustness': "Prop-Firm Validated", 'atr_days': exp_days_t3,
                'exit_mode': final_exit_mode_prop, 'status': 'OPEN', 'exit_price': None, 'pnl_eur': None, 'pnl_pct': None,
                'r_multiple': None, 'exit_reason': "", 'notes': trade_notes_prop,
                'strategy_version': 'v1.0.0', 'execution_type': 'COPILOT_MANUAL'
            }
            df_j = pd.concat([df_j, pd.DataFrame([new_trade])], ignore_index=True)
            save_trade_journal(df_j)
            st.toast(f"✅ Trade für {active_sym} in '{sel_pf_acc_name}' eingeloggt!", icon="📝")
            st.rerun()
    with st.expander("⚙️ Globale Standardvorgaben (Erweitert)", expanded=False):
        with st.form("sidebar_risk_form_advanced"):
            gs = st.session_state.config.get("global_settings", {})
            new_prop_guard = st.checkbox("🛡️ Prop-Firm Modus (Risiko-Limitierung global)", value=bool(gs.get("prop_guard", True)))
            new_dyn_scaling = st.checkbox("⚡ Dynamische CRV-Skalierung erlauben (Smart Sizing)", value=bool(gs.get("dynamic_risk_scaling", False)))
            new_compounding = st.checkbox("⚡ Zinseszins (Compounding) im Risk-Management", value=bool(gs.get("compounding", False)))
            st.markdown("---")
            stored_fee = gs.get("fee_mode", "Keine Gebühren / Raw")
            fee_opts = [
                "Apex / Tradovate (Futures Insti-Rate)",
                "FTMO / MetaTrader 5 (Forex Raw Spread)",
                "Interactive Brokers / Flatex (Aktien Flat)",
                "Bybit / Krypto-Börse (0.06% / 0.02%)",
                "Bitpanda Fusion (0.10% / 0.05%)",
                "Bitpanda Retail (1.49% Spread)",
                "Keine Gebühren / Raw"
            ]
            if stored_fee not in fee_opts:
                if "1.49%" in stored_fee or "Retail" in stored_fee: stored_fee = "Bitpanda Retail (1.49% Spread)"
                elif "Fusion" in stored_fee or "0.25%" in stored_fee or "0.10%" in stored_fee: stored_fee = "Bitpanda Fusion (0.10% / 0.05%)"
                elif "Bybit" in stored_fee or "0.06%" in stored_fee: stored_fee = "Bybit / Krypto-Börse (0.06% / 0.02%)"
                elif "Aktien Broker" in stored_fee or "Flat" in stored_fee or "Interactive" in stored_fee or "Flatex" in stored_fee: stored_fee = "Interactive Brokers / Flatex (Aktien Flat)"
                elif "Apex" in stored_fee or "Tradovate" in stored_fee: stored_fee = "Apex / Tradovate (Futures Insti-Rate)"
                elif "FTMO" in stored_fee or "MetaTrader" in stored_fee: stored_fee = "FTMO / MetaTrader 5 (Forex Raw Spread)"
                else: stored_fee = "Keine Gebühren / Raw"
            fee_idx = fee_opts.index(stored_fee)
            new_fee_mode = st.selectbox("Gebühren-Modus", fee_opts, index=fee_idx)
        
            new_curr_view = st.radio("Währungs-Ansicht", ["Duale Ansicht (Original & EUR)", "Nur Bitpanda EUR (€)", "Nur Original"], index=["Duale Ansicht (Original & EUR)", "Nur Bitpanda EUR (€)", "Nur Original"].index(gs.get("currency_view", "Duale Ansicht (Original & EUR)")))
            
            if st.form_submit_button("💾 Standardvorgaben speichern", use_container_width=True):
                st.session_state.config["global_settings"].update({
                    "prop_guard": new_prop_guard, "currency_view": new_curr_view,
                    "dynamic_risk_scaling": new_dyn_scaling, "fee_mode": new_fee_mode,
                    "compounding": new_compounding
                })
                save_config(st.session_state.config)
                st.success("Gespeichert!")
                st.rerun()
#endregion

#region MAIN APP TABS
tab_screen, tab_futures, tab_lab = st.tabs(["⚡ Swing-Scanner (Aktien & Krypto)", "🎯 Prop-Desk (Futures & Forex)", "🏦 Konten- & Portfolio-Desk"])
#endregion

#region TAB 1 UI (DEAKTIVIERT)
_UNUSED_TAB_1_CODE = '''
with tab_watch:

    with st.expander("⚙️ 🛠️ Pro-Modus (Longterm Einstellungen)", expanded=False):
        c_key = "counter_tab1_settings"
        if c_key not in st.session_state: st.session_state[c_key] = 0
        cc = st.session_state[c_key]
        
        with st.form(key=f"form_tab1_{cc}", border=False):
            gs = st.session_state.config.get("global_settings", {})
            new_vals = {}
            
            st.markdown("#### 1. Indikatoren-Schwellenwerte")
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: new_vals["threshold_mode"] = st.radio("Modus", ["Statisch", "Dynamisch (Z-Score)"], index=["Statisch", "Dynamisch (Z-Score)"].index(gs.get("threshold_mode", "Statisch")), key=f"tm_{cc}")
            with c2: new_vals["rsi_defensiv"] = st.number_input("RSI Kauf (Def)", value=float(gs.get("rsi_defensiv", 35.0)), step=1.0, key=f"rd_{cc}")
            with c3: new_vals["rsi_aggressiv"] = st.number_input("RSI Kauf (Agg)", value=float(gs.get("rsi_aggressiv", 30.0)), step=1.0, key=f"ra_{cc}")
            with c4: new_vals["rsi_sell_defensiv"] = st.number_input("RSI Verkauf (Def)", value=float(gs.get("rsi_sell_defensiv", 70.0)), step=1.0, key=f"rsd_{cc}")
            with c5: new_vals["rsi_sell_aggressiv"] = st.number_input("RSI Verkauf (Agg)", value=float(gs.get("rsi_sell_aggressiv", 80.0)), step=1.0, key=f"rsa_{cc}")
            
            c6, c7, _, _, _ = st.columns(5)
            with c6: new_vals["z_score_buy"] = st.number_input("Z-Score Kauf", value=float(gs.get("z_score_buy", -2.0)), step=0.5, key=f"zb_{cc}")
            with c7: new_vals["z_score_sell"] = st.number_input("Z-Score Verkauf", value=float(gs.get("z_score_sell", 2.0)), step=0.5, key=f"zs_{cc}")
            
            if st.form_submit_button("💾 Einstellungen speichern", use_container_width=True):
                st.session_state.config["global_settings"].update(new_vals)
                save_config(st.session_state.config)
                st.success("Gespeichert!")
                st.rerun()

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("❌ Änderungen verwerfen", key="discard_tab1", use_container_width=True):
                st.session_state[c_key] += 1
                st.rerun()
        with col_b2:
            if st.button("🔄 Tab 1 Einstellungen zurücksetzen", key="reset_tab1", use_container_width=True):
                st.session_state.config["global_settings"] = {"threshold_mode": "Statisch", "rsi_defensiv": 35.0, "rsi_aggressiv": 30.0, "rsi_sell_defensiv": 70.0, "rsi_sell_aggressiv": 80.0, "z_score_buy": -2.0, "z_score_sell": 2.0, "ema_trend_default": 200.0, "custom_sectors": [], "risk_mode": "Festes Euro-Risiko (€)", "account_size": 10000.0, "risk_eur": 100.0, "risk_pct": 1.0, "fixed_investment": 1000.0}
                save_config(st.session_state.config)
                st.session_state[c_key] += 1
                st.rerun()

    # --- START NEU: ESG UI ---
    with st.expander("🌱 ESG & Ethik-Filter (Blacklist)", expanded=False):
        esg_cfg = st.session_state.config.get("esg_blacklist", {"aktiv": False, "tickers": []})
        c_esg1, c_esg2 = st.columns([1, 2])
        with c_esg1:
            esg_aktiv = st.checkbox("Ethik-Filter (ESG Blacklist) aktivieren", value=esg_cfg.get("aktiv", False))
            if esg_aktiv != esg_cfg.get("aktiv", False):
                st.session_state.config["esg_blacklist"]["aktiv"] = esg_aktiv
                save_config(st.session_state.config)
                st.rerun()
        with c_esg2:
            current_esg_tickers = esg_cfg.get("tickers", [])
            selected_esg = st.multiselect("Aktuelle Blacklist:", options=current_esg_tickers, default=current_esg_tickers)
            new_esg = st.text_input("Neuen Ticker sperren (z.B. RHM.DE):")
            if st.button("💾 Blacklist speichern", use_container_width=True):
                updated_esg = list(set(selected_esg))
                if new_esg and new_esg.strip().upper() not in updated_esg:
                    updated_esg.append(new_esg.strip().upper())
                st.session_state.config["esg_blacklist"]["tickers"] = updated_esg
                save_config(st.session_state.config)
                st.success("Blacklist aktualisiert!")
                st.rerun()

    render_search_bar("tickers", is_tab1=True)
    render_management_panel("tickers", show_sectors=True)

    with st.expander("⚙️ Individuelle Ticker-Einstellungen (Tabelle)", expanded=False):
        df_c = pd.DataFrame([{"#": i+1, "Ticker": t["symbol"], "Name": t["name"], "Sektor": t.get("sector", "Standard"), "Risiko": t.get("risk_class", "Wachstum/Aggressiv"), "Custom?": t.get("use_custom", False), "Ziel RSI Unten": float(t.get("custom_rsi_buy", 30)), "Ziel RSI Oben": float(t.get("custom_rsi_sell", 70))} for i, t in enumerate(st.session_state.config["tickers"])])
        if not df_c.empty:
            opts_sec = sorted(list(set(["Standard", "Cybersecurity", "Tech", "ETF", "Industrie", "Krypto"] + st.session_state.config["global_settings"].get("custom_sectors", []) + [t.get("sector", "Standard") for t in st.session_state.config["tickers"]])))
            edited = st.data_editor(df_c, hide_index=True, use_container_width=True, disabled=["#", "Ticker", "Name"], column_config={"Sektor": st.column_config.SelectboxColumn(options=opts_sec), "Risiko": st.column_config.SelectboxColumn(options=["Defensiv", "Wachstum/Aggressiv"])})
            upd = [{"symbol": r["Ticker"], "name": r["Name"], "sector": r["Sektor"], "risk_class": r["Risiko"], "use_custom": r["Custom?"], "custom_rsi_buy": float(r["Ziel RSI Unten"]), "custom_rsi_sell": float(r["Ziel RSI Oben"])} for _, r in edited.iterrows()]
            if upd != st.session_state.config["tickers"]: st.session_state.config["tickers"] = upd; save_config(st.session_state.config); st.rerun()

    st.markdown("---")
    if st.button("🔔 Alarm Bot aktualisieren (GitHub Push)", use_container_width=True):
        ok, msg = push_to_github()
        st.success(msg) if ok else st.error(msg)

    t_list = [t["symbol"] for t in st.session_state.config["tickers"]]
    if t_list:
        with st.spinner("Lade Wochen-Daten..."):
            try:
                b_df = fetch_market_data(t_list, "5y", "1wk")
                if isinstance(b_df.columns, pd.MultiIndex) and len(t_list) == 1: b_df.columns = b_df.columns.get_level_values(0)
                res_t1, tb_data = {}, []
                for t_dict in st.session_state.config["tickers"]:
                    sym, rsk, cst = t_dict["symbol"], t_dict["risk_class"], t_dict["use_custom"]
                    t_b = float(t_dict["custom_rsi_buy"]) if cst else st.session_state.config["global_settings"]["rsi_defensiv" if rsk == "Defensiv" else "rsi_aggressiv"]
                    t_s = float(t_dict["custom_rsi_sell"]) if cst else st.session_state.config["global_settings"]["rsi_sell_defensiv" if rsk == "Defensiv" else "rsi_sell_aggressiv"]
                    
                    df_t = b_df[sym].copy() if len(t_list) > 1 else b_df.copy()
                    if not df_t.empty and "Close" in df_t:
                        glob_cfg = st.session_state.config.get("global_settings", {})
                        dyn_mode = glob_cfg.get("threshold_mode", "Statisch") == "Dynamisch (Z-Score)"
                        z_b_val = float(glob_cfg.get("z_score_buy", -2.0))
                        z_s_val = float(glob_cfg.get("z_score_sell", 2.0))
                        
                        calc = calc_rsi_and_targets(df_t, t_b, t_s, strategy_mode="5_saeulen_core", is_dynamic=dyn_mode, z_buy=z_b_val, z_sell=z_s_val)
                        if calc:
                            r, p_b, p_s, plot, details = calc
                            res_t1[sym] = (plot, t_b, t_s, t_dict["name"], t_dict["sector"])
                            c_p_raw = plot['Close'].iloc[-1]
                            c_p, warn_icon = validate_price_sanity(c_p_raw, plot)
                            
                            rs_ratio = calc_relative_strength(sym, plot)
                            if rs_ratio is None: rs_str = "⚪ N/A"
                            elif rs_ratio >= 1.05: rs_str = f"🟢 {rs_ratio:.2f}"
                            elif rs_ratio < 0.95: rs_str = f"🔴 {rs_ratio:.2f}"
                            else: rs_str = f"⚪ {rs_ratio:.2f}"
                            
                            ema_200 = plot['EMA_200'].iloc[-1]
                            ema_20 = plot['EMA_20'].iloc[-1]
                            
                            esg_cfg = st.session_state.config.get("esg_blacklist", {})
                            is_esg_blocked = esg_cfg.get("aktiv", False) and sym in esg_cfg.get("tickers", [])

                            if is_esg_blocked: signal_text = "🚫 ESG-Sperre"
                            elif r >= t_s: signal_text = "🔴 Zu teuer"
                            elif r <= t_b:
                                if c_p > ema_200: signal_text = "🟢 Kaufen"
                                elif c_p > ema_20: signal_text = "🟠 Bodenbildung (Rebound)"
                                else: signal_text = "🔴 Blockiert (Trend)"
                            else: signal_text = "➖ Warten"
                            if is_esg_blocked: signal_text = "🚫 ESG-Sperre"
                            elif r >= t_s: signal_text = "🔴 Zu teuer"
                            elif "Trend-Kauf" in details["ampel"]: signal_text = details["ampel"]
                            elif r <= t_b:
                                if c_p > ema_200: signal_text = "🟢 Kaufen"
                                elif c_p > ema_20: signal_text = "🟠 Bodenbildung (Rebound)"
                                else: signal_text = "🔴 Blockiert (Trend)"
                            else: signal_text = "➖ Warten"
                            sl, tp, crv_rating = calculate_sl_tp_crv(plot, c_p, p_s, "tab1")

                            mc_ratio, mc_label = run_monte_carlo_test(c_p, sl, tp)
                            fx_rate = get_fx_rate(get_currency_symbol(sym))
                            pos_size, inv_cap, _, _, _ = calculate_position_size(c_p, sl, tp, st.session_state.config, fx_rate)
                            pos_size_str = f"{int(pos_size)} Stk." if float(pos_size).is_integer() else f"{pos_size:.4f} Stk."
                        
                            tb_data.append({
                            "Sektor": t_dict["sector"], "Ticker": sym, "Name": t_dict["name"], 
                            "Kurs": f"{c_p:.2f} {warn_icon}".strip(), "RSI": f"{r:.2f}", "Z-Score": f"{details.get('z_score', 0):.2f}",
                            "Säulen-Details": details["breakdown"], "Rel. Stärke": rs_str, 
                            "Kauf-Zielpreis": f"{p_b:.2f}", "Verkauf-Zielpreis": f"{p_s:.2f}", 
                            "Stop Loss (SL)": f"{sl:.2f}", "Take Profit (TP)": f"{tp:.2f}", 
                            "CRV Rating": crv_rating, "Signal": signal_text, 
                            "Plateau": details.get("plateau", "⚪ N/A"), "Monte-Carlo": mc_label,
                            "Stückzahl": pos_size_str, "Investition": f"{inv_cap:,.2f} €"
                            })
                if tb_data:
                    st.subheader("📊 Live-Auswertung")
                    df_res = pd.DataFrame(tb_data)
                    sel_sec = st.selectbox("📂 Nach Sektor filtern:", ["Alle"] + sorted(list(df_res["Sektor"].unique())))
                    f_res = df_res if sel_sec == "Alle" else df_res[df_res["Sektor"] == sel_sec]
                   
                    def highlight_tab1(row):
                        sig = str(row["Signal"])
                        if "ESG-Sperre" in sig: return ["background-color: #e2e3e5; color: #383d41; text-decoration: line-through;"] * len(row)
                        if "Zu teuer" in sig or "Blockiert" in sig: return ["background-color: #f8d7da; color: #721c24; font-weight: bold"] * len(row)
                        if "Bodenbildung" in sig: return ["background-color: #fff3cd; color: #856404; font-weight: bold"] * len(row)
                        if "Kaufen" in sig: return ["background-color: #d4edda; color: #155724; font-weight: bold"] * len(row)
                        if "Trend-Kauf" in sig: return ["background-color: #cce5ff; color: #004085; font-weight: bold"] * len(row)
                        return [""] * len(row)
                    st.dataframe(f_res.style.apply(highlight_tab1, axis=1), use_container_width=True, hide_index=True)
                    render_chart_system(res_t1, "t1", sel_sec, show_trend_box=True)
            except Exception as e: st.error(f"Fehler: {e}")
'''
#endregion

#region TAB 2 UI
with tab_screen:
    st.header("⚡ Shortterm Scanner & Scoring")
    st.markdown("Durchsuche vordefinierte Markt-Universen nach deinen Kriterien und speichere die besten Setups als Favoriten.")

    render_dynamic_settings(
        "🛠️ Pro-Modus: 6-Säulen-Bedingungen", "pro_mode_settings", 
        [
            {"label": "EMA 200 (Killerkriterium)", "key": "ema200_killer", "default": "Aktiv", "type": "radio", "options": ["Aktiv", "Inaktiv"], "help": "Zeigt den langfristigen Trend. Kurs über der Linie = Aufwärtstrend, darunter = Abwärtstrend (Achtung, fallendes Messer!)."}, 
            {"label": "RSI Extremzone", "key": "rsi_aktiv", "default": "Aktiv", "type": "radio", "options": ["Aktiv", "Inaktiv"], "help": "Misst die aktuelle Markttemperatur. Ist der Wert unter deiner gesetzten Grenze, gilt der Markt als 'überverkauft' (potenziell günstig)."}, 
            {"label": "Bollinger Bänder", "key": "bollinger_aktiv", "default": "Aktiv", "type": "radio", "options": ["Aktiv", "Inaktiv"], "help": "Zeigt die Schwankungsbreite. Kratzt der Kurs am unteren Band, ist er statistisch gesehen ungewöhnlich stark gefallen."}, 
            {"label": "MACD Trend", "key": "macd_aktiv", "default": "Aktiv", "type": "radio", "options": ["Aktiv", "Inaktiv"], "help": "Misst den Schwung (Momentum). Dreht der Indikator ins Plus, baut sich neuer Kaufdruck auf."}, 
            {"label": "Volumen-Bestätigung", "key": "volumen_aktiv", "default": "Aktiv", "type": "radio", "options": ["Aktiv", "Inaktiv"], "help": "Prüft, ob aktuell überdurchschnittlich stark gehandelt wird. Ein hohes Volumen gibt dem Signal mehr Gewicht."},
            {"label": "Keltner Kanal (Volatilität)", "key": "keltner_aktiv", "default": "Aktiv", "type": "radio", "options": ["Aktiv", "Inaktiv"], "help": "Nutzt die Average True Range (ATR). Fällt der Kurs unter das untere Band, liegt eine starke Übertreibung vor."},
            {"label": "Plateau-Check (Overfitting)", "key": "plateau_aktiv", "default": "Inaktiv", "type": "radio", "options": ["Aktiv", "Inaktiv"], "help": "Prüft Nachbar-Parameter (z.B. RSI 12, 13, 15, 16). Schützt vor Glückstreffern."}
        ], 
        key_prefix="tab2_", expanded=False, reset_label="🔄 Tab 2 Einstellungen zurücksetzen", defaults_to_reset={"ema200_killer": "Aktiv", "rsi_aktiv": "Aktiv", "bollinger_aktiv": "Aktiv", "macd_aktiv": "Aktiv", "volumen_aktiv": "Aktiv", "keltner_aktiv": "Aktiv", "plateau_aktiv": "Inaktiv"}, extra_resets={"tab2_settings": {"tf": "1d", "rsi_buy": 30.0, "rsi_sell": 70.0}}
    )

    st.subheader("📂 Universen & Listen verwalten")
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        with st.expander("📂 Listen verwalten (Neu / Löschen)", expanded=False):
            new_u = st.text_input("Neue Liste erstellen (z.B. 'Meine Tech Aktien'):", key="new_u")
            if st.button("➕ Liste erstellen") and new_u:
                f_name = new_u.replace(" ", "_").lower() + ".json"
                os.makedirs(MEGA_LISTS_DIR, exist_ok=True)
                with open(os.path.join(MEGA_LISTS_DIR, f_name), "w", encoding="utf-8") as f: json.dump([], f)
                st.success(f"Liste '{new_u}' erstellt!"); st.rerun()
            st.markdown("---")
            available_universes = list(st.session_state.config.get("scan_universes", {}).keys())
            del_u = st.selectbox("Liste komplett löschen:", ["- Auswählen -"] + available_universes, key="del_u_list")
            if st.button("🗑️ Liste löschen") and del_u != "- Auswählen -":
                f_name = del_u.replace(" ", "_").lower() + ".json"
                f_path = os.path.join(MEGA_LISTS_DIR, f_name)
                if os.path.exists(f_path): os.remove(f_path)
                del st.session_state.config["scan_universes"][del_u]
                st.success(f"Liste '{del_u}' wurde physisch gelöscht!"); st.rerun()

    with col_u2:
        with st.expander("✏️ Ticker in Liste bearbeiten / löschen", expanded=False):
            if available_universes:
                sel_u = st.selectbox("Liste auswählen:", available_universes, key="sel_u")
                tickers_in_list = st.session_state.config["scan_universes"][sel_u].get("tickers", [])
                del_opt = {f"{t['symbol']} ({t['name']})": t['symbol'] for t in tickers_in_list}
                to_delete = st.multiselect("Wähle Wertpapiere zum Löschen:", list(del_opt.keys()), key="del_u_tickers")
                if st.button("🗑️ Ausgewählte Ticker löschen", type="primary", key="btn_del_u_tickers") and to_delete:
                    syms_del = [del_opt[i] for i in to_delete]
                    new_data = [t for t in tickers_in_list if t["symbol"] not in syms_del]
                    f_name = sel_u.replace(" ", "_").lower() + ".json"
                    with open(os.path.join(MEGA_LISTS_DIR, f_name), "w", encoding="utf-8") as f: json.dump(new_data, f, indent=4)
                    st.success("Ticker erfolgreich gelöscht!"); st.rerun()
                st.markdown("---")
                st.write("Schnelleingabe (Tabelle):")
                df_u = pd.DataFrame(tickers_in_list)
                if df_u.empty: df_u = pd.DataFrame(columns=["symbol", "name"])
                ed_u = st.data_editor(df_u, num_rows="dynamic", use_container_width=True, key="ed_u")
                if st.button("💾 Tabellen-Änderungen speichern", key="save_u"):
                    new_data = [{"symbol": r["symbol"], "name": r["name"]} for _, r in ed_u.iterrows() if pd.notna(r.get("symbol")) and str(r.get("symbol")).strip() != ""]
                    f_name = sel_u.replace(" ", "_").lower() + ".json"
                    with open(os.path.join(MEGA_LISTS_DIR, f_name), "w", encoding="utf-8") as f: json.dump(new_data, f, indent=4)
                    st.success(f"{sel_u} wurde aktualisiert!"); st.rerun()
            else: st.info("Keine Listen vorhanden.")
    st.markdown("---")
    st.subheader("⚙️ Scanner-Kriterien & Universum")
    available_universes = list(st.session_state.config.get("scan_universes", {}).keys())
    
    # Sektoren filtern basierend auf Anlageklasse
    crypto_tags = []
    equity_tags = []
    for tag in available_universes:
        tag_upper = tag.upper()
        is_crypto_tag = ("KRYPTO" in tag_upper) or ("CRYPTO" in tag_upper)
        if not is_crypto_tag:
            for t in st.session_state.config.get("scan_universes", {}).get(tag, {}).get("tickers", []):
                if any(ext in str(t.get("symbol", "")).upper() for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]):
                    is_crypto_tag = True
                    break
        
        if is_crypto_tag and not ("FUTURES" in tag_upper or "CME" in tag_upper):
            crypto_tags.append(tag)
        elif not is_crypto_tag:
            equity_tags.append(tag)
    
    scan_asset_filter = st.radio(
        "Anlageklasse für den Scan (Primärer Fokus: Aktien & ETFs):", 
        ['📈 Aktien & ETFs', '🪙 Krypto'],
        index=0,
        format_func=lambda x: "🪙 Krypto (Labor-Modus)" if x == "🪙 Krypto" else x,
        horizontal=True
    )

    scan_mode_z = st.radio("Berechnungs-Modus (RSI vs. Z-Score):", ["Statisch (RSI)", "Dynamisch (Z-Score)"], horizontal=True, key="scan_mode_z")
    
    valid_tags = crypto_tags if scan_asset_filter == '🪙 Krypto' else equity_tags
    default_tags = valid_tags if valid_tags else None

    if scan_asset_filter == '🪙 Krypto':
        scan_all_tags = True
        selected_tags = valid_tags
        st.caption(f"📁 Scanne automatisch alle {len(valid_tags)} Krypto-Listen ({', '.join(valid_tags[:4])}...)")
    else:
        scan_all_tags = st.checkbox("🌐 Alle verfügbaren Listen dieser Klasse scannen", value=True, key="scan_all_tags_cb")
        if scan_all_tags:
            st.caption(f"📁 Scanne alle {len(valid_tags)} Listen dieser Anlageklasse ({', '.join(valid_tags[:4])}...)")
            selected_tags = valid_tags
        else:
            selected_tags = st.multiselect("Gezielte Listen auswählen:", valid_tags, default=valid_tags[:3] if len(valid_tags) >= 3 else valid_tags)

    with st.form(key="scanner_form", border=False):
        c1, c2, c3 = st.columns(3)
        with c1: scan_tf = st.radio("Timeframe:", ["1d", "1wk"], key="scan_tf", horizontal=True)
        with c2: 
            default_rsi = 25.0 if scan_asset_filter == '🪙 Krypto' else 30.0
            default_z = -2.2 if scan_asset_filter == '🪙 Krypto' else -2.0
            asset_key_suffix = "crypto" if scan_asset_filter == '🪙 Krypto' else "equity"
            if scan_mode_z == "Statisch (RSI)":
                scan_limit = st.number_input("RSI Grenzwert:", value=default_rsi, step=1.0, key=f"scan_limit_rsi_{asset_key_suffix}")
            else:
                scan_limit = st.number_input("Z-Score Grenzwert:", value=default_z, step=0.5, key=f"scan_limit_z_{asset_key_suffix}")
        with c3: 
            st.write("")
        run_scanner = st.form_submit_button("🚀 Scanner starten", type="primary", use_container_width=True)

    st.markdown("---")
    st.subheader("📋 Suchergebnisse & Favoriten-Auswahl")
    
    if "scanner_results" not in st.session_state: st.session_state.scanner_results = pd.DataFrame()
    
    if run_scanner:
        if not selected_tags:
            st.warning("⚠️ Bitte wähle mindestens einen Tag aus.")
        else:
            with st.spinner("Initialisiere Live-Scan..."):
                all_tickers_to_scan = []
                seen_symbols = set()
                
                for tag in selected_tags:
                    tag_data = st.session_state.config.get("scan_universes", {}).get(tag, {})
                    for t_dict in tag_data.get("tickers", []):
                        sym = str(t_dict["symbol"]).strip()
                        sym_u = sym.upper()
                        tag_u = str(tag).upper()
                        
                        # Strict Asset-Check basierend auf der Pill-Auswahl
                        is_crypto_sym = any(ext in sym_u for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]) or ("KRYPTO" in tag_u or "CRYPTO" in tag_u)
                        is_forex_sym = any(ext in sym_u for ext in ["=X", "DX-Y"])
                        is_future_sym = "=F" in sym_u
                        
                        keep = False
                        if scan_asset_filter == '📈 Aktien & ETFs' and not (is_crypto_sym or is_forex_sym or is_future_sym):
                            keep = True
                        elif scan_asset_filter == '🪙 Krypto' and is_crypto_sym and not (is_forex_sym or is_future_sym):
                            keep = True
                            if "-" not in sym_u and "." not in sym_u:
                                sym = f"{sym_u}-USD"
                        
                        if keep and sym not in seen_symbols:
                            seen_symbols.add(sym)
                            merged_t = t_dict.copy()
                            merged_t["symbol"] = sym
                            merged_t["source_universe"] = tag
                            all_tickers_to_scan.append(merged_t)
                            
            if not all_tickers_to_scan:
                st.warning("Keine Ticker in den ausgewählten Tags gefunden.")
            else:
                # Setup für Progressive Live-Loading (Batching / Chunking)
                BATCH_SIZE = 25
                total_tickers = len(all_tickers_to_scan)
                scan_results_list = []
                
                # Container für Live-UI Updates
                live_status = st.empty()
                live_progress = st.progress(0)
                live_table_preview = st.empty()
                
                esg_cfg = st.session_state.config.get("esg_blacklist", {})
                period = "1y" if scan_tf == "1d" else "5y"
                
                for i in range(0, total_tickers, BATCH_SIZE):
                    batch = all_tickers_to_scan[i:i + BATCH_SIZE]
                    batch_symbols = [t["symbol"] for t in batch]
                    
                    live_status.text("Laden...")
                    live_progress.progress(min((i + BATCH_SIZE) / total_tickers, 1.0))
                    
                    try:
                        b_df = fetch_market_data(batch_symbols, period, scan_tf)
                        if isinstance(b_df.columns, pd.MultiIndex) and len(batch_symbols) == 1: 
                            b_df.columns = b_df.columns.get_level_values(0)
                            
                        for t_dict in batch:
                            sym, name, source_u = t_dict["symbol"], t_dict["name"], t_dict["source_universe"]
                            
                            if esg_cfg.get("aktiv", False) and sym in esg_cfg.get("tickers", []):
                                continue
                                
                            try:
                                df_t = b_df[sym].copy() if (isinstance(b_df.columns, pd.MultiIndex) and sym in b_df.columns.get_level_values(0)) else (b_df.xs(sym, level=1, axis=1).copy() if isinstance(b_df.columns, pd.MultiIndex) else b_df.copy())
                            except Exception:
                                continue
                                
                            if not df_t.empty and "Close" in df_t:
                                t_sell = st.session_state.config["tab2_settings"].get("rsi_sell", 70.0)
                                is_dyn = (scan_mode_z == "Dynamisch (Z-Score)")
                                calc = calc_rsi_and_targets(df_t, scan_limit if not is_dyn else 30.0, t_sell, strategy_mode="5_saeulen_core", is_dynamic=is_dyn, z_buy=scan_limit if is_dyn else -2.0, ticker=sym)
                                
                                if calc:
                                    r, p_b, p_s, plot, details = calc
                                    is_crypto_scan = (details.get("asset_class") == "CRYPTO")
                                    ampel_str = str(details.get("ampel", ""))
                                    is_hit = (
                                        (details.get("z_score", 0) <= scan_limit if is_dyn else r <= scan_limit)
                                        or ("Long" in ampel_str)
                                        or ("Kauf" in ampel_str)
                                    )
                                    min_atr_req = 1.5 if is_crypto_scan else 2.5
                                    if not is_hit or details.get("atr_pct", 0.0) < min_atr_req:
                                        continue
                                    c_p_raw = plot['Close'].iloc[-1]
                                    c_p, warn_icon = validate_price_sanity(c_p_raw, plot)
                                    rs_ratio = calc_relative_strength(sym, plot)
                                    sl, tp, crv_rating = calculate_sl_tp_crv(plot, c_p, p_s, "tab2")
                                    
                                    mc_ratio, mc_label = run_monte_carlo_test(c_p, sl, tp)
                                    fx_rate = get_fx_rate(get_currency_symbol(sym))
                                    pos_size, inv_cap, max_r_eur, fee_rt, _ = calculate_position_size(c_p, sl, tp, st.session_state.config, fx_rate)
                                    m_score_val, m_score_str, m_score_breakdown = calculate_master_score(details, crv_rating, rs_ratio, r, scan_limit)

                                    rsi_display = f"{r:.2f} (Z: {details.get('z_score', 0):.2f})" if details.get("is_dynamic") else f"{r:.2f}"
                                    scan_results_list.append({
                                        "Favorit": False, "Kategorie": source_u, "Ticker": sym, "Name": name, 
                                        "DNA": details.get("dna", "⚪ N/A"), "ATR%": details.get("atr_pct", 0.0),
                                        "Kurs": f"{c_p:.2f} {warn_icon}".strip(), "RSI": rsi_display, 
                                        "Master-Score": m_score_str, "Score-Details": m_score_breakdown, 
                                        "Ampel": details["ampel"], "Säulen": f"{details['score']}/{details['score_max']}", 
                                        "Säulen-Details": details["breakdown"], "Plateau": details.get("plateau", "⚪ N/A"), 
                                        "Sort_Score": m_score_val, "CRV Rating": crv_rating, 
                                        "Rel. Stärke": f"{rs_ratio:.2f}" if rs_ratio else "N/A",
                                        "MC_Ratio": mc_ratio, "Monte-Carlo": mc_label,
                                        "Stückzahl": f"{int(pos_size)} Stk." if float(pos_size).is_integer() else f"{pos_size:.4f} Stk.", 
                                        "Investition": f"{inv_cap:,.2f} €",
                                        "SL": sl, "TP": tp, "MaxRiskEur": max_r_eur,
                                        "ATR": details.get("atr", 0.0)
                                    })
                    except Exception:
                        pass
                    
                    # Nach jedem Batch: Puffer aktualisieren und Live-Tabelle sortiert ausgeben
                    if scan_results_list:
                        temp_df = pd.DataFrame(scan_results_list).sort_values(by=["Sort_Score", "RSI"], ascending=[False, True])
                        st.session_state.scanner_results = temp_df
                        with live_table_preview.container():
                            st.caption(f"🔄 Live-Zwischenstand ({len(scan_results_list)} Treffer bisher gefiltert)...")
                            st.dataframe(temp_df[["Kategorie", "Ticker", "Name", "Kurs", "Master-Score", "Ampel"]].head(5), use_container_width=True, hide_index=True)

                # Aufräumen der Live-Anzeigen nach Beendigung
                live_status.empty()
                live_progress.empty()
                live_table_preview.empty()
                if scan_results_list:
                    st.success(f"✅ Scan abgeschlossen! {len(scan_results_list)} relevante Setups gefunden.")
                else:
                    st.session_state.scanner_results = pd.DataFrame()
                    st.info(f"ℹ️ Scan über {total_tickers} Werte abgeschlossen: Aktuell notiert kein Wert in der überverkauften Extremzone (Z <= {scan_limit} bzw. RSI <= {scan_limit}). Alle geprüften Werte sind aktuell neutral oder überhitzt.")

    if "scanner_results" in st.session_state and not st.session_state.scanner_results.empty:
        st.info("Wähle deine Favoriten in der linken Spalte aus und speichere sie ab.")
        disp_df = st.session_state.scanner_results.copy()
        
        # --- NEU: Gesamtsieger (Overall Top 3) ---
        st.markdown("### 🏆 Top Picks (Gesamtauswahl)")
        overall_top3 = disp_df.head(3)
        if not overall_top3.empty:
            cols_ov = st.columns(3)
            medals = ["🥇 1. Platz", "🥈 2. Platz", "🥉 3. Platz"]
            for i, (_, row) in enumerate(overall_top3.iterrows()):
                with cols_ov[i]:
                    # Zeigt auch an, aus welchem Universum der Gesamtsieger stammt
                    st.metric(label=f"{medals[i]}: {row['Ticker']} ({row['Kategorie']})", value=row["Master-Score"], delta=row["Ampel"], delta_color="off")
        st.markdown("---")
        
        # 1. Top-Picks pro Universum anzeigen (Kacheln)
        st.markdown("### 🏅 Top 3 pro Universum")
        for univ in disp_df["Kategorie"].unique():
            univ_df = disp_df[disp_df["Kategorie"] == univ].head(3) 
            if not univ_df.empty:
                st.markdown(f"**{univ}**")
                cols = st.columns(3)
                for i, (_, row) in enumerate(univ_df.iterrows()):
                    with cols[i]:
                        st.metric(label=f"{medals[i]}: {row['Ticker']}", value=row["Master-Score"], delta=row["Ampel"], delta_color="off")
        
        st.markdown("---")
        
        # --- FIX: Die Farb-Funktion wieder einfügen! ---
        def highlight_ampel(val):
            val_str = str(val)
            if "⚡ Long (Trend)" in val_str: return "background-color: #cce5ff; color: #004085; font-weight: bold"
            if "🔄 Long (Reversal)" in val_str: return "background-color: #d1ecf1; color: #0c5460; font-weight: bold"
            if "Rebound" in val_str: return "background-color: #fff3cd; color: #856404; font-weight: bold"
            if "Zu teuer" in val_str or "Blockiert" in val_str: return "background-color: #f8d7da; color: #721c24; font-weight: bold"
            return "background-color: #fff3cd; color: #856404;"
        # 2. Dynamischer Filter für die Haupttabelle
        sel_univ = st.selectbox("📂 Universum filtern:", ["Alle Universen"] + sorted(list(disp_df["Kategorie"].unique())))
        filtered_df = disp_df if sel_univ == "Alle Universen" else disp_df[disp_df["Kategorie"] == sel_univ]
        
        if not filtered_df.empty:
            filtered_df_clean = filtered_df.drop(columns=["Sort_Score"])
            
            if "scanner_favorite_tickers" not in st.session_state: st.session_state.scanner_favorite_tickers = []
            if "active_order_ticker" not in st.session_state: st.session_state.active_order_ticker = None
            if "scanner_info_tickers" not in st.session_state: st.session_state.scanner_info_tickers = []
            
            filtered_df_clean["Favorit"] = filtered_df_clean["Ticker"].isin(st.session_state.scanner_favorite_tickers)
            filtered_df_clean.insert(1, "🛒 Order", filtered_df_clean["Ticker"] == st.session_state.active_order_ticker)
            filtered_df_clean.insert(2, "🔍 Info", filtered_df_clean["Ticker"].isin(st.session_state.scanner_info_tickers))
            display_cols = ["Favorit", "🛒 Order", "🔍 Info", "Ticker", "Name", "Kategorie", "DNA", "Kurs", "Master-Score", "Ampel"]
            edited_df = st.data_editor(
                filtered_df_clean[display_cols].style.map(highlight_ampel, subset=["Ampel"]), 
                hide_index=True, 
                use_container_width=True, 
                disabled=["Ticker", "Name", "Kategorie", "DNA", "Kurs", "Master-Score", "Ampel"], 
                column_config={
                    "Favorit": st.column_config.CheckboxColumn("📌 Speichern", default=False),
                    "🛒 Order": st.column_config.CheckboxColumn("🛒 Order", default=False),
                    "🔍 Info": st.column_config.CheckboxColumn("🔍 Info", default=False)
                },
                key="scanner_editor"
            )
            
            # Info-Boxen (Multi-Select fähig)
            new_infos = edited_df[edited_df["🔍 Info"] == True]["Ticker"].tolist()
            if set(new_infos) != set(st.session_state.scanner_info_tickers):
                st.session_state.scanner_info_tickers = new_infos

            # Favoriten State-Sicherung (View-Ebene vs. Global)
            new_favs_view = edited_df[edited_df["Favorit"] == True]["Ticker"].tolist()
            view_tickers = filtered_df_clean["Ticker"].tolist()
            current_favs = set(st.session_state.scanner_favorite_tickers)
            for t in view_tickers:
                if t in new_favs_view: current_favs.add(t)
                else: current_favs.discard(t)
            st.session_state.scanner_favorite_tickers = list(current_favs)

            # Sidebar Broker-Order (Exklusivitäts-Logik mit Toast)
            current_orders = edited_df[edited_df["🛒 Order"] == True]["Ticker"].tolist()
            selected_ticker = None
            if len(current_orders) > 0:
                new_ones = [t for t in current_orders if t != st.session_state.active_order_ticker]
                if new_ones: selected_ticker = new_ones[0]
                elif len(current_orders) == 1 and st.session_state.active_order_ticker != current_orders[0]: selected_ticker = current_orders[0]
            
            if selected_ticker:
                if st.session_state.get("active_futures_order"):
                    old_asset = st.session_state.active_futures_order
                    st.session_state.active_futures_order = None
                    st.toast(f"⚠️ Aktive Order für {old_asset} verworfen – {selected_ticker} in den Order-Desk geladen!", icon="🔄")
                elif st.session_state.get("active_order_ticker"):
                    old_asset = st.session_state.active_order_ticker
                    st.toast(f"⚠️ Vorherige Order für {old_asset} durch {selected_ticker} ersetzt!", icon="🔄")
                else:
                    st.toast(f"🛒 Order-Desk geladen für: {selected_ticker}", icon="✅")
                st.session_state.active_order_ticker = selected_ticker
                st.rerun()
            elif len(current_orders) == 0 and st.session_state.active_order_ticker in filtered_df_clean["Ticker"].values:
                st.session_state.active_order_ticker = None
                st.toast("Order-Desk geleert.", icon="ℹ️")
                st.rerun()

            for sym in st.session_state.scanner_info_tickers:
                if sym in disp_df["Ticker"].values:
                    row_data = disp_df[disp_df["Ticker"] == sym].iloc[0]
                    breakdown_str = row_data.get('Score-Details', '')
                    parts = breakdown_str.split()
                    pts_saeulen = int(parts[0].split(":")[1]) if len(parts) > 0 else 0
                    pts_crv = int(parts[1].split(":")[1]) if len(parts) > 1 else 0
                    pts_rs = int(parts[2].split(":")[1]) if len(parts) > 2 else 0
                    pts_signal = int(parts[3].split(":")[1]) if len(parts) > 3 else 0
                    
                    with st.container(border=True):
                        st.markdown(f"### 🔍 Detail-Analyse: **{row_data['Ticker']}** ({row_data['Name']})")
                        sym_u_scan = str(sym).upper().strip()
                        if sym_u_scan == "NQ=F":
                            richtwert_str = "Ziel-Korridor: 60–65 (Deckel: Werte >= 70 meiden)"
                        elif sym_u_scan in ["CL=F", "MCL"]:
                            richtwert_str = "Ziel-Korridor: 65–70"
                        elif sym_u_scan in ["USDJPY=X", "GBPUSD=X"]:
                            richtwert_str = "Ziel-Korridor: 60–70"
                        elif sym_u_scan == "EURUSD=X":
                            richtwert_str = "Ziel-Korridor: 65–75"
                        elif any(ext in sym_u_scan for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]):
                            richtwert_str = "Ziel-Korridor: 65–80"
                        elif "=F" in sym_u_scan or any(ext in sym_u_scan for ext in ["=X", "DX-Y"]):
                            richtwert_str = "Ziel-Korridor: 60–70"
                        else:
                            richtwert_str = "Zielwert: >= 70 (Relative Stärke)"
                        st.metric(label="🚀 Gesamtwertung", value=f"{row_data.get('Master-Score', 'N/A')} | {richtwert_str}", delta=row_data.get("Ampel", ""), delta_color="off")
                        st.markdown(f"**🧬 Ticker-DNA:** {row_data.get('DNA', 'N/A')} (ATR: {row_data.get('ATR%', 0.0):.2f}%)")
                        sort_score = row_data.get("Sort_Score", 0)
                        guideline_scan = get_action_guideline(sym_u_scan, sort_score, row_data.get("DNA", ""))
                        if "🛑" in guideline_scan or "⚠️" in guideline_scan:
                            st.warning(f"**🧭 Handlungsanweisung:** {guideline_scan}")
                        else:
                            st.info(f"**🧭 Handlungsanweisung:** {guideline_scan}")
                        if "⚡ Long" in row_data.get("Ampel", ""): rec_text = "🔵 Starkes Trend-Setup (Pullback im Bullenmarkt)"
                        elif sort_score >= 75: rec_text = "🚀 Starkes Setup (Kaufzone)"
                        elif sort_score >= 60: rec_text = "🟡 Auf der Watchlist beobachten (Reifendes Setup)"
                        else: rec_text = "🔴 Aktuell kein Einstieg"
                        st.markdown(f"**Empfehlung:** {rec_text}")
                        st.markdown("---")
                        rec_t2_scan = get_asset_strategy_recommendation(sym)
                        with st.container(border=True):
                            st.markdown(f"**🧬 Strategie-DNA & Empfehlung**")
                            st.markdown(f"**{rec_t2_scan['label']}**")
                            st.markdown(f"🎯 **Konto:** {rec_t2_scan['konto_typ']} | ⏱️ **TF:** {rec_t2_scan['timeframe']}")
                            st.markdown(f"**Profil:** `{rec_t2_scan['profil']}`")
                            st.caption(f"_{rec_t2_scan['hinweis']}_")
                        st.markdown("""<style>[data-testid="stProgress"] { margin-top: -10px !important; margin-bottom: 35px !important; } [data-testid="stProgress"] > div > div > div, [data-testid="stProgress"] > div > div { height: 28px !important; border-radius: 10px !important; }</style>""", unsafe_allow_html=True)
                        c_bars, c_empty = st.columns(2)
                        with c_bars:
                            is_setup_b = "Trend-Kauf" in str(row_data.get("Ampel", ""))
                            max_saeulen = 35 if is_setup_b else 45
                            max_crv = 20 if is_setup_b else 30
                            
                            st.markdown(f"**🏛️ Indikatoren: {pts_saeulen} / {max_saeulen} Pkt.**")
                            st.progress(min(pts_saeulen / float(max_saeulen), 1.0))
                            st.info(f"Details: {row_data.get('Säulen-Details', 'N/A')}")
                            st.write("")
                            st.markdown(f"**⚖️ CRV-Bonus: {pts_crv} / {max_crv} Pkt.** ({row_data.get('CRV Rating', 'N/A')})")
                            st.progress(min(pts_crv / float(max_crv), 1.0))
                            
                            if is_setup_b:
                                st.markdown(f"**📈 Rel. Stärke: {pts_rs} / 30 Pkt.** (Ratio: {row_data.get('Rel. Stärke', 'N/A')})")
                                st.progress(min(pts_rs / 30.0, 1.0))
                            else:
                                st.markdown(f"**📈 Rel. Stärke: 0 / 0 Pkt.** (⚪ N/A – Rebound-Setup)")
                                st.progress(0.0)
                                st.caption("ℹ️ Bei antizyklischen Rebounds (Setup A) ist eine schwache relative Stärke mathematisch normal und wird nicht bewertet.")
                                
                            st.markdown(f"**🛡️ Signal & Plateau: {pts_signal} / 15 Pkt.** ({row_data.get('Plateau', 'N/A')})")
                            st.progress(min(pts_signal / 15.0, 1.0))
                            mc_ratio_val = float(row_data.get("MC_Ratio", 0.0))
                            st.markdown(f"**🎲 Monte-Carlo Stresstest:** {row_data.get('Monte-Carlo', 'N/A')}")
                            
            col_btn1, col_btn2, col_btn3 = st.columns(3)
            fav_cands = st.session_state.scanner_favorite_tickers
            
            with col_btn1:
                if st.button("💾 In Shortterm-Liste (Tab 2) speichern", use_container_width=True):
                    if fav_cands:
                        added = 0
                        sel_rows = disp_df[disp_df["Ticker"].isin(fav_cands)]
                        for _, row in sel_rows.iterrows():
                            if not any(t["symbol"] == row["Ticker"] for t in st.session_state.config["screener_tickers"]):
                                st.session_state.config["screener_tickers"].append({"symbol": row["Ticker"], "name": row["Name"], "sector": row["Kategorie"]})
                                added += 1
                        if added > 0: save_config(st.session_state.config); st.success(f"✅ {added} Ticker in Tab 2 gespeichert!")
                        else: st.info("ℹ️ Ticker waren bereits in der Liste.")
            with col_btn2:
                if st.button("➡️ In Longterm Watchlist (Tab 1) kopieren", type="primary", use_container_width=True):
                    if fav_cands:
                        added = 0
                        sel_rows = disp_df[disp_df["Ticker"].isin(fav_cands)]
                        for _, row in sel_rows.iterrows():
                            if not any(t["symbol"] == row["Ticker"] for t in st.session_state.config["tickers"]):
                                st.session_state.config["tickers"].append({"symbol": row["Ticker"], "name": row["Name"], "sector": row["Kategorie"], "risk_class": "Wachstum/Aggressiv", "use_custom": False, "custom_rsi_buy": st.session_state.config["global_settings"]["rsi_aggressiv"], "custom_rsi_sell": st.session_state.config["global_settings"]["rsi_sell_aggressiv"]})
                                added += 1
                        if added > 0: save_config(st.session_state.config); st.success(f"✅ {added} Ticker nach Tab 1 kopiert!")
                        else: st.info("ℹ️ Ticker waren bereits in Tab 1.")
            with col_btn3:
                if st.button("📤 An Kader-Optimizer senden (Tab 4)", type="primary", use_container_width=True):
                    if fav_cands:
                        st.session_state["transfer_candidates"] = list(set(st.session_state.get("transfer_candidates", []) + fav_cands))
                        st.toast(f"✅ {len(fav_cands)} Kandidaten für den Tab 4 Optimizer vorgemerkt!", icon="📤")
                    else:
                        st.info("ℹ️ Bitte wähle zuerst Favoriten (📌 Speichern) aus.")

    st.markdown("---")
    st.header("📌 Deine gespeicherte Shortterm Watchlist")
    render_search_bar("screener_tickers", is_tab1=False)
    render_management_panel("screener_tickers", show_sectors=False)

    with st.expander("⚙️ Individuelle Ticker-Einstellungen (Tabelle)", expanded=False):
        df_st = pd.DataFrame([{"#": i+1, "Ticker": t["symbol"], "Name": t["name"], "Sektor": t.get("sector", "Standard")} for i, t in enumerate(st.session_state.config["screener_tickers"])])
        if not df_st.empty:
            edited_st = st.data_editor(df_st, hide_index=True, use_container_width=True, disabled=["#", "Ticker", "Name"])
            upd_st = [{"symbol": r["Ticker"], "name": r["Name"], "sector": r["Sektor"]} for _, r in edited_st.iterrows()]
            if upd_st != st.session_state.config["screener_tickers"]: st.session_state.config["screener_tickers"] = upd_st; save_config(st.session_state.config); st.rerun()

    t_list_2 = [t["symbol"] for t in st.session_state.config["screener_tickers"]]
    if t_list_2:
        with st.spinner("Lade Shortterm-Daten..."):
            try:
                tf = st.session_state.config["tab2_settings"].get("tf", "1d")
                period = "1y" if tf == "1d" else "5y"
                b_df2 = fetch_market_data(t_list_2, period, tf)
                if isinstance(b_df2.columns, pd.MultiIndex) and len(t_list_2) == 1: b_df2.columns = b_df2.columns.get_level_values(0)
                res_t2, tb_data2 = {}, []
                t_b2 = st.session_state.config["tab2_settings"].get("rsi_buy", 30.0)
                t_s2 = st.session_state.config["tab2_settings"].get("rsi_sell", 70.0)
                for t_dict in st.session_state.config["screener_tickers"]:
                    sym = t_dict["symbol"]
                    df_t = pd.DataFrame()
                    if isinstance(b_df2.columns, pd.MultiIndex):
                        if sym in b_df2.columns.get_level_values(0): df_t = b_df2[sym].copy()
                        elif sym in b_df2.columns.get_level_values(1): df_t = b_df2.xs(sym, level=1, axis=1).copy()
                    else: df_t = b_df2.copy()
                    
                    if not df_t.empty and "Close" in df_t:
                        calc = calc_rsi_and_targets(df_t, t_b2, t_s2, strategy_mode="5_saeulen_core", ticker=sym)
                        if calc:
                            r, p_b, p_s, plot, details = calc

                            esg_cfg = st.session_state.config.get("esg_blacklist", {})
                            if esg_cfg.get("aktiv", False) and sym in esg_cfg.get("tickers", []):
                                details["ampel"] = "🚫 ESG-Sperre"

                            res_t2[sym] = (plot, t_b2, t_s2, t_dict["name"], t_dict.get("sector", "Standard"))
                            
                            c_p_raw = plot['Close'].iloc[-1]
                            c_p, warn_icon = validate_price_sanity(c_p_raw, plot)
                            
                            sl, tp, crv_rating = calculate_sl_tp_crv(plot, c_p, p_s, "tab2")
                            mc_ratio, mc_label = run_monte_carlo_test(c_p, sl, tp)
                            fx_rate = get_fx_rate(get_currency_symbol(sym))
                            pos_size, inv_cap, max_r_eur, fee_rt, _ = calculate_position_size(c_p, sl, tp, st.session_state.config, fx_rate)
                            pos_size_str = f"{int(pos_size)} Stk." if float(pos_size).is_integer() else f"{pos_size:.4f} Stk."

                            rs_ratio = calc_relative_strength(sym, plot)
                            m_score_val, m_score_str, m_score_breakdown = calculate_master_score(details, crv_rating, rs_ratio, r, t_b2)

                            tb_data2.append({
                                "Sektor": t_dict.get("sector", "Standard"), "Ticker": sym, "Name": t_dict["name"],
                                "DNA": details.get("dna", "⚪ N/A"), "ATR%": details.get("atr_pct", 0.0), 
                                "Kurs": f"{c_p:.2f} {warn_icon}".strip(), "RSI": f"{r:.2f}", "Z-Score": f"{details.get('z_score', 0):.2f}",
                                "Säulen-Details": details["breakdown"], "Kauf-Zielpreis": f"{p_b:.2f}", 
                                "Verkauf-Zielpreis": f"{p_s:.2f}", "Stop Loss (SL)": f"{sl:.2f}", 
                                "Take Profit (TP)": f"{tp:.2f}", "CRV Rating": crv_rating, 
                                "Ampel": details["ampel"], "Plateau": details.get("plateau", "⚪ N/A"),
                                "Monte-Carlo": mc_label, "Stückzahl": pos_size_str, "Investition": f"{inv_cap:,.2f} €",
                                "Master-Score": m_score_str, "Score-Details": m_score_breakdown, "Rel. Stärke": f"{rs_ratio:.2f}" if rs_ratio else "N/A",
                                "ATR": details.get("atr", 0.0)
                            })
                if tb_data2:
                    st.subheader("📊 Live-Auswertung (Shortterm)")
                    df_res2 = pd.DataFrame(tb_data2)
                    st.session_state.watchlist_results = df_res2
                    sel_sec2 = st.selectbox("📂 Nach Sektor filtern:", ["Alle"] + sorted(list(df_res2["Sektor"].unique())), key="sec_filter_t2")
                    f_res2 = df_res2 if sel_sec2 == "Alle" else df_res2[df_res2["Sektor"] == sel_sec2]
                    def highlight_ampel_t2(val):
                        val_str = str(val)
                        if "ESG-Sperre" in val_str: return "background-color: #e2e3e5; color: #383d41; text-decoration: line-through;"
                        if "⚡ Long (Trend)" in val_str: return "background-color: #cce5ff; color: #004085; font-weight: bold"
                        if "🔄 Long (Reversal)" in val_str: return "background-color: #d1ecf1; color: #0c5460; font-weight: bold"
                        if "Rebound" in val_str: return "background-color: #fff3cd; color: #856404; font-weight: bold"
                        if "Zu teuer" in val_str or "Blockiert" in val_str: return "background-color: #f8d7da; color: #721c24; font-weight: bold"
                        return ""
                    f_res2_disp = f_res2.copy()
                    if "active_order_ticker" not in st.session_state: st.session_state.active_order_ticker = None
                    if "watchlist_info_tickers" not in st.session_state: st.session_state.watchlist_info_tickers = []
                    
                    f_res2_disp.insert(0, "🛒 Order", f_res2_disp["Ticker"] == st.session_state.active_order_ticker)
                    f_res2_disp.insert(1, "🔍 Info", f_res2_disp["Ticker"].isin(st.session_state.watchlist_info_tickers))
                    display_cols_w = ["🛒 Order", "🔍 Info", "Ticker", "Name", "Sektor", "DNA", "Kurs", "Master-Score", "RSI", "Ampel"]
                    edited_w = st.data_editor(
                        f_res2_disp[display_cols_w].style.map(highlight_ampel_t2, subset=["Ampel"]), 
                        use_container_width=True, hide_index=True,
                        disabled=["Ticker", "Name", "Sektor", "DNA", "Kurs", "Master-Score", "RSI", "Ampel"],
                        column_config={
                            "🛒 Order": st.column_config.CheckboxColumn("🛒 Order", default=False),
                            "🔍 Info": st.column_config.CheckboxColumn("🔍 Info", default=False)
                        },
                        key="watchlist_tab2_editor"
                    )
                    
                    # Info-Box (Multi-Select fähig)
                    new_infos_w = edited_w[edited_w["🔍 Info"] == True]["Ticker"].tolist()
                    if set(new_infos_w) != set(st.session_state.watchlist_info_tickers):
                        st.session_state.watchlist_info_tickers = new_infos_w

                    # Sidebar Broker-Order (Exklusivitäts-Logik mit Toast)
                    current_orders_w = edited_w[edited_w["🛒 Order"] == True]["Ticker"].tolist()
                    selected_ticker_w = None
                    if len(current_orders_w) > 0:
                        new_ones = [t for t in current_orders_w if t != st.session_state.active_order_ticker]
                        if new_ones: selected_ticker_w = new_ones[0]
                        elif len(current_orders_w) == 1 and st.session_state.active_order_ticker != current_orders_w[0]: selected_ticker_w = current_orders_w[0]
                    
                    if selected_ticker_w:
                        if st.session_state.get("active_futures_order"):
                            old_asset = st.session_state.active_futures_order
                            st.session_state.active_futures_order = None
                            st.toast(f"⚠️ Aktive Order für {old_asset} verworfen – {selected_ticker_w} in den Order-Desk geladen!", icon="🔄")
                        elif st.session_state.get("active_order_ticker"):
                            old_asset = st.session_state.active_order_ticker
                            st.toast(f"⚠️ Vorherige Order für {old_asset} durch {selected_ticker_w} ersetzt!", icon="🔄")
                        else:
                            st.toast(f"🛒 Order-Desk geladen für: {selected_ticker_w}", icon="✅")
                        st.session_state.active_order_ticker = selected_ticker_w
                        st.rerun()
                    elif len(current_orders_w) == 0 and st.session_state.active_order_ticker in f_res2_disp["Ticker"].values:
                        st.session_state.active_order_ticker = None
                        st.toast("Order-Desk geleert.", icon="ℹ️")
                        st.rerun()
                        
                    for sym in st.session_state.watchlist_info_tickers:
                        if sym in f_res2_disp["Ticker"].values:
                            w_row = f_res2_disp[f_res2_disp["Ticker"] == sym].iloc[0]
                            
                            breakdown_str = w_row.get('Score-Details', '')
                            parts = breakdown_str.split()
                            pts_saeulen = int(parts[0].split(":")[1]) if len(parts) > 0 else 0
                            pts_crv = int(parts[1].split(":")[1]) if len(parts) > 1 else 0
                            pts_rs = int(parts[2].split(":")[1]) if len(parts) > 2 else 0
                            pts_signal = int(parts[3].split(":")[1]) if len(parts) > 3 else 0
                            
                            with st.container(border=True):
                                st.markdown(f"### 🔍 Maximale Tiefe: **{w_row['Ticker']}** ({w_row['Name']}) | Sektor: {w_row.get('Sektor', 'N/A')}")
                                sym_u_watch = str(sym).upper().strip()
                                if sym_u_watch == "NQ=F":
                                    richtwert_str = "Ziel-Korridor: 60–65 (Deckel: Werte >= 70 meiden)"
                                elif sym_u_watch in ["CL=F", "MCL"]:
                                    richtwert_str = "Ziel-Korridor: 65–70"
                                elif sym_u_watch in ["USDJPY=X", "GBPUSD=X"]:
                                    richtwert_str = "Ziel-Korridor: 60–70"
                                elif sym_u_watch == "EURUSD=X":
                                    richtwert_str = "Ziel-Korridor: 65–75"
                                elif any(ext in sym_u_watch for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]):
                                    richtwert_str = "Ziel-Korridor: 65–80"
                                elif "=F" in sym_u_watch or any(ext in sym_u_watch for ext in ["=X", "DX-Y"]):
                                    richtwert_str = "Ziel-Korridor: 60–70"
                                else:
                                    richtwert_str = "Zielwert: >= 70 (Relative Stärke)"
                                st.metric(label="🚀 Gesamtwertung", value=f"{w_row.get('Master-Score', 'N/A')} | {richtwert_str}", delta=w_row.get("Ampel", ""), delta_color="off")
                                st.markdown(f"**🧬 Ticker-DNA:** {w_row.get('DNA', 'N/A')} (ATR: {w_row.get('ATR%', 0.0):.2f}%)")
                                score_str = str(w_row.get("Master-Score", "0"))
                                score_val = 0
                                for word in score_str.split():
                                    if '/' in word:
                                        try: score_val = int(word.split('/')[0])
                                        except: pass
                                guideline_watch = get_action_guideline(sym_u_watch, score_val, w_row.get("DNA", ""))
                                if "🛑" in guideline_watch or "⚠️" in guideline_watch:
                                    st.warning(f"**🧭 Handlungsanweisung:** {guideline_watch}")
                                else:
                                    st.info(f"**🧭 Handlungsanweisung:** {guideline_watch}")
                                
                                if "⚡ Long" in w_row.get("Ampel", ""): rec_text = "🔵 Starkes Trend-Setup (Pullback im Bullenmarkt)"
                                elif score_val >= 75: rec_text = "🚀 Starkes Setup (Kaufzone)"
                                elif score_val >= 60: rec_text = "🟡 Auf der Watchlist beobachten (Reifendes Setup)"
                                else: rec_text = "🔴 Aktuell kein Einstieg"
                                st.markdown(f"**Empfehlung:** {rec_text}")
                                st.markdown("---")
                                rec_t2_watch = get_asset_strategy_recommendation(sym)
                                with st.container(border=True):
                                    st.markdown(f"**🧬 Strategie-DNA & Empfehlung**")
                                    st.markdown(f"**{rec_t2_watch['label']}**")
                                    st.markdown(f"🎯 **Konto:** {rec_t2_watch['konto_typ']} | ⏱️ **TF:** {rec_t2_watch['timeframe']}")
                                    st.markdown(f"**Profil:** `{rec_t2_watch['profil']}`")
                                    st.caption(f"_{rec_t2_watch['hinweis']}_")
                                st.markdown("""<style>[data-testid="stProgress"] { margin-top: -10px !important; margin-bottom: 35px !important; } [data-testid="stProgress"] > div > div > div, [data-testid="stProgress"] > div > div { height: 28px !important; border-radius: 10px !important; }</style>""", unsafe_allow_html=True)
                                c_w_bars, c_w_extra = st.columns(2)
                                
                                with c_w_bars:
                                    is_setup_b = "Trend-Kauf" in str(w_row.get("Ampel", ""))
                                    max_saeulen = 35 if is_setup_b else 45
                                    max_crv = 20 if is_setup_b else 30
                                    
                                    st.markdown(f"**🏛️ Indikatoren: {pts_saeulen} / {max_saeulen} Pkt.**")
                                    st.progress(min(pts_saeulen / float(max_saeulen), 1.0))
                                    st.info(f"Details: {w_row.get('Säulen-Details', 'N/A')}")
                                    st.write("")
                                    st.markdown(f"**⚖️ CRV-Bonus: {pts_crv} / {max_crv} Pkt.** ({w_row.get('CRV Rating', 'N/A')})")
                                    st.progress(min(pts_crv / float(max_crv), 1.0))
                                    
                                    if is_setup_b:
                                        st.markdown(f"**📈 Rel. Stärke: {pts_rs} / 30 Pkt.** (Ratio: {w_row.get('Rel. Stärke', 'N/A')})")
                                        st.progress(min(pts_rs / 30.0, 1.0))
                                    else:
                                        st.markdown(f"**📈 Rel. Stärke: 0 / 0 Pkt.** (⚪ N/A – Rebound-Setup)")
                                        st.progress(0.0)
                                        st.caption("ℹ️ Bei antizyklischen Rebounds (Setup A) ist eine schwache relative Stärke mathematisch normal und wird nicht bewertet.")
                                        
                                    st.markdown(f"**🛡️ Signal & Plateau: {pts_signal} / 15 Pkt.** ({w_row.get('Plateau', 'N/A')})")
                                    st.progress(min(pts_signal / 15.0, 1.0))
                                    mc_ratio_w = float(str(w_row.get('Monte-Carlo', '0')).split('(')[-1].replace('%)', '')) if '(' in str(w_row.get('Monte-Carlo', '')) else 0.0
                                    st.markdown(f"**🎲 Monte-Carlo Stresstest:** {w_row.get('Monte-Carlo', 'N/A')}")
                                    st.progress(min(mc_ratio_w / 100.0, 1.0))
                                
                                with c_w_extra:
                                    c_sym = get_currency_symbol(sym)
                                    fx_info = get_fx_rate(c_sym)
                                    
                                    def fmt_c(val_str):
                                        if val_str == 'N/A': return 'N/A'
                                        try:
                                            val = float(val_str)
                                            return f"{val:.2f} {c_sym} (≈ {val * fx_info:.2f} €)" if c_sym not in ["€", "EUR"] else f"{val:.2f} €"
                                        except:
                                            return f"{val_str} {c_sym}"

                                    st.markdown("### 🎯 Detail-Kennzahlen")
                                    einstieg_clean = str(w_row.get('Kurs', 'N/A')).split()[0]
                                    st.markdown(f"- **📍 Einstieg:** {fmt_c(einstieg_clean)}")
                                    st.markdown(f"- **📉 RSI:** {w_row.get('RSI', 'N/A')}")
                                    st.markdown(f"- **📊 Z-Score:** {w_row.get('Z-Score', 'N/A')}")
                                    st.markdown(f"- **🎯 RSI-Extrempreis Tief (RSI 30):** {fmt_c(w_row.get('Kauf-Zielpreis', 'N/A'))}")
                                    st.markdown(f"- **🎯 RSI-Extrempreis Hoch (RSI 70):** {fmt_c(w_row.get('Verkauf-Zielpreis', 'N/A'))}")
                                    st.markdown(f"- **🛡️ Stop Loss (SL):** {fmt_c(w_row.get('Stop Loss (SL)', 'N/A'))}")
                                    st.markdown(f"- **💸 Take Profit (TP):** {fmt_c(w_row.get('Take Profit (TP)', 'N/A'))}")
                    
                    render_chart_system(res_t2, "t2_chart", sel_sec2)
            except Exception as e: st.error(f"Fehler: {e}")
#endregion

#region TAB 3 UI
with tab_futures:
    st.header("🎯 Prop-Firm Multi-Asset Desk (Intraday & Swing)")
    
    # --- 1. HEADER & PROP-FIRM RADAR ---
    c_prof1, c_prof2 = st.columns([1, 3])
    pf_profiles = {
        "Apex 50k (Futures)": {"size": 50000, "daily_loss": 1250, "trail_dd": 2500, "target": 3000},
        "FTMO 50k (Forex/CFD)": {"size": 50000, "daily_loss": 2500, "trail_dd": 5000, "target": 5000},
        "Privatkonto (10k)": {"size": 10000, "daily_loss": 500, "trail_dd": 1000, "target": 1000}
    }
    
    with c_prof1:
        sel_pf = st.selectbox("💼 Prop-Profil wählen:", list(pf_profiles.keys()) + ["Benutzerdefiniert"])
    
    if sel_pf == "Benutzerdefiniert":
        with st.expander("⚙️ Eigene Parameter", expanded=True):
            c_c1, c_c2, c_c3, c_c4 = st.columns(4)
            acc_size = c_c1.number_input("Kontogröße", 10000)
            dl = c_c2.number_input("Tagesverlust Limit", 500)
            mdd = c_c3.number_input("Max Drawdown", 1000)
            tgt = c_c4.number_input("Profit Target", 1000)
    else:
        acc_size, dl, mdd, tgt = pf_profiles[sel_pf]["size"], pf_profiles[sel_pf]["daily_loss"], pf_profiles[sel_pf]["trail_dd"], pf_profiles[sel_pf]["target"]

    c_m1, c_m2, c_m3, c_m4 = st.columns(4)
    c_m1.metric("Konto-Größe", f"${acc_size:,}")
    c_m2.metric("Tagesverlust-Puffer", f"${dl:,}")
    c_m3.metric("Max Trailing Drawdown", f"${mdd:,}")
    c_m4.metric("Profit-Target Progress", f"${tgt:,}")

    st.markdown("---")
    
    # --- 2. ELITE-UNIVERSUM & WATCHLIST-MANAGER ---
    render_dynamic_settings(
        "Futures & Forex Parameter", "tab3_settings", 
        [{"label": "Timeframe Futures & Rohstoffe:", "key": "tf_futures", "options": ["1h", "4h", "15m", "1d"], "type": "radio", "default": "1h"},
         {"label": "Timeframe Forex Majors:", "key": "tf_forex", "options": ["4h", "1h", "1d"], "type": "radio", "default": "4h"}, 
         {"label": "RSI Short Entry", "key": "rsi_short_entry", "default": 70.0, "type": "number"}, 
         {"label": "RSI Long Entry", "key": "rsi_long_entry", "default": 30.0, "type": "number"}], 
        expanded=False, reset_label="🔄 Tab 3 Einstellungen zurücksetzen", defaults_to_reset={"tf_futures": "1h", "tf_forex": "4h", "rsi_short_entry": 70.0, "rsi_long_entry": 30.0}
    )

    st.subheader("🌐 Elite-Universum (Kader-Verwaltung)")
    
    # Vollständiges 20-Ticker Universum laden, falls unvollständig
    full_elite_tickers = [
        {"symbol": "NQ=F", "name": "Nasdaq 100", "asset_class": "Futures", "contract": "MNQ"},
        {"symbol": "ES=F", "name": "S&P 500", "asset_class": "Futures", "contract": "MES"},
        {"symbol": "YM=F", "name": "Dow Jones", "asset_class": "Futures", "contract": "MYM"},
        {"symbol": "RTY=F", "name": "Russell 2000", "asset_class": "Futures", "contract": "M2K", "active": False},
        {"symbol": "GC=F", "name": "Gold", "asset_class": "Rohstoffe", "contract": "MGC"},
        {"symbol": "SI=F", "name": "Silber", "asset_class": "Rohstoffe", "contract": "SIL", "active": False},
        {"symbol": "CL=F", "name": "Crude Oil", "asset_class": "Rohstoffe", "contract": "MCL"},
        {"symbol": "NG=F", "name": "Erdgas", "asset_class": "Rohstoffe", "contract": "QG"},
        {"symbol": "HG=F", "name": "Kupfer", "asset_class": "Rohstoffe", "contract": "MHG"},
        {"symbol": "EURUSD=X", "name": "EUR/USD", "asset_class": "Forex", "contract": "Lot"},
        {"symbol": "GBPUSD=X", "name": "GBP/USD", "asset_class": "Forex", "contract": "Lot"},
        {"symbol": "USDJPY=X", "name": "USD/JPY", "asset_class": "Forex", "contract": "Lot"},
        {"symbol": "AUDUSD=X", "name": "AUD/USD", "asset_class": "Forex", "contract": "Lot"},
        {"symbol": "USDCAD=X", "name": "USD/CAD", "asset_class": "Forex", "contract": "Lot"},
        {"symbol": "USDCHF=X", "name": "USD/CHF", "asset_class": "Forex", "contract": "Lot"},
        {"symbol": "EURJPY=X", "name": "EUR/JPY", "asset_class": "Forex", "contract": "Lot"},
        {"symbol": "DX-Y.NYB", "name": "US Dollar Index", "asset_class": "Forex", "contract": "Lot"},
       ]
    # Harte Krypto-Säuberung aus Tab 3 (Altlasten bereinigen)
    cleaned_futures = []
    for t in st.session_state.config.get("futures_tickers", []):
        sym_u = str(t.get("symbol", "")).upper()
        is_crypto_sym = any(ext in sym_u for ext in ["-USD", "-EUR", "-USDT"]) or any(ext in sym_u for ext in ["BTC", "ETH", "SOL"]) or t.get("asset_class", "") == "Krypto"
        if not is_crypto_sym:
            cleaned_futures.append(t)
    
    if len(cleaned_futures) != len(st.session_state.config.get("futures_tickers", [])):
        st.session_state.config["futures_tickers"] = cleaned_futures
        save_config(st.session_state.config)
    
    if not st.session_state.config.get("futures_tickers") or len(st.session_state.config.get("futures_tickers", [])) < 15:
        # Füge fehlende Attribute zu existierenden hinzu und ergänze neue
        st.session_state.config["futures_tickers"] = full_elite_tickers
        save_config(st.session_state.config)
    
    for t in st.session_state.config["futures_tickers"]:
        if "active" not in t: t["active"] = True

    st.markdown("**⚡ Schnell-Kader (Presets):**")
    c_btn1, c_btn2, c_btn3 = st.columns(3)
    if c_btn1.button("🇺🇸 US-Indizes & Metalle", use_container_width=True):
        for t in st.session_state.config["futures_tickers"]: t["active"] = (t["asset_class"] in ["Futures", "Rohstoffe"])
        save_config(st.session_state.config); st.rerun()
    if c_btn2.button("💱 Forex & Makro", use_container_width=True):
        for t in st.session_state.config["futures_tickers"]: t["active"] = (t["asset_class"] == "Forex")
        save_config(st.session_state.config); st.rerun()
    if c_btn3.button("🌐 Alle aktivieren", use_container_width=True):
        for t in st.session_state.config["futures_tickers"]: t["active"] = True
        save_config(st.session_state.config); st.rerun()

    with st.expander("✏️ Ticker-Tabelle bearbeiten", expanded=False):
        c_s_1, c_s_2 = st.columns([3, 1])
        with c_s_1:
            sq_t3 = st.text_input("Yahoo-Suche oder Ticker eingeben (z.B. GC=F):", key="search_t3_acc")
        sug_t3 = []
        if sq_t3 and len(sq_t3.strip()) >= 2:
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={sq_t3.strip()}&quotesCount=5", headers=headers, timeout=3)
                if resp.status_code == 200:
                    for q in resp.json().get("quotes", []):
                        if "symbol" in q: sug_t3.append(f"{q['symbol']} - {q.get('longname', q.get('shortname', ''))}")
            except: pass
            
        chosen_t3 = None
        if sug_t3:
            chosen_t3_raw = st.selectbox("Treffer:", sug_t3, key="sel_t3_acc")
            chosen_t3 = chosen_t3_raw.split(" - ")[0]
            chosen_name = chosen_t3_raw.split(" - ")[1] if " - " in chosen_t3_raw else chosen_t3
            
        with c_s_2:
            st.write(""); st.write("")
            if st.button("➕ Hinzufügen", use_container_width=True, key="add_t3_btn") and chosen_t3:
                if not any(t["symbol"] == chosen_t3 for t in st.session_state.config["futures_tickers"]):
                    a_cls = "Forex" if "USD=X" in chosen_t3 else ("Krypto" if "BTC" in chosen_t3 else "Futures")
                    c_typ = "Lot" if a_cls == "Forex" else ("BTC" if a_cls == "Krypto" else "Micro")
                    st.session_state.config["futures_tickers"].append({"symbol": chosen_t3, "name": chosen_name, "asset_class": a_cls, "contract": c_typ, "active": True})
                    save_config(st.session_state.config)
                    st.rerun()

        st.markdown("---")
        df_f = pd.DataFrame([{"Aktiv": t["active"], "Löschen": False, "Ticker": t["symbol"], "Name": t["name"], "Klasse": t["asset_class"], "Kontraktart": t["contract"]} for t in st.session_state.config["futures_tickers"]])
        if not df_f.empty:
            edited_f = st.data_editor(df_f, hide_index=True, use_container_width=True, disabled=["Ticker"], column_config={"Klasse": st.column_config.SelectboxColumn(options=["Futures", "Rohstoffe", "Forex"]), "Kontraktart": st.column_config.SelectboxColumn(options=["MNQ", "MES", "MYM", "M2K", "MGC", "MCL", "MHG", "QG", "SIL", "Micro", "Lot", "Custom"])})
            
            c_act1, c_act2 = st.columns(2)
            with c_act1:
                if st.button("💾 Änderungen speichern", type="primary", use_container_width=True):
                    new_f = []
                    for _, r in edited_f.iterrows():
                        if not r["Löschen"]:
                            new_f.append({"symbol": r["Ticker"], "name": r["Name"], "asset_class": r["Klasse"], "contract": r["Kontraktart"], "active": r["Aktiv"]})
                    st.session_state.config["futures_tickers"] = new_f
                    save_config(st.session_state.config); st.success("Gespeichert!"); st.rerun()
            with c_act2:
                if st.button("🗑️ Ausgewählte (Löschen) entfernen", use_container_width=True):
                    to_delete = edited_f[edited_f["Löschen"] == True]["Ticker"].tolist()
                    if to_delete:
                        st.session_state.config["futures_tickers"] = [t for t in st.session_state.config["futures_tickers"] if t["symbol"] not in to_delete]
                        save_config(st.session_state.config)
                        st.rerun()

    st.markdown("---")

    # --- 3. SCANNER & BIDIREKTIONALE LOGIK ---
    st.subheader("🔍 Prop-Desk Screener")
    if "futures_scan_results" not in st.session_state: 
        st.session_state.futures_scan_results = None
    active_elite_t3 = [t for t in st.session_state.config.get("futures_tickers", []) if t.get("active", True)]
    c_ql1, c_ql2 = st.columns([3, 1])
    with c_ql1:
        ql_opts_t3 = {f"{t['symbol']} – {t['name']} ({t.get('asset_class', 'Futures')})": t for t in active_elite_t3}
        sel_ql_label = st.selectbox("🎯 Ticker direkt in Order-Desk laden", list(ql_opts_t3.keys()) if ql_opts_t3 else ["Keine aktiven Ticker"], key="t3_direct_load_sel")
    with c_ql2:
        st.write("")
        st.write("")
        if st.button("Laden", key="t3_direct_load_btn", use_container_width=True, disabled=not bool(ql_opts_t3)):
            t_dict_ql = ql_opts_t3[sel_ql_label]
            sym_ql = t_dict_ql["symbol"]
            t_name_ql = t_dict_ql["name"]
            a_class_ql = t_dict_ql.get("asset_class", "Futures")
            c_type_ql = t_dict_ql.get("contract", "Micro")
            cfg_ql = st.session_state.config["tab3_settings"]
            is_fx_ql = (a_class_ql == "Forex") or sym_ql.endswith("=X") or ("DX-Y" in sym_ql)
            tf_ql = cfg_ql.get("tf_forex", "4h") if is_fx_ql else cfg_ql.get("tf_futures", cfg_ql.get("tf", "1h"))
            period_ql = "60d" if tf_ql == "15m" else ("720d" if tf_ql in ["1h", "4h"] else "1y")
            fetch_tf_ql = "1h" if tf_ql in ["1h", "4h"] else tf_ql
            with st.spinner(f"Lade Live-Daten für {sym_ql} in den Order-Desk..."):
                try:
                    df_ql = fetch_market_data([sym_ql], period_ql, fetch_tf_ql)
                    if isinstance(df_ql.columns, pd.MultiIndex):
                        if sym_ql in df_ql.columns.get_level_values(0):
                            df_ql = df_ql[sym_ql].copy()
                        elif sym_ql in df_ql.columns.get_level_values(1):
                            df_ql = df_ql.xs(sym_ql, level=1, axis=1).copy()
                        elif "Close" in df_ql.columns.get_level_values(1):
                            df_ql.columns = df_ql.columns.get_level_values(1)
                        else:
                            df_ql.columns = df_ql.columns.get_level_values(0)
                    if tf_ql == "4h" and not df_ql.empty and "Close" in df_ql:
                        agg_d = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
                        if 'Volume' in df_ql.columns: agg_d['Volume'] = 'sum'
                        df_ql = df_ql.resample('4h').agg(agg_d).dropna(subset=['Close'])
                    if not df_ql.empty and "Close" in df_ql:
                        df_ql = df_ql.dropna(subset=["Close"])
                        calc_ql = calc_rsi_and_targets(df_ql, cfg_ql["rsi_long_entry"], cfg_ql["rsi_short_entry"], ticker=sym_ql)
                        if calc_ql:
                            r_ql, p_b_ql, p_s_ql, plot_ql, details_ql = calc_ql
                            c_p_ql = float(plot_ql['Close'].iloc[-1])
                            ema200_ql, ema20_ql = float(plot_ql['EMA_200'].iloc[-1]), float(plot_ql['EMA_20'].iloc[-1])
                            z_score_ql = details_ql.get("z_score", 0)
                            kc_upper_ql = float(plot_ql.get("KC_upper", plot_ql["EMA_20"]).iloc[-1])
                            
                            signal_ql, is_short_ql = "🟡 Neutral", False
                            if c_p_ql > ema200_ql and (38 <= r_ql <= 52) and (abs(c_p_ql - ema20_ql)/ema20_ql <= 0.015): signal_ql = "🟢 ⚡ Long (Trend)"
                            elif r_ql <= cfg_ql["rsi_long_entry"] or z_score_ql <= -2.0: signal_ql = "🟢 🔄 Long (Reversal)"
                            elif c_p_ql < ema200_ql and (48 <= r_ql <= 62) and (abs(c_p_ql - ema20_ql)/ema20_ql <= 0.015): signal_ql, is_short_ql = "🟢 ⚡ Short (Trend)", True
                            elif r_ql >= cfg_ql["rsi_short_entry"] or z_score_ql >= 2.0 or c_p_ql >= kc_upper_ql: signal_ql, is_short_ql = "🟢 🔄 Short (Reversal)", True
                            
                            sl_ql, tp_ql, _ = calculate_sl_tp_crv(plot_ql, c_p_ql, p_s_ql if not is_short_ql else p_b_ql, "tab3")
                            if not is_short_ql:
                                sl_ql = float(plot_ql["Low"].tail(24).min()) if "Low" in plot_ql.columns else c_p_ql * 0.98
                                if sl_ql >= c_p_ql: sl_ql = c_p_ql * 0.98
                                tp_ql = float(plot_ql["High"].tail(24).max()) if "High" in plot_ql.columns else c_p_ql * 1.02
                        else:
                            plot_ql = df_ql.copy()
                            c_p_ql = float(plot_ql['Close'].iloc[-1])
                            r_ql = 50.0
                            signal_ql, is_short_ql = "🟡 Neutral", False
                            sl_ql = float(plot_ql["Low"].tail(24).min()) if "Low" in plot_ql.columns else c_p_ql * 0.98
                            if sl_ql >= c_p_ql: sl_ql = c_p_ql * 0.98
                            tp_ql = float(plot_ql["High"].tail(24).max()) if "High" in plot_ql.columns else c_p_ql * 1.02
                            details_ql = {"pts_saeulen": 0, "pts_signal": 0, "setup_type": "A", "asset_class": "FUTURES" if "=F" in sym_ql else "FOREX", "vol_missing": True, "ampel": signal_ql, "breakdown": "N/A"}
                            
                        risk_pts_ql = abs(c_p_ql - sl_ql)
                        tick_val_ql = get_point_value(sym_ql, c_type_ql)
                        max_risk_amt_ql = dl * 0.10
                        raw_qty_ql = max_risk_amt_ql / (risk_pts_ql * tick_val_ql) if risk_pts_ql > 0 else 0
                        
                        if a_class_ql in ["Futures", "Rohstoffe"]:
                            qty_ql = int(raw_qty_ql)
                            size_str_ql = f"{qty_ql} {c_type_ql}" if qty_ql >= 1 else f"⚠️ SL zu weit ({c_type_ql})"
                            actual_risk_ql = qty_ql * risk_pts_ql * tick_val_ql
                        else:
                            qty_ql = round(raw_qty_ql, 2) if a_class_ql == "Forex" else round(raw_qty_ql, 4)
                            size_str_ql = f"{qty_ql} {c_type_ql}" if qty_ql > 0 else f"⚠️ SL zu weit ({c_type_ql})"
                            actual_risk_ql = qty_ql * risk_pts_ql * tick_val_ql
                            
                        trades_dl_ql = int(dl / actual_risk_ql) if actual_risk_ql > 0 else 0
                        trades_mdd_ql = int(mdd / actual_risk_ql) if actual_risk_ql > 0 else 0
                        crv_val_ql = (abs(tp_ql - c_p_ql) / risk_pts_ql) if risk_pts_ql > 0 else 0
                        tab3_crv_ql = f"🟢 Top CRV (1:{crv_val_ql:.1f})" if crv_val_ql >= 2.0 else (f"🟡 Passabel (1:{crv_val_ql:.1f})" if crv_val_ql >= 1.5 else f"🔴 Unattraktiv (1:{crv_val_ql:.1f})")
                        rs_ratio_ql = calc_relative_strength(sym_ql, plot_ql)
                        details_ql["ampel"] = signal_ql
                        details_ql["setup_type"] = "B" if "Trend" in signal_ql else "A"
                        sort_score_ql, m_score_str_ql, m_score_bd_ql = calculate_master_score(details_ql, tab3_crv_ql, rs_ratio_ql, r_ql, cfg_ql["rsi_long_entry"], direction="Short" if is_short_ql else "Long", is_multi_asset=True)
                        
                        if sym_ql.endswith("=X"):
                            pips_ql = risk_pts_ql * 100 if "JPY" in sym_ql else risk_pts_ql * 10000
                            abstand_str_ql = f"{pips_ql:.1f} Pips"
                        else:
                            abstand_str_ql = f"{risk_pts_ql:.4f} Pkt." if risk_pts_ql < 1.0 else f"{risk_pts_ql:.2f} Pkt."
                            
                        ema200_val_ql = float(plot_ql['EMA_200'].iloc[-1]) if 'EMA_200' in plot_ql.columns else c_p_ql
                        ema200_ok_ql = c_p_ql > ema200_val_ql
                        atr_pct_ql = float(details_ql.get("atr_pct", 0.0))
                        ql_row = {
                            "Ticker": sym_ql, "Name": t_name_ql, "Klasse": a_class_ql, "Signal": signal_ql, "Kurs": f"{c_p_ql:.4f}",
                            "RSI": f"{r_ql:.2f}", "Stop Loss": f"{sl_ql:.4f}", "Take Profit": f"{tp_ql:.4f}", "Abstand": abstand_str_ql,
                            "Risiko ($)": f"${actual_risk_ql:.2f}" if actual_risk_ql > 0 else "N/A",
                            "Empf. Größe": size_str_ql,
                            "_raw_cp": c_p_ql, "_raw_sl": sl_ql, "_raw_tp": tp_ql, "_raw_qty": qty_ql,
                            "_raw_is_short": is_short_ql, "_raw_name": t_name_ql, "_actual_risk": actual_risk_ql,
                            "_corr_group": "Other", "_crv": crv_val_ql, "Sort_Score": sort_score_ql,
                            "Master-Score": m_score_str_ql, "Score-Details": m_score_bd_ql,
                            "Säulen-Details": details_ql.get("breakdown", "N/A"),
                            "Stresstest": f"Tagespuffer: {trades_dl_ql} Fehltrades | Max: {trades_mdd_ql}",
                            "_ema200_ok": ema200_ok_ql, "_atr_pct": atr_pct_ql
                        }
                        if not st.session_state.get("futures_scan_results") or not isinstance(st.session_state.futures_scan_results, dict):
                            st.session_state.futures_scan_results = {"tb_data": [ql_row], "res_t3": {sym_ql: (plot_ql, cfg_ql["rsi_long_entry"], cfg_ql["rsi_short_entry"], t_name_ql, a_class_ql)}}
                        else:
                            existing_tb = [r for r in st.session_state.futures_scan_results.get("tb_data", []) if r.get("Ticker") != sym_ql]
                            existing_tb.append(ql_row)
                            st.session_state.futures_scan_results["tb_data"] = existing_tb
                            st.session_state.futures_scan_results.setdefault("res_t3", {})[sym_ql] = (plot_ql, cfg_ql["rsi_long_entry"], cfg_ql["rsi_short_entry"], t_name_ql, a_class_ql)
                        if "futures_info_tickers" not in st.session_state:
                            st.session_state.futures_info_tickers = []
                        if sym_ql not in st.session_state.futures_info_tickers:
                            st.session_state.futures_info_tickers.append(sym_ql)
                        st.session_state.pop("t3_data_editor", None)
                        st.session_state.active_order_ticker = None
                        st.session_state.active_futures_order = sym_ql
                        st.toast(f"🛒 {sym_ql} direkt in den Prop-Order-Desk geladen!", icon="🎯")
                        st.rerun()
                    else:
                        st.error(f"Keine Kursdaten für {sym_ql} empfangen.")
                except Exception as e:
                    st.error(f"Fehler beim Direkt-Laden von {sym_ql}: {e}")

    # On-Demand Detail-Infobox für direkt geladenen Ticker (auch bei Score < 60 / Neutral)
    active_f_sym = st.session_state.get("active_futures_order")
    if active_f_sym and st.session_state.get("futures_scan_results"):
        tb_all_od = st.session_state.futures_scan_results.get("tb_data", [])
        od_matches = [r for r in tb_all_od if r.get("Ticker") == active_f_sym]
        if od_matches:
            od_row = od_matches[0]
            od_sym_u = str(active_f_sym).upper().strip()
            if od_sym_u == "NQ=F":
                od_richtwert = "Ziel-Korridor: 60–65 (Deckel: Werte >= 70 meiden)"
            elif od_sym_u in ["CL=F", "MCL"]:
                od_richtwert = "Ziel-Korridor: 65–70"
            elif od_sym_u in ["USDJPY=X", "GBPUSD=X"]:
                od_richtwert = "Ziel-Korridor: 60–70"
            elif od_sym_u == "EURUSD=X":
                od_richtwert = "Ziel-Korridor: 65–75"
            elif any(ext in od_sym_u for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]) or od_row.get("Klasse") == "Krypto":
                od_richtwert = "Ziel-Korridor: 65–80"
            elif "=F" in od_sym_u or any(ext in od_sym_u for ext in ["=X", "DX-Y"]) or od_row.get("Klasse") in ["Futures", "Rohstoffe", "Forex"]:
                od_richtwert = "Ziel-Korridor: 60–70"
            else:
                od_richtwert = "Zielwert: >= 70 (Relative Stärke)"

            od_score = od_row.get("Sort_Score", 0)
            od_guideline = get_action_guideline(od_sym_u, od_score, od_row.get("Klasse", ""))
            od_bd_parts = str(od_row.get("Score-Details", "")).split()
            od_pts_saeulen = int(od_bd_parts[0].split(":")[1]) if len(od_bd_parts) > 0 and ":" in od_bd_parts[0] else 0
            od_pts_crv = int(od_bd_parts[1].split(":")[1]) if len(od_bd_parts) > 1 and ":" in od_bd_parts[1] else 0
            od_pts_rs = int(od_bd_parts[2].split(":")[1]) if len(od_bd_parts) > 2 and ":" in od_bd_parts[2] else 0
            od_pts_sig = int(od_bd_parts[3].split(":")[1]) if len(od_bd_parts) > 3 and ":" in od_bd_parts[3] else 0

            res_t3_dict = st.session_state.futures_scan_results.get("res_t3", {})
            od_macro_str = "🟢 Bullisch (über EMA 200)" if od_row.get("_ema200_ok", True) else "🔴 Unter EMA 200 (Trend-Filter beachten)"
            od_atr_pct = float(od_row.get("_atr_pct", 0.0))
            if active_f_sym in res_t3_dict:
                try:
                    od_plot = res_t3_dict[active_f_sym][0]
                    if "EMA_200" in od_plot.columns and "Close" in od_plot.columns:
                        od_c_last = float(od_plot["Close"].iloc[-1])
                        od_e200_last = float(od_plot["EMA_200"].iloc[-1])
                        od_macro_str = "🟢 Intakt (Kurs > EMA 200)" if od_c_last > od_e200_last else "🔴 Unter EMA 200"
                    if "ATR" in od_plot.columns and "Close" in od_plot.columns and float(od_plot["Close"].iloc[-1]) > 0:
                        od_atr_pct = (float(od_plot["ATR"].iloc[-1]) / float(od_plot["Close"].iloc[-1])) * 100.0
                except Exception:
                    pass

            with st.container(border=True):
                st.markdown(f"### 🎯 On-Demand Detail-Analyse: **{od_row['Ticker']}** ({od_row['Name']}) | {od_row.get('Klasse', 'N/A')}")
                st.metric(label="🚀 Gesamtwertung", value=f"{od_row.get('Master-Score', 'N/A')} | {od_richtwert}", delta=od_row.get("Signal", ""), delta_color="off")
                if "🛑" in od_guideline or "⚠️" in od_guideline:
                    st.warning(f"**🧭 Handlungsanweisung:** {od_guideline}")
                else:
                    st.info(f"**🧭 Handlungsanweisung:** {od_guideline}")

                if od_sym_u in ["CL=F", "MCL", "EURUSD=X"] or any(ext in od_sym_u for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]) or od_row.get("Klasse") == "Krypto":
                    od_min_score_threshold = 65
                elif "=F" in od_sym_u or any(ext in od_sym_u for ext in ["=X", "DX-Y"]) or od_row.get("Klasse") in ["Futures", "Rohstoffe", "Forex"]:
                    od_min_score_threshold = 60
                else:
                    od_min_score_threshold = 70

                if od_score >= od_min_score_threshold:
                    od_typ_info = "Setup B (Trend-Pullback)" if "Trend" in str(od_row.get('Signal', '')) else "Setup A (Reversal/Extremum)"
                    od_dir_info = "Short" if "Short" in str(od_row.get('Signal', '')) else "Long"
                    st.markdown(f"**Typ:** {od_typ_info} ({od_dir_info}) | **Kurs:** {od_row.get('Kurs', 'N/A')} | **SL:** {od_row.get('Stop Loss', 'N/A')} | **TP:** {od_row.get('Take Profit', 'N/A')} | **Abstand:** {od_row.get('Abstand', 'N/A')}")
                st.markdown(f"**🌍 Makro-Status (EMA 200):** {od_macro_str} | **📊 RSI:** {od_row.get('RSI', 'N/A')} | **⚡ ATR:** {od_atr_pct:.2f}% | **⚖️ CRV:** {float(od_row.get('_crv', 0.0)):.2f}")
                st.caption(f"🏛️ **Indikatoren-Aufschlüsselung:** {od_row.get('Säulen-Details', 'N/A')} | **Score-Split:** Säulen:{od_pts_saeulen} CRV:{od_pts_crv} RS:{od_pts_rs} Sig:{od_pts_sig} | **🛡️ Stresstest:** {od_row.get('Stresstest', 'N/A')}")
    c_s1, c_s2 = st.columns([1, 2])
    with c_s1: scan_all_t3 = st.checkbox("🌐 Alle Ticker scannen (Ignoriert Presets)", value=False)
    
    if st.button("🚀 Screener ausführen", type="primary", key="run_t3", use_container_width=True):
        target_list = st.session_state.config["futures_tickers"]
        if not scan_all_t3: target_list = [t for t in target_list if t.get("active", True)]
        
        t_list = [t["symbol"] for t in target_list]
        if t_list:
            with st.spinner("Analysiere Märkte & berechne Stresstests..."):
                cfg = st.session_state.config["tab3_settings"]
                try:
                    tf_fut = cfg.get("tf_futures", cfg.get("tf", "1h"))
                    tf_fx = cfg.get("tf_forex", "4h")
                    
                    def _resolve_period_tf(tf_val):
                        if tf_val == "15m": return "60d", "15m"
                        elif tf_val in ["1h", "4h"]: return "720d", "1h"
                        else: return "1y", tf_val

                    p_fut, f_fut = _resolve_period_tf(tf_fut)
                    p_fx, f_fx = _resolve_period_tf(tf_fx)
                    
                    if (p_fut, f_fut) == (p_fx, f_fx):
                        b_df = fetch_market_data(t_list, p_fut, f_fut)
                        if isinstance(b_df.columns, pd.MultiIndex) and len(t_list) == 1: 
                            b_df.columns = b_df.columns.get_level_values(0)
                        b_df_fut, b_df_fx = b_df, b_df
                        len_fut, len_fx = len(t_list), len(t_list)
                    else:
                        fut_list = [t["symbol"] for t in target_list if not (t.get("asset_class") == "Forex" or t["symbol"].endswith("=X") or "DX-Y" in t["symbol"])]
                        fx_list = [t["symbol"] for t in target_list if (t.get("asset_class") == "Forex" or t["symbol"].endswith("=X") or "DX-Y" in t["symbol"])]
                        b_df_fut = fetch_market_data(fut_list, p_fut, f_fut) if fut_list else pd.DataFrame()
                        if isinstance(b_df_fut.columns, pd.MultiIndex) and len(fut_list) == 1:
                            b_df_fut.columns = b_df_fut.columns.get_level_values(0)
                        b_df_fx = fetch_market_data(fx_list, p_fx, f_fx) if fx_list else pd.DataFrame()
                        if isinstance(b_df_fx.columns, pd.MultiIndex) and len(fx_list) == 1:
                            b_df_fx.columns = b_df_fx.columns.get_level_values(0)
                        len_fut, len_fx = len(fut_list), len(fx_list)
                    
                    tb_data, res_t3 = [], {}
                    
                    for t_dict in target_list:
                        sym, t_name, a_class, c_type = t_dict["symbol"], t_dict["name"], t_dict.get("asset_class", "Futures"), t_dict.get("contract", "Micro")
                        is_fx_item = (a_class == "Forex" or sym.endswith("=X") or "DX-Y" in sym)
                        item_tf = tf_fx if is_fx_item else tf_fut
                        src_df = b_df_fx if is_fx_item else b_df_fut
                        src_len = len_fx if is_fx_item else len_fut
                        df_t = src_df[sym].copy() if src_len > 1 else src_df.copy()
                        
                        if item_tf == "4h" and not df_t.empty and "Close" in df_t:
                            agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
                            if 'Volume' in df_t.columns:
                                agg_dict['Volume'] = 'sum'
                            df_t = df_t.resample('4h').agg(agg_dict).dropna(subset=['Close'])
                        
                        if not df_t.empty and "Close" in df_t:
                            calc = calc_rsi_and_targets(df_t, cfg["rsi_long_entry"], cfg["rsi_short_entry"])
                            if calc:
                                r, p_b, p_s, plot, details = calc
                                c_p = plot['Close'].iloc[-1]
                                ema200, ema20 = plot['EMA_200'].iloc[-1], plot['EMA_20'].iloc[-1]
                                z_score = details.get("z_score", 0)
                                kc_upper = plot.get("KC_upper", plot["EMA_20"]).iloc[-1]
                                
                                # Bidirektionale Ampel-Logik
                                signal, is_short = "🟡 Neutral", False
                                if c_p > ema200 and (38 <= r <= 52) and (abs(c_p - ema20)/ema20 <= 0.015): signal = "🟢 ⚡ Long (Trend)"
                                elif r <= cfg["rsi_long_entry"] or z_score <= -2.0: signal = "🟢 🔄 Long (Reversal)"
                                elif c_p < ema200 and (48 <= r <= 62) and (abs(c_p - ema20)/ema20 <= 0.015): signal, is_short = "🟢 ⚡ Short (Trend)", True
                                elif r >= cfg["rsi_short_entry"] or z_score >= 2.0 or c_p >= kc_upper: signal, is_short = "🟢 🔄 Short (Reversal)", True
                                    
                                # --- 4. DRAWDOWN-STRESSTEST & KONTRAKT-SIZING ---
                                sl, tp, crv_rating = calculate_sl_tp_crv(plot, c_p, p_s if not is_short else p_b, "tab3")
                                
                                if not is_short:
                                    sl = plot["Low"].tail(24).min() if "Low" in plot.columns else c_p * 0.98
                                    if sl >= c_p: sl = c_p * 0.98
                                    tp = plot["High"].tail(24).max() if "High" in plot.columns else c_p * 1.02
                                
                                risk_pts = abs(c_p - sl)
                                tick_val = 1.0
                                # Grobes Mapping für Tick/Point Values (Standard Micro/Lot Größen als Referenz)
                                if "NQ" in sym or "ES" in sym or "YM" in sym or "RTY" in sym: tick_val = 2.0 if "NQ" in sym else (5.0 if "ES" in sym else 0.5)
                                elif "GC" in sym or "CL" in sym: tick_val = 10.0
                                elif "SI" in sym: tick_val = 10.0
                                elif "USD=X" in sym or "JPY=X" in sym: tick_val = 100000.0
                                
                                max_risk_amt = dl * 0.10 # Max. 10% vom Tagesverlust-Limit pro Trade
                                raw_qty = max_risk_amt / (risk_pts * tick_val) if risk_pts > 0 else 0
                                
                                size_str = ""
                                actual_risk = 0.0
                                trades_dl, trades_mdd = 0, 0
                                
                                if a_class in ["Futures", "Rohstoffe"]:
                                    qty = int(raw_qty)
                                    if qty < 1: size_str = "⚠️ SL zu weit für Risikolimit"
                                    else:
                                        size_str = f"{qty} {c_type}"
                                        actual_risk = qty * risk_pts * tick_val
                                elif a_class == "Forex" or a_class == "Krypto":
                                    qty = round(raw_qty, 2) if a_class == "Forex" else round(raw_qty, 4)
                                    if qty <= 0: size_str = "⚠️ SL zu weit für Risikolimit"
                                    else:
                                        size_str = f"{qty} {c_type}"
                                        actual_risk = qty * risk_pts * tick_val
                                        
                                if actual_risk > 0:
                                    trades_dl = int(dl / actual_risk)
                                    trades_mdd = int(mdd / actual_risk)
                                
                                # Korrelations-Gruppe bestimmen (für den Optimizer)
                                corr_group = "Other"
                                if a_class == "Futures": corr_group = "US-Indizes"
                                elif a_class == "Forex" and "USD" in sym: corr_group = "USD-Wetten"
                                elif a_class == "Rohstoffe": corr_group = "Rohstoffe"
                                elif a_class == "Krypto": corr_group = "Krypto"
                                crv_val = (abs(tp - c_p)/risk_pts) if risk_pts > 0 else 0
                                
                                if crv_val >= 2.0: tab3_crv_rating = f"🟢 Top CRV (1:{crv_val:.1f})"
                                elif crv_val >= 1.5: tab3_crv_rating = f"🟡 Passabel (1:{crv_val:.1f})"
                                else: tab3_crv_rating = f"🔴 Unattraktiv (1:{crv_val:.1f})"

                                rs_ratio = calc_relative_strength(sym, plot)
                                details["ampel"] = signal
                                details["setup_type"] = "B" if "Trend" in signal else "A"
                                sort_score, m_score_str, m_score_breakdown = calculate_master_score(details, tab3_crv_rating, rs_ratio, r, cfg["rsi_long_entry"], direction="Short" if is_short else "Long", is_multi_asset=True)

                                if sym.endswith("=X"):
                                    if "JPY" in sym:
                                        pips = risk_pts * 100
                                    else:
                                        pips = risk_pts * 10000
                                    abstand_str = f"{pips:.1f} Pips"
                                else:
                                    if risk_pts < 1.0:
                                        abstand_str = f"{risk_pts:.4f} Pkt."
                                    else:
                                        abstand_str = f"{risk_pts:.2f} Pkt."

                                tb_data.append({
                                    "Ticker": sym, "Name": t_name, "Klasse": a_class, "Signal": signal, "Kurs": f"{c_p:.4f}", 
                                    "RSI": f"{r:.2f}", "Stop Loss": f"{sl:.4f}", "Take Profit": f"{tp:.4f}", "Abstand": abstand_str,
                                    "Risiko ($)": f"${actual_risk:.2f}" if actual_risk > 0 else "N/A",
                                    "Empf. Größe": size_str,
                                    "_raw_cp": c_p, "_raw_sl": sl, "_raw_tp": tp, "_raw_qty": qty if 'qty' in locals() else 0, 
                                    "_raw_is_short": is_short, "_raw_name": t_name, "_actual_risk": actual_risk,
                                    "_corr_group": corr_group, "_crv": crv_val, "Sort_Score": sort_score,
                                    "Master-Score": m_score_str, "Score-Details": m_score_breakdown,
                                    "Säulen-Details": details.get("breakdown", "N/A"),
                                    "Stresstest": f"Tagespuffer: {trades_dl} Fehltrades | Max: {trades_mdd}"
                                })
                                res_t3[sym] = (plot, cfg["rsi_long_entry"], cfg["rsi_short_entry"], t_name, a_class)
                    
                    if tb_data:
                        st.session_state.futures_scan_results = {"tb_data": tb_data, "res_t3": res_t3}
                    else:
                        st.session_state.futures_scan_results = None
                        st.info("Aktuell keine gültigen Einstiegssignale gefunden.")
                except Exception as e: st.error(f"Fehler bei der Prop-Analyse: {e}")

    if st.session_state.get("futures_scan_results"):
        tb_data = st.session_state.futures_scan_results["tb_data"]
        res_t3 = st.session_state.futures_scan_results["res_t3"]
        df_res = pd.DataFrame(tb_data)
        
        valid_signals = df_res[~df_res["Signal"].str.contains("Neutral") & ~df_res["Empf. Größe"].str.contains("⚠️")]
        
        if not valid_signals.empty:
            df_sorted = valid_signals.sort_values(by="Sort_Score", ascending=False).copy()
            
            # --- 1. KACHEL-DASHBOARD (Top-Picks) ---
            st.markdown("### 🏆 Overall Top 3 (Klassenübergreifend)")
            top3 = df_sorted.head(3)
            cols_ov = st.columns(3)
            medals = ["🥇 1. Platz", "🥈 2. Platz", "🥉 3. Platz"]
            for i, (_, row) in enumerate(top3.iterrows()):
                with cols_ov[i]:
                    st.metric(label=f"{medals[i]}: {row['Ticker']} ({row['Klasse']})", value=row['Master-Score'], delta=row['Signal'], delta_color="off")
                    
            st.markdown("### 🏅 Top-Pick pro Asset-Klasse")
            classes = ["Futures", "Rohstoffe", "Forex"]
            cols_cl = st.columns(3)
            for i, cls in enumerate(classes):
                cls_df = df_sorted[df_sorted["Klasse"] == cls]
                with cols_cl[i]:
                    if not cls_df.empty:
                        best = cls_df.iloc[0]
                        st.metric(label=f"{cls}: {best['Ticker']}", value=best['Master-Score'], delta=best['Signal'], delta_color="off")
                    else:
                        st.metric(label=f"{cls}", value="-", delta="Kein Setup", delta_color="off")
            st.markdown("---")
            # --- 1.1 DAILY PROP-BASKET OPTIMIZER ---
            def get_ticker_cluster(sym, a_cls):
                us_indices = ["NQ=F", "ES=F", "YM=F", "RTY=F"]
                commodities = ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"]
                cryptos = ["BTC-USD", "ETH-USD", "SOL-USD"]
                if sym in us_indices: return "US-Indizes"
                if sym in commodities or a_cls == "Rohstoffe": return "Rohstoffe"
                if sym in cryptos or a_cls == "Krypto": return "Krypto"
                if "USD" in sym and sym.endswith("=X"): return "USD-Forex"
                if a_cls == "Forex": return "Forex-Cross"
                return "Sonstige"
            # Deaktiviert für v1.0.0 (Fokus auf Asset-spezifische Spezialkonten statt aggregierter Baskets)
            if bool(False): # ehemals: with st.expander("🎯 Optimaler Tages-Basket...", expanded=True):
                # Vorbereitung der qualifizierten Kandidaten
                cands_pool = []
                for _, r_cand in df_sorted.iterrows():
                    actual_r = float(r_cand.get("_actual_risk", 0.0))
                    sort_score = float(r_cand.get("Sort_Score", 0))
                    if actual_r > 0 and sort_score >= 60:
                        c_group = get_ticker_cluster(r_cand["Ticker"], r_cand.get("Klasse", ""))
                        cands_pool.append({
                            "row": r_cand,
                            "ticker": r_cand["Ticker"],
                            "name": r_cand["Name"],
                            "signal": r_cand["Signal"],
                            "score": sort_score,
                            "risk": actual_r,
                            "cluster": c_group
                        })

                if not cands_pool:
                    st.info("ℹ️ Aktuell liegen keine Setups mit ausreichender Qualität (Score ≥ 60) vor. Für Prop-Firm Challenges wird heute kein Korb empfohlen (Kapitalschutz).")
                else:
                    best_basket = None
                    best_basket_score = -1.0
                    
                    # Teste 3er-Kombinationen, Fallback auf 2er-Kombinationen
                    for k_size in [3, 2]:
                        if len(cands_pool) >= k_size:
                            import itertools
                            for comb in itertools.combinations(cands_pool, k_size):
                                clusters = [c["cluster"] for c in comb]
                                # Hard Constraint: Max 1 Setup pro Cluster
                                if len(clusters) == len(set(clusters)):
                                    total_r = sum(c["risk"] for c in comb)
                                    if total_r > 0:
                                        sum_score = sum(c["score"] for c in comb)
                                        ratio = sum_score / total_r
                                        if ratio > best_basket_score:
                                            best_basket_score = ratio
                                            best_basket = comb
                        if best_basket is not None and len(best_basket) == 3:
                            break

                    if not best_basket and len(cands_pool) == 1:
                        best_basket = [cands_pool[0]]

                    if best_basket:
                        cum_risk = sum(c["risk"] for c in best_basket)
                        dl_limit_f = float(dl) if dl > 0 else 1.0
                        util_pct = (cum_risk / dl_limit_f) * 100.0

                        st.markdown(f"**Empfohlener Korb ({len(best_basket)} unkorrelierte Setups):**")
                        b_cols = st.columns(len(best_basket))
                        for i_b, item in enumerate(best_basket):
                            r_data = item["row"]
                            with b_cols[i_b]:
                                with st.container(border=True):
                                    st.markdown(f"**{item['ticker']}** ({item['name']})")
                                    st.caption(f"📂 Cluster: **{item['cluster']}**")
                                    st.write(f"Richtung: **{r_data['Signal']}**")
                                    st.write(f"Größe: **{r_data['Empf. Größe']}**")
                                    st.write(f"Risiko: **${item['risk']:.2f}** | Score: **{int(item['score'])}/100**")
                                    if st.button("🛒 In Order-Desk laden", key=f"btn_load_basket_{item['ticker']}", use_container_width=True):
                                        st.session_state.active_futures_order = item['ticker']
                                        st.toast(f"🛒 Order-Desk geladen für: {item['ticker']}", icon="✅")
                                        st.rerun()

                        st.markdown("---")
                        mb1, mb2, mb3 = st.columns(3)
                        mb1.metric("Kumuliertes Risiko (Worst Case)", f"${cum_risk:,.2f}")
                        mb2.metric("Puffer-Auslastung (Daily Loss)", f"{util_pct:.1f} %", delta=f"{dl_limit_f - cum_risk:,.2f} $ verbleibend")
                        mb3.metric("Korrelations-Schutz", f"{len(best_basket)} verschiedene Cluster", delta="Diversifiziert", delta_color="off")

                        if util_pct > 30.0:
                            st.warning(f"⚠️ **Hohe Risiko-Auslastung ({util_pct:.1f}%):** Bei gleichzeitigem Stop-Loss-Treffer aller Positionen wird über 30% deines Tagesverlust-Puffers aufgebraucht!")
                        else:
                            st.success(f"✅ **Sicherer Puffer ({util_pct:.1f}% Auslastung):** Das Portfolio ist vor Klumpenrisiken geschützt und bleibt weit unter der Tagesverlust-Schwelle.")
                            
                        st.write("")
                        if st.button("📤 Diesen Korb im Strategie-Labor (Tab 4) validieren", type="primary", use_container_width=True):
                            basket_tickers = [item['ticker'] for item in best_basket]
                            lab_accs = st.session_state.config.setdefault("lab_accounts", {})
                            active_id = st.session_state.get("active_lab_account")
                            if not active_id or active_id not in lab_accs:
                                active_id = list(lab_accs.keys())[0] if lab_accs else None
                            
                            if active_id:
                                target_acc = lab_accs[active_id]
                                target_acc["tickers"] = list(set(target_acc.get("tickers", []) + basket_tickers))
                                save_config(st.session_state.config)
                                st.toast(f"✅ {len(basket_tickers)} Ticker erfolgreich an Tab 4 übergeben!", icon="📤")
                                st.rerun()
                    else:
                        st.info("ℹ️ Keine unkorrelierte Mehrfach-Kombination gefunden. Bitte prüfe die Einzel-Setups in der Tabelle.")
            st.markdown("---")

            # --- 2. QUIET UI (Data Editor) ---
            if "active_futures_order" not in st.session_state: st.session_state.active_futures_order = None
            if "futures_info_tickers" not in st.session_state: st.session_state.futures_info_tickers = []
            
            df_sorted.insert(0, "🛒 Order", df_sorted["Ticker"] == st.session_state.active_futures_order)
            df_sorted.insert(1, "🔍 Info", df_sorted["Ticker"].isin(st.session_state.futures_info_tickers))
            
            def color_t3_new(row):
                s = str(row["Signal"])
                if "⚡ Long" in s: return ["background-color: #cce5ff; color: #004085; font-weight: bold"] * len(row)
                if "🔄 Long" in s: return ["background-color: #d1ecf1; color: #0c5460; font-weight: bold"] * len(row)
                if "⚡ Short" in s: return ["background-color: #e2d9f3; color: #38187a; font-weight: bold"] * len(row)
                if "🔄 Short" in s: return ["background-color: #e8daef; color: #512e5f; font-weight: bold"] * len(row)
                if "Blockiert" in s or "Neutral" in s: return ["background-color: #f8d7da; color: #721c24; font-weight: bold"] * len(row)
                return [""] * len(row)

            df_sorted["CRV"] = df_sorted["_crv"].apply(lambda x: f"{x:.2f}")
            disp_cols_display = ["🛒 Order", "🔍 Info", "Klasse", "Ticker", "Name", "Master-Score", "Signal", "Kurs", "RSI", "CRV", "Risiko ($)", "Empf. Größe"]

            edited_t3 = st.data_editor(
                df_sorted[disp_cols_display].style.apply(color_t3_new, axis=1), 
                hide_index=True, use_container_width=True,
                disabled=["Klasse", "Ticker", "Name", "Master-Score", "Signal", "Kurs", "RSI", "CRV", "Risiko ($)", "Empf. Größe"],
                column_config={
                    "🛒 Order": st.column_config.CheckboxColumn("🛒 Order", default=False),
                    "🔍 Info": st.column_config.CheckboxColumn("🔍 Info", default=False)
                },
                key="t3_data_editor"
            )

            # State-Handling Info
            new_infos_t3 = edited_t3[edited_t3["🔍 Info"] == True]["Ticker"].tolist()
            if set(new_infos_t3) != set(st.session_state.futures_info_tickers):
                st.session_state.futures_info_tickers = new_infos_t3

            # Sidebar Broker-Order (Exklusivitäts-Logik mit Toast)
            current_orders_t3 = edited_t3[edited_t3["🛒 Order"] == True]["Ticker"].tolist()
            selected_ticker_t3 = None
            if len(current_orders_t3) > 0:
                new_ones = [t for t in current_orders_t3 if t != st.session_state.active_futures_order]
                if new_ones: selected_ticker_t3 = new_ones[0]
                elif len(current_orders_t3) == 1 and st.session_state.active_futures_order != current_orders_t3[0]: selected_ticker_t3 = current_orders_t3[0]
            
            if selected_ticker_t3:
                if st.session_state.get("active_order_ticker"):
                    old_asset = st.session_state.active_order_ticker
                    st.session_state.active_order_ticker = None
                    st.toast(f"⚠️ Aktive Order für {old_asset} verworfen – {selected_ticker_t3} in den Prop-Desk geladen!", icon="🔄")
                elif st.session_state.get("active_futures_order"):
                    old_asset = st.session_state.active_futures_order
                    st.toast(f"⚠️ Vorherige Order für {old_asset} durch {selected_ticker_t3} ersetzt!", icon="🔄")
                else:
                    st.toast(f"🛒 Prop-Desk geladen für: {selected_ticker_t3}", icon="✅")
                st.session_state.active_futures_order = selected_ticker_t3
                st.rerun()
            elif len(current_orders_t3) == 0 and st.session_state.active_futures_order in df_sorted["Ticker"].values:
                st.session_state.active_futures_order = None
                st.toast("Order-Desk geleert.", icon="ℹ️")
                st.rerun()

            # --- 3. DETAIL-BOXEN (🔍 Info) ---

            # --- 3. DETAIL-BOXEN (🔍 Info) ---
            for sym in st.session_state.futures_info_tickers:
                if sym == st.session_state.get("active_futures_order"):
                    continue
                if sym in df_sorted["Ticker"].values:
                    row_data = df_sorted[df_sorted["Ticker"] == sym].iloc[0]
                    breakdown_str = row_data.get('Score-Details', '')
                    parts = breakdown_str.split()
                    pts_saeulen = int(parts[0].split(":")[1]) if len(parts) > 0 else 0
                    pts_crv = int(parts[1].split(":")[1]) if len(parts) > 1 else 0
                    pts_rs = int(parts[2].split(":")[1]) if len(parts) > 2 else 0
                    pts_signal = int(parts[3].split(":")[1]) if len(parts) > 3 else 0
                    
                    with st.container(border=True):
                        st.markdown(f"### 🔍 Detail-Analyse: **{row_data['Ticker']}** ({row_data['Name']}) | {row_data['Klasse']}")
                        sym_u_t3 = str(sym).upper().strip()
                        if sym_u_t3 == "NQ=F":
                            richtwert_str = "Ziel-Korridor: 60–65 (Deckel: Werte >= 70 meiden)"
                        elif sym_u_t3 in ["CL=F", "MCL"]:
                            richtwert_str = "Ziel-Korridor: 65–70"
                        elif sym_u_t3 in ["USDJPY=X", "GBPUSD=X"]:
                            richtwert_str = "Ziel-Korridor: 60–70"
                        elif sym_u_t3 == "EURUSD=X":
                            richtwert_str = "Ziel-Korridor: 65–75"
                        elif any(ext in sym_u_t3 for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]) or row_data.get("Klasse") == "Krypto":
                            richtwert_str = "Ziel-Korridor: 65–80"
                        elif "=F" in sym_u_t3 or any(ext in sym_u_t3 for ext in ["=X", "DX-Y"]) or row_data.get("Klasse") in ["Futures", "Rohstoffe", "Forex"]:
                            richtwert_str = "Ziel-Korridor: 60–70"
                        else:
                            richtwert_str = "Zielwert: >= 70 (Relative Stärke)"
                        st.metric(label="🚀 Gesamtwertung", value=f"{row_data.get('Master-Score', 'N/A')} | {richtwert_str}", delta=row_data.get("Signal", ""), delta_color="off")
                        guideline_t3 = get_action_guideline(sym_u_t3, row_data.get("Sort_Score", 0), row_data.get("Klasse", ""))
                        if "🛑" in guideline_t3 or "⚠️" in guideline_t3:
                            st.warning(f"**🧭 Handlungsanweisung:** {guideline_t3}")
                        else:
                            st.info(f"**🧭 Handlungsanweisung:** {guideline_t3}")
                        
                        if sym_u_t3 in ["CL=F", "MCL", "EURUSD=X"] or any(ext in sym_u_t3 for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL", "NEAR"]) or row_data.get("Klasse") == "Krypto":
                            t3_min_score_threshold = 65
                        elif "=F" in sym_u_t3 or any(ext in sym_u_t3 for ext in ["=X", "DX-Y"]) or row_data.get("Klasse") in ["Futures", "Rohstoffe", "Forex"]:
                            t3_min_score_threshold = 60
                        else:
                            t3_min_score_threshold = 70

                        if row_data.get("Sort_Score", 0) >= t3_min_score_threshold:
                            typ_info = "Setup B (Trend-Pullback)" if "Trend" in row_data['Signal'] else "Setup A (Reversal/Extremum)"
                            dir_info = "Short" if "Short" in row_data['Signal'] else "Long"
                            st.markdown(f"**Typ:** {typ_info} ({dir_info}) | **Kurs:** {row_data['Kurs']} | **SL:** {row_data['Stop Loss']} | **TP:** {row_data['Take Profit']}")
                        rec_t3 = get_asset_strategy_recommendation(sym)
                        with st.container(border=True):
                            st.markdown(f"**🧬 Strategie-DNA & Empfehlung**")
                            st.markdown(f"**{rec_t3['label']}**")
                            st.markdown(f"🎯 **Konto:** {rec_t3['konto_typ']} | ⏱️ **TF:** {rec_t3['timeframe']}")
                            st.markdown(f"**Profil:** `{rec_t3['profil']}`")
                            st.caption(f"_{rec_t3['hinweis']}_")
                        st.markdown("""<style>[data-testid="stProgress"] { margin-top: -10px !important; margin-bottom: 25px !important; } [data-testid="stProgress"] > div > div > div, [data-testid="stProgress"] > div > div { height: 28px !important; border-radius: 10px !important; }</style>""", unsafe_allow_html=True)
                        
                        c_inf1, c_inf2 = st.columns(2)
                        with c_inf1:
                            is_setup_b = "Trend" in str(row_data.get("Signal", ""))
                            max_saeulen = 35 if is_setup_b else 45
                            max_crv = 20 if is_setup_b else 30
                            
                            st.markdown(f"**🏛️ Indikatoren: {pts_saeulen} / {max_saeulen} Pkt.**")
                            st.progress(min(pts_saeulen / float(max_saeulen), 1.0))
                            st.info(f"Details: {row_data.get('Säulen-Details', 'N/A')}")
                            
                            st.markdown(f"**⚖️ CRV-Bonus: {pts_crv} / {max_crv} Pkt.**")
                            st.progress(min(pts_crv / float(max_crv), 1.0))
                            if is_setup_b:
                                st.markdown(f"**📈 Rel. Stärke: {pts_rs} / 30 Pkt.**")
                                st.progress(min(pts_rs / 30.0, 1.0))
                            else:
                                st.markdown(f"**📈 Rel. Stärke: 0 / 0 Pkt.** (⚪ N/A)")
                                st.progress(0.0)
                            
                            st.markdown(f"**🛡️ Signal & Trend: {pts_signal} / 15 Pkt.**")
                            st.progress(min(pts_signal / 15.0, 1.0))
                            
                        with c_inf2:
                                st.markdown("**🛡️ Prop-Firm Stresstest**")
                                st.info(row_data['Stresstest'])
                                st.write("")
                                crv_val = row_data['_crv']
                                st.markdown(f"**⚖️ CRV (absolut): {crv_val:.2f}**")
                                st.markdown(f"**📊 RSI:** {row_data['RSI']}")

        else:
            st.info("Aktuell keine gültigen Einstiegssignale gefunden.")
            
        render_chart_system(res_t3, "t3")
#endregion

#region TAB 4 UI
with tab_lab:
    st.header("🏦 Operativer Konten- & Portfolio-Desk")
    
    if "lab_accounts" not in st.session_state.config or not st.session_state.config["lab_accounts"]:
        st.session_state.config["lab_accounts"] = {
            "default": {
                "id": "default", "name": "Standard Portfolio", "account_size": 10000.0, "risk_pct": 1.0, 
                "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Fusion (0.10% / 0.05%)", 
                "min_score": 70, "years": 5, "tickers": [], "last_backtest": None
            }
        }
        save_config(st.session_state.config)
        
    accounts = st.session_state.config["lab_accounts"]
    acc_opts = {acc["name"]: acc_id for acc_id, acc in accounts.items()}
    
    if "active_lab_account" not in st.session_state or st.session_state.active_lab_account not in accounts:
        st.session_state.active_lab_account = list(accounts.keys())[0]
        
    active_acc = accounts[st.session_state.active_lab_account]

    tab_lab_ops, tab_lab_strat = st.tabs(["🏦 Live-Desk & Journal", "🧪 Strategie-Labor & Optimizer"])
    
    # --- KPIs & Journal Data laden (Vorab-Berechnung für das aktive Konto) ---
    df_j = load_trade_journal()
    df_acc = df_j[df_j['account_name'] == active_acc['name']] if not df_j.empty else pd.DataFrame()
    
    df_closed = df_acc[df_acc['status'] == 'CLOSED'] if not df_acc.empty else pd.DataFrame()
    df_open = df_acc[df_acc['status'] == 'OPEN'] if not df_acc.empty else pd.DataFrame()
    
    df_closed_trading = df_closed[~df_closed['setup_type'].isin(['DEPOSIT', 'WITHDRAWAL'])] if not df_closed.empty else pd.DataFrame()
    realized_pnl = df_closed_trading['pnl_eur'].sum() if not df_closed_trading.empty else 0.0
    floating_pnl = 0.0
    open_trades_data = []
    
    if not df_open.empty:
        open_symbols = df_open['symbol'].unique().tolist()
        try:
            df_prices = fetch_market_data(open_symbols, "5d", "1d")
            for idx, row in df_open.iterrows():
                sym = row['symbol']
                ep = float(row['entry_price'])
                fx = float(row.get('fx_rate', 1.0))
                qty = float(row['position_size'])
                dir_m = 1 if row['direction'] == 'Long' else -1
                
                cur_p = ep
                if isinstance(df_prices.columns, pd.MultiIndex):
                    if sym in df_prices.columns.get_level_values(0):
                        cur_p = df_prices[sym]["Close"].dropna().iloc[-1]
                    elif sym in df_prices.columns.get_level_values(1):
                        cur_p = df_prices.xs(sym, level=1, axis=1)["Close"].dropna().iloc[-1]
                elif "Close" in df_prices:
                    cur_p = df_prices["Close"].dropna().iloc[-1]
                    
                point_val = float(row.get('point_value', 1.0)) if pd.notna(row.get('point_value')) else 1.0
                tr_raw_pnl = (cur_p - ep) * qty * point_val * dir_m
                tr_pnl = tr_raw_pnl * fx
                est_fees = float(row.get('est_fees_eur', 0.0) if pd.notna(row.get('est_fees_eur')) else 0.0)
                net_tr_pnl = tr_pnl - est_fees
                floating_pnl += net_tr_pnl
                
                sec = "Standard"
                for tag, t_data in st.session_state.config.get("scan_universes", {}).items():
                    if any(x["symbol"] == sym for x in t_data.get("tickers", [])):
                        sec = tag; break
                date_str = str(row['entry_date'])
                try: 
                    entry_dt = datetime.datetime.strptime(date_str, "%d/%m/%Y %H:%M")
                except ValueError:
                    try: entry_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                    except ValueError: entry_dt = datetime.datetime.now()
                    
                delta_t = datetime.datetime.now() - entry_dt
                t_sec = int(delta_t.total_seconds())
                d_days = max(0, t_sec // 86400)
                d_hours = max(0, (t_sec % 86400) // 3600)
                
                if d_days == 0:
                    days_str = f"{d_hours} Std."
                elif d_days == 1:
                    days_str = f"1 Tag, {d_hours} Std."
                else:
                    days_str = f"{d_days} Tage, {d_hours} Std."
                    
                c_type = str(row.get('contract_type', ''))
                if c_type == 'nan': c_type = ''
                
                inv_eur = float(row.get('invest_eur', 0.0))
                if inv_eur <= 0: inv_eur = ep * qty * (float(row.get('point_value', 1.0)) if pd.notna(row.get('point_value')) else 1.0) * fx
                net_pnl_pct = (net_tr_pnl / inv_eur) * 100 if inv_eur > 0 else 0.0
                
                open_trades_data.append({
                    "symbol": sym, "sector": sec, "entry": ep, "current": cur_p, 
                    "pnl_eur": net_tr_pnl, "pnl_raw": tr_raw_pnl, "pnl_pct": net_pnl_pct,
                    "days": days_str, "fx": fx, "curr": row['currency'],
                    "qty": qty, "contract_type": c_type, "base_currency": str(row.get('base_currency', 'EUR'))
                })
        except Exception:
                    pass

    total_pnl = realized_pnl + floating_pnl
    start_cap = float(active_acc.get("account_size", 10000.0))
    total_deposits = df_acc[df_acc['setup_type'] == 'DEPOSIT']['pnl_eur'].sum() if not df_acc.empty else 0.0
    total_withdrawals = abs(df_acc[df_acc['setup_type'] == 'WITHDRAWAL']['pnl_eur'].sum()) if not df_acc.empty else 0.0
    effective_base_cap = start_cap + total_deposits - total_withdrawals
    current_cap = effective_base_cap + total_pnl
    # ==========================================
    # SUB-TAB 1: LIVE-DESK & JOURNAL
    # ==========================================
    with tab_lab_ops:
        
        # --- 1. LIVE JOURNAL (OFFENE TRADES) ---
        st.header("📓 Live-Performance & Trade-Journal")
        
        acc_filter_opts = ["Alle Konten"] + list(acc_opts.keys())
        sel_j_acc = st.selectbox("Journal filtern nach Konto:", acc_filter_opts, index=0)
        
        df_journal_filtered = df_j.copy()
        if not df_journal_filtered.empty and sel_j_acc != "Alle Konten":
            df_journal_filtered = df_journal_filtered[df_journal_filtered['account_name'] == sel_j_acc]
            
        df_open_list = df_journal_filtered[df_journal_filtered['status'] == 'OPEN'] if not df_journal_filtered.empty else pd.DataFrame()
        if not df_open_list.empty:
            st.subheader("🟢 Offene Trades verwalten")
            
            for idx, row in df_open_list.iterrows():
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
                    with col1:
                        entry_d_str = str(row['entry_date'])
                        try: 
                            entry_dt = datetime.datetime.strptime(entry_d_str, "%d/%m/%Y %H:%M")
                            delta_c = datetime.datetime.now() - entry_dt
                            t_sec_c = int(delta_c.total_seconds())
                            c_days = max(0, t_sec_c // 86400)
                            c_hours = max(0, (t_sec_c % 86400) // 3600)
                            if c_days == 0:
                                curr_days_str = f"{c_hours} Std."
                            elif c_days == 1:
                                curr_days_str = f"1 Tag, {c_hours} Std."
                            else:
                                curr_days_str = f"{c_days} Tage, {c_hours} Std."
                        except Exception: 
                            try: 
                                entry_dt = datetime.datetime.strptime(entry_d_str, "%Y-%m-%d %H:%M")
                                delta_c = datetime.datetime.now() - entry_dt
                                t_sec_c = int(delta_c.total_seconds())
                                c_days = max(0, t_sec_c // 86400)
                                c_hours = max(0, (t_sec_c % 86400) // 3600)
                                if c_days == 0:
                                    curr_days_str = f"{c_hours} Std."
                                elif c_days == 1:
                                    curr_days_str = f"1 Tag, {c_hours} Std."
                                else:
                                    curr_days_str = f"{c_days} Tage, {c_hours} Std."
                            except Exception: 
                                curr_days_str = "0 Std."
                                
                        plan_days = int(float(row.get('atr_days', 0) if pd.notna(row.get('atr_days')) else 0))
                        
                        dir_label = "⬆️ LONG" if row['direction'] == 'Long' else "⬇️ SHORT"
                        st.write(f"**{row['symbol']} ({row['name']})** | `{dir_label}`")
                        st.caption(f"📅 **Eröffnet:** {entry_d_str} | ⏳ **Dauer:** {curr_days_str} (Geplant: {plan_days} Tage) | 🏦 **Konto:** {row['account_name']}")
                        
                        fx = float(row.get('fx_rate', 1.0))
                        curr = row['currency']
                        ep = float(row['entry_price'])
                        
                        cur_p = ep
                        found = False
                        if sel_j_acc == active_acc['name'] or sel_j_acc == "Alle Konten":
                            for t in open_trades_data:
                                if t["symbol"] == row['symbol']:
                                    cur_p = t["current"]
                                    found = True
                                    break
                        if not found:
                            try:
                                df_p = fetch_market_data([row['symbol']], "5d", "1d")
                                if not df_p.empty:
                                    if isinstance(df_p.columns, pd.MultiIndex):
                                        if "Close" in df_p.columns.get_level_values(0):
                                            cur_p = float(df_p["Close"].dropna().iloc[-1])
                                        elif row['symbol'] in df_p.columns.levels[0]:
                                            cur_p = float(df_p[row['symbol']]["Close"].dropna().iloc[-1])
                                    elif "Close" in df_p.columns:
                                        cur_p = float(df_p["Close"].dropna().iloc[-1])
                            except Exception:
                                cur_p = ep

                        cur_p_eur = cur_p * fx
                        pnl_temp = (cur_p - ep) / ep * 100 if row['direction'] == 'Long' else (ep - cur_p) / ep * 100
                        icon = "🟢" if pnl_temp >= 0 else "🔴"
                        
                        is_forex = str(row['symbol']).endswith('=X') or ep < 10.0
                        fmt = ".4f" if is_forex else ".2f"
                        dir_m = 1 if row['direction'] == 'Long' else -1
                        point_val = float(row.get('point_value', 1.0)) if pd.notna(row.get('point_value')) else 1.0
                        qty = float(row['position_size'])
                        raw_pnl = (cur_p - ep) * qty * point_val * dir_m
                        net_pnl_eur = (raw_pnl * fx) - float(row.get('est_fees_eur', 0.0) if pd.notna(row.get('est_fees_eur')) else 0.0)
                        inv_eur = float(row.get('invest_eur', 0.0))
                        if inv_eur <= 0:
                            inv_eur = ep * qty * point_val * fx
                        net_pnl_pct = (net_pnl_eur / inv_eur) * 100 if inv_eur > 0 else 0.0

                        if curr not in ["€", "EUR"]:
                            pnl_disp = f"**PnL:** {icon} {raw_pnl:+.2f} {curr} (≈ {net_pnl_eur:+.2f} € | Netto: {net_pnl_pct:+.1f}%)"
                        else:
                            pnl_disp = f"**PnL:** {icon} {net_pnl_eur:+.2f} € (Netto: {net_pnl_pct:+.1f}%)"
                        
                        st.markdown(f"**Kurs:** {cur_p:{fmt}} {curr} (≈ {cur_p_eur:.2f} € | Kurs: {pnl_temp:+.1f}%) | {pnl_disp}")
                        st.caption(f"Entry: {ep:{fmt}} {curr} (≈ {ep * fx:.2f} €) | Inv: {row['invest_eur']:.2f} €")
                        
                    with col2:
                        sl = float(row['sl_price'])
                        tp = float(row['tp_price'])
                        st.write(f"Initial-SL: {sl:{fmt}} {curr} (≈ {sl * fx:.2f} €)")
                        st.write(f"TP: {tp:{fmt}} {curr} (≈ {tp * fx:.2f} €)")
                        
                        if tp > ep and ep > sl:
                            atr_proxy = (tp - ep) / max(1.0, float(row.get('atr_days', 10.0)))
                            exit_mode_val = str(row.get('exit_mode', ''))
                            if not exit_mode_val or exit_mode_val == 'nan':
                                acc_prof = "prop_guard"
                                for a_id, a_data in st.session_state.config.get("lab_accounts", {}).items():
                                    if a_data["name"] == row['account_name']:
                                        acc_prof = a_data.get("exit_profile", "prop_guard")
                                        break
                                if acc_prof == "apex_lock": exit_mode_val = "TARGET_LOCKED"
                                elif acc_prof in ["prop_guard", "defensive_swing", "apex_commodity_scale", "commodity_scale"]: exit_mode_val = "PROP_DEFENSIVE"
                                else: exit_mode_val = "HOME_RUN_TREND" if "Trend" in str(row.get("setup_type", "")) else "ALPHA_CASHFLOW"

                            sym_str = str(row['symbol']).upper()
                            is_crypto_asset = any(sym_str.endswith(ext) for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF"])
                            rec_sl, sl_status = calculate_trailing_stop(cur_p, ep, sl, tp, atr_proxy, exit_mode=exit_mode_val, is_crypto=is_crypto_asset, direction=row['direction'])
                            st.write("")
                            is_improved = (rec_sl > sl) if row['direction'] == 'Long' else (rec_sl < sl)
                            if is_improved:
                                st.success(f"🎯 **Empf. Trail-SL: {rec_sl:{fmt}} {curr}**\n\n{sl_status}")
                            else:
                                st.markdown(f"🛡️ **Status:** {sl_status}")
                                
                    with col3:
                        st.write(f"Risk: {row['planned_risk_eur']:.2f} €")
                        st.write(f"Score: {row['master_score']}")
                        
                    with col4:
                        close_reason = st.selectbox("Grund:", ["🎯 Take Profit erreicht", "🛑 Stop Loss gegriffen", "🛑 Trailing-Stop gegriffen", "⏳ Time-Stop ausgelöst", "✋ Manueller Exit"], key=f"rsn_{row['id']}")
                        
                        def_price = ep
                        if "Take Profit" in close_reason: def_price = tp
                        elif "Stop Loss" in close_reason or "Trailing" in close_reason: def_price = sl
                        
                        c_ex1, c_ex2 = st.columns([2, 1])
                        with c_ex1:
                            step_val = 0.0001 if is_forex else 0.01
                            fmt_str = "%.4f" if is_forex else "%.2f"
                            exit_p_input = st.number_input("Aktueller / Exit-Kurs:", value=float(def_price), step=step_val, format=fmt_str, key=f"ex_{row['id']}_{idx}")
                                
                        with c_ex2:
                            curr_opts = [curr, "€"] if curr not in ["€", "EUR"] else ["€"]
                            exit_curr = st.selectbox("In:", curr_opts, key=f"ex_c_{row['id']}_{idx}")
                            
                        c_btn1, c_btn2 = st.columns(2)
                        
                        with c_btn1:
                            if st.button("Trade schließen", key=f"btn_{row['id']}_{idx}", use_container_width=True):
                                full_journal = load_trade_journal()
                                target_idx = full_journal[full_journal['id'] == row['id']].index[0]
                                
                                final_exit_price = exit_p_input
                                if exit_curr == "€" and curr not in ["€", "EUR"]:
                                    final_exit_price = exit_p_input / fx
                                    
                                full_journal['exit_date'] = full_journal['exit_date'].astype(object)
                                full_journal['exit_reason'] = full_journal['exit_reason'].astype(object)
                                
                                full_journal.at[target_idx, 'exit_price'] = final_exit_price
                                full_journal.at[target_idx, 'exit_date'] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                                full_journal.at[target_idx, 'exit_reason'] = close_reason
                                full_journal.at[target_idx, 'status'] = 'CLOSED'
                                
                                qty = float(row['position_size'])
                                point_val = float(row.get('point_value', 1.0)) if pd.notna(row.get('point_value')) else 1.0
                                dir_m = 1 if row['direction'] == 'Long' else -1
                                
                                raw_pnl = (final_exit_price - ep) * qty * point_val * dir_m
                                if any(ext in str(row['symbol']).upper() for ext in ["JPY=X", "CHF=X", "CAD=X"]) and final_exit_price > 0:
                                    raw_pnl = raw_pnl / final_exit_price
                                    
                                pnl = raw_pnl * fx
                                est_fees = float(row.get('est_fees_eur', 0.0) if pd.notna(row.get('est_fees_eur')) else 0.0)
                                pnl -= est_fees
                                pnl_pct = ((final_exit_price / ep) - 1) * 100 * dir_m
                                risk_eur = float(row['planned_risk_eur'])
                                r_mult = (pnl / risk_eur) if risk_eur > 0 else 0.0
                                
                                full_journal.at[target_idx, 'pnl_eur'] = pnl
                                full_journal.at[target_idx, 'pnl_pct'] = pnl_pct
                                full_journal.at[target_idx, 'r_multiple'] = r_mult
                                
                                save_trade_journal(full_journal)
                                st.success("Trade geschlossen!")
                                st.rerun()
                                
                        with c_btn2:
                            with st.popover("🗑️ Löschen", use_container_width=True):
                                st.markdown("⚠️ **Trade restlos löschen?**")
                                if st.button("✅ Ja, endgültig löschen", key=f"btn_del_yes_{row['id']}_{idx}", type="primary", use_container_width=True):
                                    full_journal = load_trade_journal()
                                    full_journal = full_journal[full_journal['id'] != row['id']]
                                    save_trade_journal(full_journal)
                                    st.success("Trade restlos gelöscht!")
                                    st.rerun()

        st.markdown("---")
        
        # --- 2. KONTO-ÜBERSICHT & LIVE-PORTFOLIO ---
        st.subheader("🏦 Konto-Übersicht & Live-Portfolio")
        
        c_acc1, c_acc2, c_acc3 = st.columns([2, 1, 1])
        with c_acc1:
            sel_acc_name = st.selectbox("Aktives Konto auswählen:", list(acc_opts.keys()), index=list(acc_opts.values()).index(st.session_state.active_lab_account))
            if acc_opts[sel_acc_name] != st.session_state.active_lab_account:
                st.session_state.active_lab_account = acc_opts[sel_acc_name]
                st.rerun()
                
        with c_acc2:
            st.write(""); st.write("")
            if st.button("➕ Neues Konto", use_container_width=True):
                new_id = str(uuid.uuid4())[:8]
                accounts[new_id] = {
                    "id": new_id, "name": f"Konto {len(accounts)+1}", "account_size": 10000.0, "risk_pct": 1.0, 
                    "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Fusion (0.10% / 0.05%)", 
                    "min_score": 70, "years": 5, "tickers": [], "last_backtest": None, "tax_category": "private"
                }
                st.session_state.active_lab_account = new_id
                save_config(st.session_state.config)
                st.rerun()
                
        with c_acc3:
            st.write(""); st.write("")
            if len(accounts) > 1:
                if st.button("🗑️ Konto löschen", use_container_width=True):
                    del accounts[st.session_state.active_lab_account]
                    st.session_state.active_lab_account = list(accounts.keys())[0]
                    save_config(st.session_state.config)
                    st.rerun()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Basis-Kapital", f"{effective_base_cap:,.2f} €", delta=f"{total_deposits - total_withdrawals:+,.2f} € Netto-Zufluss" if (total_deposits or total_withdrawals) else None)
        m2.metric("Aktueller Kontostand", f"{current_cap:,.2f} €", f"{floating_pnl:+.2f} € offen", delta_color="normal")
        m3.metric("Gesamt PnL (Netto)", f"{total_pnl:,.2f} €", f"{(total_pnl/effective_base_cap)*100:+.2f} %" if effective_base_cap > 0 else "0.00 %")
        m4.metric("Offene Trades", f"{len(open_trades_data)} / 3")

        with st.expander("💸 Kapital-Zufluss / Entnahme buchen (Privateinlage / Entnahme)", expanded=False):
            with st.form("form_cash_flow", border=False):
                c_cf1, c_cf2, c_cf3 = st.columns([1, 1, 2])
                with c_cf1:
                    cf_type = st.selectbox("Buchungsart", ["Einzahlung (Privateinlage / Reinvestment)", "Auszahlung (Privatentnahme)"])
                with c_cf2:
                    cf_amount = st.number_input("Betrag (€)", min_value=10.0, step=100.0, value=500.0, format="%.2f")
                with c_cf3:
                    cf_notes = st.text_input("Verwendungszweck / Mittelherkunft", placeholder="z. B. Reinvestment aus Apex Payout März 2026")
                    
                cf_submit = st.form_submit_button("💾 Buchung unwiderruflich erfassen", use_container_width=True)
                if cf_submit:
                    df_j_cf = load_trade_journal()
                    is_deposit = "Einzahlung" in cf_type
                    signed_amount = float(cf_amount) if is_deposit else -float(cf_amount)
                    
                    new_cf_entry = {
                        'id': str(uuid.uuid4())[:8],
                        'account_name': active_acc['name'],
                        'entry_date': datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        'exit_date': datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        'symbol': 'CASH',
                        'name': 'Kapitalzuführung' if is_deposit else 'Kapitalentnahme',
                        'direction': 'DEPOSIT' if is_deposit else 'WITHDRAWAL',
                        'signal_price': 1.0,
                        'entry_price': 1.0,
                        'currency': '€',
                        'fx_rate': 1.0,
                        'position_size': abs(signed_amount),
                        'contract_type': '',
                        'point_value': 1.0,
                        'base_currency': 'EUR',
                        'invest_eur': abs(signed_amount) if is_deposit else 0.0,
                        'sl_price': 0.0,
                        'tp_price': 0.0,
                        'planned_risk_eur': 0.0,
                        'est_fees_eur': 0.0,
                        'master_score': 0,
                        'setup_type': 'DEPOSIT' if is_deposit else 'WITHDRAWAL',
                        'mc_robustness': 'N/A',
                        'atr_days': 0,
                        'exit_mode': 'CASH_FLOW',
                        'status': 'CLOSED',
                        'exit_price': 1.0,
                        'pnl_eur': signed_amount,
                        'pnl_pct': 0.0,
                        'r_multiple': 0.0,
                        'exit_reason': 'Kapitalfluss',
                        'notes': cf_notes if cf_notes else ('Privateinlage' if is_deposit else 'Privatentnahme'),
                        'strategy_version': 'v1.0.0',
                        'execution_type': 'MANUAL_CASH'
                    }
                    df_j_cf = pd.concat([df_j_cf, pd.DataFrame([new_cf_entry])], ignore_index=True)
                    save_trade_journal(df_j_cf)
                    st.toast(f"✅ {cf_type.split()[0]} von {cf_amount:,.2f} € erfasst!", icon="💸")
                    st.rerun()

        with st.expander(f"⚙️ Kontodaten bearbeiten: {active_acc['name']}", expanded=False):
            acc_tax_cat = active_acc.get("tax_category", "private")
            cat_map = {"prop_firm": "🏢 Fremdkapital / Prop-Challenge", "private": "👤 Privates Vermögensdepot"}
            cat_rev_map = {v: k for k, v in cat_map.items()}
            
            new_cat_label = st.selectbox("Konto-Kategorie (Zweck)", list(cat_map.values()), index=list(cat_map.keys()).index(acc_tax_cat), key=f"tax_out_{active_acc['id']}")
            new_tax_cat_val = cat_rev_map[new_cat_label]
            
            if new_tax_cat_val != acc_tax_cat:
                active_acc["tax_category"] = new_tax_cat_val
                st.session_state.config["lab_accounts"][active_acc["id"]] = active_acc
                save_config(st.session_state.config)
                st.rerun()

            with st.form(f"form_acc_{active_acc['id']}"):
                c_s1, c_s2, c_s3, c_s4 = st.columns(4)
                with c_s1: new_name = st.text_input("Kontoname", value=active_acc.get("name", ""), key=f"name_{active_acc['id']}")
                with c_s2: new_cap = st.number_input("Startkapital (€)", value=float(active_acc.get("account_size", 10000.0)), step=1000.0, key=f"cap_{active_acc['id']}")
                with c_s3: new_risk = st.number_input("Risiko pro Trade (%)", value=float(active_acc.get("risk_pct", 1.0)), step=0.1, key=f"risk_{active_acc['id']}")
                with c_s4: 
                    broker_options = [
                        "Apex / Tradovate (Futures Insti-Rate)",
                        "FTMO / MetaTrader 5 (Forex Raw Spread)",
                        "Interactive Brokers / Flatex (Aktien Flat)",
                        "Bybit / Krypto-Börse (0.06% / 0.02%)",
                        "Bitpanda Fusion (0.10% / 0.05%)",
                        "Bitpanda Retail (1.49% Spread)"
                    ]
                    current_broker = active_acc.get("broker_profile", "Bitpanda Fusion (0.10% / 0.05%)")
                    
                    # Abwärtskompatibilität gewährleisten
                    if current_broker == "Apex / CME Futures (Insti-Rate)": current_broker = "Apex / Tradovate (Futures Insti-Rate)"
                    elif current_broker == "FTMO / Forex (Raw Spread)": current_broker = "FTMO / MetaTrader 5 (Forex Raw Spread)"
                    elif current_broker == "Aktien Broker (1.00 € Flat)": current_broker = "Interactive Brokers / Flatex (Aktien Flat)"
                    
                    if current_broker not in broker_options:
                        if "Fusion" in current_broker: current_broker = "Bitpanda Fusion (0.10% / 0.05%)"
                        elif "Retail" in current_broker: current_broker = "Bitpanda Retail (1.49% Spread)"
                        elif "Apex" in current_broker: current_broker = "Apex / Tradovate (Futures Insti-Rate)"
                        elif "FTMO" in current_broker: current_broker = "FTMO / MetaTrader 5 (Forex Raw Spread)"
                        elif "Flat" in current_broker or "Interactive" in current_broker: current_broker = "Interactive Brokers / Flatex (Aktien Flat)"
                        elif "Bybit" in current_broker: current_broker = "Bybit / Krypto-Börse (0.06% / 0.02%)"
                        else: current_broker = "Bitpanda Fusion (0.10% / 0.05%)"
                    new_broker = st.selectbox("Broker-Profil", broker_options, index=broker_options.index(current_broker), key=f"broker_{active_acc['id']}")
                c_s5, c_s6, c_s7, c_s8 = st.columns(4)
                with c_s5: new_years = st.slider("Backtest-Jahre", min_value=1, max_value=6, value=int(active_acc.get("years", 5)), key=f"years_{active_acc['id']}")
                with c_s6: new_score = st.slider("Min. Score", min_value=60, max_value=85, value=int(active_acc.get("min_score", 70)), step=5, key=f"score_{active_acc['id']}")
                with c_s7: new_comp = st.selectbox("Zinseszins", ["active", "inactive"], index=["active", "inactive"].index(active_acc.get("compounding", "inactive")), key=f"comp_{active_acc['id']}")
                acc_tax_cat = active_acc.get("tax_category", "private")
                prop_profiles = {
                    "Target-Lock Intraday (Apex)": "apex_lock",
                    "Forex Swing-Runner (FTMO)": "ftmo_swing"
                }
                private_profiles = {
                    "Home-Run Trend (Maximal-Alpha)": "private_alpha",
                    "Rohstoff-Runner (Privat-Alpha)": "commodity_alpha",
                    "Scale-Out Defensiv (Rohstoff-Swing)": "commodity_scale",
                    "Defensiv-Swing (Teilgewinn ab +1.0 R)": "defensive_swing"
                }
                
                cur_prof = active_acc.get("exit_profile", "prop_guard")
                if cur_prof == "prop_guard": cur_prof = "defensive_swing"
                elif cur_prof == "apex_commodity_scale": cur_prof = "commodity_scale"
                
                available_profiles = prop_profiles if acc_tax_cat == "prop_firm" else private_profiles
                labels = list(available_profiles.keys())
                default_label = labels[0]
                for lbl, key_val in available_profiles.items():
                    if key_val == cur_prof:
                        default_label = lbl
                        break
                        
                with c_s8:
                    selected_label = st.selectbox("Exit-Profil", labels, index=labels.index(default_label), key=f"prof_{active_acc['id']}")
                    chosen_exit_profile = available_profiles[selected_label]
                
                def_dir = "both" if chosen_exit_profile in ["prop_guard", "defensive_swing", "apex_lock"] else "long"
                new_direction = st.selectbox("Handelsrichtung: Bidirektional (Both) / Long-Only / Short-Only", ["both", "long", "short"], index=["both", "long", "short"].index(active_acc.get("direction", def_dir)), key=f"dir_{active_acc['id']}")
                if st.form_submit_button("💾 Kontodaten speichern", use_container_width=True):
                    active_acc.update({
                        "name": new_name, 
                        "account_size": new_cap, 
                        "risk_pct": new_risk, 
                        "broker_profile": new_broker, 
                        "years": new_years, 
                        "min_score": new_score, 
                        "compounding": new_comp, 
                        "exit_profile": chosen_exit_profile, 
                        "direction": new_direction, 
                        "mode": active_acc.get("mode", "walk_forward"), 
                        "trailing_stop": active_acc.get("trailing_stop", "active")
                    })
                    st.session_state.config["lab_accounts"][active_acc["id"]] = active_acc
                    st.session_state.active_lab_account = active_acc["id"]
                    save_config(st.session_state.config)
                    st.success("Gespeichert!")
                    st.rerun()
            dl_limit = float(active_acc.get("daily_loss", start_cap * 0.05)) # Fallback 5%
            mdd_limit = float(active_acc.get("trail_dd", start_cap * 0.10)) # Fallback 10%
            
            # PnL von heute für Daily Loss berechnen
            today_str = datetime.datetime.now().strftime("%d/%m/%Y")
            df_closed_today = df_closed_trading[df_closed_trading['exit_date'].astype(str).str.contains(today_str, na=False)] if not df_closed_trading.empty else pd.DataFrame()
            today_realized_pnl = df_closed_today['pnl_eur'].sum() if not df_closed_today.empty else 0.0
            daily_pnl = today_realized_pnl + floating_pnl
            
            st.markdown("### 🛡️ Prop-Firm Live-Monitoring")
            c_prop1, c_prop2 = st.columns(2)
            c_prop1.metric("Daily PnL vs Limit", f"{daily_pnl:,.2f} €", f"Limit: -{dl_limit:,.2f} €", delta_color="normal" if daily_pnl >= -dl_limit else "inverse")
            
            peak_equity = active_acc.get("peak_equity", start_cap)
            if current_cap > peak_equity: 
                peak_equity = current_cap
                active_acc["peak_equity"] = peak_equity
                save_config(st.session_state.config)
                
            current_drawdown = peak_equity - current_cap
            c_prop2.metric("Trailing Drawdown (Aktuell)", f"-{current_drawdown:,.2f} €", f"Max DD Erlaubt: {mdd_limit:,.2f} €", delta_color="normal" if current_drawdown <= mdd_limit else "inverse")
            st.markdown("---")

        kader_tickers = active_acc.get("tickers", [])
        if kader_tickers:
            st.markdown(f"**📋 Zugewiesener Konto-Kader ({len(kader_tickers)} Ticker):** " + " · ".join(kader_tickers))
            if st.button("🔍 Live-Check: Meinen Konto-Kader auf Signale prüfen", type="primary", use_container_width=True):
                with st.spinner("Prüfe aktuelle Setup-Bedingungen für den Kader..."):
                    try:
                        cfg_t2 = st.session_state.config.get("tab2_settings", {})
                        t_b_check = cfg_t2.get("rsi_buy", 30.0)
                        t_s_check = cfg_t2.get("rsi_sell", 70.0)
                        
                        b_df_check = fetch_market_data(kader_tickers, "1y", "1d")
                        if isinstance(b_df_check.columns, pd.MultiIndex) and len(kader_tickers) == 1: 
                            b_df_check.columns = b_df_check.columns.get_level_values(0)
                            
                        check_res = []
                        for sym in kader_tickers:
                            df_t = b_df_check[sym].copy() if (isinstance(b_df_check.columns, pd.MultiIndex) and sym in b_df_check.columns.get_level_values(0)) else (b_df_check.xs(sym, level=1, axis=1).copy() if isinstance(b_df_check.columns, pd.MultiIndex) else b_df_check.copy())
                            
                            if not df_t.empty and "Close" in df_t:
                                calc = calc_rsi_and_targets(df_t, t_b_check, t_s_check, strategy_mode="5_saeulen_core", ticker=sym)
                                if calc:
                                    r, p_b, p_s, plot, details = calc
                                    c_p = plot['Close'].iloc[-1]
                                    rs_ratio = calc_relative_strength(sym, plot)
                                    sl, tp, crv_rating = calculate_sl_tp_crv(plot, c_p, p_s, "tab2")
                                    m_score_val, m_score_str, _ = calculate_master_score(details, crv_rating, rs_ratio, r, t_b_check)
                                    
                                    if m_score_val >= 70 or "Long" in details["ampel"] or "Kauf" in details["ampel"] or "Trend-Kauf" in details["ampel"]:
                                        diag = "🟢 Kaufzone"
                                    elif c_p < plot['EMA_200'].iloc[-1] or "Blockiert" in details["ampel"] or "blockiert" in details["ampel"]:
                                        diag = "🔴 Trend blockiert (unter EMA 200)"
                                    else:
                                        diag = "🟡 Neutral"
                                        
                                    check_res.append({
                                        "Ticker": sym, "Kurs": f"{c_p:.2f}", "RSI": f"{r:.2f}",
                                        "Ampel": details["ampel"], "Master-Score": m_score_val,
                                        "Diagnose": diag, "Laden": False
                                    })
                        if check_res:
                            df_check = pd.DataFrame(check_res).sort_values(by="Master-Score", ascending=False)
                            st.markdown("#### 📡 Status-Report (Konto-Kader)")
                            
                            def color_check(row):
                                sig = str(row["Diagnose"])
                                if "Zombie" in sig or "blockiert" in sig: return ["background-color: #f8d7da; color: #721c24"] * len(row)
                                if "Kaufzone" in sig: return ["background-color: #d4edda; color: #155724; font-weight: bold"] * len(row)
                                return [""] * len(row)
                            
                            ed_check = st.data_editor(
                                df_check.style.apply(color_check, axis=1), 
                                hide_index=True, use_container_width=True,
                                disabled=["Ticker", "Kurs", "RSI", "Ampel", "Master-Score", "Diagnose"],
                                column_config={"Laden": st.column_config.CheckboxColumn("🛒 In Desk", default=False)},
                                key="kader_check_editor"
                            )
                            
                            load_syms = ed_check[ed_check["Laden"] == True]["Ticker"].tolist()
                            if load_syms:
                                st.session_state.active_order_ticker = load_syms[0]
                                st.toast(f"🛒 {load_syms[0]} in den Order-Desk geladen! (Wechsle in die Seitenleiste)", icon="✅")
                        else:
                            st.info("Konnte keine Ticker-Daten abrufen.")
                    except Exception as e:
                        st.error(f"Fehler beim Live-Check: {e}")
        else:
            st.info("ℹ️ **Leerer Kader:** Füge im 'Strategie-Labor' (Tab 4.2) Ticker hinzu, um den Konto-Check und Optimizer zu nutzen.")
        if st.button("✏️ Kader direkt in Tab 4.2 bearbeiten", use_container_width=True):
            st.info("ℹ️ Bitte wechsle oben auf den Reiter '🧪 Strategie-Labor & Optimizer'.")
        st.markdown("---")

        st.markdown("### 🎛️ Live-Portfolio (Aktuell gehandelt)")
        slots = st.columns(3)
        open_sectors = []
        for i in range(3):
            with slots[i]:
                with st.container(border=True):
                    if i < len(open_trades_data):
                        tr = open_trades_data[i]
                        open_sectors.append(tr["sector"])
                        st.markdown(f"**{tr['symbol']}**")
                        st.caption(f"📂 {tr['sector']}")
                        icon = "🟢" if tr["pnl_eur"] >= 0 else "🔴"
                        
                        # Dynamische Währungsanzeige (USD vs EUR)
                        if tr.get('base_currency', 'EUR') == 'USD' or tr['curr'] == 'USD':
                            raw_val = tr.get('pnl_raw', tr['pnl_eur'] / tr['fx'] if tr['fx'] > 0 else tr['pnl_eur'])
                            st.markdown(f"**PnL:** {icon} **${raw_val:,.2f}**")
                            st.markdown(f"<span style='font-size:0.8em;'>💶 ≈ {tr['pnl_eur']:,.2f} € ({tr['pnl_pct']:+.1f}%)</span>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"**PnL:** {icon} **{tr['pnl_eur']:,.2f} €** ({tr['pnl_pct']:+.1f}%)")
                        
                        qty_disp = f"{tr.get('qty', 0):g} {tr.get('contract_type', '')}".strip() if tr.get('contract_type', '') else f"{tr.get('qty', 0):.2f} Stk."
                        st.write(f"Size: {qty_disp}")
                        
                        st.write(f"Entry: {tr['entry']:.2f} {tr['curr']} | Cur: {tr['current']:.2f} {tr['curr']}")
                        st.caption(f"⏱️ Gehalten: {tr['days']}")
                    else:
                        st.markdown("### ⚪ Slot frei für neues Setup")
                        st.caption("Bereit für Order")
                        st.write("")
                        st.write("")
                        st.write("")
                        
        sec_counts = {}
        for s in open_sectors: sec_counts[s] = sec_counts.get(s, 0) + 1
        sec_warnings = []
        for s, c in sec_counts.items():
            if c >= 2: sec_warnings.append(f"⚠️ {s} {c}/2 belegt – maximal 2 pro Branche erlaubt!")
            else: sec_warnings.append(f"✅ {s} ({c}/2)")
        if sec_warnings: st.info(" | ".join(sec_warnings))
        else: st.success("✅ Alle Sektoren frei (max. 2 pro Branche erlaubt).")

        st.markdown("---")

        # --- 3. MANUELL NACHTRAGEN ---
        with st.expander("➕ Trade manuell nachtragen (Historischer Snapshot)", expanded=False):
            c_man_search, c_man_acc = st.columns([2, 1])
            with c_man_search:
                sq_man = st.text_input("Yahoo-Suche oder Ticker (für manuellen Trade):", key="search_man_acc")
                sug_man = []
                if sq_man and len(sq_man.strip()) >= 2:
                    try:
                        headers = {"User-Agent": "Mozilla/5.0"}
                        resp = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={sq_man.strip()}&quotesCount=5", headers=headers, timeout=3)
                        if resp.status_code == 200:
                            for q in resp.json().get("quotes", []):
                                if "symbol" in q: sug_man.append(f"{q['symbol']} - {q.get('longname', q.get('shortname', ''))}")
                    except: pass
                chosen_man_raw = st.selectbox("Treffer:", sug_man, key="sel_man_acc") if sug_man else None
                
            with c_man_acc:
                man_acc = st.selectbox("Ziel-Konto", list(acc_opts.keys()), key="man_acc_sel")
                
            with st.form("manual_trade_form"):
                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    man_date = st.date_input("Kaufdatum", value=datetime.date.today(), format="DD/MM/YYYY")
                    man_time = st.time_input("Uhrzeit (ca.)", value=datetime.time(15, 30))
                    man_dir = st.selectbox("Richtung", ["Long", "Short"])
                with col_m2:
                    man_price = st.number_input("Tatsächlicher Kaufkurs", min_value=0.0, step=0.01)
                    input_mode = st.radio("Eingabe via:", ["Stückzahl", "Investitionsbetrag (€)"])
                with col_m3:
                    man_size_input = st.number_input("Stückzahl", min_value=0.0, step=0.1, format="%.4f")
                    man_invest_input = st.number_input("Investitionsbetrag (€)", min_value=0.0, step=10.0, format="%.2f")
                    
                if st.form_submit_button("💾 Trade nachtragen & simulieren", use_container_width=True):
                    if chosen_man_raw:
                        man_ticker = chosen_man_raw.split(" - ")[0]
                        man_name = chosen_man_raw.split(" - ")[1] if " - " in chosen_man_raw else man_ticker
                        
                        if man_price <= 0.0:
                            import datetime as dt
                            end_dt = man_date + dt.timedelta(days=5)
                            try:
                                df_h_fallback = yf.download(man_ticker, start=man_date, end=end_dt, progress=False)
                                if isinstance(df_h_fallback.columns, pd.MultiIndex):
                                    df_h_fallback.columns = df_h_fallback.columns.get_level_values(0)
                                man_price = float(df_h_fallback["Close"].dropna().iloc[0])
                                st.toast(f"ℹ️ Kaufkurs 0.00: Historischer Schlusskurs von {man_price:.2f} verwendet.", icon="📈")
                            except Exception:
                                st.error("Konnte historischen Kurs nicht abrufen.")
                                st.stop()

                        fx_m = get_fx_rate(get_currency_symbol(man_ticker))
                        
                        if input_mode == "Investitionsbetrag (€)":
                            man_size = round(man_invest_input / (man_price * fx_m), 4) if (man_price * fx_m) > 0 else 0
                        else:
                            man_size = man_size_input
                            
                        if man_size > 0:
                            with st.spinner("Lade Historie & berechne Setup..."):
                                try:
                                    df_h = yf.download(man_ticker, period="2y", interval="1d", progress=False)
                                    if isinstance(df_h.columns, pd.MultiIndex):
                                        df_h.columns = df_h.columns.get_level_values(0)
                                    
                                    df_slice = df_h.loc[:pd.to_datetime(man_date)]
                                    if not df_slice.empty:
                                        calc = calc_rsi_and_targets(df_slice, 30, 70, strategy_mode="5_saeulen_core", ticker=man_ticker)
                                        if calc:
                                            r, p_b, p_s, plot_h, details_h = calc
                                            sl_m, tp_m, crv_m = calculate_sl_tp_crv(plot_h, man_price, p_s, "tab2")
                                            atr_m = plot_h["ATR"].iloc[-1] if "ATR" in plot_h.columns else 0
                                            
                                            is_setup_b = "Trend" in str(details_h.get("ampel", ""))
                                            if is_setup_b:
                                                exp_days = 15
                                            else:
                                                exp_days = (abs(tp_m - man_price) / atr_m) if atr_m > 0 else 10
                                                exp_days = max(3.0, round(exp_days, 1))
                                                
                                            rs_ratio = calc_relative_strength(man_ticker, plot_h)
                                            m_score, m_str, m_breakdown = calculate_master_score(details_h, crv_m, rs_ratio, r, 30, direction=man_dir)
                                            
                                            dt_str = datetime.datetime.combine(man_date, man_time).strftime("%d/%m/%Y %H:%M")
                                            inv_eur = man_price * man_size * fx_m
                                            risk_eur = abs(man_price - sl_m) * man_size * fx_m
                                            
                                            # Gebuehren Engine
                                            acc_broker_m = st.session_state.config.get("lab_accounts", {}).get(acc_opts[man_acc], {}).get("broker_profile", "Bitpanda Fusion (0.10% / 0.05%)")
                                            est_fees = 0.0
                                            if "Bitpanda Standard" in acc_broker_m or "Retail" in acc_broker_m or "1.49%" in acc_broker_m: est_fees = max(2.00, inv_eur * 2 * 0.0199)
                                            elif "Bitpanda Fusion" in acc_broker_m or "0.10%" in acc_broker_m: est_fees = inv_eur * 2 * 0.0010
                                            elif "Krypto Börse" in acc_broker_m or "0.25%" in acc_broker_m: est_fees = inv_eur * 2 * 0.0025
                                            elif "Bybit" in acc_broker_m or "0.06%" in acc_broker_m: est_fees = inv_eur * 2 * 0.0006
                                            elif "Apex" in acc_broker_m or "Tradovate" in acc_broker_m: est_fees = inv_eur * 2 * (0.00005 + 0.0001)
                                            elif "FTMO" in acc_broker_m or "MetaTrader" in acc_broker_m: est_fees = inv_eur * 2 * (0.00003 + 0.00002)
                                            elif "Aktien Broker" in acc_broker_m or "Interactive" in acc_broker_m or "Flatex" in acc_broker_m or "Flat" in acc_broker_m: est_fees = 2.00
                                            
                                            acc_prof_m = st.session_state.config.get("lab_accounts", {}).get(acc_opts[man_acc], {}).get("exit_profile", "prop_guard")
                                            if acc_prof_m in ["apex_lock", "prop_guard", "defensive_swing", "apex_commodity_scale", "commodity_scale"]:
                                                determined_exit_mode = "TARGET_LOCKED" if acc_prof_m == "apex_lock" else "PROP_DEFENSIVE"
                                            else:
                                                determined_exit_mode = "HOME_RUN_TREND" if is_setup_b else "ALPHA_CASHFLOW"

                                            new_man_trade = {
                                                'id': str(uuid.uuid4())[:8], 'account_name': man_acc,
                                                'entry_date': dt_str, 'exit_date': "", 'symbol': man_ticker,
                                                'name': man_name, 'direction': man_dir,
                                                'signal_price': man_price, 'entry_price': man_price, 'currency': get_currency_symbol(man_ticker),
                                                'fx_rate': fx_m, 'position_size': man_size, 'invest_eur': inv_eur,
                                                'sl_price': sl_m, 'tp_price': tp_m, 'planned_risk_eur': risk_eur,
                                                'est_fees_eur': est_fees, 'master_score': m_score,
                                                'setup_type': details_h.get("ampel", "Manuell"),
                                                'mc_robustness': "N/A", 'atr_days': exp_days,
                                                'exit_mode': determined_exit_mode,
                                                'status': 'OPEN', 'exit_price': None, 'pnl_eur': None, 'pnl_pct': None,
                                                'r_multiple': None, 'exit_reason': "", 'notes': "Historischer Nachtrag",
                                                'strategy_version': 'v1.0.0', 'execution_type': 'HISTORICAL_MANUAL'
                                            }
                                            df_j_temp = load_trade_journal()
                                            df_j_temp = pd.concat([df_j_temp, pd.DataFrame([new_man_trade])], ignore_index=True)
                                            save_trade_journal(df_j_temp)
                                            st.success(f"✅ Trade für {man_name} am {man_date} rekonstruiert und eingeloggt!")
                                            st.rerun()
                                except Exception as e:
                                    st.error(f"Fehler bei Rekonstruktion: {e}")

        # --- 4. HISTORIE ---
        df_closed_list = df_journal_filtered[df_journal_filtered['status'] == 'CLOSED'] if not df_journal_filtered.empty else pd.DataFrame()
        if not df_closed_list.empty:
            st.markdown("---")
            st.subheader("📚 Historie & Performance (Geschlossene Trades)")
            
            csv_export_data = df_journal_filtered.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Mein Trade-Journal herunterladen (CSV-Export)",
                data=csv_export_data,
                file_name=f"trade_journal_{st.session_state.username}.csv",
                mime="text/csv",
                use_container_width=True
            )
            st.write("")
            
            df_closed_trades_only = df_closed_list[~df_closed_list['symbol'].isin(['CASH', 'PAYOUT', 'CHALLENGE_FEE']) & ~df_closed_list['setup_type'].isin(['DEPOSIT', 'WITHDRAWAL', 'PAYOUT', 'CHALLENGE_FEE'])]
            total_pnl_all = df_closed_trades_only['pnl_eur'].sum() if not df_closed_trades_only.empty else 0.0
            win_count_all = len(df_closed_trades_only[df_closed_trades_only['pnl_eur'] > 0]) if not df_closed_trades_only.empty else 0
            win_rate_all = (win_count_all / len(df_closed_trades_only) * 100) if len(df_closed_trades_only) > 0 else 0.0
            avg_r_all = df_closed_trades_only['r_multiple'].mean() if not df_closed_trades_only.empty else 0.0
            if pd.isna(avg_r_all): avg_r_all = 0.0
            
            c_k1, c_k2, c_k3 = st.columns(3)
            c_k1.metric("Realisierter PnL (€)", f"{total_pnl_all:,.2f} €", delta=f"{total_pnl_all:,.2f} €", delta_color="normal" if total_pnl_all != 0 else "off")
            c_k2.metric("Winrate (%)", f"{win_rate_all:.1f} %")
            c_k3.metric("Ø R-Multiple", f"{avg_r_all:.2f} R")
            st.write("")
            
            def calc_hd(row):
                try:
                    try: e_dt = datetime.datetime.strptime(str(row['entry_date']), "%d/%m/%Y %H:%M")
                    except: e_dt = datetime.datetime.strptime(str(row['entry_date']), "%Y-%m-%d %H:%M")
                    try: x_dt = datetime.datetime.strptime(str(row['exit_date']), "%d/%m/%Y %H:%M")
                    except: x_dt = datetime.datetime.strptime(str(row['exit_date']), "%Y-%m-%d %H:%M")
                    delta = x_dt - e_dt
                    if delta.days <= 0: return "Intraday"
                    return f"{delta.days} Tage, {delta.seconds // 3600} Std."
                except: return "Unbekannt"

            df_closed_list['Haltedauer'] = df_closed_list.apply(calc_hd, axis=1)

            display_cols = ['account_name', 'entry_date', 'exit_date', 'Haltedauer', 'symbol', 'name', 'direction', 'exit_reason', 'pnl_eur', 'pnl_pct', 'r_multiple']
            df_disp = df_closed_list[display_cols].copy()
            df_disp.rename(columns={
                'account_name': 'Konto',
                'entry_date': 'Entry-Datum',
                'exit_date': 'Exit-Datum',
                'symbol': 'Ticker',
                'name': 'Name',
                'direction': 'Richtung',
                'exit_reason': 'Exit-Grund',
                'pnl_eur': 'PnL (€)',
                'pnl_pct': 'PnL (%)',
                'r_multiple': 'R-Multiple'
            }, inplace=True)
            
            df_disp['PnL (€)'] = df_disp['PnL (€)'].apply(lambda x: f"{x:.2f} €")
            df_disp['PnL (%)'] = df_disp['PnL (%)'].apply(lambda x: f"{x:.2f} %")
            df_disp['R-Multiple'] = df_disp['R-Multiple'].apply(lambda x: f"{x:.2f} R")
            
            def highlight_pnl(row):
                val = row['PnL (€)']
                if val.startswith('-'): return ['background-color: #f8d7da; color: #721c24'] * len(row)
                elif val != '0.00 €': return ['background-color: #d4edda; color: #155724'] * len(row)
                return [''] * len(row)
                
            st.dataframe(df_disp.style.apply(highlight_pnl, axis=1), use_container_width=True, hide_index=True)
            
            st.markdown("---")
            detail_opts = [f"{r['symbol']} ({r['exit_date']})" for _, r in df_closed_list.iterrows()]
            sel_detail = st.selectbox("🔍 Trade-Details einblenden:", ["- Auswählen -"] + detail_opts)
            if sel_detail != "- Auswählen -":
                dt_str = sel_detail.split(" (")[1].replace(")", "")
                sym_str = sel_detail.split(" (")[0]
                tr_row = df_closed_list[(df_closed_list['symbol'] == sym_str) & (df_closed_list['exit_date'] == dt_str)].iloc[0]
                with st.container(border=True):
                    st.markdown(f"### 🔍 Details: {tr_row['symbol']} ({tr_row['name']})")
                    st.markdown("#### 🎯 Ergebnis")
                    c_d1, c_d2, c_d3, c_d4 = st.columns(4)
                    c_d1.metric("Kaufkurs (Einstieg)", f"{float(tr_row['entry_price']):.4f}")
                    c_d2.metric("Exit-Kurs", f"{float(tr_row['exit_price']):.4f}")
                    c_d3.metric("Realisierter Netto-PnL (€)", f"{float(tr_row['pnl_eur']):.2f} €")
                    c_d4.metric("Erzieltes R-Multiple", f"{float(tr_row['r_multiple']):.2f} R")
                    
                    st.markdown("#### 📏 Plan vs. Realität")
                    c_d5, c_d6, c_d7, c_d8, c_d9 = st.columns(5)
                    sig_p_val = float(tr_row.get('signal_price', tr_row['entry_price'])) if pd.notna(tr_row.get('signal_price')) else float(tr_row['entry_price'])
                    diff_slip = float(tr_row['entry_price']) - sig_p_val
                    if str(tr_row.get('direction', 'Long')) == "Short":
                        diff_slip = -diff_slip
                    c_d5.metric("Signal-Kurs (Soll)", f"{sig_p_val:.4f}", f"{diff_slip:+.4f}", delta_color="inverse" if diff_slip != 0 else "off")
                    c_d6.metric("Ursprünglicher Stop Loss", f"{float(tr_row['sl_price']):.4f}")
                    c_d7.metric("Ursprünglicher Take Profit", f"{float(tr_row['tp_price']):.4f}")
                    c_d8.metric("Geplantes Risiko (€)", f"{float(tr_row['planned_risk_eur']):.2f} €")
                    c_d9.metric("Angefallene Gebühren (€)", f"{float(tr_row.get('est_fees_eur', 0)):.2f} €")
                    
                    st.markdown("#### 📝 Text-Analyse")
                    st.write(f"**Setup-Typ:** {tr_row.get('setup_type', 'N/A')} (Master-Score: {tr_row.get('master_score', 'N/A')})")
                    
                    brutto_pnl = float(tr_row['pnl_eur']) + float(tr_row.get('est_fees_eur', 0))
                    kosten_pct = (float(tr_row.get('est_fees_eur', 0)) / brutto_pnl * 100) if brutto_pnl > 0 else 0.0
                    st.write(f"**Kosten-Check:** Die Gebührenbelastung betrug {kosten_pct:.1f}% des Bruttoertrags.")
                    
                    exit_rsn = str(tr_row.get('exit_reason', 'Unbekannt'))
                    if "Take Profit" in exit_rsn: disziplin = "🎯 Take Profit diszipliniert erreicht."
                    elif "Stop Loss" in exit_rsn: disziplin = "🛡️ Stop Loss griff planmäßig zum Kapitalschutz."
                    elif "Time-Stop" in exit_rsn: disziplin = "⏳ Time-Stop: Trade nach Ablauf der Zeitspanne ohne Momentum beendet."
                    else: disziplin = f"✋ {exit_rsn}"
                    st.write(f"**Disziplin-Urteil:** {disziplin}")
                    
                    st.write(f"**Notizen:** {tr_row.get('notes', 'Keine')}")
                    
        elif df_journal_filtered.empty:
            st.info("Noch keine Trades im Journal gespeichert.")

    # --- 5. STEUER- & JAHRESABSCHLUSS-EXPORT ---
        st.markdown("---")
        with st.expander("🏛️ Steuer- & Jahresabschluss-Export", expanded=False):
            df_closed_tax = df_j[df_j['status'] == 'CLOSED'].copy()
            if df_closed_tax.empty:
                st.info("Keine abgeschlossenen Trades für den Steuer-Export vorhanden.")
            else:
                def extract_year(d):
                    try: return datetime.datetime.strptime(str(d), "%d/%m/%Y %H:%M").year
                    except: 
                        try: return datetime.datetime.strptime(str(d), "%Y-%m-%d %H:%M").year
                        except: return None
                df_closed_tax['year'] = df_closed_tax['exit_date'].apply(extract_year)
                available_years = sorted([int(y) for y in df_closed_tax['year'].dropna().unique()], reverse=True)
                if not available_years: available_years = [datetime.datetime.now().year]
                
                c_tax1, c_tax2, c_tax3 = st.columns(3)
                with c_tax1:
                    tax_year = st.selectbox("Steuerjahr", available_years)
                with c_tax2:
                    default_jur = st.session_state.config.get("global_settings", {}).get("tax_jurisdiction", "DE")
                    idx_jur = 0 if default_jur == "DE" else 1
                    tax_jur = st.selectbox("Steuer-Domizil", ["Deutschland (§ 20 / Gewerbe)", "Schweiz (Vermögenssteuer / Payouts)"], index=idx_jur)
                with c_tax3:
                    tax_acc = st.selectbox("Konto auswerten", ["Alle Konten"] + list(acc_opts.keys()))
                
                if st.button("📊 Steuer-Report generieren", type="primary", use_container_width=True):
                    df_report, t_mets = calc_tax_report(df_j, tax_year, tax_jur, tax_acc, st.session_state.config.get("lab_accounts", {}))
                    if df_report.empty:
                        st.warning(f"Keine relevanten Buchungen für {tax_year} in der gewählten Konfiguration gefunden.")
                    else:
                        st.markdown(f"### 📈 Zusammenfassung (Steuerjahr {tax_year})")
                        mt1, mt2, mt3, mt4 = st.columns(4)
                        if t_mets.get("is_prop", False) and tax_acc != "Alle Konten": # Reines Prop-Firm Konto
                            mt1.metric("Summe Payouts", f"{t_mets['payouts']:,.2f} €")
                            mt2.metric("Challenge-Gebühren", f"-{t_mets['challenge_fees']:,.2f} €")
                            mt3.metric("Netto / Gewerbeertrag", f"{(t_mets['payouts'] - t_mets['challenge_fees']):,.2f} €")
                        else:
                            mt1.metric("Brutto-Gewinne", f"{t_mets['brutto_gewinn']:,.2f} €")
                            mt2.metric("Brutto-Verluste", f"-{t_mets['brutto_verlust']:,.2f} €")
                            mt3.metric("Transaktionskosten", f"-{t_mets['fees']:,.2f} €")
                            mt4.metric("Reingewinn (Netto)", f"{t_mets['netto']:,.2f} €")
                            
                        if tax_jur == "Deutschland (§ 20 / Gewerbe)" and t_mets["brutto_verlust"] > 20000:
                            st.info("ℹ️ **Rechtlicher Hinweis (JStG 2024):** Brutto-Verluste aus Termingeschäften übersteigen 20.000 €. Gemäß Jahressteuergesetz 2024 ist die vormalige Verlustverrechnungsbeschränkung (§ 20 Abs. 6 Satz 5 EStG a.F.) aufgehoben. Verluste sind uneingeschränkt steuerlich verrechenbar.")
                        if "Schweiz" in tax_jur:
                            st.info("ℹ️ **Steuer- & Deklarationshinweis Schweiz (Selbständiger Nebenerwerb / KS 36 ESTV):** Aktives Intraday-/Swing-Trading sowie Fremdkapital-Payouts erfüllen in der Praxis die Kriterien des gewerbsmässigen Wertschriftenhandels. Reingewinne unterliegen der ordentlichen Einkommenssteuer (Bund/Kanton/Gemeinde) und der AHV/IV/EO-Beitragspflicht. Sämtliche Verluste, Transaktionskosten und Challenge-Gebühren sind geschäftsmässig begründeter Aufwand und steuerlich voll abzugsfähig. Der Stichtagswert per 31.12. ist für die kantonale Vermögenssteuer massgebend.")    
                        st.markdown("**Steuerrelevante Buchungszeilen**")
                        st.dataframe(df_report[['id', 'account_name', 'exit_date', 'symbol', 'direction', 'setup_type', 'pnl_eur', 'est_fees_eur']], hide_index=True, use_container_width=True)
                        
                        csv_data = df_report.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Steuer-Export als CSV herunterladen", data=csv_data, file_name=f"steuer_export_{tax_year}.csv", mime="text/csv", use_container_width=True)

                        # --- 6. ADMIN MASTER-ANALYSE ---
        if st.session_state.role == "admin":
            st.markdown("---")
            with st.expander("🔬 Master-Analyse (Kollektive Trade-Logs)", expanded=False):
                st.info("🛡️ **Admin-Bereich:** Anonymisierte Aggregation aller Mandanten-Journale.")
                if st.button("📊 Kollektive Daten auswerten", type="primary", use_container_width=True):
                    all_closed = []
                    mandant_idx = 1
                    try:
                        for user_folder in os.listdir(USERS_DIR):
                            uf_path = os.path.join(USERS_DIR, user_folder)
                            if os.path.isdir(uf_path):
                                j_path = os.path.join(uf_path, "trade_journal.csv")
                                if os.path.exists(j_path):
                                    df_user = pd.read_csv(j_path)
                                    df_c = df_user[df_user['status'] == 'CLOSED'].copy()
                                    if not df_c.empty:
                                        df_c['Mandant'] = f"Mandant {mandant_idx}"
                                        all_closed.append(df_c)
                                        mandant_idx += 1
                        
                        if all_closed:
                            df_master = pd.concat(all_closed, ignore_index=True)
                            
                            # Globale Metriken
                            total_trades = len(df_master)
                            wins = len(df_master[df_master['pnl_eur'] > 0])
                            winrate = (wins / total_trades) * 100 if total_trades > 0 else 0
                            gross_profit = df_master[df_master['pnl_eur'] > 0]['pnl_eur'].sum()
                            gross_loss = abs(df_master[df_master['pnl_eur'] <= 0]['pnl_eur'].sum())
                            pf = gross_profit / gross_loss if gross_loss > 0 else float('nan')
                            net_pnl = df_master['pnl_eur'].sum()
                            avg_r = df_master['r_multiple'].mean()
                            
                            st.markdown("### 🌍 Globale Performance-Metriken")
                            c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                            c_m1.metric("Aggregierte Trades", total_trades)
                            c_m2.metric("Globale Winrate", f"{winrate:.1f} %")
                            c_m3.metric("Globaler Profit Factor", f"{pf:.2f}")
                            c_m4.metric("Ø R-Multiple", f"{avg_r:.2f} R")
                            st.metric("Netto PnL (Alle Mandanten)", f"{net_pnl:,.2f} €")
                            
                            # Setup Split
                            st.markdown("### 🧬 Analyse nach Setup-Typ")
                            df_master['Base_Setup'] = df_master['setup_type'].astype(str).apply(lambda x: 'Setup B (Trend)' if 'Trend' in x else 'Setup A (Reversal)')
                            
                            setup_stats = []
                            for setup_name, group in df_master.groupby('Base_Setup'):
                                s_total = len(group)
                                s_wins = len(group[group['pnl_eur'] > 0])
                                s_winrate = (s_wins / s_total) * 100 if s_total > 0 else 0
                                s_g_profit = group[group['pnl_eur'] > 0]['pnl_eur'].sum()
                                s_g_loss = abs(group[group['pnl_eur'] <= 0]['pnl_eur'].sum())
                                s_pf = s_g_profit / s_g_loss if s_g_loss > 0 else float('nan')
                                s_net = group['pnl_eur'].sum()
                                s_r = group['r_multiple'].mean()
                                
                                setup_stats.append({
                                    "Setup-Typ": setup_name, "Trades": s_total, "Winrate": f"{s_winrate:.1f}%", 
                                    "Profit Factor": f"{s_pf:.2f}", "Ø R-Multiple": f"{s_r:.2f} R", "Netto PnL": f"{s_net:,.2f} €"
                                })
                            
                            st.dataframe(pd.DataFrame(setup_stats), use_container_width=True, hide_index=True)
                            
                        else:
                            st.info("Keine geschlossenen Trades bei den Mandanten gefunden.")
                    except Exception as e:
                        st.error(f"Fehler bei der Aggregation: {e}")
            with st.expander("👥 Mandanten- & Benutzerverwaltung (Admin)", expanded=False):
                st.info("🛠️ **Verwaltung:** Benutzer sperren, Passwörter zurücksetzen oder Konten restlos löschen.")
                
                # 1. Mandanten-Übersichtstabelle
                user_list = []
                all_users = []
                for user_folder in os.listdir(USERS_DIR):
                    uf_path = os.path.join(USERS_DIR, user_folder)
                    if os.path.isdir(uf_path):
                        all_users.append(user_folder)
                        pf_path = os.path.join(uf_path, "user_profile.json")
                        u_role, u_chat, u_tos, u_active = "user", "", "Ausstehend", True
                        
                        if os.path.exists(pf_path):
                            with open(pf_path, "r", encoding="utf-8") as f:
                                p_data = json.load(f)
                                u_role = p_data.get("role", "user")
                                u_chat = p_data.get("telegram_chat_id", "")
                                u_tos = str(p_data.get("tos_accepted_at", "Ausstehend"))
                                u_active = p_data.get("is_active", True)
                        
                        u_chat_clean = str(u_chat).strip() if u_chat is not None else ""
                        if len(u_chat_clean) >= 4:
                            u_chat_display = f"Verknüpft (***{u_chat_clean[-4:]})"
                        else:
                            u_chat_display = "Nicht hinterlegt"

                        user_list.append({
                            "Benutzer": user_folder,
                            "Rolle": u_role,
                            "Status": "🟢 Aktiv" if u_active else "🔴 Gesperrt",
                            "Telegram Chat-ID": u_chat_display,
                            "TOS Akzeptiert": u_tos if u_tos != "None" else "Ausstehend"
                        })
                
                st.dataframe(pd.DataFrame(user_list), use_container_width=True, hide_index=True)
                st.markdown("---")
                
                # 2. 1-Klick Aktionen
                c_adm1, c_adm2 = st.columns([1, 2])
                with c_adm1:
                    target_user = st.selectbox("Nutzer auswählen:", sorted(all_users))
                
                with c_adm2:
                    if target_user:
                        is_admin_user = (target_user == "admin")
                        t_lock, t_pw, t_del = st.tabs(["🔒 Status", "🔑 Passwort", "🗑️ Löschen"])
                        
                        # Sperren / Entsperren
                        with t_lock:
                            if is_admin_user:
                                st.warning("Der Admin-Account kann nicht gesperrt werden.")
                            else:
                                target_pf = os.path.join(USERS_DIR, target_user, "user_profile.json")
                                t_active = True
                                if os.path.exists(target_pf):
                                    with open(target_pf, "r", encoding="utf-8") as f: 
                                        t_active = json.load(f).get("is_active", True)
                                
                                new_status = not t_active
                                btn_txt = "🔴 Zugang temporär sperren" if t_active else "🟢 Zugang wieder entsperren"
                                if st.button(btn_txt, use_container_width=True):
                                    if os.path.exists(target_pf):
                                        with open(target_pf, "r", encoding="utf-8") as f: p_data = json.load(f)
                                        p_data["is_active"] = new_status
                                        with open(target_pf, "w", encoding="utf-8") as f: json.dump(p_data, f, indent=4)
                                        st.success(f"Status von {target_user} wurde aktualisiert!")
                                        st.rerun()
                                        
                        # Passwort Reset
                        with t_pw:
                            new_adm_pw = st.text_input("Neues Passwort setzen:", type="password", key=f"pw_{target_user}")
                            if st.button("💾 Passwort überschreiben", use_container_width=True) and new_adm_pw:
                                if len(new_adm_pw) < 6:
                                    st.error("Mindestens 6 Zeichen erforderlich.")
                                else:
                                    with open(AUTH_FILE, "r", encoding="utf-8") as f: creds = json.load(f)
                                    creds[target_user] = hash_password(new_adm_pw)
                                    with open(AUTH_FILE, "w", encoding="utf-8") as f: json.dump(creds, f, indent=4)
                                    st.success(f"Passwort für {target_user} erfolgreich aktualisiert!")
                                    
                        # Restlos Löschen
                        with t_del:
                            if is_admin_user:
                                st.error("Der primäre Admin-Account darf nicht gelöscht werden.")
                            else:
                                st.warning(f"⚠️ Warnung: Dies löscht den Nutzer **{target_user}** und ALLE seine Daten (Trades, Einstellungen) unwiderruflich!")
                                del_confirm = st.checkbox(f"Ja, ich möchte {target_user} endgültig löschen.")
                                if st.button("🗑️ Konto restlos löschen", type="primary", use_container_width=True, disabled=not del_confirm):
                                    with open(AUTH_FILE, "r", encoding="utf-8") as f: creds = json.load(f)
                                    if target_user in creds: 
                                        del creds[target_user]
                                        with open(AUTH_FILE, "w", encoding="utf-8") as f: json.dump(creds, f, indent=4)
                                    
                                    tgt_dir = os.path.join(USERS_DIR, target_user)
                                    if os.path.exists(tgt_dir): 
                                        shutil.rmtree(tgt_dir)
                                        
                                    st.success(f"Benutzer {target_user} wurde restlos aus dem System getilgt.")
                                    st.rerun()

    # ==========================================
    # SUB-TAB 2: STRATEGIE-LABOR & OPTIMIZER
    # ==========================================
    with tab_lab_strat:
        c_strat_acc, _ = st.columns([1, 2])
        with c_strat_acc:
            sel_acc_name_strat = st.selectbox("Aktives Konto für das Strategie-Labor:", list(acc_opts.keys()), index=list(acc_opts.values()).index(st.session_state.active_lab_account), key="acc_sel_strat")
            if acc_opts[sel_acc_name_strat] != st.session_state.active_lab_account:
                st.session_state.active_lab_account = acc_opts[sel_acc_name_strat]
                st.rerun()
        st.markdown("---")
        
        st.subheader("📋 Ticker-Verwaltung")
        
        c_search, c_btn = st.columns([3, 1])
        with c_search:
            sq_lab = st.text_input("Yahoo-Suche oder Freitext (Ticker hinzufügen):", key="search_lab_acc")
        suggestions_lab = []
        if sq_lab and len(sq_lab.strip()) >= 2:
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={sq_lab.strip()}&quotesCount=5", headers=headers, timeout=3)
                if resp.status_code == 200:
                    for q in resp.json().get("quotes", []):
                        if "symbol" in q: suggestions_lab.append(f"{q['symbol']} - {q.get('longname', q.get('shortname', ''))}")
            except: pass
            
        chosen_lab = None
        if suggestions_lab:
            chosen_lab_raw = st.selectbox("Treffer:", suggestions_lab, key="sel_lab_acc")
            chosen_lab = chosen_lab_raw.split(" - ")[0]
            
        with c_btn:
            st.write(""); st.write("")
            if st.button("➕ Hinzufügen", use_container_width=True) and chosen_lab:
                if chosen_lab not in active_acc.get("tickers", []):
                    active_acc.setdefault("tickers", []).append(chosen_lab)
                    save_config(st.session_state.config); st.rerun()

        st.markdown("**⚡ Schnell-Import & Verwaltung**")
        i1, i2, i3, i4, i5 = st.columns(5)
        curr_tickers = active_acc.get("tickers", [])
        def add_with_sector_limit(current_tickers, new_tickers):
            sec_counts = {}
            for t in current_tickers:
                sec = "Standard"
                for tag_name, tag_data in st.session_state.config.get("scan_universes", {}).items():
                    if any(x["symbol"] == t for x in tag_data.get("tickers", [])): sec = tag_name; break
                sec_counts[sec] = sec_counts.get(sec, 0) + 1
            added, skipped = [], []
            for t in new_tickers:
                if t in current_tickers or t in added: continue
                sec = "Standard"
                for tag_name, tag_data in st.session_state.config.get("scan_universes", {}).items():
                    if any(x["symbol"] == t for x in tag_data.get("tickers", [])): sec = tag_name; break
                if sec_counts.get(sec, 0) < 2:
                    added.append(t)
                    sec_counts[sec] = sec_counts.get(sec, 0) + 1
                else: skipped.append(t)
            return added, skipped

        with i1:
            if st.button("📥 Aus Tab 1 Watchlist importieren", use_container_width=True):
                new_t = [t["symbol"] for t in st.session_state.config.get("tickers", [])]
                added, skipped = add_with_sector_limit(curr_tickers, new_t)
                active_acc["tickers"] = curr_tickers + added
                if skipped: st.toast(f"⚠️ Übersprungen wegen Sektor-Limit (max. 2): {', '.join(skipped)}", icon="⚠️")
                if added: st.toast(f"✅ {len(added)} Ticker übernommen!", icon="📥")
                save_config(st.session_state.config); st.rerun()
        with i2:
            if st.button("📥 Aus Tab 2 Watchlist importieren", use_container_width=True):
                new_t = [t["symbol"] for t in st.session_state.config.get("screener_tickers", [])]
                added, skipped = add_with_sector_limit(curr_tickers, new_t)
                active_acc["tickers"] = curr_tickers + added
                if skipped: st.toast(f"⚠️ Übersprungen wegen Sektor-Limit (max. 2): {', '.join(skipped)}", icon="⚠️")
                if added: st.toast(f"✅ {len(added)} Ticker übernommen!", icon="📥")
                save_config(st.session_state.config); st.rerun()
        with i3:
            if st.button("📥 Aus aktuellem Tab 2 Scanner", use_container_width=True):
                if "scanner_results" in st.session_state and not st.session_state.scanner_results.empty:
                    new_t = st.session_state.scanner_results["Ticker"].tolist()
                    added, skipped = add_with_sector_limit(curr_tickers, new_t)
                    active_acc["tickers"] = curr_tickers + added
                    if skipped: st.toast(f"⚠️ Übersprungen wegen Sektor-Limit (max. 2): {', '.join(skipped)}", icon="⚠️")
                    if added: st.toast(f"✅ {len(added)} Ticker übernommen!", icon="📥")
                    save_config(st.session_state.config); st.rerun()
                else: st.toast("Keine Scanner-Ergebnisse vorhanden.")
        with i4:
            if st.button("📥 Aus Tab 3 Prop-Kader importieren", use_container_width=True):
                new_t = [t["symbol"] for t in st.session_state.config.get("futures_tickers", []) if t.get("active", True)]
                added, skipped = add_with_sector_limit(curr_tickers, new_t)
                active_acc["tickers"] = curr_tickers + added
                if skipped: st.toast(f"⚠️ Übersprungen wegen Sektor-Limit (max. 2): {', '.join(skipped)}", icon="⚠️")
                if added: st.toast(f"✅ {len(added)} Ticker übernommen!", icon="📥")
                save_config(st.session_state.config); st.rerun()
        with i5:
            if st.button("🗑️ Alle Ticker leeren", use_container_width=True):
                active_acc["tickers"] = []
                save_config(st.session_state.config); st.rerun()
                
        if curr_tickers:
            sec_map_all = {}
            for tag_name, tag_data in st.session_state.config.get("scan_universes", {}).items():
                for x in tag_data.get("tickers", []):
                    if x["symbol"] not in sec_map_all: sec_map_all[x["symbol"]] = tag_name
            for t_fut in st.session_state.config.get("futures_tickers", []):
                if t_fut["symbol"] not in sec_map_all: sec_map_all[t_fut["symbol"]] = t_fut.get("asset_class", "Futures")
            
            df_t_list = []
            for t in curr_tickers:
                t_name = t
                for tag_name, tag_data in st.session_state.config.get("scan_universes", {}).items():
                    for x in tag_data.get("tickers", []):
                        if x["symbol"] == t:
                            t_name = x.get("name", t)
                            break
                if t_name == t:
                    for t_fut in st.session_state.config.get("futures_tickers", []):
                        if t_fut["symbol"] == t:
                            t_name = t_fut.get("name", t)
                            break
                df_t_list.append({"Löschen": False, "Ticker": t, "Name": t_name, "Sektor": sec_map_all.get(t, "Standard")})
                
            df_tk = pd.DataFrame(df_t_list)
            edited_tk = st.data_editor(df_tk, hide_index=True, use_container_width=True, disabled=["Ticker", "Name", "Sektor"], key=f"tk_ed_{active_acc['id']}")
            
            if st.button("🗑️ Ausgewählte Ticker löschen", type="primary"):
                to_delete = edited_tk[edited_tk["Löschen"] == True]["Ticker"].tolist()
                if to_delete:
                    active_acc["tickers"] = [t for t in curr_tickers if t not in to_delete]
                    save_config(st.session_state.config)
                    st.rerun()
        else:
            st.info("Keine Ticker für dieses Konto hinterlegt.")

        st.markdown("---")
        with st.expander("🎯 Basket-Pool Optimizer (Portfolio-Optimierung)", expanded=False):
            c_opt1, c_opt2 = st.columns([2, 1])
            with c_opt1:
                opt_source = st.selectbox("Datenbasis:", ["Aktuelle Konto-Ticker", "Ausgewählte Tags / Universen", "🔄 Kader-Challenge (Stammkader + Transfer-Kandidaten)"], key=f"opt_src_{active_acc['id']}")
                opt_tags = []
                scan_all_opt = False
                if opt_source == "Ausgewählte Tags / Universen":
                    scan_all_opt = st.checkbox("🌐 Alle Universen / Tags durchsuchen", value=False, key=f"opt_all_{active_acc['id']}")
                    if not scan_all_opt:
                        opt_tags = st.multiselect("Tags / Universen wählen:", list(st.session_state.config.get("scan_universes", {}).keys()), key=f"opt_tags_{active_acc['id']}")
            with c_opt2:
                current_kader_size = len(active_acc.get("tickers", []))
                if opt_source == "🔄 Kader-Challenge (Stammkader + Transfer-Kandidaten)":
                    if current_kader_size >= 10:
                        target_size = current_kader_size
                        st.info(f"🔒 Zielgröße fixiert auf {target_size} (One-In, One-Out)")
                    else:
                        target_size = st.slider("Aufbau-Zielgröße", min_value=max(2, current_kader_size + 1), max_value=20, value=max(10, current_kader_size + 1), key=f"opt_sz_{active_acc['id']}")
                        st.info(f"🏗️ Kader im Aufbau (aktuell {current_kader_size}). One-In, One-Out greift ab 10 Tickern.")
                else:
                    target_size = st.slider("Ziel-Poolgröße", min_value=2, max_value=20, value=max(5, current_kader_size), key=f"opt_sz_{active_acc['id']}")
            
            acc_prof_opt = active_acc.get("exit_profile", "prop_guard")
            acc_broker_opt = active_acc.get("broker_profile", "Fusion (0.10% / 0.05%)")
            st.info(f"ℹ️ **Aktive Kontoparameter:** Exit-Profil: `{acc_prof_opt}` | Broker: `{acc_broker_opt}`\n\n*(Matrix-Regel: Bei Krypto-Assets überschreibt die Krypto-DNA automatisch das Konto-Exit-Profil für weitere Stops!)*")
            transfer_cands = st.session_state.get("transfer_candidates", [])
            if transfer_cands:
                st.info(f"📌 **Vorgemerkte Transfer-Kandidaten aus Tab 2:** {', '.join(transfer_cands)}")
            else:
                st.caption("ℹ️ Keine Transfer-Kandidaten aus Tab 2 vorgemerkt.")            
            is_crypto_involved = False
            if opt_source == "Ausgewählte Tags / Universen":
                target_tags_check = list(st.session_state.config.get("scan_universes", {}).keys()) if scan_all_opt else opt_tags
                for tag in target_tags_check:
                    if "KRYPTO" in tag.upper() or "CRYPTO" in tag.upper():
                        is_crypto_involved = True
            else:
                check_list = active_acc.get("tickers", []) + st.session_state.get("transfer_candidates", [])
                if any(any(ext in str(t).upper() for ext in ["-USD", "-EUR", "-GBP", "-USDT", "-CHF", "BTC", "ETH", "SOL"]) for t in check_list):
                    is_crypto_involved = True
                    
            if is_crypto_involved and acc_prof_opt in ["commodity_scale", "apex_commodity_scale", "apex_lock", "prop_guard"]:
                st.warning("⚠️ **Hinweis:** Krypto-Assets sollten im Profil Home-Run Trend (private_alpha) optimiert werden, da enge Prop-Stops bei Krypto oft zu Whipsaw-Verlusten führen.")

            if st.button("🚀 Optimalen Basket berechnen", type="primary", use_container_width=True, key=f"opt_btn_{active_acc['id']}"):
                cand_tickers = []
                if opt_source == "Aktuelle Konto-Ticker":
                    cand_tickers = active_acc.get("tickers", [])
                elif opt_source == "🔄 Kader-Challenge (Stammkader + Transfer-Kandidaten)":
                    cand_tickers = list(set(active_acc.get("tickers", []) + st.session_state.get("transfer_candidates", [])))
                    st.session_state[f"opt_baseline_{active_acc['id']}"] = active_acc.get("tickers", [])
                else:
                    target_tags = list(st.session_state.config.get("scan_universes", {}).keys()) if scan_all_opt else opt_tags
                    for tag in target_tags:
                        for t in st.session_state.config.get("scan_universes", {}).get(tag, {}).get("tickers", []):
                            if t["symbol"] not in cand_tickers: cand_tickers.append(t["symbol"])
                
                if len(cand_tickers) < 2:
                    st.warning("⚠️ Die gewählte Datenbasis enthält zu wenige Ticker (Minimum: 2).")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    def opt_progress(current, total, msg=""):
                        pct = min(current / float(total), 1.0) if total > 0 else 0
                        progress_bar.progress(pct)
                        status_text.text(msg)
                    
                    with st.spinner("Berechnung läuft..."):
                        if "Apex" in acc_broker_opt or "CME" in acc_broker_opt: f_rate, s_rate = 0.00005, 0.0001
                        elif "FTMO" in acc_broker_opt or "Forex" in acc_broker_opt: f_rate, s_rate = 0.00003, 0.00002
                        elif "Bybit" in acc_broker_opt: f_rate, s_rate = 0.0006, 0.0002
                        elif "Fusion" in acc_broker_opt: f_rate, s_rate = 0.001, 0.0005
                        elif "Retail" in acc_broker_opt: f_rate, s_rate = 0.0149, 0.0015
                        elif "Aktien Broker" in acc_broker_opt or "Flat" in acc_broker_opt: f_rate, s_rate = 0.0005, 0.0005
                        else: f_rate, s_rate = 0.001, 0.0005
                        
                        sec_map_opt = {}
                        for tag_name, tag_data in st.session_state.config.get("scan_universes", {}).items():
                            for x in tag_data.get("tickers", []):
                                if x["symbol"] not in sec_map_opt: sec_map_opt[x["symbol"]] = tag_name
                                
                        try:
                            res = bte.optimize_basket_pool(
                                candidate_tickers=cand_tickers,
                                sector_map=sec_map_opt,
                                target_size=target_size,
                                years=active_acc.get("years", 5),
                                fee_rate=f_rate,
                                slippage=s_rate,
                                min_score=active_acc.get("min_score", 70),
                                account_size=active_acc.get("account_size", 10000.0),
                                risk_pct=active_acc.get("risk_pct", 1.0),
                                compounding=active_acc.get("compounding", "inactive"),
                                trailing_stop_mode=active_acc.get("trailing_stop", "active"),
                                mode=active_acc.get("mode", "walk_forward"),
                                exit_profile=acc_prof_opt,
                                progress_callback=opt_progress
                            )
                            st.session_state[f"opt_res_{active_acc['id']}"] = res
                            progress_bar.empty()
                            status_text.empty()
                        except Exception as e:
                            st.error(f"Fehler bei der Optimierung: {e}")

            opt_res_key = f"opt_res_{active_acc['id']}"
            if opt_res_key in st.session_state:
                res = st.session_state[opt_res_key]
                if "error" in res:
                    st.error(res["error"])
                else:
                    if res.get("warning_msg"):
                        st.warning(res["warning_msg"])
                    st.success("✅ Basket erfolgreich optimiert!")
                    skipped_tickers = res.get("skipped_tickers", {})
                    if skipped_tickers:
                        with st.expander(f"ℹ️ Nicht berücksichtigte Ticker ({len(skipped_tickers)})", expanded=False):
                            for s_sym, s_reason in skipped_tickers.items():
                                st.write(f"- **{s_sym}:** {s_reason}")
                    mets = res["metrics"]
                    st.markdown("### 📊 Erwartete Performance des Baskets")
                    mo1, mo2, mo3, mo4 = st.columns(4)
                    mo1.metric("Winrate", f"{mets.get('Winrate (%)', 0):.2f} %")
                    mo2.metric("Profit Factor", f"{mets.get('Profit Factor', 0):.2f}")
                    mo3.metric("Max Drawdown", f"{mets.get('Max Drawdown (€)', 0):.2f} €")
                    mo4.metric("Net PnL", f"{mets.get('Total Net PnL', 0):.2f} €")
                    
                    st.markdown("### 🧺 Zusammensetzung")
                    sec_map_disp = {}
                    for tag_name, tag_data in st.session_state.config.get("scan_universes", {}).items():
                        for x in tag_data.get("tickers", []):
                            if x["symbol"] not in sec_map_disp: sec_map_disp[x["symbol"]] = tag_name
                            
                    tk_disp = [{"Ticker": t, "Sektor": sec_map_disp.get(t, "Standard")} for t in res["best_basket"]]
                    st.dataframe(pd.DataFrame(tk_disp), use_container_width=True, hide_index=True)
                    if opt_source == "🔄 Kader-Challenge (Stammkader + Transfer-Kandidaten)":
                        baseline_kader = st.session_state.get(f"opt_baseline_{active_acc['id']}", [])
                        best_basket = res["best_basket"]
                        out_tickers = [t for t in baseline_kader if t not in best_basket]
                        in_tickers = [t for t in best_basket if t not in baseline_kader]
                        
                        st.markdown("### 🔄 Transfer-Empfehlung (One-In, One-Out)")
                        if not out_tickers and not in_tickers:
                            st.success("✅ **Kein Tausch nötig:** Dein bestehender Kader performt stabiler als die Neuzugänge!")
                        else:
                            st.info(f"💡 **Tausch-Empfehlung:** Ersetze **{', '.join(out_tickers)}** durch **{', '.join(in_tickers)}**.")
                    
                    if st.button("📥 Diesen Basket ins Konto übernehmen", type="primary", use_container_width=True, key=f"take_opt_{active_acc['id']}"):
                        active_acc["tickers"] = res["best_basket"]
                        save_config(st.session_state.config)
                        del st.session_state[opt_res_key]
                        st.toast("✅ Basket übernommen!")
                        st.rerun()

        with st.expander("🔬 Portfolio-Backtest & Validierung", expanded=False):
            if st.button(f"▶️ Backtest für '{active_acc['name']}' ausführen", type="primary", use_container_width=True):
                if not active_acc.get("tickers"):
                    st.warning("⚠️ Bitte wähle zuerst Ticker aus!")
                else:
                    with st.spinner(f"Führe Portfolio-Backtest für {len(active_acc['tickers'])} Ticker aus..."):
                        try:
                            if "Apex" in active_acc["broker_profile"] or "Tradovate" in active_acc["broker_profile"] or "CME" in active_acc["broker_profile"]: f_rate, s_rate = 0.00005, 0.0001
                            elif "FTMO" in active_acc["broker_profile"] or "MetaTrader" in active_acc["broker_profile"] or "Forex" in active_acc["broker_profile"]: f_rate, s_rate = 0.00003, 0.00002
                            elif "Bybit" in active_acc["broker_profile"]: f_rate, s_rate = 0.0006, 0.0002
                            elif "Fusion" in active_acc["broker_profile"]: f_rate, s_rate = 0.001, 0.0005
                            elif "Retail" in active_acc["broker_profile"]: f_rate, s_rate = 0.0149, 0.0015
                            elif "Interactive" in active_acc["broker_profile"] or "Aktien Broker" in active_acc["broker_profile"] or "Flat" in active_acc["broker_profile"]: f_rate, s_rate = 0.0005, 0.0005
                            else: f_rate, s_rate = 0.001, 0.0005
                            
                            sec_map = {}
                            for t in active_acc["tickers"]:
                                sec = "Standard"
                                for tag, t_data in st.session_state.config.get("scan_universes", {}).items():
                                    if any(x["symbol"] == t for x in t_data.get("tickers", [])):
                                        sec = tag; break
                                sec_map[t] = sec
                                
                            trades = bte.run_portfolio_backtest(
                                active_acc["tickers"], sec_map, active_acc["years"], f_rate, s_rate, 
                                active_acc["min_score"], active_acc["account_size"], active_acc["risk_pct"], 
                                active_acc["compounding"], active_acc.get("trailing_stop", "active"), active_acc.get("mode", "walk_forward")
                            )
                            sec_map = {}
                            for t in active_acc["tickers"]:
                                sec = "Standard"
                                for tag, t_data in st.session_state.config.get("scan_universes", {}).items():
                                    if any(x["symbol"] == t for x in t_data.get("tickers", [])):
                                        sec = tag; break
                                if sec == "Standard":
                                    for t_fut in st.session_state.config.get("futures_tickers", []):
                                        if t_fut["symbol"] == t:
                                            sec = t_fut.get("asset_class", "Futures"); break
                                sec_map[t] = sec
                                
                            acc_direction = active_acc.get("direction", "both" if active_acc.get("exit_profile", "prop_guard") in ["prop_guard", "defensive_swing", "apex_lock"] else "long")
                            acc_exit_prof = active_acc.get("exit_profile", "prop_guard")
                                
                            trades = bte.run_portfolio_backtest(
                                active_acc["tickers"], sec_map, active_acc["years"], f_rate, s_rate, 
                                active_acc["min_score"], active_acc["account_size"], active_acc["risk_pct"], 
                                active_acc.get("compounding", "inactive"), active_acc.get("trailing_stop", "active"), active_acc.get("mode", "walk_forward"),
                                exit_profile=acc_exit_prof, allowed_direction=acc_direction
                            )
                            metrics = bte.calculate_metrics(trades)
                            active_acc["last_backtest"] = {
                                "timestamp": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                                "metrics": metrics,
                                "trades": trades
                            }
                            save_config(st.session_state.config)
                            st.success("✅ Backtest erfolgreich beendet und archiviert!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fehler beim Backtest: {e}")

            if active_acc.get("last_backtest"):
                res = active_acc["last_backtest"]
                st.info(f"📅 Letzter Backtest: {res['timestamp']}")
                
                trades = res.get("trades", [])
                df_trades = pd.DataFrame(trades)
                
                if not df_trades.empty:
                    metrics_all = res["metrics"]
                    
                    is_trades = df_trades[~df_trades["is_oos"]].to_dict('records') if "is_oos" in df_trades else trades
                    oos_trades = df_trades[df_trades["is_oos"]].to_dict('records') if "is_oos" in df_trades else []
                    
                    metrics_is = bte.calculate_metrics(is_trades) if is_trades else {}
                    metrics_oos = bte.calculate_metrics(oos_trades) if oos_trades else {}
                    
                    st.markdown("### 1. Gesamtergebnisse")
                    m1_b, m2_b, m3_b, m4_b = st.columns(4)
                    m1_b.metric("Total Trades", f"{metrics_all.get('Total Trades', 0)}")
                    m2_b.metric("Winrate", f"{metrics_all.get('Winrate (%)', 0):.2f} %")
                    m3_b.metric("Profit Factor", f"{metrics_all.get('Profit Factor', 0):.2f}")
                    m4_b.metric("Net PnL", f"{metrics_all.get('Total Net PnL', 0):.2f} €")
                    
                    c_ex1, c_ex2 = st.columns(2)
                    c_ex1.metric("Max Drawdown", f"{metrics_all.get('Max Drawdown (€)', 0):.2f} €")
                    c_ex2.metric("Ø R-Multiple", f"{metrics_all.get('Ø R-Multiple', 0):.2f} R")

                    st.markdown("### 2. In-Sample vs. Out-of-Sample (Vergleich)")
                    c_is, c_oos = st.columns(2)
                    with c_is:
                        st.markdown("**🔬 In-Sample (Training)**")
                        st.write(f"- Winrate: {metrics_is.get('Winrate (%)', 0):.2f} %")
                        st.write(f"- Profit Factor: {metrics_is.get('Profit Factor', 0):.2f}")
                        st.write(f"- Net PnL: {metrics_is.get('Total Net PnL', 0):.2f} €")
                    with c_oos:
                        st.markdown("**🚀 Out-of-Sample (Validierung)**")
                        st.write(f"- Winrate: {metrics_oos.get('Winrate (%)', 0):.2f} %")
                        st.write(f"- Profit Factor: {metrics_oos.get('Profit Factor', 0):.2f}")
                        st.write(f"- Net PnL: {metrics_oos.get('Total Net PnL', 0):.2f} €")

                    st.markdown("### 3. Equity-Kurve & Drawdown")
                    df_trades['cum_pnl'] = df_trades['net_pnl'].cumsum()
                    df_trades['equity'] = active_acc["account_size"] + df_trades['cum_pnl']
                    df_trades['peak'] = df_trades['equity'].cummax()
                    df_trades['drawdown_pct'] = ((df_trades['equity'] - df_trades['peak']) / df_trades['peak']) * 100
                    
                    oos_start_idx = df_trades[df_trades['is_oos']].index.min() if df_trades['is_oos'].any() else None
                    
                    fig_eq = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3])
                    fig_eq.add_trace(go.Scatter(x=df_trades.index, y=df_trades['equity'], name="Equity (€)", line=dict(color='#2ca02c', width=2)), row=1, col=1)
                    
                    if oos_start_idx is not None:
                        fig_eq.add_vline(x=oos_start_idx, line_dash="dash", line_color="orange", annotation_text="OOS Validierung", row=1, col=1)
                    
                    fig_eq.add_trace(go.Scatter(x=df_trades.index, y=df_trades['drawdown_pct'], name="Drawdown (%)", fill='tozeroy', fillcolor='rgba(214, 39, 40, 0.3)', line=dict(color='#d62728', width=1)), row=2, col=1)
                    
                    fig_eq.update_layout(height=500, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified", showlegend=False)
                    st.plotly_chart(fig_eq, use_container_width=True)
                    if "window" in df_trades and df_trades["window"].nunique() > 1:

                        st.markdown("### 4. Walk-Forward-Fenster (Übersicht)")
                        wf_data = []
                        for window in df_trades["window"].unique():
                            w_oos = df_trades[(df_trades["window"] == window) & (df_trades["is_oos"])]
                            if not w_oos.empty:
                                w_met = bte.calculate_metrics(w_oos.to_dict('records'))
                                wf_data.append({
                                    "Fenster": window, 
                                    "Trades": w_met.get('Total Trades', 0),
                                    "Winrate": f"{w_met.get('Winrate (%)', 0):.1f} %",
                                    "Profit Factor": f"{w_met.get('Profit Factor', 0):.2f}",
                                    "Net PnL": f"{w_met.get('Total Net PnL', 0):.2f} €"
                                })
                        if wf_data:
                            st.dataframe(pd.DataFrame(wf_data), use_container_width=True, hide_index=True)
                            
                    with st.expander("📝 Alle Trades anzeigen"):
                        st.dataframe(df_trades, use_container_width=True)
                else:
                    st.write("Keine Trades ausgelöst.")
            else:
                st.info("Noch kein Backtest für dieses Konto gespeichert.")

#region DANGER ZONE
st.markdown("---")
_dz_feedback = st.session_state.pop("dz_feedback_msg", None)
if _dz_feedback:
    st.toast(_dz_feedback, icon="✅")

with st.expander("⚠️ Danger Zone (Werkseinstellungen)", expanded=bool(_dz_feedback)):
    if _dz_feedback:
        st.success(_dz_feedback)
    st.warning("Hier kannst du das gesamte Dashboard auf den Auslieferungszustand zurücksetzen. Alle Ticker, individuellen Einstellungen und Listen werden restlos gelöscht.")
    clean_slate_check = st.checkbox("⚠️ Ich bestätige: Mein persönliches Trade-Journal unwiderruflich auf Null zurücksetzen", key="clean_slate_confirm_check")
    with st.popover("🧹 V1.0.0 Clean Slate: Mein Trade-Journal leeren", disabled=not clean_slate_check, use_container_width=True):
        st.error("🚨 ACHTUNG: Dies tilgt sämtliche offenen und geschlossenen Trades in deinem persönlichen Konto restlos (deine Ticker-Listen und Einstellungen bleiben erhalten). Andere Benutzer bleiben unberührt!")
        if st.button("💥 Ja, mein Trade-Journal jetzt endgültig leeren", type="primary", use_container_width=True, key="btn_clean_slate_final"):
            cols = ['id', 'account_name', 'entry_date', 'exit_date', 'symbol', 'name', 'direction', 'signal_price', 'entry_price', 'currency', 'fx_rate', 'position_size', 'contract_type', 'point_value', 'base_currency', 'invest_eur', 'sl_price', 'tp_price', 'planned_risk_eur', 'est_fees_eur', 'master_score', 'setup_type', 'mc_robustness', 'atr_days', 'exit_mode', 'status', 'exit_price', 'pnl_eur', 'pnl_pct', 'r_multiple', 'exit_reason', 'notes', 'strategy_version', 'execution_type']
            user_j_path = get_user_file("trade_journal.csv")
            os.makedirs(os.path.dirname(user_j_path), exist_ok=True)
            prev_count = 0
            if os.path.exists(user_j_path):
                try:
                    prev_count = len(pd.read_csv(user_j_path))
                except Exception:
                    prev_count = 0
            pd.DataFrame(columns=cols).to_csv(user_j_path, index=False)
            with open(get_user_file("alert_state.json"), "w", encoding="utf-8") as f:
                json.dump({}, f)
            st.session_state.pop("clean_slate_confirm_check", None)
            if prev_count > 0:
                st.session_state["dz_feedback_msg"] = f"🧹 Clean Slate ausgeführt: {prev_count} Einträge aus deinem persönlichen Trade-Journal wurden restlos gelöscht!"
            else:
                st.session_state["dz_feedback_msg"] = "ℹ️ Clean Slate ausgeführt: Dein Trade-Journal war bereits leer (0 Einträge) und wurde frisch initialisiert."
            st.rerun()

    danger_check = st.checkbox("⚠️ Ich möchte mein persönliches Dashboard unwiderruflich auf Werkseinstellungen zurücksetzen", key="danger_user_reset_check")
    with st.popover("🚨 Mein Konto auf Werkseinstellungen zurücksetzen", disabled=not danger_check, use_container_width=True):
        st.error("🚨 ACHTUNG: Dies setzt deine Ticker-Listen, Kontoeinstellungen und dein persönliches Trade-Journal auf den Auslieferungszustand zurück. Andere Benutzer bleiben unberührt!")
        if st.button("💥 Ja, mein Konto jetzt unwiderruflich zurücksetzen", type="primary", use_container_width=True, key="btn_user_factory_reset_final"):
            user_cfg_path = get_user_file("ticker_config.json")
            os.makedirs(os.path.dirname(user_cfg_path), exist_ok=True)
            default_config = {
                "global_settings": {"rsi_defensiv": 35.0, "rsi_aggressiv": 30.0, "rsi_sell_defensiv": 70.0, "rsi_sell_aggressiv": 80.0, "ema_trend_default": 200.0, "custom_sectors": [], "risk_mode": "Festes Euro-Risiko (€)", "account_size": 10000.0, "risk_eur": 100.0, "risk_pct": 1.0, "fixed_investment": 1000.0, "currency_view": "Duale Ansicht (Original & EUR)", "dynamic_risk_scaling": False, "fee_mode": "Keine Gebühren / Raw", "tax_jurisdiction": "DE"},
                "pro_mode_settings": {"ema200_killer": "Aktiv", "rsi_aktiv": "Aktiv", "bollinger_aktiv": "Aktiv", "macd_aktiv": "Aktiv", "volumen_aktiv": "Aktiv", "keltner_aktiv": "Aktiv", "plateau_aktiv": "Inaktiv"},
                "esg_blacklist": {"aktiv": False, "tickers": ["NESN.SW", "GLEN.L", "RHM.DE"]}, 
                "tab2_settings": {"tf": "1d", "rsi_buy": 30.0, "rsi_sell": 70.0},
                "tab3_settings": {"tf_futures": "1h", "tf_forex": "4h", "rsi_short_entry": 70.0, "rsi_long_entry": 30.0},
                "tickers": [], 
                "screener_tickers": [], 
                "futures_tickers": [{"symbol": "NQ=F", "name": "Nasdaq 100"}],
                "lab_accounts": {
                    "default": {
                        "id": "default", "name": "Privatkonto (10k)", "account_size": 10000.0, "risk_pct": 1.0, 
                        "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Bitpanda Fusion (0.10% / 0.05%)", 
                        "min_score": 70, "years": 5, "tickers": [], "last_backtest": None, "tax_category": "private", "exit_profile": "private_alpha"
                    },
                    "apex": {
                        "id": "apex", "name": "Apex 50k Demo", "account_size": 50000.0, "risk_pct": 1.0, 
                        "compounding": "inactive", "trailing_stop": "active", "broker_profile": "Apex / CME Futures (Insti-Rate)", 
                        "min_score": 60, "years": 2, "tickers": ["NQ=F"], "last_backtest": None, "tax_category": "prop_firm", "exit_profile": "apex_lock"
                    },
                    "ftmo": {
                        "id": "ftmo", "name": "FTMO 50k Demo", "account_size": 50000.0, "risk_pct": 1.0, 
                        "compounding": "inactive", "trailing_stop": "active", "broker_profile": "FTMO / Forex (Raw Spread)", 
                        "min_score": 60, "years": 2, "tickers": ["USDJPY=X", "GBPUSD=X"], "last_backtest": None, "tax_category": "prop_firm", "exit_profile": "ftmo_swing"
                    }
                },
                "scan_universes": {}
            }
            with open(user_cfg_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
                
            cols = ['id', 'account_name', 'entry_date', 'exit_date', 'symbol', 'name', 'direction', 'signal_price', 'entry_price', 'currency', 'fx_rate', 'position_size', 'contract_type', 'point_value', 'base_currency', 'invest_eur', 'sl_price', 'tp_price', 'planned_risk_eur', 'est_fees_eur', 'master_score', 'setup_type', 'mc_robustness', 'atr_days', 'exit_mode', 'status', 'exit_price', 'pnl_eur', 'pnl_pct', 'r_multiple', 'exit_reason', 'notes', 'strategy_version', 'execution_type']
            pd.DataFrame(columns=cols).to_csv(get_user_file("trade_journal.csv"), index=False)
            
            with open(get_user_file("alert_state.json"), "w", encoding="utf-8") as f:
                json.dump({}, f)
                
            st.session_state.config = load_config()
            for transient_key in ["scanner_results", "watchlist_results", "futures_scan_results", "active_order_ticker", "active_futures_order", "scanner_favorite_tickers", "scanner_info_tickers", "watchlist_info_tickers", "futures_info_tickers", "active_lab_account", "transfer_candidates", "danger_user_reset_check", "clean_slate_confirm_check"]:
                st.session_state.pop(transient_key, None)
                
            st.session_state["dz_feedback_msg"] = "🔄 Werkseinstellungen wiederhergestellt: Deine persönlichen Konten, Ticker-Listen und dein Trade-Journal wurden auf den Auslieferungszustand zurückgesetzt!"
            st.rerun()
#endregion