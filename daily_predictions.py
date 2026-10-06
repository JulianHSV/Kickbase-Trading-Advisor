import os
import time
import requests
import smtplib
import pandas as pd
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

# ==========================================
# ENVIRONMENT & CONFIGURATION
# ==========================================

load_dotenv()

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

START_TOTAL_VALUE = 180000000  # 180 Mio. Euro Baseline
MAX_SQUAD_SIZE = 20


# ==========================================
# HELPER & UTILITY FUNCTIONS
# ==========================================

def fmt_de(val):
    if pd.isna(val) or val is None:
        return "0"
    try:
        val = float(val)
        return f"{val:,.0f}".replace(",", ".")
    except Exception as e:
        return str(val)


def parse_num(val):
    if isinstance(val, dict):
        for key in ["mv", "v", "val", "m", "amount", "price", "p", "marketValue", "value"]:
            if key in val and val[key] is not None:
                return parse_num(val[key])
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        clean_str = val.replace("-", "").replace(".", "").replace(",", "").strip()
        if clean_str.isdigit():
            return int(clean_str)
    return 0


def extract_history_val(item):
    if isinstance(item, dict):
        return parse_num(item.get("mv") or item.get("v") or item.get("val") or item.get("m"))
    if isinstance(item, (int, float)):
        return int(item)
    return 0


