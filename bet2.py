import streamlit as st
import requests
import pandas as pd
import datetime
import time

# --- 1. KONFIGURACJA I STYL (APPLE-LIKE) ---
st.set_page_config(
    page_title="BetSignal Pro",
    page_icon="⚽",
    layout="centered",
    initial_sidebar_state="expanded"
)

# Wymuszamy jasny motyw i czysty styl
st.markdown("""
    <style>
    /* Reset tła */
    [data-testid="stAppViewContainer"] { background-color: #f5f5f7; }
    [data-testid="stSidebar"] { background-color: #ffffff; }
    [data-testid="stHeader"] { background-color: rgba(0,0,0,0); }
    
    /* Karty meczowe */
    .signal-card {
        background-color: #ffffff;
        padding: 24px;
        border-radius: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.04);
        margin-bottom: 24px;
        border: 1px solid #e5e5ea;
        color: #1d1d1f;
    }
    
    /* Typografia */
    h1, h2, h3, p, span, div, li {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        color: #1d1d1f;
    }
    
    .metric-label {
        font-size: 11px;
        color: #86868b !important;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        font-weight: 600;
        margin-top: 4px;
        display: block;
    }
    
    .team-name {
        font-size: 18px;
        font-weight: 700;
        margin: 0;
        line-height: 1.2;
    }
    
    /* Badges */
    .badge {
        padding: 6px 12px;
        border-radius: 100px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: white !important;
    }
    .bg-green { background-color: #34c759; }
    .bg-yellow { background-color: #ff9f0a; }
    .bg-blue { background-color: #007aff; }
    
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNKCJE POMOCNICZE ---
def clean_html(html_str):
    """Usuwa znaki nowej linii, aby Markdown nie psuł renderowania HTML."""
    return html_str.replace("\n", "").replace("    ", " ")

# --- 3. SILNIK ANALITYCZNY ---
LEAGUES = {
    'Premier League (ANG)': 'PL',
    'La Liga (HIS)': 'PD',
    'Bundesliga (NIEM)': 'BL1',
    'Serie A (WŁO)': 'SA',
    'Ligue 1 (FRA)': 'FL1'
}

class BettingSignalEngine:
    def __init__(self, api_key: str):
        self.headers = {'X-Auth-Token': api_key}
        self.base_url = "http://api.football-data.org/v4"
        self.request_timestamps = []

    def _rate_limit(self):
        """Ochrona przed limitem 10 zapytań/minutę."""
        now = time.time()
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 60]
        if len(self.request_timestamps) >= 9: # Zapas bezpieczeństwa
            sleep_time = 61 - (now - self.request_timestamps[0])
            if sleep_time > 0:
                with st.spinner(f"⏳ Oczekiwanie na API (Limit darmowy)... {int(sleep_time)}s"):
                    time.sleep(sleep_time)
                self.request_timestamps = []
        self.request_timestamps.append(time.time())

    def _fetch(self, endpoint: str):
        self._rate_limit()
        try:
            response = requests.get(f"{self.base_url}/{endpoint}", headers=self.headers)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                st.toast("⚠️ Przekroczono limit API. Czekam...")
                time.sleep(10) # Krótka pauza i ponowienie
                return self._fetch(endpoint)
            return None
        except:
            return None

    def get_standings(self, league_code):
        data = self._fetch(f"competitions/{league_code}/standings")
        if not data: return pd.DataFrame()
        
        teams = {}
        for table in data.get('standings', []):
            if table['type'] == 'TOTAL':
                for row in table['table']:
                    t_name = row['team']['name']
                    form_str = row.get('form', '') # np. "W,L,W,D,L"
                    if form_str: form_str = form_str.replace(',', '')
                    
                    teams[t_name] = {
                        'rank': row['position'],
                        'points': row['points'],
                        'played': row['playedGames'],
                        'form': form_str, # String np "WLWDL"
                        'goal_diff': row['goalDifference']
                    }
        return pd.DataFrame.from_dict(teams, orient='index')

    def get_matches(self, league_code):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        future = (datetime.datetime.now() + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
        data = self._fetch(f"competitions/{league_code}/matches?dateFrom={today}&dateTo={future}")
        return data.get('matches', []) if data else []

    def calculate_form_points(self, form_str):
        """Zamienia string formy (np. 'WWDL') na punkty (max 15)."""
        if not form_str: return 0
        points = 0
        for char in form_str[-5:]: # Ostatnie 5 meczy
            if char == 'W': points += 3
            elif char == 'D': points += 1
        return points

    def analyze_match_strength(self, match, standings, league_name):
        home = match['homeTeam']['name']
        away = match['awayTeam']['name']
        
        if home not in standings.index or away not in standings.index: return None
        
        h_stats = standings.loc[home]
        a_stats = standings.loc[away]
        
        # --- NOWY ALGORYTM PUNKTACJI (0-100) ---
        score = 50 # Baza (mecz wyrównany)
        reasons = []
        
        # 1. Różnica w tabeli (Im większa różnica rankingu na korzyść gospodarza, tym lepiej)
        rank_diff = a_stats['rank'] - h_stats['rank'] # Np. Away(18) - Home(2) = +16 (Dobrze dla Home)
        score += (rank_diff * 1.5)
        
        if rank_diff > 10: reasons.append(f"📈 **Przepaść w tabeli:** {home} jest o {rank_diff} miejsc wyżej.")
        if rank_diff < -10: reasons.append(f"📉 **Przepaść w tabeli:** {away} jest o {abs(rank_diff)} miejsc wyżej.")

        # 2. Różnica punktowa (Siła ogólna)
        pts_diff = h_stats['points'] - a_stats['points']
        score += (pts_diff * 0.5)

        # 3. Aktualna forma (Ostatnie 5 meczy)
        h_form_pts = self.calculate_form_points(h_stats['form'])
        a_form_pts = self.calculate_form_points(a_stats['form'])
        form_diff = h_form_pts - a_form_pts # Max różnica to +/- 15
        
        score += (form_diff * 2.0)
        
        if h_form_pts >= 12: reasons.append(f"🔥 **Super forma:** {home} (Ostatnie 5: {h_stats['form']})")
        if a_form_pts <= 2: reasons.append(f"❄️ **Kryzys:** {away} (Ostatnie 5: {a_stats['form']})")
        
        # 4. Atut własnego boiska (stały bonus)
        score += 5 

        # Normalizacja do zakresu 0-100
        final_score = max(min(int(score), 99), 1)
        
        # Ustalenie typu sygnału
        if final_score > 60:
            type_label = "HOME WIN"
            color = "green"
        elif final_score < 40:
            type_label = "AWAY WIN" 
            final_score = 100 - final_score # Odwracamy skalę dla gości, żeby pokazać "siłę zakładu"
            color = "blue"
        else:
            type_label = "REMIS / RYZYKO"
            color = "yellow"

        # Dodatkowa analiza dla użytkownika
        return {
            "date": match['utcDate'][:10],
            "time": match['utcDate'][11:16],
            "league": league_name,
            "home": home,
            "away": away,
            "score": final_score,
            "raw_score": score, # Do debugowania
            "type": type_label,
            "color": color,
            "reasons": reasons[:3] # Max 3 powody
        }

# --- 4. INTERFEJS UŻYTKOWNIKA ---

with st.sidebar:
    st.header("⚙️ Ustawienia")
    api_key = st.text_input("Klucz API", type="password", help="Football-Data.org")
    st.divider()
    selected_leagues = st.multiselect("Wybierz ligi", list(LEAGUES.keys()), default=list(LEAGUES.keys())[:3])
    run_btn = st.button("🚀 Pokaż najlepsze typy", type="primary", use_container_width=True)

st.title("BetSignal Pro v2")
st.markdown("### Algorytm Rankingowy")
st.info("💡 System teraz ocenia KAŻDY mecz i pokazuje ranking spotkań z największą przewagą statystyczną.")

if run_btn:
    if not api_key:
        st.error("Wprowadź klucz API w pasku bocznym.")
    else:
        engine = BettingSignalEngine(api_key)
        all_matches_ranked = []
        
        # Pasek postępu
        prog_bar = st.progress(0)
        status_text = st.empty()
        
        for i, (l_name, l_code) in enumerate(LEAGUES.items()):
            if l_name in selected_leagues:
                status_text.text(f"Analizuję: {l_name}...")
                prog_bar.progress((i + 1) / len(LEAGUES))
                
                standings = engine.get_standings(l_code)
                matches = engine.get_matches(l_code)
                
                for m in matches:
                    if m['status'] == 'TIMED' or m['status'] == 'SCHEDULED':
                        res = engine.analyze_match_strength(m, standings, l_name)
                        if res: all_matches_ranked.append(res)
        
        prog_bar.empty()
        status_text.empty()
        
        # SORTOWANIE: Najlepsze zakłady (najwyższe Score) na górze
        all_matches_ranked.sort(key=lambda x: x['score'], reverse=True)
        
        # Wyświetlamy TOP 10 lub wszystkie jeśli mniej
        top_picks = all_matches_ranked
        
        if not top_picks:
            st.warning("Brak nadchodzących meczów w wybranych ligach (lub przerwa w rozgrywkach).")
        else:
            st.success(f"Przeanalizowano mecze. Oto ranking najlepszych okazji:")
            
            for match in top_picks:
                # Kolory i badge
                if match['color'] == 'green': 
                    badge_class = 'bg-green'
                    bar_color = '#34c759'
                elif match['color'] == 'blue': 
                    badge_class = 'bg-blue'
                    bar_color = '#007aff'
                else: 
                    badge_class = 'bg-yellow'
                    bar_color = '#ff9f0a'

                reasons_html = "".join([f'<li style="margin-bottom:4px; font-size:13px; color:#424245;">{r}</li>' for r in match['reasons']])
                
                # Budujemy HTML w jednej linii (dla pewności)
                html_content = f"""
                <div class="signal-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <span class="metric-label">📅 {match['date']} {match['time']} • {match['league']}</span>
                        <span class="badge {badge_class}">{match['type']}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div style="width:40%; text-align:left;">
                            <p class="team-name">{match['home']}</p>
                            <span class="metric-label">Gospodarz</span>
                        </div>
                        <div style="font-weight:bold; color:#d1d1d6; font-size:18px;">VS</div>
                        <div style="width:40%; text-align:right;">
                            <p class="team-name">{match['away']}</p>
                            <span class="metric-label">Gość</span>
                        </div>
                    </div>
                    <div style="margin-top:20px;">
                        <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                            <span class="metric-label">SIŁA SYGNAŁU</span>
                            <span style="font-weight:700; color:{bar_color};">{match['score']}%</span>
                        </div>
                        <div style="width:100%; background-color:#f0f0f5; height:8px; border-radius:4px; overflow:hidden;">
                            <div style="width:{match['score']}%; background-color:{bar_color}; height:100%; border-radius:4px;"></div>
                        </div>
                    </div>
                    <div style="margin-top:15px; background-color:#f9f9fb; padding:12px; border-radius:12px;">
                        <ul style="margin:0; padding-left:20px;">
                            {reasons_html}
                        </ul>
                    </div>
                </div>
                """
                
                # Renderowanie
                st.markdown(clean_html(html_content), unsafe_allow_html=True)

else:
    st.markdown("""
    <div style="text-align: center; margin-top: 50px; opacity: 0.6;">
        <h3 style="color:#1d1d1f">Czekam na start...</h3>
        <p>Wprowadź klucz API i kliknij przycisk, aby przeskanować rynek.</p>
    </div>
    """, unsafe_allow_html=True)
