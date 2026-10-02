import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

KB_EMAIL = os.getenv("KB_EMAIL") or "julianbuttler2701@gmail.com"
KB_PASSWORD = os.getenv("KB_PASSWORD") or "pygmyq7faNni6pyxxoh"

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
    return data.get("token")

def get_leagues(headers):
    url = f"{API_BASE_URL}/v4/leagues"
    resp = fetch_with_retry(url, headers)
    if resp and resp.status_code == 200:
        return resp.json().get("leagues", [])
    return []

def get_teams(league_id, headers):
    url = f"{API_BASE_URL}/v4/leagues/{league_id}/teams"
    resp = fetch_with_retry(url, headers)
    if resp and resp.status_code == 200:
        return resp.json().get("teams", [])
    return []

def get_team_players(league_id, team_id, headers):
    url = f"{API_BASE_URL}/v4/leagues/{league_id}/teams/{team_id}/players"
    resp = fetch_with_retry(url, headers)
    if resp and resp.status_code == 200:
        return resp.json().get("players", [])
    return []

def main():
    if not KB_EMAIL or not KB_PASSWORD:
        raise ValueError("KB_EMAIL oder KB_PASSWORD fehlt!")
        
    print("Starte Kickbase Login...")
    token = login()
    print("Login erfolgreich!")
    
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    
    leagues = get_leagues(headers)
    if not leagues:
        print("Keine Ligen gefunden.")
        return
        
    league_id = leagues[0].get("id")
    print(f"Verwende Liga-ID: {league_id}")
    
    teams = get_teams(league_id, headers)
    print(f"{len(teams)} Teams gefunden. Starte Abruf aller Spieler...")
    
    predictions = []
    
    for team in teams:
        team_id = team.get("id")
        team_name = team.get("name", "Unbekannt")
        
        players = get_team_players(league_id, team_id, headers)
        print(f"Lade {len(players)} Spieler für {team_name}...")
        
        for player in players:
            p_id = player.get("id")
            p_name = f"{player.get('firstName', '')} {player.get('lastName', '')}".strip() or player.get("name", "Unbekannt")
            mv = player.get("marketValue", 0)
            mv_change = player.get("marketValueChange", 0)
            
            # Trend-Berechnung
            trend_factor = 1.05 if mv_change > 0 else 0.95
            predicted_mv = int(mv * trend_factor)
            
            predictions.append({
                "player_id": p_id,
                "name": p_name,
                "team": team_name,
                "market_value": mv,
                "mv_change": mv_change,
                "predicted_market_value": predicted_mv
            })
            time.sleep(0.15)  # Rate Limit Schutz
            
        time.sleep(0.5)

    df = pd.DataFrame(predictions)
    df.to_csv("predictions.csv", index=False)
    print(f"Fertig! Insgesamt {len(predictions)} Spieler verarbeitet und in predictions.csv gespeichert.")

if __name__ == "__main__":
    main()
