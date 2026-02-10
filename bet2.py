import streamlit as st
import requests
import pandas as pd
import datetime
import time
import logging

# --- 1. CONFIGURATION & STYLE ---
st.set_page_config(
    page_title="BetSignal Pro",
    page_icon="⚽",
    layout="centered",
    initial_sidebar_state="expanded"
)

# Apple-like CSS: Minimalist, rounded, clean typography
st.markdown("""
    <style>
    /* Main Background */
    .stApp {
        background-color: #f5f5f7;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Card Container */
    .signal-card {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 18px;
        box_shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        border: 1px solid #e1e1e6;
        transition: transform 0.2s;
    }
    .signal-card:hover {
        transform: translateY(-2px);
        box_shadow: 0 8px 16px rgba(0,0,0,0.1);
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #1d1d1f;
        font-weight: 600;
    }
    
    /* Metric Text */
    .metric-label {
        font-size: 12px;
        color: #86868b;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value {
        font-size: 24px;
        font-weight: 700;
        color: #1d1d1f;
    }
    
    /* High Confidence Badge */
    .badge-high {
        background-color: #34c759;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: bold;
    }
    
    /* Medium Confidence Badge */
    .badge-med {
        background-color: #ff9f0a;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. BACKEND ENGINE (CACHED) ---

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
        """Strict 10 req/min limit handling."""
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
            t_type = table['type'] # TOTAL, HOME, AWAY
            for row in table['table']:
                t_name = row['team']['name']
                if t_name not in teams: teams[t_name] = {}
                teams[t_name][f'{t_type}_rank'] = row['position']
                teams[t_name][f'{t_type}_form'] = row.get('form', '')
        
        # Add league size for Bottom 5 logic
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

        # Criteria 1: Top 4 Home vs Bottom 5 Away
        if h_stats['TOTAL_rank'] <= 4 and a_stats['TOTAL_rank'] >= (h_stats['league_size'] - 4):
            signals.append("Mismatch")
            score += 40
            reasons.append(f"🏰 **Mismatch:** {home} (Rank {h_stats['TOTAL_rank']}) vs {away} (Rank {a_stats['TOTAL_rank']})")

        # Criteria 2: Home Fortress (Home Win > 80% recent)
        h_form = h_stats.get('HOME_form', '') or ''
        # Clean form string (sometimes it's comma separated, sometimes not)
        h_games = h_form.replace(',', '')[-5:]
        if len(h_games) >= 3:
            win_pct = (h_games.count('W') / len(h_games)) * 100
            if win_pct >= 80:
                signals.append("Fortress")
                score += 30
                reasons.append(f"🔥 **Home Form:** {home} has won {int(win_pct)}% of recent home games.")

        # Criteria 3: Away Weakness (Away Loss > 80% recent)
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

# --- 3. UI LAYOUT ---

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    api_key = "99d57be449264cc089914bc6d78967c2"
    
    st.divider()

    selected_leagues = st.multiselect(
        "Select Leagues", 
        list(LEAGUES.keys()), 
        default=list(LEAGUES.keys())
    )
    
    run_btn = st.button("🔍 Find Signals", type="primary", use_container_width=True)
    
    st.markdown("---")
    st.markdown("*Only Top 4 vs Bottom 5 or extreme form disparities are flagged.*")

# Main Content
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
        
        # Progress Bar
        progress_text = "Scanning Leagues..."
        my_bar = st.progress(0, text=progress_text)
        
        total_steps = len(selected_leagues)
        
        for idx, league_name in enumerate(selected_leagues):
            code = LEAGUES[league_name]
            my_bar.progress((idx / total_steps), text=f"Analyzing {league_name}...")
            
            # Fetch Data
            standings = engine.get_standings(code)
            if standings.empty: continue
            
            matches = engine.get_matches(code)
            
            # Analyze
            for match in matches:
                if match['status'] != 'FINISHED':
                    res = engine.analyze(match, standings, league_name)
                    if res: all_signals.append(res)
        
        my_bar.progress(1.0, text="Analysis Complete!")
        time.sleep(0.5)
        my_bar.empty()

        # --- RESULTS DISPLAY ---
        if not all_signals:
            st.info("✅ No high-risk signals found for the upcoming week. The markets are efficient right now.")
        else:
            # Sort by confidence
            all_signals.sort(key=lambda x: x['score'], reverse=True)
            
            st.markdown(f"Found **{len(all_signals)}** high-value signals.")
            
            for signal in all_signals:
                # Determine Color Logic based on Score
                score = signal['score']
                score_color = "#34c759" if score >= 80 else "#ff9f0a"
                badge_class = "badge-high" if score >= 80 else "badge-med"
                badge_text = "HIGH PROBABILITY" if score >= 80 else "MODERATE PROBABILITY"
                
                # Render Card using HTML/CSS inside Markdown
                html_card = f"""
                <div class="signal-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <span class="metric-label">📅 {signal['match_date']} • {signal['league']}</span>
                        <span class="{badge_class}">{badge_text}</span>
                    </div>
                    
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                        <div style="text-align:left; width:45%;">
                            <h2 style="margin:0;">{signal['home']}</h2>
                            <span class="metric-label">HOME</span>
                        </div>
                        <div style="text-align:center; font-size:20px; color:#86868b;">VS</div>
                        <div style="text-align:right; width:45%;">
                            <h2 style="margin:0;">{signal['away']}</h2>
                            <span class="metric-label">AWAY</span>
                        </div>
                    </div>
                    
                    <hr style="border:0; border-top:1px solid #f0f0f5; margin:15px 0;">
                    
                    <div style="margin-bottom:10px;">
                        <span class="metric-label">CONFIDENCE SCORE</span>
                        <div style="display:flex; align-items:center;">
                            <div style="width:100%; background-color:#e1e1e6; height:8px; border-radius:4px; margin-right:10px;">
                                <div style="width:{score}%; background-color:{score_color}; height:8px; border-radius:4px;"></div>
                            </div>
                            <span style="font-weight:bold; color:{score_color}">{score}%</span>
                        </div>
                    </div>
                    
                    <div>
                        <span class="metric-label">ANALYSIS</span>
                        <ul style="margin-top:5px; padding-left:20px; color:#424245;">
                            {''.join([f'<li>{r}</li>' for r in signal['reasons']])}
                        </ul>
                    </div>
                </div>
                """
                st.markdown(html_card, unsafe_allow_html=True)

else:
    # Initial State Hero
    st.markdown("""
    <div style="text-align: center; padding: 50px; color: #86868b;">
        <h3>Ready to Analyze?</h3>
        <p>Enter your API key in the sidebar and click "Find Signals" to scan the Top 5 European Leagues.</p>
    </div>
    """, unsafe_allow_html=True)