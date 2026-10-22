"""
Pull historical hourly weather for a team's home stadium from Open-Meteo (no API key)
and match it to each home game's first pitch.

Requires: games_history table already in tickets.db (run mlb_attendance_pull.py first)

Setup:
    pip install requests pandas

Run:
    python weather_pull.py            # Dodgers (default)
    python weather_pull.py angels

Outputs (tickets.db) - this team's rows are replaced, other teams' rows are kept:
    weather_hourly  - every hour across the season date range (raw-ish)
    game_weather    - one row per game_pk: conditions at first pitch + over the game window

Note: close tickets.db in DB Browser before running.
"""

import sqlite3
import sys
import time

import requests
import pandas as pd

DB = "tickets.db"
STADIUMS = {
    "dodgers": (34.0739, -118.2400),   # Dodger Stadium
    "angels": (33.8003, -117.8827),    # Angel Stadium, Anaheim
}
TEAM = sys.argv[1].lower() if len(sys.argv) > 1 else "dodgers"
LAT, LON = STADIUMS[TEAM]
TZ = "America/Los_Angeles"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARS = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "cloud_cover",
    "wind_speed_10m",
]
GAME_WINDOW_HOURS = 3  # first pitch + next 2 hours


def fetch_hourly(start_date, end_date):
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARS),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": TZ,   # returned times are local LA time
    }
    for attempt in range(5):
        r = requests.get(ARCHIVE_URL, params=params, timeout=60)
        if r.status_code == 200:
            return r.json()
        wait = 2 ** attempt
        print(f"  HTTP {r.status_code}: {r.text[:200]} - retrying in {wait}s")
        time.sleep(wait)
    raise RuntimeError("Open-Meteo request failed")


def main():
    with sqlite3.connect(DB) as conn:
        games = pd.read_sql(
            "SELECT game_pk, official_date, game_datetime_utc FROM games_history WHERE team = ?",
            conn, params=(TEAM,)
        )
    if games.empty:
        raise SystemExit(f"No '{TEAM}' games in games_history - run mlb_attendance_pull.py {TEAM} first.")

    # First pitch in local time, rounded down to the hour -> join key
    games["first_pitch_local"] = (
        pd.to_datetime(games["game_datetime_utc"], utc=True)
        .dt.tz_convert(TZ)
        .dt.tz_localize(None)
    )
    games["first_pitch_hour"] = games["first_pitch_local"].dt.floor("h")

    # One request per season keeps each call small and skips the off-season
    hourly_frames = []
    for season, g in games.groupby(games["first_pitch_local"].dt.year):
        start = g["first_pitch_local"].min().strftime("%Y-%m-%d")
        end = g["first_pitch_local"].max().strftime("%Y-%m-%d")
        print(f"{season}: fetching {start} -> {end}")
        data = fetch_hourly(start, end)
        df = pd.DataFrame(data["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        hourly_frames.append(df)
        time.sleep(1)

    hourly = pd.concat(hourly_frames, ignore_index=True).drop_duplicates("time")
    hourly = hourly.rename(columns={"time": "hour_local"})
    print(f"Hourly rows: {len(hourly)}")

    # Conditions at first pitch
    at_pitch = games.merge(
        hourly, left_on="first_pitch_hour", right_on="hour_local", how="left"
    )

    # Aggregates over the game window (rain during the game, avg temp)
    rows = []
    h = hourly.set_index("hour_local")
    for _, gm in games.iterrows():
        window = h.loc[gm["first_pitch_hour"]:
                       gm["first_pitch_hour"] + pd.Timedelta(hours=GAME_WINDOW_HOURS - 1)]
        rows.append({
            "game_pk": gm["game_pk"],
            "game_avg_temp_f": window["temperature_2m"].mean(),
            "game_total_precip_in": window["precipitation"].sum(),
            "game_max_wind_mph": window["wind_speed_10m"].max(),
        })
    window_df = pd.DataFrame(rows)

    game_weather = (
        at_pitch[["game_pk", "first_pitch_local"] + HOURLY_VARS]
        .rename(columns={v: f"pitch_{v}" for v in HOURLY_VARS})
        .merge(window_df, on="game_pk", how="left")
    )
    game_weather["first_pitch_local"] = game_weather["first_pitch_local"].astype(str)
    hourly["hour_local"] = hourly["hour_local"].astype(str)
    hourly["team"] = TEAM

    # Replace only this team's rows, keep the other teams'
    with sqlite3.connect(DB) as conn:
        try:
            old_hourly = pd.read_sql("SELECT * FROM weather_hourly", conn)
            if "team" not in old_hourly.columns:  # table from before multi-team support = Dodgers
                old_hourly["team"] = "dodgers"
            old_hourly = old_hourly[old_hourly["team"] != TEAM]
        except Exception:
            old_hourly = pd.DataFrame()
        try:
            old_gw = pd.read_sql("SELECT * FROM game_weather", conn)
            old_gw = old_gw[~old_gw["game_pk"].isin(games["game_pk"])]
        except Exception:
            old_gw = pd.DataFrame()
        pd.concat([old_hourly, hourly], ignore_index=True).to_sql(
            "weather_hourly", conn, if_exists="replace", index=False)
        pd.concat([old_gw, game_weather], ignore_index=True).to_sql(
            "game_weather", conn, if_exists="replace", index=False)

    missing = game_weather["pitch_temperature_2m"].isna().sum()
    print(f"\nGames with weather: {len(game_weather) - missing} / {len(game_weather)}")
    print(game_weather[["first_pitch_local", "pitch_temperature_2m",
                        "game_total_precip_in"]].describe().round(1))
    print("\nSaved: weather_hourly, game_weather in tickets.db")


if __name__ == "__main__":
    main()