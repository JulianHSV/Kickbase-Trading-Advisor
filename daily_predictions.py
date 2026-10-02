import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

# Lade lokale .env Datei, falls vorhanden (für lokale Testläufe)
load_dotenv()

# Anmeldedaten aus Umgebungsvariablen / Secrets auslesen
KB_EMAIL = os.getenv("KB_EMAIL")
KB_PASSWORD = os.getenv("KB_PASSWORD")

API_BASE_URL = "https://api.kickbase.com"

# Standard-Header inkl. Browser User-Agent gegen Cloudflare-/Bot-Blocking
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def fetch_with_retry(url, headers, max_retries=3, delay=1.0):
    """Führt einen GET-Request mit Retry-Logik bei Netzwerkausfällen/SSL-Fehlern aus."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                # Rate Limit erreicht -> Gestaffelte Pause
                time.sleep(2.0 * (attempt + 1))
        except (requests.exceptions.SSLError, requests.exceptions.RequestException) as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(delay * (attempt + 1))
    return None

def login():
    """Authentifizierung an der Kickbase v4 API"""
    login_url = f"{API_BASE_URL}/v4/user/login"
    payload = {
        "email": KB_EMAIL,
        "password": KB_PASSWORD
    }
    
    response = requests.post(login_url, json=payload, headers=BASE_HEADERS, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data.get("token")

def main():
    if not KB_EMAIL or not KB_PASSWORD:
        raise ValueError("KB_EMAIL oder KB_PASSWORD Secret fehlt!")

    print("Starte Login...")
    token = login()
    print("Login erfolgreich!")

    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"

    # 1. Transfermarkt / Spielerdaten abrufen
    print("Hole Marktdaten...")
    market_url = f"{API_BASE_URL}/v4/market"
    res = fetch_with_retry(market_url, headers)
    
    if not res:
        print("Fehler beim Abrufen der Marktdaten.")
        return

    market_data = res.json()
    players_data = market_data.get("players", [])
    print(f"{len(players_data)} Spieler gefunden.")

    predictions = []

    # 2. Schleife für Performance-Daten mit Rate-Limiting-Bremse
    for idx, player in enumerate(players_data):
        player_id = player.get("id")
        name = player.get("lastName", player.get("firstName", "Unbekannt"))
        
        # Performance-URL
        perf_url = f"{API_BASE_URL}/v4/competitions/1/players/{player_id}/performance"
        
        try:
            perf_res = fetch_with_retry(perf_url, headers)
            if perf_res:
                perf_data = perf_res.json()
                predictions.append({
                    "id": player_id,
                    "name": name,
                    "market_value": player.get("marketValue", 0),
                    "performance": perf_data
                })
        except Exception as e:
            print(f"Fehler bei Spieler {name} ({player_id}): {e}")

        # Wichtig: 200ms Pause zwischen den Anfragen verhindert den SSL Connection Reset
        time.sleep(0.2)

        if (idx + 1) % 25 == 0:
            print(f"{idx + 1}/{len(players_data)} Spieler verarbeitet...")

    print(f"Fertig! {len(predictions)} Vorhersagen generiert.")

    # Ergebnisse speichern
    df = pd.DataFrame(predictions)
    df.to_csv("predictions.csv", index=False)
    print("Ergebnisse in predictions.csv gespeichert.")

if __name__ == "__main__":
    main()
