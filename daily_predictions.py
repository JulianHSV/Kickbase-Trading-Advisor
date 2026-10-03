import os
import time
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

# DIREKTINGABE (Verhindert jegliche Secret-Fehler)
KB_EMAIL = "julianbuttler2701@gmail.com"
KB_PASSWORD = "pygmyq7faNni6pyxxoh"

# E-Mail Absender / Empfänger
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER") or KB_EMAIL
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_PASS") or KB_PASSWORD
EMAIL_TO = os.getenv("EMAIL_TO") or os.getenv("EMAIL_USER") or KB_EMAIL

API_BASE_URL = "https://api.kickbase.com"

BASE_HEADERS = {
    "User-Agent": "Kickbase/3.52.0 (Android; 13)",
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
        except (requests.exceptions.SSLError, requests.exceptions.RequestException):
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
    return data.get("token"), data.get("user", {}).get("id")

def main():
    if not KB_EMAIL or not KB_PASSWORD:
        raise ValueError("KB_EMAIL oder KB_PASSWORD fehlt!")

    token, user_id = login()
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"

        # Liga holen (v4 kompatibel)
    resp = fetch_with_retry(f"{API_BASE_URL}/v4/leagues", headers)
    leagues_data = resp.json() if resp else {}
    
    # In v4 kann die Antwort entweder eine Liste oder ein Dictionary mit "leagues" sein
    if isinstance(leagues_data, list):
        leagues = leagues_data
    else:
        leagues = leagues_data.get("leagues", [])
        
    if not leagues:
        print("Keine Liga gefunden. API-Antwort:", leagues_data)
        return
    
    league_id = leagues[0].get("id")
    print(f"Liga erfolgreich gefunden: {league_id}")


    # 1. Eigener Kader
    resp_squad = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/users/{user_id}/players", headers)
    squad_players = resp_squad.json().get("players", []) if resp_squad else []

    squad_text = "--- DEIN KADER ---\n"
    for p in squad_players:
        name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or p.get("name", "Spieler")
        mv = p.get("marketValue", 0)
        change = p.get("marketValueChange", 0)
        squad_text += f"• {name}: {mv:,} € ({'+' if change >= 0 else ''}{change:,} €)\n"

    # 2. Transfermarkt
    resp_mkt = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/market", headers)
    mkt_players = resp_mkt.json().get("players", []) if resp_mkt else []

    mkt_text = "\n--- TRANSFERMARKT ---\n"
    for p in mkt_players:
        name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or p.get("name", "Spieler")
        price = p.get("price", 0)
        mv = p.get("marketValue", 0)
        seller = p.get("sellerName", "Kickbase")
        mkt_text += f"• {name} | Preis: {price:,} € | MV: {mv:,} € | Verkäufer: {seller}\n"

    # 3. Manager Budgets
    resp_users = fetch_with_retry(f"{API_BASE_URL}/v4/leagues/{league_id}/users", headers)
    users = resp_users.json().get("users", []) if resp_users else []

    budget_text = "\n--- LIGA MANAGER ---\n"
    for u in users:
        u_name = u.get("name", "Manager")
        team_val = u.get("teamValue", 0)
        budget = u.get("budget", 0)
        budget_text += f"• {u_name} | Teamwert: {team_val:,} € | Geschätztes Budget: {budget:,} €\n"

    # E-Mail Zusammenbau
    full_email_body = f"Moin Julian,\n\nhier ist dein aktuelles Kickbase Update:\n\n"
    full_email_body += squad_text + mkt_text + budget_text + "\nViel Erfolg heute!"

    # E-Mail Versand
    if SMTP_USER and SMTP_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = "Dein tägliches Kickbase Update"
        msg.attach(MIMEText(full_email_body, 'plain', 'utf-8'))

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