def fetch_with_retry(url, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 429:
                print(f"[API WARN] Rate limit auf {url}. Warte {(attempt + 1) * 2} Sek...")
                time.sleep(2.0 * (attempt + 1))
            else:
                print(f"[API HTTP {resp.status_code}] Fehler beim Aufruf von {url}")
        except Exception as e:
            print(f"[API EXCEPTION] Versuch {attempt + 1} fehlgeschlagen für {url}: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


# ==========================================
# AUTHENTICATION & LOGIN LOGIC
# ==========================================

def login():
    login_url = f"{API_BASE_URL}/v4/user/login"
    payload = {
        "em": KB_EMAIL.strip(),
        "pass": KB_PASSWORD.strip(),
        "loy": False,
        "rep": {}
    }
    
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    resp = session.post(login_url, json=payload, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    
    token = data.get("tkn") or data.get("token")
    user_info = data.get("u") or {}
    user_id = user_info.get("id") or user_info.get("i")
    leagues = data.get("lins") or []
    
    print(f"[LOGIN SUCCESS] Eingeloggt als User-ID: {user_id}")
    return token, user_id, leagues


# ==========================================
# DETAILED PLAYER & MARKET ANALYSIS
# ==========================================

def get_player_details(league_id, player_id, headers):
    urls = [
        f"{API_BASE_URL}/v4/leagues/{league_id}/players/{player_id}",
        f"{API_BASE_URL}/v4/players/{player_id}",
        f"{API_BASE_URL}/v4/leagues/{league_id}/market/{player_id}"
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
    
    # 1. Direkter Trend-Wert aus v4
    change = parse_num(p.get("tfhmvt"))
    
    # 2. Alternative Keys im Spieler-Objekt durchsuchen
    if change == 0:
        for key in ["mvc", "marketValueChange", "dayChange", "delta", "d", "mvc24"]:
            if key in p and p[key] is not None:
                val = parse_num(p[key])
                if abs(val) > 0:
                    change = val
                    break

    # 3. Auswertung der historischen Marktwert-Liste (mh / marketHistory)
    if change == 0:
        mh = p.get("mh") or p.get("marketHistory") or p.get("mvh") or p.get("h") or []
        if isinstance(mh, list) and len(mh) >= 2:
            v_today = extract_history_val(mh[-1])
            v_yesterday = extract_history_val(mh[-2])
            if v_today > 0 and v_yesterday > 0:
                change = v_today - v_yesterday

    # Marktwert-Prognose für morgen (Fortführung des Trends mit Dämpfung)
    if change != 0:
        pred = int(change * 0.92)
    else:
        pred = 0

    return mv, change, pred, team_name


# ==========================================
# HISTORICAL FEED & SQUAD TRACKING
# ==========================================

def fetch_all_league_transfers_and_squads(league_id, headers):
    net_transfers = {}
    squad_counts = {}
    
    cursor_dt = None
    max_pages = 50
    page = 0

    print("[FEED] Starte tiefen Abruf aller historischen Liga-Transfers...")

    while page < max_pages:
        if cursor_dt:
            url = f"{API_BASE_URL}/v4/leagues/{league_id}/feed?dt={cursor_dt}"
        else:
            url = f"{API_BASE_URL}/v4/leagues/{league_id}/feed"

        resp = fetch_with_retry(url, headers)
        if not resp or resp.status_code != 200:
            print(f"[FEED WARN] Abruf gestoppt bei Seite {page}")
            break
            
        data = resp.json()
        items = data.get("it") or data.get("items") or []
        
        if not items:
            break

        for item in items:
            item_type = item.get("t") or item.get("type")
            u_id = str(item.get("uid") or item.get("userId") or item.get("u") or "")
            amount = parse_num(item.get("a") or item.get("amount") or item.get("v") or item.get("p"))
            
            cursor_dt = item.get("dt") or item.get("date") or cursor_dt

            if not u_id:
                continue

            if u_id not in net_transfers:
                net_transfers[u_id] = 0
            if u_id not in squad_counts:
                squad_counts[u_id] = 0

            # Transfer-Auswertung (12 = Kauf, 13 = Verkauf)
            if item_type in [12, "buy", "BUY"]:
                if amount > 0:
                    net_transfers[u_id] -= amount
                squad_counts[u_id] += 1

            elif item_type in [13, "sell", "SELL"]:
                if amount > 0:
                    net_transfers[u_id] += amount
                squad_counts[u_id] = max(0, squad_counts[u_id] - 1)

        page += 1

    print(f"[FEED SUCCESS] Transfers von {len(net_transfers)} Managern erfolgreich verarbeitet.")
    return net_transfers, squad_counts


# ==========================================
# MANAGER BUDGETS & KADERGRÖSSEN
# ==========================================

def calculate_manager_budgets(league_id, my_user_id, headers):
    users_raw = []
    
    endpoints = [
        f"{API_BASE_URL}/v4/leagues/{league_id}/ranking",
        f"{API_BASE_URL}/v4/leagues/{league_id}/users",
        f"{API_BASE_URL}/v4/leagues/{league_id}/stats",
        f"{API_BASE_URL}/v4/leagues/{league_id}/table"
    ]
    
    for ep in endpoints:
        resp_rank = fetch_with_retry(ep, headers)
        if resp_rank and resp_rank.status_code == 200:
            raw = resp_rank.json()
            if isinstance(raw, list):
                users_raw = raw
                break
            elif isinstance(raw, dict):
                users_raw = (
                    raw.get("us") or 
                    raw.get("u") or 
                    raw.get("users") or 
                    raw.get("items") or 
                    raw.get("ranking") or []
                )
                if users_raw:
                    break

    net_transfers, squad_counts_feed = fetch_all_league_transfers_and_squads(league_id, headers)

    budget_list = []
    for u in users_raw:
        if not isinstance(u, dict):
            continue
            
        u_id = str(u.get("i") or u.get("id") or u.get("uid"))
        name = u.get("n") or u.get("name") or u.get("userName") or u.get("un") or "Manager"
        
        team_val = parse_num(u.get("tv") or u.get("teamValue") or u.get("v") or u.get("value"))
        
        # Erkennung der Kadergröße aus verschiedenen v4-Keys
        squad_count = parse_num(
            u.get("s") or u.get("sc") or u.get("playerCount") or 
            u.get("pc") or u.get("squadSize") or u.get("c") or u.get("sq") or u.get("playersCount")
        )
        
        # Fallback auf die gezählten Feed-Käufe
        if squad_count == 0 and u_id in squad_counts_feed:
            squad_count = squad_counts_feed[u_id]

        direct_budget = parse_num(u.get("b") or u.get("budget"))
        
        # Budget-Berechnung: Startkapital - Kaderwert + Netto-Transferbalance
        if u_id == str(my_user_id) and direct_budget != 0:
            est_cash = direct_budget
        else:
            transfer_balance = net_transfers.get(u_id, 0)
            est_cash = (START_TOTAL_VALUE - team_val) + transfer_balance

        # Bietpower inklusive Dispo (33% Beleihung des Kaderwerts)
        max_dispo = int(team_val * 0.33)
        max_available = est_cash + max_dispo
        
        budget_list.append({
            "Manager": name,
            "Team Value": fmt_de(team_val),
            "Squad": f"{squad_count}/{MAX_SQUAD_SIZE}",
            "Est. Cash": fmt_de(est_cash),
            "Max Available": fmt_de(max_available)
        })

    return pd.DataFrame(budget_list)


# ==========================================
# TRANSFERMARKT & PROGNOSEN
# ==========================================

def get_market_predictions(league_id, headers):
    resp_mkt = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/market", headers)
    market_rows = []
    
    if resp_mkt and resp_mkt.status_code == 200:
        mkt_players = resp_mkt.json().get("it") or resp_mkt.json().get("players") or []
        for p in mkt_players:
            p_id = p.get("i") or p.get("id")
            last_name = p.get("n") or p.get("lastName") or p.get("ln") or "Unbekannt"
            
            mv_base = parse_num(p.get("mv"))
            team_base = p.get("tn") or p.get("teamName") or "Unbekannt"
            
            mv, change, pred, team_name = get_player_details(league_id, p_id, headers)
            
            if mv == 0:
                mv = mv_base
            if team_name == "Unbekannt":
                team_name = team_base

            market_rows.append({
                "last_name": last_name,
                "team_name": team_name,
                "mv": fmt_de(mv),
                "change_raw": change,
                "mv_change_yesterday": fmt_de(change),
                "predicted_mv_target": fmt_de(pred),
                "s_11_prob": "None",
                "hours_to_exp": "NaN",
                "expiring_today": False
            })

    df_market = pd.DataFrame(market_rows)
    if not df_market.empty:
        df_market = df_market.sort_values(by="change_raw", ascending=False)
        df_market = df_market.drop(columns=["change_raw"])
        
    return df_market


# ==========================================
# EIGENER KADER & PROGNOSEN
# ==========================================

def get_squad_predictions(league_id, headers):
    resp_lineup = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/lineup", headers)
    squad_rows = []
    
    if resp_lineup and resp_lineup.status_code == 200:
        squad_players = resp_lineup.json().get("it") or resp_lineup.json().get("players") or []
        for p in squad_players:
            p_id = p.get("i") or p.get("id")
            last_name = p.get("n") or p.get("lastName") or p.get("ln") or "Unbekannt"
            
            mv_base = parse_num(p.get("mv"))
            team_base = p.get("tn") or p.get("teamName") or "Unbekannt"
            
            mv, change, pred, team_name = get_player_details(league_id, p_id, headers)
            
            if mv == 0:
                mv = mv_base
            if team_name == "Unbekannt":
                team_name = team_base

            squad_rows.append({
                "last_name": last_name,
                "team_name": team_name,
                "mv": fmt_de(mv),
                "change_raw": change,
                "mv_change_yesterday": fmt_de(change),
                "predicted_mv_target": fmt_de(pred),
                "s_11_prob": "NaN"
            })

    df_squad = pd.DataFrame(squad_rows)
    if not df_squad.empty:
        df_squad = df_squad.sort_values(by="change_raw", ascending=False)
        df_squad = df_squad.drop(columns=["change_raw"])
        
    return df_squad


# ==========================================
# HTML REPORT BUILDER & EMAIL DISPATCH
# ==========================================

def send_email_report(df_budgets, df_market, df_squad):
    today_str = datetime.now().strftime("%d-%m-%Y")
    
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #2b2b2b; color: #e0e0e0; padding: 20px; }}
            h1, h2 {{ color: #ffffff; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 25px; background-color: #333333; color: #ffffff; font-size: 13px; }}
            th {{ background-color: #444444; text-align: left; padding: 8px; border: 1px solid #555; color: #ffffff; }}
            td {{ padding: 8px; border: 1px solid #555; }}
            tr:nth-child(even) {{ background-color: #3a3a3a; }}
        </style>
    </head>
    <body>
        <h1>Kickbase Report for {today_str}</h1>
        <p>Greetings!</p>
        
        <h2>Manager Budgets & Squad Limits</h2>
        <p>Estimated cash reserves and maximum bidding power (180M baseline, 20 max squad size):</p>
        {df_budgets.to_html(index=False, escape=False) if not df_budgets.empty else '<p>No data available</p>'}
        
        <h2>Current Market Predictions</h2>
        <p>The following table shows all available players with predicted market values:</p>
        {df_market.to_html(index=False, escape=False) if not df_market.empty else '<p>No data available</p>'}
        
        <h2>Your Squad Predictions</h2>
        <p>Here are the predicted market values for all players currently in your squad:</p>
        {df_squad.to_html(index=False, escape=False) if not df_squad.empty else '<p>No data available</p>'}
        
        <br>
        <p>Best regards,<br>Your KickAdvisor Bot</p>
        <hr>
        <p style="font-size: 11px; color: #888888;">This email was generated by the Kickbase Trading Advisor</p>
    </body>
    </html>
    """

    sender_email = SMTP_USER or KB_EMAIL
    sender_password = SMTP_PASSWORD or KB_PASSWORD
    recipient = EMAIL_TO or sender_email

    if not sender_email or not sender_password:
        print("[ERROR] Keine SMTP-Anmeldedaten vorhanden.")
        return

    print(f"\n[EMAIL] Versuche E-Mail zu senden an {recipient} via {SMTP_SERVER}:{SMTP_PORT}...")

    try:
        msg = MIMEMultipart("alternative")
        msg['From'] = sender_email
        msg['To'] = recipient
        msg['Subject'] = f"Kickbase: {today_str}"
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print("[EMAIL SUCCESS] E-Mail erfolgreich versendet!")
    except Exception as e:
        print(f"[EMAIL ERROR] Fehler beim Versenden der E-Mail: {e}")


# ==========================================
# MAIN EXECUTION ROUTINE
# ==========================================

def main():
    print("==========================================")
    print("  KICKBASE ADVISOR - BOT START")
    print("==========================================")
    
    if not KB_EMAIL or not KB_PASSWORD:
        raise ValueError("FEHLER: KB_EMAIL oder KB_PASSWORD fehlt in den Umgebungsvariablen!")

    token, user_id, leagues = login()
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"

    if not leagues:
        print("[ERROR] Keine Ligen für diesen Account gefunden.")
        return

    first_league = leagues[0]
    league_id = first_league.get("i") or first_league.get("id")
    print(f"[INFO] Gewählte Liga ID: {league_id}")

    # 1. MANAGER BUDGETS
    print("\n--- 1. Berechne Manager-Budgets ---")
    df_budgets = calculate_manager_budgets(league_id, user_id, headers)

    # 2. MARKET PREDICTIONS
    print("\n--- 2. Lade Transfermarkt & erstelle Prognosen ---")
    df_market = get_market_predictions(league_id, headers)

    # 3. SQUAD PREDICTIONS
    print("\n--- 3. Lade eigenen Kader & erstelle Prognosen ---")
    df_squad = get_squad_predictions(league_id, headers)

    # 4. EMAIL REPORT
    send_email_report(df_budgets, df_market, df_squad)


if __name__ == "__main__":
    main()
