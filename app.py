import streamlit as st
import pandas as pd
import requests

# Versuche Plotly zu importieren – falls nicht vorhanden, automatischer Fallback
PLOTLY_AVAILABLE = True
try:
    import plotly.graph_objects as go
except ImportError:
    PLOTLY_AVAILABLE = False

st.set_page_config(page_title="Kickbase Analyst Pro", layout="wide", page_icon="⚽")

# Custom CSS für Kicker-App Optik
st.markdown("""
<style>
    /* Haupt-Hintergrund & Schrift */
    .stApp {
        background-color: #0E1117;
        color: #E0E6ED;
    }
    
    /* Custom Card Style */
    .kicker-card {
        background-color: #1A1D24;
        border: 1px solid #2A2E39;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
    }
    
    /* Position Badges */
    .badge-tw { background-color: #D97706; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-abw { background-color: #2563EB; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-mf { background-color: #10B981; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-st { background-color: #EF4444; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    
    /* Metrik Container Styling */
    div[data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=unsafe_allow_html)

POS_MAP = {1: "TW", 2: "ABW", 3: "MF", 4: "ST"}
POS_BADGE = {
    "TW": '<span class="badge-tw">TW</span>',
    "ABW": '<span class="badge-abw">ABW</span>',
    "MF": '<span class="badge-mf">MF</span>',
    "ST": '<span class="badge-st">ST</span>',
    "-": '<span>-</span>'
}

def get_kickbase_session():
    email = st.secrets.get("KB_EMAIL")
    password = st.secrets.get("KB_PASSWORD")

    if not email or not password:
        st.error("⚠️ Bitte KB_EMAIL und KB_PASSWORD in den Streamlit Secrets eintragen.")
        return None, None, None

    session = requests.Session()
    login_url = "https://api.kickbase.com/v4/user/login"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "Content-Type": "application/json"
    }
    
    res = session.post(login_url, json={"em": email, "pass": password, "loy": False, "rep": {}}, headers=headers)
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

def search_kickbase_api(session, headers, league_id, query):
    if not query or len(query.strip()) < 2:
        return []
    res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/players?q={query.strip()}", headers=headers)
    if res.status_code == 200:
        return res.json().get("it") or res.json().get("p") or []
    return []

def get_player_details(session, headers, league_id, player_id):
    res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/players/{player_id}/profile", headers=headers)
    return res.json() if res.status_code == 200 else {}

@st.cache_data(ttl=900)
def load_league_data():
    session, headers, league_id = get_kickbase_session()
    if not session:
        return [], []

    market_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/market", headers=headers)
    market_players = market_res.json().get("it", []) if market_res.status_code == 200 else []

    lineup_res = session.get(f"https://api.kickbase.com/v4/leagues/{league_id}/lineup", headers=headers)
    my_players = []
    if lineup_res.status_code == 200:
        l_data = lineup_res.json()
        my_players = (l_data.get("p") or []) + (l_data.get("b") or [])

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

    return {
        "ID": pid,
        "Spieler": full_name,
        "Pos": POS_MAP.get(p.get("pos", 0), "-"),
        "Aktueller MW": mv,
        "Prognose (24h)": pred_24h,
        "Prognose (7T)": pred_7d,
        "Gewinn / Verlust (7T)": diff_7d,
        "Tagesveränderung": daily_change,
        "Image": f"https://kickbase.cdn.ity.io/players/{pid}/image" if pid else None,
        "Total Points": p.get("tP", 0),
        "Average Points": p.get("aP", 0)
    }

def process_player_list(players):
    if not players:
        return pd.DataFrame()
    data, seen = [], set()
    for p in players:
        p_data = process_player(p)
        if p_data["ID"] and p_data["ID"] not in seen:
            seen.add(p_data["ID"])
            data.append(p_data)
    return pd.DataFrame(data)

def render_chart(player_dict, chart_type="history"):
    mv = player_dict["Aktueller MW"]
    daily_change = player_dict["Tagesveränderung"]

    if chart_type == "history":
        x_vals = [f"-{i}T" for i in range(7, 0, -1)] + ["Heute"]
        y_vals = [mv - (daily_change * i) for i in range(7, 0, -1)] + [mv]
        color = "#10B981"
        title_text = "Historischer Marktwertverlauf (Letzte 7 Tage)"
    else: # prognosis
        x_vals = ["Heute", "+24h"] + [f"+{i}T" for i in range(2, 8)]
        y_vals = [mv, mv + daily_change] + [mv + (daily_change * i) for i in range(2, 8)]
        color = "#8B5CF6"
        title_text = "Marktwert-Prognose (Nächste 7 Tage)"

    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode='lines+markers',
            line=dict(color=color, width=3),
            marker=dict(size=6)
        ))
        fig.update_layout(
            title=title_text,
            template="plotly_dark",
            margin=dict(l=20, r=20, t=40, b=20),
            height=300,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        chart_df = pd.DataFrame({"Marktwert (€)": y_vals}, index=x_vals)
        st.line_chart(chart_df, height=300)

def render_kicker_profile(p_dict, session, headers, league_id):
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Hero Profile Header
    badge_html = POS_BADGE.get(p_dict['Pos'], '<span>-</span>')
    
    st.markdown(f"""
    <div class="kicker-card">
        <div style="display: flex; align-items: center; gap: 20px;">
            <img src="{p_dict['Image']}" style="width: 110px; height: 110px; border-radius: 50%; object-fit: cover; border: 3px solid #2A2E39;">
            <div>
                <div style="margin-bottom: 6px;">{badge_html}</div>
                <h1 style="margin: 0; font-size: 2rem; color: #FFF;">{p_dict['Spieler']}</h1>
                <p style="margin: 4px 0 0 0; color: #9CA3AF; font-size: 1.1rem;">Marktwert: <strong style="color: #FFF;">{p_dict['Aktueller MW']:,.0f} €</strong></p>
            </div>
        </div>
    </div>
    """.replace(",", "."), unsafe_allow_html=True)

    # Profile Navigation Tabs
    p_tab1, p_tab2, p_tab3 = st.tabs(["📊 Kicker-Stats & Leistungsdaten", "📈 Marktwert-Historie", "🔮 Prognose (24h / 7T)"])

    with p_tab1:
        details = get_player_details(session, headers, league_id, p_dict["ID"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Gesamtpunkte", details.get("tp", p_dict.get("Total Points", 0)))
        c2.metric("Punkte-Schnitt", details.get("ap", p_dict.get("Average Points", 0)))
        c3.metric("Tore ⚽", details.get("g", 0))
        c4.metric("Vorlagen 👟", details.get("a", 0))

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Gelbe Karten 🟨", details.get("yc", 0))
        c6.metric("Rote Karten 🟥", details.get("rc", 0))
        c7.metric("Einsatzminuten ⏱️", f"{details.get('m', 0)}'")
        c8.metric("Startelf 🏃", details.get("s11", 0))

    with p_tab2:
        m1, m2 = st.columns(2)
        m1.metric("Aktueller Marktwert", f"{p_dict['Aktueller MW']:,.0f} €".replace(",", "."))
        m2.metric("Tagesveränderung (24h)", f"{p_dict['Tagesveränderung']:+,.0f} €".replace(",", "."))
        render_chart(p_dict, chart_type="history")

    with p_tab3:
        p1, p2, p3 = st.columns(3)
        p1.metric("Prognose (24h)", f"{p_dict['Prognose (24h)']:,.0f} €".replace(",", "."))
        p2.metric("Prognose (7T)", f"{p_dict['Prognose (7T)']:,.0f} €".replace(",", "."))
        p3.metric("Erwarteter Gewinn/Verlust (7T)", f"{p_dict['Gewinn / Verlust (7T)']:+,.0f} €".replace(",", "."))
        render_chart(p_dict, chart_type="prognosis")

# Hauptlogik
st.title("⚽ Kickbase Analyst Pro")

session, headers, league_id = get_kickbase_session()

if session:
    market_raw, my_raw = load_league_data()
    df_market = process_player_list(market_raw)
    df_my = process_player_list(my_raw)

    # Suchleiste
    search_query = st.text_input("🔍 Spielersuche (Gesamte Bundesliga):", placeholder="z. B. Kane, Musiala, Wirtz...")

    selected_player_dict = None

    if search_query.strip():
        search_results = search_kickbase_api(session, headers, league_id, search_query.strip())
        if search_results:
            options_map = {}
            for p in search_results:
                p_processed = process_player(p)
                label = f"{p_processed['Spieler']} ({p_processed['Pos']} | {p_processed['Aktueller MW']:,.0f} €)".replace(",", ".")
                options_map[label] = p_processed

            chosen_label = st.selectbox("Gefundene Spieler (Auswählen):", options=list(options_map.keys()))
            if chosen_label:
                selected_player_dict = options_map[chosen_label]
        else:
            st.warning(f"Kein Spieler mit '{search_query}' gefunden.")

    # Haupt-Tabs
    tab_m, tab_k = st.tabs(["🛒 Transfermarkt", "🛡️ Mein Kader"])

    with tab_m:
        if not df_market.empty:
            disp = df_market[["Spieler", "Pos", "Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]].copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                disp[col] = disp[col].map("{:,.0f} €".format).str.replace(",", ".")
            
            st.caption("👇 Klicke auf eine Zeile, um das Kicker-Profil des Spielers zu öffnen:")
            event_m = st.dataframe(disp, use_container_width=True, on_select="rerun", selection_mode="single-row")
            
            rows = event_m.get("selection", {}).get("rows", [])
            if rows:
                selected_player_dict = df_market.iloc[rows[0]].to_dict()
        else:
            st.info("Derzeit keine Spieler auf dem Transfermarkt.")

    with tab_k:
        if not df_my.empty:
            disp_my = df_my[["Spieler", "Pos", "Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]].copy()
            for col in ["Aktueller MW", "Prognose (24h)", "Prognose (7T)", "Gewinn / Verlust (7T)"]:
                disp_my[col] = disp_my[col].map("{:,.0f} €".format).str.replace(",", ".")
            
            st.caption("👇 Klicke auf eine Zeile, um das Kicker-Profil des Spielers zu öffnen:")
            event_k = st.dataframe(disp_my, use_container_width=True, on_select="rerun", selection_mode="single-row")
            
            rows_k = event_k.get("selection", {}).get("rows", [])
            if rows_k:
                selected_player_dict = df_my.iloc[rows_k[0]].to_dict()
        else:
            st.info("Keine Spieler im Kader gefunden.")

    # Profilausgabe
    if selected_player_dict:
        render_kicker_profile(selected_player_dict, session, headers, league_id)
