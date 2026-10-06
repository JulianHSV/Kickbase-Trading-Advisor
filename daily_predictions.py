import os
import time
import requests
import smtplib
import pandas as pd
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

# Anmeldedaten und Ausweich-Variablen für GitHub Secrets
KB_EMAIL = os.getenv("KB_EMAIL") or os.getenv("KICK_USER")
KB_PASSWORD = os.getenv("KB_PASSWORD") or os.getenv("KICK_PASS")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER") or KB_EMAIL
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_PASS") or KB_PASSWORD
EMAIL_TO = os.getenv("EMAIL_TO") or os.getenv("EMAIL_USER") or KB_EMAIL

API_BASE_URL = "https://api.kickbase.com"

BASE_HEADERS = {
    "User-Agent": "Kickbase/4.8.3 (Android; 14)",
    "Accept": "application/json",
    "Accept-Language": "de-DE",
    "Content-Type": "application/json; charset=UTF-8"
}

# Liga-Regeln
START_TOTAL_VALUE = 180000000  # 100 Mio. Kaderwert + 80 Mio. Startbudget
MAX_SQUAD_SIZE = 20           # Max. 20 Spieler im Kader

def fmt_de(val):
    if pd.isna(val) or val is None:
        return "0"
    try:
        val = float(val)
        return f"{val:,.0f}".replace(",", ".")
    except Exception:
        return str(val)

def fetch_with_retry(url, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
            else:
                print(f"HTTP {resp.status_code} bei {url}")
        except Exception as e:
            print(f"Fehler bei Request {url}: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(1.0 * (attempt + 1))
    return None

def login():
    login_url = f"{API_BASE_URL}/v4/user/login"
    payload = {"em": KB_EMAIL.strip(), "pass": KB_PASSWORD.strip(), "loy": False, "rep": {}}
    
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    resp = session.post(login_url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    
    token = data.get("tkn") or data.get("token")
    user_info = data.get("u") or {}
    user_id = user_info.get("id") or user_info.get("i")
    leagues = data.get("lins") or []
    return token, user_id, leagues

def parse_num(val):
    if isinstance(val, dict):
        return val.get("mv") or val.get("v") or val.get("val") or val.get("m") or val.get("amount") or 0
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str) and val.replace("-", "").isdigit():
        return int(val)
    return 0

def extract_history_val(item):
    if isinstance(item, dict):
        return parse_num(item.get("mv") or item.get("v") or item.get("val")
