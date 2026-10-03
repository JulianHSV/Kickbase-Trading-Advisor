import os
import time
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

# ZUGANGSDATEN AUS ENVIRONMENT / SECRETS
KB_EMAIL = os.getenv("KB_EMAIL") or os.getenv("KICK_USER")
KB_PASSWORD = os.getenv("KB_PASSWORD") or os.getenv("KICK_PASS")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER") or KB_EMAIL
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_PASS") or KB_PASSWORD
EMAIL_TO = os.getenv("EMAIL_TO") or os.getenv("EMAIL_USER") or KB_EMAIL

API_BASE_URL = "https://api.kickbase.com"

# AKTUELLES USER-AGENT HEADER (wichtig gegen ClientTooOld)
BASE_HEADERS = {
    "User-Agent": "Kickbase/4.2.0 (Android; 14)",
    "Accept": "application/json",
    "Accept-Language": "de-DE",
    "Content-Type": "application/json; charset=UTF-8"
}

def fetch_with_retry(url, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(1.0 * (attempt + 1))
    return None

def login():
    login_url = f"{API_BASE_URL}/v4/user/login"
    payload = {
        "email": KB_EMAIL.strip(),
        "password": KB_PASSWORD.strip(),
        "ext": "false"
    }
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    response = session.post(login_url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    if data.get("err") == 5 or "token" not in data:
        raise ValueError(f"Login fehlgeschlagen: {data.get('errMsg', 'Kein Token')}")
        
    token = data.get("token")
    user_id = data.get("user", {}).get("id")
    leagues = data.get("leagues", []) or data.get("user", {}).get("leagues", [])
    return token, user_id, leagues

def main():
    if not KB_EMAIL or not KB_PASSWORD:
        raise ValueError("KB_EMAIL oder KB_PASSWORD fehlt!")

    token, user_id, leagues = login()
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"

    if not leagues:
        resp = fetch_with_retry(f"{API_BASE_URL}/v4/user/me", headers)
        if resp:
            me_data = resp.json()
            leagues = me_data.get("leagues", []) or me_data.get("user", {}).get("leagues", [])

    if not leagues:
        print("Keine Liga gefunden.")
        return

    league_id = leagues[0].get("id")
    league_name = leagues[0].get("name", "Kickbase Liga")
    print(f"Erfolgreich eingeloggt in Liga: {league_name} ({league_id})")

    # 1. KADER & MARKTWERT-TRENDS
    resp_squad = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/users/{user_id}/players", headers)
    squad_players = resp_squad.json().get("players", []) if resp_squad else []

    total_squad_value = 0
    total_daily_change = 0
    squad_lines = []

    for p in squad_players:
        name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or p.get("name", "Spieler")
        mv = p.get("marketValue", 0)
        change = p.get("marketValueChange", 0)
        total_squad_value += mv
        total_daily_change += change
        
        trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        squad_lines.append(f"  • {name}: {mv:,} € ({trend} {change:+,,} €)")

    # 2. TRANSFERMARKT
    resp_mkt = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/market", headers)
    mkt_players = resp_mkt.json().get("players", []) if resp_mkt else []

    mkt_lines = []
    for p in mkt_players:
        name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or p.get("name", "Spieler")
        price = p.get("price", 0)
        mv = p.get("marketValue", 0)
        seller = p.get("sellerName", "Kickbase")
        diff = price - mv
        diff_str = f"({diff:+,,} € zum MV)" if diff != 0 else "(Marktwert)"
        
        mkt_lines.append(f"  • {name} | Preis: {price:,} € {diff_str} | Verkäufer: {seller}")

    # 3. LIGA-TABELLE & FINANZEN
    resp_users = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/users", headers)
    users = resp_users.json().get("users", []) if resp_users else []

    budget_lines = []
    for u in users:
        u_name = u.get("name", "Manager")
        team_val = u.get("teamValue", 0)
        budget = u.get("budget", 0)
        points = u.get("points", 0)
        budget_lines.append(f"  • {u_name} | Punkte: {points:,} | Teamwert: {team_val:,} € | Geschätztes Budget: {budget:,} €")

    # E-MAIL SUMMARY FORMATIERUNG
    email_body = f"""Moin Julian,

hier ist dein tägliches Kickbase Update für die Liga "{league_name}":

========================================
1. KADER-ÜBERSICHT & PROGNOSE
========================================
Gesamtwert Kader: {total_squad_value:,} €
Tagesveränderung: {total_daily_change:+,,} €

Einzelwerte:
""" + "\n".join(squad_lines) + f"""

========================================
2. TRANSFERMARKT
========================================
""" + ("\n".join(mkt_lines) if mkt_lines else "  Keine Spieler auf dem Transfermarkt.") + f"""

========================================
3. LIGA-TABELLE & FINANZEN
========================================
""" + "\n".join(budget_lines) + """

Viel Erfolg auf dem Transfermarkt!
"""

    # E-MAIL VERSAND
    if SMTP_USER and SMTP_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = f"Kickbase Update: {total_daily_change:+,,} € heute"
        msg.attach(MIMEText(email_body, 'plain', 'utf-8'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("E-Mail erfolgreich versendet!")
    else:
        print("SMTP Daten fehlen, E-Mail konnte nicht gesendet werden.")

if __name__ == "__main__":
    main()
