import streamlit as st
import requests
import pandas as pd
import datetime
import time

# --- 1. KONFIGURACJA UI ---
st.set_page_config(page_title="BetSignal Pro", page_icon="⚽", layout="centered")

st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #f5f5f7; }
    [data-testid="stSidebar"] { background-color: #ffffff; }
    
    .signal-card {
        background-color: #ffffff;
        padding: 24px;
        border-radius: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.04);
        margin-bottom: 24px;
        border: 1px solid #e5e5ea;
        color: #1d1d1f;
    }
    
    .team-name { font-size: 18px; font-weight: 800; margin: 0; color: #1d1d1f; }
    .metric-label { font-size: 10px; color: #86868b; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; }
    .stat-box { background-color: #f5f5f7; padding: 8px; border-radius: 8px; text-align: center; width: 48%; }
    .stat-val { font-weight: 700; font-size: 14px; color: #1d1d1f; }
    
    .badge { padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: 700; color: white; }
    .bg-green { background-color: #34c759; }
    .bg-blue { background-color: #007aff; }
    .bg-yellow { background-color: #ff9f0a; }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNKCJE ---
def clean_html(html_str):
    return html_str.replace("\n", " ").strip()

LEAGUES = {
    'Premier League': 'PL',
    'La Liga': 'PD',
    'Bundesliga': 'BL1',
    'Serie A': 'SA',
    'Ligue 1': 'FL1'
}

class BettingSignalEngine:
    def __init__(self, api_key):
        self.headers = {'X-Auth-Token': api_key}
        self.base_url = "http://api.football-data.org/v4"
        self.timestamps = []

    def _rate_limit(self):
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= 9:
            time.sleep(6) # Prosty sleep dla bezpieczeństwa
            self.timestamps = []
        self.timestamps.append(time.time())

    def _fetch(self, endpoint):
        self._rate_limit()
        try:
            res = requests.get(f"{self.base_url}/{endpoint}", headers=self.headers)
            return res.json() if res.status_code == 200 else None
        except: return None

    def get_data(self, league_code):
        # Pobieramy tabelę
        standings_data = self._fetch(f"competitions/{league_code}/standings")
        if not standings_data: return pd.DataFrame(), []
        
        teams = {}
        # Parsowanie tabel: TOTAL, HOME, AWAY
        for table in standings_data.get('standings', []):
            t_type = table['type'] # 'TOTAL', 'HOME', 'AWAY'
            for row in table['table']:
                t_name = row['team']['name']
                if t_name not in teams: teams[t_name] = {}
                
                # Zapisujemy statystyki dla każdego kontekstu
                played = row['playedGames']
                points = row['points']
                goals_diff = row['goalDifference']
                
                # Obliczamy PPG (Points Per Game)
                ppg = round(points / played, 2) if played > 0 else 0.0
                
                teams[t_name][f'{t_type}_rank'] = row['position']
                teams[t_name][f'{t_type}_ppg'] = ppg
                teams[t_name][f'{t_type}_gd'] = goals_diff # Bilans bramek
        
        standings_df = pd.DataFrame.from_dict(teams, orient='index')
        
        # Pobieramy mecze
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        future = (datetime.datetime.now() + datetime.timedelta(days=6)).strftime("%Y-%m-%d")
        matches_data = self._fetch(f"competitions/{league_code}/matches?dateFrom={today}&dateTo={future}")
        matches = matches_data.get('matches', []) if matches_data else []
        
        return standings_df, matches

    def analyze(self, match, standings, league_name):
        home, away = match['homeTeam']['name'], match['awayTeam']['name']
        if home not in standings.index or away not in standings.index: return None
        
        h = standings.loc[home]
        a = standings.loc[away]
        
        reasons = []
        score = 50 # Startujemy od środka
        
        # 1. SIŁA DOM vs WYJAZD (Kluczowa zmiana zamiast Last 5)
        # Porównujemy jak Gospodarz gra u siebie vs jak Gość gra na wyjeździe
        h_ppg = h.get('HOME_ppg', h.get('TOTAL_ppg', 0)) # Fallback do total jeśli brak home
        a_ppg = a.get('AWAY_ppg', a.get('TOTAL_ppg', 0))
        
        diff_ppg = h_ppg - a_ppg
        # Max różnica to ok 3.0. Mnożymy x10, więc max +/- 30 pkt do score
        score += (diff_ppg * 10)
        
        if h_ppg > 2.0: reasons.append(f"🏰 **Twierdza:** {home} zdobywa śr. {h_ppg} pkt u siebie")
        if a_ppg < 0.8: reasons.append(f"🚌 **Słabe wyjazdy:** {away} zdobywa tylko {a_ppg} pkt na wyjeździe")
        
        # 2. RÓŻNICA W TABELI (TOTAL)
        rank_diff = a['TOTAL_rank'] - h['TOTAL_rank'] # Im wyższa liczba, tym lepiej dla Home
        score += rank_diff # np. 18 (spadkowicz) - 2 (lider) = +16 pkt
        
        if rank_diff > 10: reasons.append(f"📈 **Przepaść:** {home} jest o {rank_diff} miejsc wyżej")
        
        # 3. BILANS BRAMKOWY (Goal Difference)
        # Drużyny z wysokim dodatnim bilansem są silne ofensywnie/defensywnie
        gd_diff = h['TOTAL_gd'] - a['TOTAL_gd']
        score += (gd_diff * 0.5) # Lekka waga dla bramek

        # Ograniczenia wyniku 0-100
        final_score = max(min(int(score), 99), 1)
        
        # Koloryzacja
        if final_score >= 60: 
            typ, color = "HOME WIN", "bg-green"
            bar_c = "#34c759"
        elif final_score <= 40: 
            typ, color = "AWAY WIN", "bg-blue"
            final_score = 100 - final_score # Odwracamy dla wizualizacji siły
            bar_c = "#007aff"
        else: 
            typ, color = "RÓWNY MECZ", "bg-yellow"
            bar_c = "#ff9f0a"
            
        return {
            "date": match['utcDate'][:10],
            "home": home, "away": away,
            "league": league_name,
            "score": final_score,
            "type": typ, "badge": color, "bar": bar_c,
            "reasons": reasons,
            "h_ppg": h_ppg, "a_ppg": a_ppg
        }

# --- 3. UI LOGIKA ---
with st.sidebar:
    st.header("⚙️ Panel Sterowania")
    api_key = st.text_input("Klucz API", type="password")
    if not api_key: st.warning("Wymagany klucz API!")
    
    leagues_sel = st.multiselect("Ligi", list(LEAGUES.keys()), default=['Premier League', 'La Liga'])
    btn = st.button("Analizuj Mecze", type="primary", use_container_width=True)

st.title("BetSignal: PPG Edition")
st.caption("Algorytm oparty o średnią punktów (Home/Away) oraz różnicę bramek.")

if btn and api_key:
    engine = BettingSignalEngine(api_key)
    signals = []
    
    bar = st.progress(0)
    for i, lname in enumerate(leagues_sel):
        standings, matches = engine.get_data(LEAGUES[lname])
        if standings.empty: continue
        
        for m in matches:
            if m['status'] == 'TIMED' or m['status'] == 'SCHEDULED':
                res = engine.analyze(m, standings, lname)
                if res: signals.append(res)
        bar.progress((i+1)/len(leagues_sel))
    
    bar.empty()
    
    if signals:
        # Sortowanie po sile sygnału (score)
        signals.sort(key=lambda x: x['score'], reverse=True)
        
        for s in signals:
            # Generowanie HTML
            reasons_li = "".join([f"<li>{r}</li>" for r in s['reasons']])
            
            html = f"""
            <div class="signal-card">
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span class="metric-label">{s['date']} • {s['league']}</span>
                    <span class="badge {s['badge']}">{s['type']}</span>
                </div>
                
                <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:15px;">
                    <div style="width:45%;">
                        <div class="team-name">{s['home']}</div>
                        <div style="font-size:12px; color:#86868b;">Gospodarz</div>
                    </div>
                    <div style="font-weight:bold; color:#e5e5ea;">VS</div>
                    <div style="width:45%; text-align:right;">
                        <div class="team-name">{s['away']}</div>
                        <div style="font-size:12px; color:#86868b;">Gość</div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; margin-bottom:15px;">
                    <div class="stat-box">
                        <div class="stat-val">{s['h_ppg']}</div>
                        <div class="metric-label">PKT/MECZ (DOM)</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-val">{s['a_ppg']}</div>
                        <div class="metric-label">PKT/MECZ (WYJAZD)</div>
                    </div>
                </div>

                <div style="margin-bottom:5px;">
                    <div style="display:flex; justify-content:space-between;">
                        <span class="metric-label">SIŁA PROGNOZY</span>
                        <span style="font-weight:bold; font-size:12px; color:{s['bar']}">{s['score']}%</span>
                    </div>
                    <div style="background:#f0f0f5; height:6px; border-radius:3px; overflow:hidden;">
                        <div style="width:{s['score']}%; background:{s['bar']}; height:100%;"></div>
                    </div>
                </div>
                
                <ul style="margin-top:10px; padding-left:20px; font-size:13px; color:#555;">
                    {reasons_li}
                </ul>
            </div>
            """
            st.markdown(clean_html(html), unsafe_allow_html=True)
    else:
        st.info("Brak meczów w najbliższym tygodniu dla wybranych lig.")
