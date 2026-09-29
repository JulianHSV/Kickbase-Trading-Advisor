import streamlit as st
import pandas as pd
import requests

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
    headers["Authorization"] = f"Bearer {token}"

    # 1. Liga-ID abrufen
    leagues_res = session.get("https://api.kickbase.com/v4/leagues", headers=headers)
    if leagues_res.status_code != 200:
        st.error("Fehler beim Laden der Ligen.")
        return None, None, None

    leagues = leagues_res.json().get("lins") or []
    if not leagues:
        st.error("Keine Liga gefunden.")
        return None, None, None

    league_id = leagues[0].get("i")

    # 2. Transfermarkt laden
    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    market_players = []
    if market_res.status_code == 200:
        market_players = market_res.json().get("it") or []

    # 3. Eigenen Kader über 'lineup' laden
    lineup_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/lineup", headers=headers)
    my_players = []
    if lineup_res.status_code == 200:
        lineup_data = lineup_res.json()
        # Kombination aus Aufstellung (p) und Bank (b)
        my_players = (lineup_data.get("p") or []) + (lineup_data.get("b") or [])

    # 4. Alle Spieler der Liga (aus allen Teams) abrufen für die vollständige Suche
    all_league_players = []
    users_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/users", headers=headers)
    if users_res.status_code == 200:
        users = users_res.json().get("users") or users_res.json().get("u") or []
        for u in users:
            uid = u.get("i")
            if uid:
                u_lineup = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/users/{uid}/lineup", headers=headers)
                if u_lineup.status_code == 200:
                    ul_data = u_lineup.json()
                    all_league_players.extend((ul_data.get("p") or []) + (ul_data.get("b") or []))

    # Kombiniere Markt, eigenen Kader und zugewiesene Spieler
    all_combined = market_players + my_players + all_league_players

    return market_players, my_players, all_combined

def process_player_list(players):
    if not players:
        return pd.DataFrame()

    data = []
    seen_ids = set()

    for p in players:
        pid = p.get("i")
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)

        mv = p.get("mv", 0)
        mvt = p.get("mvt", 0)
        
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
            "ID": pid,
            "Spieler": full_name,
            "Pos": POS_MAP.get(p.get("pos", 0), "-"),
            "Aktueller MW": mv,
            "Prognose (24h)": pred_24h,
            "Prognose (7T)": pred_7d,
            "Gewinn / Verlust (7T)": diff_7d,
            "Tagesveränderung": daily_change
        })
    return pd.DataFrame(data)

def render_simple_chart(player_row):
    mv = player_row["Aktueller MW"]
    daily_change = player_row["Tagesveränderung"]

    labels = [f"-{i}T" for i in range(7, 0, -1)] + ["Heute"] + [f"+{i}T" for i in range(1, 8)]
    values = [mv - (daily_change * i) for i in range(7, 0, -1)] + [mv] + [mv + (daily_change * i) for i in range(1, 8)]

    chart_df = pd.DataFrame({"Tag": labels, "Marktwert (€)": values}).set_index("Tag")
    st.line_chart(chart_df)

market_raw, my_raw, all_raw = load_kickbase_data()

if market_raw is not None:
    df_market = process_player_list(market_raw)
    df_my = process_player_list(my_raw)
    df_all = process_player_list(all_raw)

    st.subheader("🔍 Spielersuche & Detail-Analyse")
    
    if not df_all.empty:
        search_options = [""] + sorted(df_all["Spieler"].unique().tolist())
        selected_name = st.selectbox(
            "Wähle einen Spieler aus der Liga / dem Transfermarkt:",
            options=search_options,
            format_func=lambda x: "Spieler suchen..." if x == "" else x
        )

        if selected_name:
            selected_player = df_all[df_all["Spieler"] == selected_name].iloc[0]
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Aktueller MW", f"{selected_player['Aktueller MW']:,.0f} €".replace(",", "."))
            col2.metric("Tagesveränderung", f"{selected_player['Tagesveränderung']:+,.0f} €".replace(",", "."))
            col3.metric("Prognose (24h)", f"{selected_player['Prognose (24h)']:,.0f} €".replace(",", "."))
            col4.metric("Gewinn / Verlust (7T)", f"{selected_player['Gewinn / Verlust (7T)']:+,.0f} €".replace(",", "."))

            st.caption("Marktwert-Verlauf (Vergangenheit & 7-Tage-Prognose)")
            render_simple_chart(selected_player)
            st.markdown("---")

    tab1, tab2 = st.tabs(["🛒 Transfermarkt", "🛡️ Mein Kader"])

    with tab1:
        if not df_market.empty:
            display_df = df_market.drop(columns=["ID", "Tagesveränderung"]).copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                display_df[col] = display_df[col].map("{:,.0f} €".format).str.replace(",", ".")
            st.dataframe(display_df, use_container_width=True)
        else:
            st.info("Keine Spieler auf dem Transfermarkt.")

    with tab2:
        if not df_my.empty:
            display_my = df_my.drop(columns=["ID", "Tagesveränderung"]).copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                display_my[col] = display_my[col].map("{:,.0f} €".format).str.replace(",", ".")
            st.dataframe(display_my, use_container_width=True)
        else:
            st.info("Keine Spieler im Kader gefunden.")
