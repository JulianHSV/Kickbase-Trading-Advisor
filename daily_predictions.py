import os
import requests
from dotenv import load_dotenv

load_dotenv()

KB_EMAIL = os.getenv("KB_EMAIL") or os.getenv("KICK_USER")
KB_PASSWORD = os.getenv("KB_PASSWORD") or os.getenv("KICK_PASS")

BASE_HEADERS = {
    "User-Agent": "Kickbase/4.8.3 (Android; 14)",
    "Accept": "application/json",
    "Content-Type": "application/json; charset=UTF-8"
}

def inspect_endpoints():
    login_url = "https://api.kickbase.com/v4/user/login"
    payload = {"em": KB_EMAIL.strip(), "pass": KB_PASSWORD.strip(), "loy": False, "rep": {}}
    
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    resp = session.post(login_url, json=payload, timeout=10)
    data = resp.json()
    
    token = data.get("tkn") or data.get("token")
    leagues = data.get("lins", [])
    if not leagues:
        print("Keine Ligen gefunden")
        return
        
    league_id = leagues[0].get("i")
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    
    endpoints = {
        "Squad Endpoint": f"https://api.kickbase.com/v4/leagues/{league_id}/me/players",
        "Market Endpoint": f"https://api.kickbase.com/v4/leagues/{league_id}/market",
        "Users Endpoint": f"https://api.kickbase.com/v4/leagues/{league_id}/users"
    }
    
    for name, url in endpoints.items():
        r = requests.get(url, headers=headers)
        print(f"=== {name} ({r.status_code}) ===")
        print(r.text[:500])

if __name__ == "__main__":
    inspect_endpoints()
