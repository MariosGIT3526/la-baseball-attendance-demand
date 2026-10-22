"""
Pull historical HOME game attendance for one team from the MLB Stats API.
No API key needed.

Setup:
    pip install requests pandas

Run:
    python mlb_attendance_pull.py            # Dodgers (default)
    python mlb_attendance_pull.py angels

Outputs:
    raw/mlb_schedule_<team>_<timestamp>.json  - raw schedule responses
    <team>_home_games.csv                     - one row per home game
    tickets.db (table: games_history)         - this team's rows are REPLACED each run;
                                                other teams' rows are kept

Note: close tickets.db in DB Browser before running, or you'll get "database is locked".
"""

import os
import re
import sys
import json
import time
import sqlite3
from datetime import datetime

import requests
import pandas as pd

BASE_URL = "https://statsapi.mlb.com/api/v1"
TEAM_IDS = {"dodgers": 119, "angels": 108}
TEAM = sys.argv[1].lower() if len(sys.argv) > 1 else "dodgers"
TEAM_ID = TEAM_IDS[TEAM]
# 2020 had no fans; 2021 started with capacity limits (keep it, flag it in SQL later)
SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]


def get(url, params=None):
    for attempt in range(5):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 200:
            time.sleep(0.2)  # be polite, no official limit published
            return r.json()
        wait = 2 ** attempt
        print(f"  HTTP {r.status_code}, retrying in {wait}s...")
        time.sleep(wait)
    raise RuntimeError(f"Failed: {url}")


def fetch_schedule(season):
    """All regular-season games for TEAM in one season."""
    data = get(f"{BASE_URL}/schedule", {
        "sportId": 1,
        "teamId": TEAM_ID,
        "season": season,
        "gameType": "R",
    })
    games = [g for d in data.get("dates", []) for g in d.get("games", [])]
    return data, games


def parse_boxscore_info(game_pk):
    """Boxscore 'info' is a list of {label, value} like
    {'label': 'Att', 'value': '52,005.'}  -> pull attendance, weather, wind."""
    box = get(f"{BASE_URL}/game/{game_pk}/boxscore")
    info = {i.get("label"): i.get("value", "") for i in box.get("info", []) if "label" in i}

    att_raw = info.get("Att", "")
    att_digits = re.sub(r"[^\d]", "", att_raw)
    return {
        "attendance": int(att_digits) if att_digits else None,
        "weather_raw": info.get("Weather"),   # e.g. "72 degrees, Clear."
        "wind_raw": info.get("Wind"),
        "first_pitch_raw": info.get("First pitch"),
        "game_time_raw": info.get("T"),       # game duration, e.g. "2:45"
    }


def flatten(g):
    home = g["teams"]["home"]
    away = g["teams"]["away"]
    return {
        "team": TEAM,
        "game_pk": g["gamePk"],
        "season": int(g["season"]),
        "official_date": g.get("officialDate"),
        "game_datetime_utc": g.get("gameDate"),
        "day_night": g.get("dayNight"),
        "double_header": g.get("doubleHeader"),
        "game_number": g.get("gameNumber"),
        "status": g["status"].get("detailedState"),
        "venue_name": g.get("venue", {}).get("name"),
        "opponent": away["team"]["name"],
        "series_game_number": g.get("seriesGameNumber"),
        "games_in_series": g.get("gamesInSeries"),
        # Records as reported for this game - may INCLUDE the game's own result.
        # If you use them as model features, lag them by one game in SQL/Python.
        "team_wins": home.get("leagueRecord", {}).get("wins"),
        "team_losses": home.get("leagueRecord", {}).get("losses"),
        "opp_wins": away.get("leagueRecord", {}).get("wins"),
        "opp_losses": away.get("leagueRecord", {}).get("losses"),
        "team_score": home.get("score"),
        "opp_score": away.get("score"),
        "team_won": home.get("isWinner"),
    }


def main():
    os.makedirs("raw", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dump, rows = {}, []

    for season in SEASONS:
        data, games = fetch_schedule(season)
        raw_dump[season] = data
        home_games = [
            g for g in games
            if g["teams"]["home"]["team"]["id"] == TEAM_ID
            and g["status"].get("abstractGameState") == "Final"
        ]
        print(f"{season}: {len(home_games)} completed home games")

        for i, g in enumerate(home_games, 1):
            row = flatten(g)
            try:
                row.update(parse_boxscore_info(g["gamePk"]))
            except Exception as e:  # don't lose the whole run over one game
                print(f"  boxscore failed for {g['gamePk']}: {e}")
            rows.append(row)
            if i % 20 == 0:
                print(f"  {i}/{len(home_games)} boxscores")

    with open(f"raw/mlb_schedule_{TEAM}_{stamp}.json", "w") as f:
        json.dump(raw_dump, f)

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset="game_pk")  # API sometimes lists the same game twice
    df.to_csv(f"{TEAM}_home_games.csv", index=False)

    # Replace only this team's rows, keep the other teams'
    with sqlite3.connect("tickets.db") as conn:
        try:
            existing = pd.read_sql("SELECT * FROM games_history", conn)
        except Exception:
            existing = pd.DataFrame()
        if not existing.empty:
            if "team" not in existing.columns:  # table from before multi-team support = Dodgers
                existing = existing.rename(columns={
                    "dodgers_wins": "team_wins", "dodgers_losses": "team_losses",
                    "dodgers_score": "team_score", "dodgers_won": "team_won"})
                existing["team"] = "dodgers"
            existing = existing[existing["team"] != TEAM]
        combined = pd.concat([existing, df], ignore_index=True)
        combined.to_sql("games_history", conn, if_exists="replace", index=False)

    print(f"\nTotal home games: {len(df)}")
    print(f"Missing attendance: {df['attendance'].isna().sum()}")
    print(df.groupby("season")["attendance"].agg(["count", "mean", "min", "max"]).round(0))
    print(f"\nSaved: {TEAM}_home_games.csv, tickets.db (games_history), raw/ JSON")
    print("games_history rows by team:", combined["team"].value_counts().to_dict())


if __name__ == "__main__":
    main()