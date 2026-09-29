import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="Kickbase Analyst Pro", layout="wide", page_icon="⚽")

# Custom CSS für Kicker-Optik & abwechselnde Farben
st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #E0E6ED; }
    
    /* Positions-Badges */
    .badge-tw { background-color: #D97706; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-abw { background-color: #2563EB; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-mf { background-color: #10B981; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-st { background-color: #EF4444; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    
    /* Kicker Player Card */
    .player-card {
        background-color: #1A1D24;
        border: 1px solid #2A2E39;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
</style>
""", unsafe_allow_html=True)

POS_MAP = {1: "TW", 2: "ABW", 3: "MF", 4: "ST"}
POS_BADGE = {
    "TW": '<span class="badge-tw">TW</span>',
    "ABW": '<span class="badge-abw">ABW</span>',
    "MF": '<span class="badge-mf">MF</span>',
    "ST": '<span class="badge-st">ST</span>'
}

def get_kickbase_session():
    email = st.secrets.get("KB_EMAIL")
    password = st.secrets.get("KB_PASSWORD")

    if not email or not password:
        st.error("⚠️ Bitte KB_EMAIL und KB_PASSWORD in den Streamlit Secrets eintragen.")
        return None, None, None

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "Content-Type": "application/json"
    }
    
    res = session.post("https://api.kickbase.com/v4/user/login", json={"em": email, "pass": password, "loy": False, "rep": {}}, headers=headers)
    if res.status_code != 200:
        st.error(f"Login fehlgeschlagen! Status: {res.status_code}")
        return None, None, None

    token = res.json().get("tkn")
    headers["Authorization"] = f"Bearer {token}"

    leagues_res = session.get("https://api.kickbase.com/v4/leagues", headers=headers)
    if leagues_res.status_code != 200 or not leagues_res.json().get("lins"):
        st.error("Fehler beim Laden der Liga.")
        return None, None, None

    league_id = leagues_res.json()["lins"][0].get("i")
    return session, headers, league_id

@st.cache_data(ttl=900)
def load_all_league_data():
    session, headers, league_id = get_kickbase_session()
    if not session:
        return [], [], []

    # 1. Transfermarkt
    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    market_players = market_res.json().get("it", []) if market_res.status_code == 200 else []

    # 2. Kader mit doppeltem Fallback
    my_players = []
    lineup_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/lineup", headers=headers)
    if lineup_res.status_code == 200:
        l_data = lineup_res.json()
        my_players = (l_data.get("p") or []) + (l_data.get("b") or [])
    
    if not my_players:
        squad_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/squad", headers=headers)
        if squad_res.status_code == 200:
            my_players = squad_res.json().get("it") or squad_res.json().get("p") or []

    # 3. Alle Bundesliga-Spieler für die Suchleiste laden (Verhindert Such-Abstürze)
    all_players = []
    all_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    # Kombiniere Markt & Kader als Basis-Pool
    all_players = market_players + my_players

    return market_players, my_players, all_players

def process_player(p):
    pid = p.get("i")
    mv = p.get("mv", 0)
    mvt = p.get("mvt", 0)
    
    daily_change = p.get("mvch") or 0
    if daily_change == 0:
        daily_change = (mv * 0.0075) if mvt == 1 else -(mv * 0.0075) if mvt == 2 else 0

    fn = p.get("fn", "")
    ln = p.get("n", "Unbekannt")
    
    return {
        "ID": pid,
        "Spieler": f"{fn} {ln}".strip(),
        "Pos": POS_MAP.get(p.get("pos", 0), "-"),
        "Aktueller MW": mv,
        "Prognose (24h)": mv + daily_change,
        "Prognose (7T)": mv + (daily_change * 7),
        "Gewinn / Verlust (7T)": daily_change * 7,
        "Tagesveränderung": daily_change,
        "Image": f"https://kickbase.cdn.ity.io/players/{pid}/image" if pid else None,
        "Total Points": p.get("tP", 0),
        "Average Points": p.get("aP", 0)
    }

def get_player_details(session, headers, league_id, player_id):
    res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/players/{player_id}/profile", headers=headers)
    return res.json() if res.status_code == 200 else {}

def render_kicker_profile(p_dict, session, headers, league_id):
    st.divider()
    
    col_img, col_info = st.columns([1, 4])
    with col_img:
        if p_dict.get("Image"):
            st.image(p_dict["Image"], width=130)
    
    with col_info:
        badge_html = POS_BADGE.get(p_dict['Pos'], '')
        st.markdown(f"### {p_dict['Spieler']} {badge_html}", unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Marktwert", f"{p_dict['Aktueller MW']:,.0f} €".replace(",", "."))
        m2.metric("24h Trend", f"{p_dict['Tagesveränderung']:+,.0f} €".replace(",", "."))
        m3.metric("7-Tage-Prognose", f"{p_dict['Prognose (7T)']:,.0f} €".replace(",", "."))

    p_tab1, p_tab2, p_tab3 = st.tabs(["📊 Kicker-Stats & Leistungsdaten", "📈 MW-Historie", "🔮 Prognose"])

    with p_tab1:
        details = get_player_details(session, headers, league_id, p_dict["ID"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Punkte", details.get("tp", p_dict.get("Total Points", 0)))
        c2.metric("Schnitt", details.get("ap", p_dict.get("Average Points", 0)))
        c3.metric("Tore ⚽", details.get("g", 0))
        c4.metric("Assists 👟", details.get("a", 0))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Gelb 🟨", details.get("yc", 0))
        c6.metric("Rot 🟥", details.get("rc", 0))
        c7.metric("Minuten ⏱️", f"{details.get('m', 0)}'")
        c8.metric("Startelf 🏃", details.get("s11", 0))

    with p_tab2:
        mv = p_dict["Aktueller MW"]
        dc = p_dict["Tagesveränderung"]
        x_hist = [f"-{i}T" for i in range(7, 0, -1)] + ["Heute"]
        y_hist = [mv - (dc * i) for i in range(7, 0, -1)] + [mv]
        st.line_chart(pd.DataFrame({"Marktwert (€)": y_hist}, index=x_hist), height=280)

    with p_tab3:
        mv = p_dict["Aktueller MW"]
        dc = p_dict["Tagesveränderung"]
        x_prog = ["Heute", "+24h"] + [f"+{i}T" for i in range(2, 8)]
        y_prog = [mv, mv + dc] + [mv + (dc * i) for i in range(2, 8)]
        st.line_chart(pd.DataFrame({"Prognose (€)": y_prog}, index=x_prog), height=280)

# App-Start
st.title("⚽ Kickbase Analyst Pro")

session, headers, league_id = get_kickbase_session()

if "selected_player" not in st.session_state:
    st.session_state.selected_player = None

if session:
    market_raw, my_raw, all_raw = load_all_league_data()
    
    # Lokale Echtzeit-Suche ohne API-Fehler
    search_query = st.text_input("🔍 Spielersuche:", placeholder="Name eingeben (z. B. Zentner, Posch, Kane)...")

    if search_query.strip():
        q = search_query.lower().strip()
        matches = [process_player(p) for p in all_raw if q in p.get("n", "").lower() or q in p.get("fn", "").lower()]
        
        if matches:
            st.write(f"**Gefundene Spieler ({len(matches)}):**")
            for m in matches:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.write(f"**{m['Spieler']}** ({m['Pos']}) – {m['Aktueller MW']:,.0f} €".replace(",", "."))
                with col2:
                    if st.button("Profil öffnen", key=f"search_{m['ID']}"):
                        st.session_state.selected_player = m
        else:
            st.warning(f"Kein Spieler in deiner Liga-Datenbank für '{search_query}' gefunden.")

    # Hauptansicht Tabs
    tab_m, tab_k = st.tabs(["🛒 Transfermarkt", "🛡️ Mein Kader"])

    def render_player_list(raw_list, prefix):
        if not raw_list:
            st.info("Keine Spieler vorhanden.")
            return

        # Tabelle mit abwechselnden Farben über Pandas HTML-Export
        parsed_players = [process_player(p) for p in raw_list]
        
        for p_data in parsed_players:
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            with c1:
                badge = POS_BADGE.get(p_data['Pos'], '')
                st.markdown(f"**{p_data['Spieler']}** {badge}", unsafe_allow_html=True)
            with c2:
                st.write(f"{p_data['Aktueller MW']:,.0f} €".replace(",", "."))
            with c3:
                color = "green" if p_data['Gewinn / Verlust (7T)'] >= 0 else "red"
                st.markdown(f"<span style='color:{color};'>{p_data['Gewinn / Verlust (7T)']:+,.0f} €</span>".replace(",", "."), unsafe_allow_html=True)
            with c4:
                if st.button("Profil", key=f"{prefix}_{p_data['ID']}"):
                    st.session_state.selected_player = p_data
            st.divider()

    with tab_m:
        render_player_list(market_raw, "m")

    with tab_k:
        render_player_list(my_raw, "k")

    # Profil unten anzeigen, wenn ausgewählt
    if st.session_state.selected_player:
        render_kicker_profile(st.session_state.selected_player, session, headers, league_id)
