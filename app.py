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
        return None, None, None, None, None

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
        return None, None, None, None, None

    token = res.json().get("tkn")
    headers["Authorization"] = f"Bearer {token}"

    # 1. Liga-ID abrufen
    leagues_res = session.get("https://api.kickbase.com/v4/leagues", headers=headers)
    if leagues_res.status_code != 200:
        st.error("Fehler beim Laden der Ligen.")
        return None, None, None, None, None

    leagues = leagues_res.json().get("lins") or []
    if not leagues:
        st.error("Keine Liga gefunden.")
        return None, None, None, None, None

    league_id = leagues[0].get("i")

    # 2. Transfermarkt laden
    market_players = []
    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    if market_res.status_code == 200:
        market_players = market_res.json().get("it") or []

    # 3. Eigenen Kader laden
    my_players = []
    lineup_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/lineup", headers=headers)
    if lineup_res.status_code == 200:
        l_data = lineup_res.json()
        my_players = (l_data.get("p") or []) + (l_data.get("b") or [])

    return market_players, my_players, session, headers, league_id

def search_kickbase_global(session, headers, league_id, query):
    if not query or len(query) < 2:
        return []
    
    # 1. Versuche ligaweite / globale Spielersuche
    search_url = f"https://api.kickbase.com/v4/leagues/{league_id}/players?q={query}"
    res = session.get(search_url, headers=headers)
    if res.status_code == 200:
        players = res.json().get("it") or res.json().get("p") or []
        if players:
            return players

    # 2. Fallback auf Wettbewerbs-Suchpfad
    search_url_alt = f"https://api.kickbase.com/v4/competitions/1/players?q={query}"
    res_alt = session.get(search_url_alt, headers=headers)
    if res_alt.status_code == 200:
        return res_alt.json().get("it") or res_alt.json().get("p") or []

    return []

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

def style_zebra(df):
    def zebra_bg(row):
        bg = 'background-color: #1e2530;' if row.name % 2 == 0 else 'background-color: #12171e;'
        return [bg] * len(row)
    return df.style.apply(zebra_bg, axis=1)

market_raw, my_raw, session, headers, league_id = load_kickbase_data()

if market_raw is not None:
    df_market = process_player_list(market_raw)
    df_my = process_player_list(my_raw)

    st.subheader("🔍 Spielersuche & Detail-Analyse")
    
    # Leeres Textfeld ohne Vorausfüllung
    search_query = st.text_input("Spielernamen eingeben:", placeholder="z. B. Kane, Musiala, Tah...")

    selected_player = None

    if search_query.strip():
        # Live-Abfrage der Kickbase API für den eingegebenen Namen
        raw_search_results = search_kickbase_global(session, headers, league_id, search_query.strip())
        df_search = process_player_list(raw_search_results)

        if not df_search.empty:
            if len(df_search) == 1:
                selected_player = df_search.iloc[0]
            else:
                chosen_name = st.selectbox("Treffer auswählen:", options=df_search["Spieler"].tolist())
                selected_player = df_search[df_search["Spieler"] == chosen_name].iloc[0]
        else:
            st.warning(f"Kein Spieler mit '{search_query}' in Kickbase gefunden.")
    else:
        # Wenn Suchfeld leer ist, zeige Schnellauswahl aus Markt + Kader
        all_local = pd.concat([df_market, df_my]).drop_duplicates(subset=['ID'])
        if not all_local.empty:
            chosen_local = st.selectbox("Oder aus Markt/Kader wählen:", options=[""] + sorted(all_local["Spieler"].tolist()))
            if chosen_local:
                selected_player = all_local[all_local["Spieler"] == chosen_local].iloc[0]

    if selected_player is not None:
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
            st.dataframe(style_zebra(display_df), use_container_width=True)
        else:
            st.info("Keine Spieler auf dem Transfermarkt.")

    with tab2:
        if not df_my.empty:
            display_my = df_my.drop(columns=["ID", "Tagesveränderung"]).copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                display_my[col] = display_my[col].map("{:,.0f} €".format).str.replace(",", ".")
            st.dataframe(style_zebra(display_my), use_container_width=True)
        else:
            st.info("Keine Spieler im Kader gefunden.")
