"""
Pull Dodgers events from the Ticketmaster Discovery API (v2).

Setup:
    pip install requests pandas
    Get a free key at https://developer.ticketmaster.com  (My Apps -> Consumer Key)
    Set it as an environment variable (don't hard-code it / commit it to GitHub):
        Windows (PowerShell):  $env:TM_API_KEY="your_key_here"
        Mac/Linux:             export TM_API_KEY="your_key_here"

Run:
    python ticketmaster_pull.py

Outputs:
    raw/events_<timestamp>.json   - untouched API response (keep for reproducibility)
    dodgers_events.csv            - flattened table
    tickets.db (table: events)    - SQLite DB, ready for SQL cleaning
"""

import os
import json
import time
import sqlite3
from datetime import datetime, timezone

import requests
import pandas as pd
from dotenv import load_dotenv  # pip install python-dotenv

load_dotenv()  # reads TM_API_KEY from the .env file in this folder
API_KEY = os.getenv("TM_API_KEY")
BASE_URL = "https://app.ticketmaster.com/discovery/v2"
TEAM_NAME = "Los Angeles Dodgers"
PAGE_SIZE = 200          # max allowed per page
RATE_LIMIT_SLEEP = 0.25  # free tier: 5 requests/sec, 5,000/day


def get(endpoint, params):
    """GET with the API key attached, basic retry on rate limit / server errors."""
    params = {**params, "apikey": API_KEY}
    for attempt in range(5):
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
        if r.status_code == 200:
            time.sleep(RATE_LIMIT_SLEEP)
            return r.json()
        if r.status_code in (429, 500, 502, 503):
            wait = 2 ** attempt
            print(f"  HTTP {r.status_code}, retrying in {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
    raise RuntimeError(f"Failed after retries: {endpoint} {params}")


def find_attraction_id(name):
    """Look up the team's attraction ID so we only get real Dodgers games,
    not every event with 'Dodgers' in the title."""
    data = get("attractions.json", {"keyword": name, "classificationName": "Baseball"})
    for a in data.get("_embedded", {}).get("attractions", []):
        if a["name"].lower() == name.lower():
            return a["id"]
    raise ValueError(f"No attraction found named '{name}'")


def fetch_events(attraction_id):
    """Page through all events. Note: Ticketmaster caps deep paging at
    size * page < 1000, which is plenty for one team."""
    events, page = [], 0
    while True:
        data = get("events.json", {
            "attractionId": attraction_id,
            "size": PAGE_SIZE,
            "page": page,
            "sort": "date,asc",
        })
        batch = data.get("_embedded", {}).get("events", [])
        events.extend(batch)
        total_pages = data.get("page", {}).get("totalPages", 0)
        print(f"  page {page + 1}/{total_pages}: {len(batch)} events")
        page += 1
        if page >= total_pages or page * PAGE_SIZE >= 1000:
            break
    return events


def flatten(event):
    """Pick the fields useful for demand analysis. Many are optional,
    so every lookup uses .get() — expect NULLs (that's the 'messy data')."""
    dates = event.get("dates", {})
    start = dates.get("start", {})
    sales = event.get("sales", {}).get("public", {})
    price = (event.get("priceRanges") or [{}])[0]
    venue = (event.get("_embedded", {}).get("venues") or [{}])[0]
    attractions = event.get("_embedded", {}).get("attractions", [])
    teams = [a.get("name") for a in attractions]
    opponent = next((t for t in teams if t != TEAM_NAME), None)
    classif = (event.get("classifications") or [{}])[0]

    return {
        "event_id": event.get("id"),
        "event_name": event.get("name"),
        "local_date": start.get("localDate"),
        "local_time": start.get("localTime"),
        "start_datetime_utc": start.get("dateTime"),
        "status": dates.get("status", {}).get("code"),
        "opponent": opponent,
        "home_game": venue.get("name") == "Dodger Stadium",
        "venue_name": venue.get("name"),
        "venue_city": venue.get("city", {}).get("name"),
        "venue_state": venue.get("state", {}).get("stateCode"),
        "price_min": price.get("min"),
        "price_max": price.get("max"),
        "currency": price.get("currency"),
        "public_sale_start": sales.get("startDateTime"),
        "public_sale_end": sales.get("endDateTime"),
        "genre": classif.get("genre", {}).get("name"),
        "subgenre": classif.get("subGenre", {}).get("name"),
        "url": event.get("url"),
        "pulled_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main():
    if not API_KEY:
        raise SystemExit("Set the TM_API_KEY environment variable first.")

    print(f"Looking up attraction ID for {TEAM_NAME}...")
    attraction_id = find_attraction_id(TEAM_NAME)
    print(f"  -> {attraction_id}")

    print("Fetching events...")
    events = fetch_events(attraction_id)
    print(f"Total events: {len(events)}")

    # 1) Save raw JSON
    os.makedirs("raw", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(f"raw/events_{stamp}.json", "w") as f:
        json.dump(events, f, indent=2)

    # 2) Flatten to a table
    df = pd.DataFrame([flatten(e) for e in events])
    df.to_csv("dodgers_events.csv", index=False)

    # 3) Append to SQLite (each run adds a snapshot -> lets you track price changes over time)
    with sqlite3.connect("tickets.db") as conn:
        df.to_sql("events", conn, if_exists="append", index=False)

    print(df[["local_date", "opponent", "home_game", "price_min", "price_max", "status"]].head(10))
    print("\nSaved: dodgers_events.csv, tickets.db, raw/ JSON")


if __name__ == "__main__":
    main()