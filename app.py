import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="Kickbase Analyst Pro", layout="wide", page_icon="⚽")

# Sauberes Kicker-Theme
st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #E0E6ED; }
    .badge-tw { background-color: #D97706; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-abw { background-color: #2563EB; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-mf { background-color: #10B981; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-st { background-color: #EF4444; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
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
        "Prognose (72h)": mv + (daily_change * 3),
        "Prognose (7T)": mv + (daily_change * 7),
        "Gewinn / Verlust (7T)": daily_change * 7,
        "Tagesveränderung": daily_change,
        "Image": f"https://kickbase.cdn.ity.io/players/{pid}/image" if pid else None,
        "Total Points": p.get("tP", 0),
        "Average Points": p.get("aP", 0)
    }

@st.cache_data(ttl=900)
def load_league_data():
    session, headers, league_id = get_kickbase_session()
    if not session:
        return [], []

    # Transfermarkt
    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    market_players = market_res.json().get("it", []) if market_res.status_code == 200 else []

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

    return [process_player(p) for p in market_players], [process_player(p) for p in my_players]

def search_global(session, headers, league_id, query):
    if not query or len(query.strip()) < 2:
        return []
    res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/players?q={query.strip()}", headers=headers)
    if res.status_code == 200:
        raw = res.json().get("it") or res.json().get("p") or []
        return [process_player(p) for p in raw]
    return []

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
        st.markdown(f"## {p_dict['Spieler']} {badge_html}", unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Aktueller MW", f"{p_dict['Aktueller MW']:,.0f} €".replace(",", "."))
        m2.metric("Prognose (24h)", f"{p_dict['Prognose (24h)']:,.0f} €".replace(",", "."))
        m3.metric("Prognose (72h)", f"{p_dict['Prognose (72h)']:,.0f} €".replace(",", "."))
        m4.metric("Prognose (7T)", f"{p_dict['Prognose (7T)']:,.0f} €".replace(",", "."))

    p_tab1, p_tab2, p_tab3 = st.tabs(["📊 Kicker-Stats & Leistungsdaten", "📈 MW-Historie (7T)", "🔮 Trend-Graph (24h / 72h / 7T)"])

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
        x_prog = ["Heute", "+24h", "+72h", "+7T"]
        y_prog = [mv, mv + dc, mv + (dc * 3), mv + (dc * 7)]
        st.line_chart(pd.DataFrame({"Prognose (€)": y_prog}, index=x_prog), height=280)

# App Start
st.title("⚽ Kickbase Analyst Pro")

session, headers, league_id = get_kickbase_session()

if session:
    market_players, my_players = load_league_data()
    
    # Suchleiste
    search_query = st.text_input("🔍 Spielersuche (Gesamte Bundesliga):", placeholder="z. B. Kane, Musiala, Zentner...")
    selected_player = None

    if search_query.strip():
        search_results = search_global(session, headers, league_id, search_query.strip())
        if search_results:
            options = {f"{p['Spieler']} ({p['Pos']} | {p['Aktueller MW']:,.0f} €)".replace(",", "."): p for p in search_results}
            chosen = st.selectbox("Gefundene Spieler auswählen:", options=list(options.keys()))
            if chosen:
                selected_player = options[chosen]
        else:
            st.warning(f"Kein Spieler mit '{search_query}' gefunden.")

    # Haupt-Tabs
    tab_m, tab_k = st.tabs(["🛒 Transfermarkt", "🛡️ Mein Kader"])

    with tab_m:
        if market_players:
            df_m = pd.DataFrame(market_players)
            disp_m = df_m[["Spieler", "Pos", "Aktueller MW", "Prognose (24h)", "Prognose (72h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]].copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (72h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                disp_m[col] = disp_m[col].map("{:,.0f} €".format).str.replace(",", ".")
            
            st.caption("Wähle eine Zeile aus, um das Kicker-Profil anzuzeigen:")
            event_m = st.dataframe(disp_m, use_container_width=True, on_select="rerun", selection_mode="single-row")
            rows_m = event_m.get("selection", {}).get("rows", [])
            if rows_m:
                selected_player = market_players[rows_m[0]]
        else:
            st.info("Keine Spieler auf dem Transfermarkt.")

    with tab_k:
        if my_players:
            df_k = pd.DataFrame(my_players)
            disp_k = df_k[["Spieler", "Pos", "Aktueller MW", "Prognose (24h)", "Prognose (72h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]].copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (72h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                disp_k[col] = disp_k[col].map("{:,.0f} €".format).str.replace(",", ".")
            
            st.caption("Wähle eine Zeile aus, um das Kicker-Profil anzuzeigen:")
            event_k = st.dataframe(disp_k, use_container_width=True, on_select="rerun", selection_mode="single-row")
            rows_k = event_k.get("selection", {}).get("rows", [])
            if rows_k:
                selected_player = my_players[rows_k[0]]
        else:
            st.info("Keine Spieler im Kader gefunden.")

    # Profil anzeigen
    if selected_player:
        render_kicker_profile(selected_player, session, headers, league_id)
