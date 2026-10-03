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

def debug_login():
    login_url = "https://api.kickbase.com/v4/user/login"
    payload = {
        "em": KB_EMAIL.strip(),
        "pass": KB_PASSWORD.strip(),
        "loy": False,
        "rep": {}
    }
    
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    response = session.post(login_url, json=payload, timeout=10)
    
    print("--- LOGIN STATUS CODE ---")
    print(response.status_code)
    
    print("--- LOGIN RESPONSE JSON ---")
    print(response.text)

    token = response.json().get("tkn") or response.json().get("token")
    if token:
        headers = BASE_HEADERS.copy()
        headers["Authorization"] = f"Bearer {token}"
        resp_leagues = requests.get("https://api.kickbase.com/v4/leagues", headers=headers)
        print("--- LEAGUES ENDPOINT RESPONSE ---")
        print(resp_leagues.text)

if __name__ == "__main__":
    debug_login()
