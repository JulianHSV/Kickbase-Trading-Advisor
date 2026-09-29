import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go

st.set_page_config(page_title="Kickbase Analyst & Prognose", layout="wide")

st.title("⚽ Kickbase Analyst & 7-Tage-Prognose")

POS_MAP = {1: "TW", 2: "ABW", 3: "MF", 4: "ST"}

def get_kickbase_session():
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

    leagues_res = session.get("https://api.kickbase.com/v4/leagues", headers=headers)
    if leagues_res.status_code != 200:
        st.error("Fehler beim Laden der Ligen.")
        return None, None, None

    leagues = leagues_res.json().get("lins") or []
    if not leagues:
        st.error("Keine Liga gefunden.")
        return None, None, None

    league_id = leagues[0].get("i")
    return session, headers, league_id

def search_kickbase_api(session, headers, league_id, query):
    if not query or len(query) < 2:
        return []
    
    # Echte globale Kickbase-Suchanfrage
    search_url = f"https://api.kickbase.com/v4/leagues/{league_id}/players?q={query}"
    res = session.get(search_url, headers=headers)
    if res.status_code == 200:
        return res.json().get("it") or res.json().get("p") or []

    return []

@st.cache_data(ttl=900)
def load_league_data():
    session, headers, league_id = get_kickbase_session()
    if not session:
        return [], [], None, None, None

    # Transfermarkt
    market_players = []
    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    if market_res.status_code == 200:
        market_players = market_res.json().get("it") or []

    # Kader
    my_players = []
    lineup_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/lineup", headers=headers)
    if lineup_res.status_code == 200:
        l_data = lineup_res.json()
        my_players = (l_data.get("p") or []) + (l_data.get("b") or [])

    if not my_players:
        squad_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/squad", headers=headers)
        if squad_res.status_code == 200:
            my_players = squad_res.json().get("it") or squad_res.json().get("p") or []

    return market_players, my_players

def process_player(p):
    pid = p.get("i")
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

    image_url = f"https://kickbase.cdn.ity.io/players/{pid}/image" if pid else None

    return {
        "ID": pid,
        "Spieler": full_name,
        "Pos": POS_MAP.get(p.get("pos", 0), "-"),
        "Aktueller MW": mv,
        "Prognose (24h)": pred_24h,
        "Prognose (7T)": pred_7d,
        "Gewinn / Verlust (7T)": diff_7d,
        "Tagesveränderung": daily_change,
        "Image": image_url
    }

def process_player_list(players):
    if not players:
        return pd.DataFrame()

    data = []
    seen_ids = set()

    for p in players:
        p_data = process_player(p)
        if p_data["ID"] and p_data["ID"] not in seen_ids:
            seen_ids.add(p_data["ID"])
            data.append(p_data)

    return pd.DataFrame(data)

def render_advanced_chart(player_dict):
    mv = player_dict["Aktueller MW"]
    daily_change = player_dict["Tagesveränderung"]

    # Generiere Punkte für die letzten 7 Tage, Heute, und die nächsten 7 Tage
    past_days = [f"-{i}T" for i in range(7, 0, -1)]
    future_days = [f"+{i}T" for i in range(1, 8)]
    
    past_values = [mv - (daily_change * i) for i in range(7, 0, -1)]
    future_values = [mv + (daily_change * i) for i in range(1, 8)]

    fig = go.Figure()

    # Historischer Verlauf + Heute
    fig.add_trace(go.Scatter(
        x=past_days + ["Heute"],
        y=past_values + [mv],
        mode='lines+markers',
        name='Vergangenheit',
        line=dict(color='#00CC96', width=3)
    ))

    # Prognose (24h bis 7 Tage)
    fig.add_trace(go.Scatter(
        x=["Heute"] + future_days,
        y=[mv] + future_values,
        mode='lines+markers',
        name='Prognose (7 Tage)',
        line=dict(color='#AB63FA', width=3, dash='dash')
    ))

    fig.update_layout(
        title=f"Marktwertverlauf & Prognose für {player_dict['Spieler']}",
        xaxis_title="Zeitraum",
        yaxis_title="Marktwert (€)",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=40, b=20),
        height=380
    )

    st.plotly_chart(fig, use_container_width=True)

def style_zebra(df):
    def zebra_bg(row):
        bg = 'background-color: #1e2530;' if row.name % 2 == 0 else 'background-color: #12171e;'
        return [bg] * len(row)
    return df.style.apply(zebra_bg, axis=1)

# Hauptlogik
session, headers, league_id = get_kickbase_session()

if session:
    market_raw, my_raw = load_league_data()
    df_market = process_player_list(market_raw)
    df_my = process_player_list(my_raw)

    st.subheader("🔍 Echte Kickbase-Spielersuche")
    
    # Freitextsuche ohne Voreinstellung
    search_query = st.text_input("Gibe hier den Spielernamen ein:", placeholder="Tippe z. B. Kane, Musiala, Wirtz...")

    selected_player_dict = None

    if search_query.strip():
        search_results = search_kickbase_api(session, headers, league_id, search_query.strip())
        
        if search_results:
            options_map = {}
            for p in search_results:
                p_processed = process_player(p)
                label = f"{p_processed['Spieler']} ({p_processed['Pos']} - {p_processed['Aktueller MW']:,.0f} €)".replace(",", ".")
                options_map[label] = p_processed

            chosen_label = st.selectbox("Gefundene Spieler (wähle einen aus):", options=list(options_map.keys()))
            if chosen_label:
                selected_player_dict = options_map[chosen_label]
        else:
            st.warning(f"Kein Spieler mit '{search_query}' in der gesamten Kickbase-Datenbank gefunden.")

    # Profilansicht anzeigen, wenn ein Spieler ausgewählt wurde
    if selected_player_dict:
        st.markdown("---")
        col_img, col_info = st.columns([1, 4])
        
        with col_img:
            if selected_player_dict["Image"]:
                st.image(selected_player_dict["Image"], width=130)
        
        with col_info:
            st.markdown(f"### {selected_player_dict['Spieler']} (`{selected_player_dict['Pos']}`)")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Aktueller MW", f"{selected_player_dict['Aktueller MW']:,.0f} €".replace(",", "."))
            c2.metric("Tagesveränderung", f"{selected_player_dict['Tagesveränderung']:+,.0f} €".replace(",", "."))
            c3.metric("Prognose (24h)", f"{selected_player_dict['Prognose (24h)']:,.0f} €".replace(",", "."))
            c4.metric("Gewinn / Verlust (7T)", f"{selected_player_dict['Gewinn / Verlust (7T)']:+,.0f} €".replace(",", "."))

        # Interaktiver Plotly-Graph
        render_advanced_chart(selected_player_dict)
        st.markdown("---")

    # Tabs für Markt & Kader
    tab1, tab2 = st.tabs(["🛒 Transfermarkt", "🛡️ Mein Kader"])

    with tab1:
        if not df_market.empty:
            display_df = df_market.drop(columns=["ID", "Tagesveränderung", "Image"]).copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                display_df[col] = display_df[col].map("{:,.0f} €".format).str.replace(",", ".")
            st.dataframe(style_zebra(display_df), use_container_width=True)
        else:
            st.info("Keine Spieler auf dem Transfermarkt.")

    with tab2:
        if not df_my.empty:
            display_my = df_my.drop(columns=["ID", "Tagesveränderung", "Image"]).copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                display_my[col] = display_my[col].map("{:,.0f} €".format).str.replace(",", ".")
            st.dataframe(style_zebra(display_my), use_container_width=True)
        else:
            st.info("Keine Spieler im Kader gefunden.")
