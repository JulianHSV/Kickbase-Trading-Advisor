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
        return parse_num(item.get("mv") or item.get("v") or item.get("val") or item.get("m"))
    if isinstance(item, (int, float)):
        return int(item)
    return 0

def get_player_details(league_id, player_id, headers):
    urls = [
        f"{API_BASE_URL}/v4/leagues/{league_id}/players/{player_id}",
        f"{API_BASE_URL}/v4/players/{player_id}"
    ]
    
    resp = None
    for url in urls:
        resp = fetch_with_retry(url, headers)
        if resp and resp.status_code == 200:
            break

    if not resp or resp.status_code != 200:
        return 0, 0, 0, "Unbekannt"
    
    data = resp.json()
    p = data.get("p") if isinstance(data.get("p"), dict) else data
    
    mv = parse_num(p.get("mv") or p.get("marketValue"))
    team_name = p.get("tn") or p.get("teamName") or p.get("t") or "Unbekannt"
    change = parse_num(p.get("tfhmvt"))
    
    if change == 0:
        for key in ["mvc", "marketValueChange", "dayChange", "delta"]:
            if key in p:
                val = parse_num(p[key])
                if abs(val) > 50:
                    change = val
                    break

    if change == 0:
        mh = p.get("mh") or p.get("marketHistory") or p.get("mvh") or p.get("h") or []
        if isinstance(mh, list) and len(mh) >= 2:
            v_today = extract_history_val(mh[-1])
            v_yesterday = extract_history_val(mh[-2])
            if v_today and v_yesterday:
                change = v_today - v_yesterday

    pred = int(change * 0.92)
    return mv, change, pred, team_name

def calculate_manager_budgets(league_id, my_user_id, headers):
    """Holt die Manager-Tabelle und berechnet Bargeld & Bietgrenzen auf Basis von 180m Startguthaben."""
    
    users_raw = []
    endpoints = [
        f"{API_BASE_URL}/v4/leagues/{league_id}/ranking",
        f"{API_BASE_URL}/v4/leagues/{league_id}/users",
        f"{API_BASE_URL}/v4/leagues/{league_id}/me"
    ]
    
    for ep in endpoints:
        resp_rank = fetch_with_retry(ep, headers)
        if resp_rank and resp_rank.status_code == 200:
            raw = resp_rank.json()
            if isinstance(raw, list):
                users_raw = raw
                break
            elif isinstance(raw, dict):
                users_raw = raw.get("us") or raw.get("u") or raw.get("users") or raw.get("items") or raw.get("ranking") or raw.get("it") or []
                if users_raw:
                    break

    # Feed für Transferhistorie auslesen
    feed_resp = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/feed", headers)
    net_transfers = {}
    
    if feed_resp and feed_resp.status_code == 200:
        feed_data = feed_resp.json()
        items = feed_data.get("it") or feed_data.get("items") or []
        for item in items:
            item_type = item.get("t") or item.get("type")
            u_id = item.get("uid") or item.get("userId")
            amount = parse_num(item.get("a") or item.get("amount") or item.get("v"))
            
            if u_id and amount > 0:
                if u_id not in net_transfers:
                    net_transfers[u_id] = 0
                if item_type in [12, "buy"]:
                    net_transfers[u_id] -= amount
                elif item_type in [13, "sell"]:
                    net_transfers[u_id] += amount

    budget_list = []
    for u in users_raw:
        if not isinstance(u, dict):
            continue
            
        u_id = str(u.get("i") or u.get("id") or u.get("uid"))
        name = u.get("n") or u.get("name") or u.get("userName") or u.get("un") or "Manager"
        
        # Abfrage des spezifischen Manager-Profils für exakte Kaderwerte & Kadergröße
        team_val = 0
        squad_count = 0
        user_detail_resp = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/users/{u_id}", headers)
        
        if user_detail_resp and user_detail_resp.status_code == 200:
            ud = user_detail_resp.json()
            players = ud.get("p") or ud.get("players") or ud.get("it") or []
            squad_count = len(players)
            
            # Marktwerte aller Spieler im Kader summieren
            for p in players:
                team_val += parse_num(p.get("mv") or p.get("marketValue") or p.get("v"))
            
            # Falls v4 den Gesamtwert direkt im Profil als 'tv' mitgibt
            direct_tv = parse_num(ud.get("tv") or ud.get("teamValue") or ud.get("kv"))
            if direct_tv > team_val:
                team_val = direct_tv

        # Fallback auf Werte aus der Rangliste, falls die Detailabfrage fehlschlägt
        if team_val == 0:
            team_val = parse_num(u.get("tv") or u.get("teamValue") or u.get("v"))
        if squad_count == 0:
            squad_count = parse_num(u.get("sc") or u.get("playerCount") or u.get("pc") or u.get("c"))

        direct_budget = parse_num(u.get("b") or u.get("budget"))
        
        if u_id == str(my_user_id) and direct_budget != 0:
            est_cash = direct_budget
        else:
            start_cash_
