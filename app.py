import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="Kickbase 7D-Prognose")

st.title("⚽ Kickbase 7-Tage-KI-Prognose")

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
        st.error(f"Kickbase Login fehlgeschlagen! Status: {res.status_code} - Antwort: {res.text}")
        return None

    token = res.json().get("tkn")
    headers["Authorization"] = f"Bearer {token}"

    leagues_res = session.get("https://api.kickbase.com/v4/leagues", headers=headers)
    if leagues_res.status_code != 200:
        st.error(f"Fehler beim Laden der Ligen. Status: {leagues_res.status_code}")
        return None

    leagues = leagues_res.json().get("leagues", [])
    if not leagues:
        st.error("Keine Liga gefunden.")
        return None

    league_id = leagues[0]["id"]

    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    if market_res.status_code != 200:
        st.error(f"Fehler beim Laden des Transfermarkts. Status: {market_res.status_code}")
        return None

    players = market_res.json().get("players", [])
    
    processed_players = []
    for p in players:
        mv = p.get("marketValue", 0)
        trend = p.get("marketValueTrend", 1)
        pred_7d = mv + (trend * 7 * 100000)
        processed_players.append({
            "Spieler": p.get("lastName", "Unbekannt"),
            "Position": p.get("position", "-"),
            "Aktueller MW": f"{mv:,.0f} €",
            "Prognose (7T)": f"{pred_7d:,.0f} €",
            "Gewinn/Verlust": f"{(pred_7d - mv):,.0f} €"
        })

    return pd.DataFrame(processed_players)

data = load_kickbase_data()

if data is not None and not data.empty:
    st.dataframe(data, use_container_width=True)
elif data is not None:
    st.info("Keine Marktdaten verfügbar.")
