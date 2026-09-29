import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go

st.set_page_config(page_title="Kickbase Analyst & Prognose", layout="wide")

st.title("⚽ Kickbase Analyst & 7-Tage-Prognose")

POS_MAP = {1: "TW", 2: "ABW", 3: "MF", 4: "ST"}

@st.cache_data(ttl=1800)
def load_kickbase_data():
    email = st.secrets.get("KB_EMAIL")
    password = st.secrets.get("KB_PASSWORD")

    if not email or not password:
        st.error("Bitte KB_EMAIL und KB_PASSWORD in den Streamlit Secrets eintragen.")
        return None, None, None

    session = requests.Session()
    login_url = "https://api.kickbase.com/v4/user/login"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "Content-Type": "application/json"
    }
    
    login_payload = {"em": email, "pass": password, "loy": False, "rep": {}}
    res = session.post(login_url, json=login_payload, headers=headers)

    if res.status_code != 200:
        st.error(f"Kickbase Login fehlgeschlagen! Status: {res.status_code}")
        return None, None, None

    token = res.json().get("tkn")
    user_id = res.json().get("u", {}).get("i")
    headers["Authorization"] = f"Bearer {token}"

    # Ligen laden
    leagues_res = session.get("https://api.kickbase.com/v4/leagues", headers=headers)
    if leagues_res.status_code != 200:
        st.error("Fehler beim Laden der Ligen.")
        return None, None, None

    leagues = leagues_res.json().get("lins") or []
    if not leagues:
        st.error("Keine Liga gefunden.")
        return None, None, None

    league_id = leagues[0].get("i")

    # 1. Transfermarkt abrufen
    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    market_players = []
    if market_res.status_code == 200:
        market_players = market_res.json().get("it") or []

    # 2. Eigenes Team abrufen
    team_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/users/{user_id}/squad", headers=headers)
    my_players = []
    if team_res.status_code == 200:
        my_players = team_res.json().get("it") or team_res.json().get("p") or []

    return market_players, my_players, headers

def process_player_list(players):
    data = []
    for p in players:
        mv = p.get("mv", 0)
        mvt = p.get("mvt", 0)
        
        # Dynamische Trend-Berechnung basierend auf Status
        daily_change = p.get("mvch") or 0
        if daily_change == 0:
            daily_change = (mv * 0.0075) if mvt == 1 else -(mv * 0.0075) if mvt == 2 else 0

        pred_24h = mv + daily_change
        pred_7d = mv + (daily_change * 7)
        diff_7d = pred_7d - mv

        fn = p.get("fn", "")
        ln = p.get("n", "Unbekannt")
        full_name = f"{fn} {ln}".strip()

        data.append({
            "ID": p.get("i"),
            "Spieler": full_name,
            "Pos": POS_MAP.get(p.get("pos", 0), "-"),
            "Aktueller MW": mv,
            "Prognose (24h)": pred_24h,
            "Prognose (7T)": pred_7d,
            "Gewinn / Verlust (7T)": diff_7d,
            "Tagesveränderung": daily_change,
            "raw_data": p
        })
    return pd.DataFrame(data)

def render_player_graph(player_row):
    mv = player_row["Aktueller MW"]
    daily_change = player_row["Tagesveränderung"]

    # Historische Daten (Simulation der letzten 7 Tage basierend auf aktueller Tendenz)
    days_past = [f"Vor {i}T" for i in range(7, 0, -1)]
    past_values = [mv - (daily_change * i) for i in range(7, 0, -1)]

    # Zukunftsprognose (24h & 7 Tage)
    days_future = ["Heute", "+24h", "+2T", "+3T", "+4T", "+5T", "+6T", "+7T"]
    future_values = [mv + (daily_change * i) for i in range(0, 8)]

    fig = go.Figure()

    # Historie
    fig.add_trace(go.Scatter(
        x=days_past + ["Heute"],
        y=past_values + [mv],
        mode='lines+markers',
        name='Vergangenheit',
        line=dict(color='#00CC96', width=3)
    ))

    # Prognose
    fig.add_trace(go.Scatter(
        x=days_future,
        y=future_values,
        mode='lines+markers',
        name='Prognose (KI)',
        line=dict(color='#FF6666', width=3, dash='dash')
    ))

    fig.update_layout(
        title=f"Marktwertverlauf & Prognose: {player_row['Spieler']}",
        xaxis_title="Zeitraum",
        yaxis_title="Marktwert (€)",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20)
    )

    st.plotly_chart(fig, use_container_width=True)

# Haupt-Workflow
market_raw, my_raw, headers = load_kickbase_data()

if market_raw is not None:
    df_market = process_player_list(market_raw)
    df_my = process_player_list(my_raw)

    # Alle verfügbaren Spieler zusammenführen für die Suche
    all_players_df = pd.concat([df_market, df_my]).drop_duplicates(subset=['ID'])

    # --- SUCHLEISTE ---
    st.subheader("🔍 Spielersuche")
    search_query = st.selectbox(
        "Wähle einen Spieler für die Detail-Analyse & Graph:",
        options=[""] + list(all_players_df["Spieler"].unique()),
        format_func=lambda x: "Spieler suchen..." if x == "" else x
    )

    if search_query:
        selected_player = all_players_df[all_players_df["Spieler"] == search_query].iloc[0]
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Aktueller MW", f"{selected_player['Aktueller MW']:,.0f} €".replace(",", "."))
        col2.metric("Tagesveränderung", f"{selected_player['Tagesveränderung']:+,.0f} €".replace(",", "."))
        col3.metric("Prognose (24h)", f"{selected_player['Prognose (24h)']:,.0f} €".replace(",", "."))
        col4.metric("Gewinn / Verlust (7T)", f"{selected_player['Gewinn / Verlust (7T)']:+,.0f} €".replace(",", "."))

        render_player_graph(selected_player)
        st.markdown("---")

    # --- TABS FÜR TRANSFERS & KADER ---
    tab1, tab2 = st.tabs(["🛒 Transfermarkt", "🛡️ Mein Kader"])

    with tab1:
        if not df_market.empty:
            display_df = df_market.drop(columns=["ID", "raw_data", "Tagesveränderung"]).copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                display_df[col] = display_df[col].map("{:,.0f} €".format).str.replace(",", ".")
            st.dataframe(display_df, use_container_width=True)
        else:
            st.info("Keine Spieler auf dem Transfermarkt.")

    with tab2:
        if not df_my.empty:
            display_my = df_my.drop(columns=["ID", "raw_data", "Tagesveränderung"]).copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                display_my[col] = display_my[col].map("{:,.0f} €".format).str.replace(",", ".")
            st.dataframe(display_my, use_container_width=True)
        else:
            st.info("Keine Spieler im Kader gefunden.")
