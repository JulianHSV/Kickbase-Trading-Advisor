import os
import requests
import json

# Trage hier direkt deine Daten ein zum Testen:
KB_EMAIL = "DEINE_KICKBASE_EMAIL"
KB_PASSWORD = "DEIN_KICKBASE_PASSWORT"

API_BASE_URL = "https://api.kickbase.com"

BASE_HEADERS = {
    "User-Agent": "Kickbase/3.52.0 (Android; 13)",
    "Accept": "application/json",
    "Accept-Language": "de-DE",
    "Content-Type": "application/json; charset=UTF-8"
}

def main():
    print("Starte Login...")
    login_url = f"{API_BASE_URL}/v4/user/login"
    payload = {
        "email": KB_EMAIL.strip(),
        "password": KB_PASSWORD.strip(),
        "ext": "false"
    }
    
    res = requests.post(login_url, json=payload, headers=BASE_HEADERS, timeout=10)
    print("STATUS LOGIN:", res.status_code)
    login_data = res.json() if res.status_code == 200 else {}
    print("LOGIN ANTWORT:", json.dumps(login_data, indent=2))
    
    token = login_data.get("token")
    if not token:
        print("Kein Token erhalten!")
        return

    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"

    print("\n--- TESTE LEAGUES ENDPUNKTE ---")
    
    res_me = requests.get(f"{API_BASE_URL}/v4/user/me", headers=headers)
    print("ANTWORT /v4/user/me:", res_me.status_code, res_me.text)

    res_user_leagues = requests.get(f"{API_BASE_URL}/v4/user/leagues", headers=headers)
    print("ANTWORT /v4/user/leagues:", res_user_leagues.status_code, res_user_leagues.text)

if __name__ == "__main__":
    main()
