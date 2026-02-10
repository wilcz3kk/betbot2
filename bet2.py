import streamlit as st
import requests
import pandas as pd
import datetime
import time

# --- 1. CONFIGURATION & STYLE ---
st.set_page_config(
    page_title="BetSignal Pro",
    page_icon="⚽",
    layout="centered",
    initial_sidebar_state="expanded"
)

# --- CSS STYLING ---
st.markdown("""
    <style>
    /* Force Light Theme Backgrounds */
    [data-testid="stAppViewContainer"] {
        background-color: #f5f5f7;
    }
    [data-testid="stSidebar"] {
        background-color: #ffffff;
    }
    [data-testid="stHeader"] {
        background-color: rgba(0,0,0,0);
    }
    
    /* Card Container */
    .signal-card {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 18px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        border: 1px solid #e1e1e6;
        color: #1d1d1f; /* Force dark text */
    }
    
    /* Text Styles */
    h1, h2, h3, h4, p, li, span, div {
        color: #1d1d1f;
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    .metric-label {
        font-size: 11px;
        color: #86868b !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
    }
    
    .badge-high {
        background-color: #34c759;
        color: white !important;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
    }
    
    .badge-med {
        background-color: #ff9f0a;
        color: white !important;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. HELPER FUNCTION TO FIX THE BUG ---
def clean_html(html_str):
    """Removes newlines and extra spaces to prevent Markdown from seeing code blocks."""
    return " ".join(html_str.split())

# --- 3. BACKEND ENGINE ---
LEAGUES = {
    'Premier League': 'PL',
    'La Liga': 'PD',
    'Bundesliga': 'BL1',
    'Serie A': 'SA',
    'Ligue 1': 'FL1'
}

class BettingSignalEngine:
    def __init__(self, api_key: str):
        self.headers = {'X-Auth-Token': api_key}
        self.base_url = "http://api.football-data.org/v4"
        self.request_timestamps = []

    def _rate_limit(self):
        now = time.time()
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 60]
        if len(self.request_timestamps) >= 10:
            sleep_time = 61 - (now - self.request_timestamps[0])
            if sleep_time > 0:
                with st.spinner(f"⏳ API Rate Limit Safety: Pausing for {int(sleep_time)}s..."):
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
                st.error("API Limit Hit. Please wait a minute.")
            elif response.status_code == 403:
                st.error("Invalid API Key.")
            return None
        except Exception as e:
            st.error(f"Connection Error: {e}")
            return None

    def get_standings(self, league_code):
        data = self._fetch(f"competitions/{league_code}/standings")
        if not data: return pd.DataFrame()
        teams = {}
        for table in data.get('standings', []):
            t_type = table['type']
            for row in table['table']:
                t_name = row['team']['name']
                if t_name not in teams: teams[t_name] = {}
                teams[t_name][f'{t_type}_rank'] = row['position']
                teams[t_name][f'{t_type}_form'] = row.get('form', '')
        
        total_teams = len(teams)
        for t in teams: teams[t]['league_size'] = total_teams
        return pd.DataFrame.from_dict(teams, orient='index')

    def get_matches(self, league_code):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        future = (datetime.datetime.now() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        data = self._fetch(f"competitions/{league_code}/matches?dateFrom={today}&dateTo={future}")
        return data.get('matches', []) if data else []

    def analyze(self, match, standings, league_name):
        home, away = match['homeTeam']['name'], match['awayTeam']['name']
        if home not in standings.index or away not in standings.index: return None
        
        h_stats, a_stats = standings.loc[home], standings.loc[away]
        signals, reasons, score = [], [], 0

        # Criteria 1: Top 4 vs Bottom 5
        if h_stats['TOTAL_rank'] <= 4 and a_stats['TOTAL_rank'] >= (h_stats['league_size'] - 4):
            signals.append("Mismatch")
            score += 40
            reasons.append(f"🏰 **Mismatch:** {home} (Rank {h_stats['TOTAL_rank']}) vs {away} (Rank {a_stats['TOTAL_rank']})")

        # Criteria 2: Home Fortress
        h_form = h_stats.get('HOME_form', '') or ''
        h_games = h_form.replace(',', '')[-5:]
        if len(h_games) >= 3:
            win_pct = (h_games.count('W') / len(h_games)) * 100
            if win_pct >= 80:
                signals.append("Fortress")
                score += 30
                reasons.append(f"🔥 **Home Form:** {home} has won {int(win_pct)}% of recent home games.")

        # Criteria 3: Away Weakness
        a_form = a_stats.get('AWAY_form', '') or ''
        a_games = a_form.replace(',', '')[-5:]
        if len(a_games) >= 3:
            loss_pct = (a_games.count('L') / len(a_games)) * 100
            if loss_pct >= 80:
                signals.append("Weak Away")
                score += 30
                reasons.append(f"❄️ **Away Slump:** {away} has lost {int(loss_pct)}% of recent away games.")

        if signals:
            return {
                "match_date": match['utcDate'][:10],
                "league": league_name,
                "home": home,
                "away": away,
                "score": min(score + 10, 100),
                "reasons": reasons,
                "signal_type": signals
            }
        return None

# --- 4. UI LAYOUT ---

with st.sidebar:
    st.header("⚙️ Configuration")
    api_key = st.text_input("API Key", type="password")
    st.divider()
    selected_leagues = st.multiselect("Select Leagues", list(LEAGUES.keys()), default=list(LEAGUES.keys()))
    run_btn = st.button("🔍 Find Signals", type="primary", use_container_width=True)
    st.markdown("---")
    st.markdown("*Analysis covers next 7 days.*")

st.title("BetSignal Pro")
st.markdown("### AI-Driven Sports Analytics Engine")

if run_btn:
    if not api_key:
        st.warning("⚠️ Please enter your API Key in the sidebar.")
    elif not selected_leagues:
        st.warning("⚠️ Please select at least one league.")
    else:
        engine = BettingSignalEngine(api_key)
        all_signals = []
        
        progress_text = "Scanning Leagues..."
        my_bar = st.progress(0, text=progress_text)
        total_steps = len(selected_leagues)
        
        for idx, league_name in enumerate(selected_leagues):
            code = LEAGUES[league_name]
            my_bar.progress((idx / total_steps), text=f"Analyzing {league_name}...")
            
            standings = engine.get_standings(code)
            if standings.empty: continue
            matches = engine.get_matches(code)
            
            for match in matches:
                if match['status'] != 'FINISHED':
                    res = engine.analyze(match, standings, league_name)
                    if res: all_signals.append(res)
        
        my_bar.progress(1.0, text="Analysis Complete!")
        time.sleep(0.5)
        my_bar.empty()

        if not all_signals:
            st.info("✅ No high-risk signals found for the upcoming week.")
        else:
            all_signals.sort(key=lambda x: x['score'], reverse=True)
            st.markdown(f"Found **{len(all_signals)}** high-value signals.")
            
            for signal in all_signals:
                score = signal['score']
                score_color = "#34c759" if score >= 80 else "#ff9f0a"
                badge_class = "badge-high" if score >= 80 else "badge-med"
                badge_text = "HIGH PROB" if score >= 80 else "MODERATE"
                
                # --- HTML CONSTRUCTION ---
                reasons_html = "".join([f'<li style="margin-bottom:4px;">{r}</li>' for r in signal['reasons']])
                
                # We build the HTML as a clean F-string
                raw_html = f"""
                <div class="signal-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <span class="metric-label">📅 {signal['match_date']} • {signal['league']}</span>
                        <span class="{badge_class}">{badge_text}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                        <div style="text-align:left; width:45%;">
                            <h2 style="margin:0; font-size:18px;">{signal['home']}</h2>
                            <span class="metric-label">HOME</span>
                        </div>
                        <div style="text-align:center; font-size:20px; color:#86868b;">VS</div>
                        <div style="text-align:right; width:45%;">
                            <h2 style="margin:0; font-size:18px;">{signal['away']}</h2>
                            <span class="metric-label">AWAY</span>
                        </div>
                    </div>
                    <hr style="border:0; border-top:1px solid #f0f0f5; margin:15px 0;">
                    <div style="margin-bottom:10px;">
                        <span class="metric-label">CONFIDENCE SCORE</span>
                        <div style="display:flex; align-items:center; margin-top:5px;">
                            <div style="flex-grow:1; background-color:#e1e1e6; height:6px; border-radius:3px; margin-right:10px;">
                                <div style="width:{score}%; background-color:{score_color}; height:6px; border-radius:3px;"></div>
                            </div>
                            <span style="font-weight:bold; color:{score_color}; font-size:14px;">{score}%</span>
                        </div>
                    </div>
                    <div style="background-color:#f9f9fb; padding:10px; border-radius:10px;">
                        <ul style="margin:0; padding-left:20px; color:#424245; font-size:14px;">
                            {reasons_html}
                        </ul>
                    </div>
                </div>
                """
                
                # --- THE FIX: Clean the HTML string before rendering ---
                st.markdown(clean_html(raw_html), unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="text-align: center; padding: 50px; color: #86868b;">
        <h3>Ready to Analyze?</h3>
        <p>Enter your API key in the sidebar and click "Find Signals".</p>
    </div>
    """, unsafe_allow_html=True)
