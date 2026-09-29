import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="Kickbase 7D-Prognose", layout="wide")

st.title("⚽ Kickbase 7-Tage-KI-Prognose")

POS_MAP = {1: "TW", 2: "ABW", 3: "MF", 4: "ST"}

@st.cache_data(ttl=3600)
def load_kickbase_data():
    email = st.secrets.get("KB_EMAIL")
    password = st.secrets.get("KB_PASSWORD")

    if not email or not password:
        st.error("Bitte KB_EMAIL und KB_PASSWORD in den Streamlit Secrets eintragen.")
        return None

    session = requests.Session()
    login_url = "https://api.kickbase.com/v4/user/login"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "Content-Type": "application/json"
    }
    
    login_payload = {
        "em": email,
        "pass": password,
        "loy": False,
        "rep": {}
    }

    res = session.post(login_url, json=login_payload, headers=headers)

    if res.status_code != 200:
        st.error(f"Kickbase Login fehlgeschlagen! Status: {res.status_code}")
        return None

    token = res.json().get("tkn")
    headers["Authorization"] = f"Bearer {token}"

    leagues_res = session.get("https://api.kickbase.com/v4/leagues", headers=headers)
    if leagues_res.status_code != 200:
        st.error(f"Fehler beim Laden der Ligen. Status: {leagues_res.status_code}")
        return None

    leagues_data = leagues_res.json()
    leagues = leagues_data.get("lins") or []
    
    if not leagues:
        st.error("Keine Liga gefunden.")
        return None

    league_id = leagues[0].get("i")

    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    if market_res.status_code != 200:
        st.error(f"Fehler beim Laden des Transfermarkts. Status: {market_res.status_code}")
        return None

    market_data = market_res.json()
    players = market_data.get("it") or []

    processed_players = []
    for p in players:
        mv = p.get("mv", 0)
        mvt = p.get("mvt", 0)
        
        # Berechnung der Marktwert-Tendenz
        # mvt: 1 = steigend, 2 = fallend / stagnierend
        trend_factor = 1 if mvt == 1 else -1 if mvt == 2 else 0
        
        # Schätzung der 7-Tage-Prognose
        daily_change = 100000 * trend_factor
        pred_7d = mv + (daily_change * 7)
        diff = pred_7d - mv

        first_name = p.get("fn", "")
        last_name = p.get("n", "Unbekannt")
        full_name = f"{first_name} {last_name}".strip()

        pos_code = p.get("pos", 0)
        pos_str = POS_MAP.get(pos_code, "-")

        processed_players.append({
            "Spieler": full_name,
            "Pos": pos_str,
            "Aktueller MW": f"{mv:,.0f} €".replace(",", "."),
            "Prognose (7T)": f"{pred_7d:,.0f} €".replace(",", "."),
            "Gewinn / Verlust": f"{diff:+,.0f} €".replace(",", ".")
        })

    return pd.DataFrame(processed_players)

data = load_kickbase_data()

if data is not None and not data.empty:
    st.dataframe(data, use_container_width=True)
elif data is not None:
    st.info("Aktuell keine Spieler auf dem Transfermarkt verfügbar.")
