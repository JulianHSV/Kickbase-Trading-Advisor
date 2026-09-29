import streamlit as st
import pandas as pd
import requests

# Konfiguration der Handy-Ansicht
st.set_page_config(page_title="Kickbase 7D-Prognose", layout="wide", initial_sidebar_state="collapsed")

st.title("⚽ Kickbase 7-Tage-KI-Prognose")

# 1. Kickbase Login & Data Fetching
@st.cache_data(ttl=3600)  # Cached die Daten für 1 Stunde
def load_kickbase_data():
    email = st.secrets.get("KB_EMAIL")
    password = st.secrets.get("KB_PASSWORD")
    
    if not email or not password:
        st.error("Bitte KB_EMAIL und KB_PASSWORD in den Streamlit Secrets hinterlegen!")
        return None
    
        session = requests.Session()
    login_url = "https://api.kickbase.com/v2/users/login"
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}
    login_payload = {"email": email, "password": password}

    res = session.post(login_url, json=login_payload, headers=headers)
    if res.status_code != 200:
        st.error(f"Kickbase Login fehlgeschlagen! Status: {res.status_code} - Antwort: {res.text}")
        return None
    
    token = res.json().get("token")
    headers = {"Authorization": f"Bearer {token}"}
    
    # Holen der Ligen
    leagues_res = session.get("https://api.kickbase.com/v2/leagues", headers=headers)
    if leagues_res.status_code != 200:
        st.error("Fehler beim Laden der Ligen.")
        return None
        
    leagues = leagues_res.json().get("leagues", [])
    if not leagues:
        st.error("Keine Liga gefunden.")
        return None
        
    league_id = leagues[0]["id"]
    
    # Marktwerte/Spieler der Liga abrufen
    market_res = session.get(f"https://api.kickbase.com/v2/leagues/{league_id}/market", headers=headers)
    players_raw = market_res.json().get("players", [])
    
    processed_players = []
    
    for p in players_raw:
        name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
        mw = p.get("marketValue", 0)
        change_24h = p.get("marketValueChange360", 0) # 24h Trend
        
        # 7-Tage-Prognose-Berechnung (Trend-Abflachungsmodell)
        total_7d_trend = 0
        current_daily = change_24h
        decay_factor = 0.88 # Flacht pro Tag um 12% ab
        
        for day in range(1, 8):
            current_daily *= decay_factor
            total_7d_trend += current_daily
            
        processed_players.append({
            "Spieler": name,
            "Position": p.get("position", "N/A"),
            "Aktueller MW": mw,
            "24h Trend": change_24h,
            "7D Prognose (€)": round(total_7d_trend),
            "7D Prognose (%)": round((total_7d_trend / mw) * 100, 2) if mw > 0 else 0,
            "MW in 7 Tagen": mw + round(total_7d_trend)
        })
        
    return pd.DataFrame(processed_players)

# 2. UI App Aufbereitung
data = load_kickbase_data()

if data is not None and not data.empty:
    # Suchleiste für das Smartphone
    search_query = st.text_input("🔍 Spieler suchen (z. B. Uzun, Kramaric, Hein):", "")
    
    if search_query:
        filtered_df = data[data["Spieler"].str.contains(search_query, case=False, na=False)]
    else:
        filtered_df = data
        
    # Sortierung nach 7D-Prognose
    filtered_df = filtered_df.sort_values(by="7D Prognose (€)", ascending=False)
    
    # Detail-Karten Anzeige
    for _, row in filtered_df.iterrows():
        trend_color = "🟢" if row["7D Prognose (€)"] >= 0 else "🔴"
        
        with st.container():
            st.markdown(f"### {row['Spieler']} ({row['Position']})")
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Marktwert:** {row['Aktueller MW']:,} €")
                st.write(f"**24h Trend:** {row['24h Trend']:,} €")
                
            with col2:
                st.write(f"**7D Prognose:** {trend_color} +{row['7D Prognose (€)']:,} €" if row["7D Prognose (€)"] >= 0 else f"**7D Prognose:** {trend_color} {row['7D Prognose (€)']:,} €")
                st.write(f"**Trend in %:** {row['7D Prognose (%)']}%")
                
            st.write(f"**Erwarteter MW (in 7 Tagen):** {row['MW in 7 Tagen']:,} €")
            st.divider()
else:
    st.info("Daten werden geladen oder keine Marktdaten verfügbar.")
