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
        except Exception:
            if attempt == max_retries - 1:
                raise
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

def get_player_full_details(league_id, player_id, headers):
    """Holt echte Marktwerte, echten Teamnamen und berechnet die Prognose."""
    resp = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/players/{player_id}", headers)
    if not resp or resp.status_code != 200:
        return 0, 0, 0, ""
    
    p = resp.json()
    mv = p.get("mv") or p.get("marketValue") or 0
    team_name = p.get("tn") or p.get("teamName") or p.get("t") or ""
    
    # Echten Zuwachs aus mvc oder mh (Historie) ermitteln
    change = p.get("mvc") or p.get("marketValueChange") or 0
    if change == 0:
        mh = p.get("mh") or []
        if len(mh) >= 2:
            v_today = mh[-1].get("m") or mh[-1].get("v") or 0
            v_yest = mh[-2].get("m") or mh[-2].get("v") or 0
            change = v_today - v_yest
            
    pred_target = int(change * 0.92) if change > 0 else 0
    return mv, change, pred_target, team_name

def main():
    if not KB_EMAIL or not KB_PASSWORD:
        raise ValueError("KB_EMAIL oder KB_PASSWORD fehlt!")

    token, user_id, leagues = login()
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"

    if not leagues:
        print("Keine Ligen gefunden.")
        return

    first_league = leagues[0]
    league_id = first_league.get("i") or first_league.get("id")

    # 1. MANAGER BUDGETS
    budget_data = []
    resp_users = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/ranking", headers)
    if resp_users and resp_users.status_code == 200:
        raw = resp_users.json()
        users = raw.get("u") or raw.get("users") or raw.get("it") or []
        for u in users:
            name = u.get("n") or u.get("name", "Manager")
            budget = u.get("b") or u.get("budget") or 0
            team_val = u.get("tv") or u.get("teamValue") or 0
            max_neg = u.get("mneg") if u.get("mneg") is not None else int(-team_val * 0.33)
            avail = budget - max_neg
            
            budget_data.append({
                "User": name,
                "Budget": fmt_de(budget),
                "Team Value": fmt_de(team_val),
                "Max Negative": fmt_de(max_neg),
                "Available Budget": fmt_de(avail)
            })

    df_budgets = pd.DataFrame(budget_data)

    # 2. CURRENT MARKET PREDICTIONS
    resp_mkt = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/market", headers)
    market_rows = []
    if resp_mkt and resp_mkt.status_code == 200:
        mkt_players = resp_mkt.json().get("it") or resp_mkt.json().get("players") or []
        for p in mkt_players:
            p_id = p.get("i") or p.get("id")
            last_name = p.get("n") or p.get("lastName", "")
            
            mv, change, pred, team_name = get_player_full_details(league_id, p_id, headers)
            if not team_name:
                team_name = p.get("tn") or p.get("teamName") or "Unbekannt"
            if mv == 0:
                mv = p.get("mv", 0)

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

    # 3. SQUAD PREDICTIONS
    resp_lineup = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/lineup", headers)
    squad_rows = []
    if resp_lineup and resp_lineup.status_code == 200:
        squad_players = resp_lineup.json().get("it") or resp_lineup.json().get("players") or []
        for p in squad_players:
            p_id = p.get("i") or p.get("id")
            last_name = p.get("n") or p.get("lastName", "")
            
            mv, change, pred, team_name = get_player_full_details(league_id, p_id, headers)
            if not team_name:
                team_name = p.get("tn") or p.get("teamName") or "Unbekannt"

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

    # HTML TEMPLATE
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
        
        <h2>Manager Budgets</h2>
        <p>Here are the current budgets of all managers in your league:</p>
        {df_budgets.to_html(index=False, escape=False) if not df_budgets.empty else '<p>No data</p>'}
        
        <h2>Current Market Predictions</h2>
        <p>The following table shows all available players with a substantial positive predicted market value for the next day:</p>
        {df_market.to_html(index=False, escape=False) if not df_market.empty else '<p>No data</p>'}
        
        <h2>Your Squad Predictions</h2>
        <p>Here are the predicted market values for all players currently in your squad:</p>
        {df_squad.to_html(index=False, escape=False) if not df_squad.empty else '<p>No data</p>'}
        
        <br>
        <p>Best regards,<br>Your KickAdvisor Bot</p>
        <hr>
        <p style="font-size: 11px; color: #888888;">This email was generated by the Kickbase Trading Advisor</p>
    </body>
    </html>
    """

    if SMTP_USER and SMTP_PASSWORD:
        msg = MIMEMultipart("alternative")
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = f"Kickbase: {today_str}"
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Report erfolgreich versendet!")

if __name__ == "__main__":
    main()
