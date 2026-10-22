"""
Pull Dodgers events + resale price stats from the SeatGeek API (v2).

Setup:
    pip install requests pandas python-dotenv
    Add to your .env file (same folder as this script):
        SEATGEEK_CLIENT_ID=your_client_id
        SEATGEEK_CLIENT_SECRET=your_secret   (optional - only if SeatGeek gave you one)

Run:
    python seatgeek_pull.py

Outputs:
    raw/seatgeek_<timestamp>.json  - untouched API response
    seatgeek_events.csv            - flattened table (this snapshot)
    tickets.db (table: seatgeek_events) - appended each run, so you build a price history
"""

import os
import json
import time
import sqlite3
from datetime import datetime, timezone

import requests
import pandas as pd
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH, encoding="utf-8-sig")

CLIENT_ID = os.getenv("SEATGEEK_CLIENT_ID")
CLIENT_SECRET = os.getenv("SEATGEEK_CLIENT_SECRET")  # may be None, that's fine
BASE_URL = "https://api.seatgeek.com/2"
PERFORMER_SLUG = "los-angeles-dodgers"
TEAM_NAME = "Los Angeles Dodgers"
PER_PAGE = 100


def get(endpoint, params):
    """GET with credentials attached, simple retry on rate limit / server errors."""
    params = {**params, "client_id": CLIENT_ID}
    if CLIENT_SECRET:
        params["client_secret"] = CLIENT_SECRET
    for attempt in range(5):
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
        if r.status_code == 200:
            time.sleep(0.5)
            return r.json()
        if r.status_code in (429, 500, 502, 503):
            wait = 2 ** attempt
            print(f"  HTTP {r.status_code}, retrying in {wait}s...")
            time.sleep(wait)
            continue
        # 401/403 = bad or unapproved credentials
        raise SystemExit(f"HTTP {r.status_code}: {r.text[:300]}")
    raise RuntimeError(f"Failed after retries: {endpoint}")


def fetch_events():
    """Page through all upcoming Dodgers events."""
    events, page = [], 1
    while True:
        data = get("events", {
            "performers.slug": PERFORMER_SLUG,
            "per_page": PER_PAGE,
            "page": page,
            "sort": "datetime_local.asc",
        })
        batch = data.get("events", [])
        events.extend(batch)
        total = data.get("meta", {}).get("total", 0)
        print(f"  page {page}: {len(batch)} events (total {total})")
        if not batch or page * PER_PAGE >= total:
            break
        page += 1
    return events


def flatten(e):
    """Keep fields useful for demand analysis. Price stats can be null
    (no listings yet, or not exposed for your key) - expect some NULLs."""
    stats = e.get("stats") or {}
    venue = e.get("venue") or {}
    performers = e.get("performers") or []
    opponent = next((p.get("name") for p in performers if p.get("name") != TEAM_NAME), None)

    return {
        "sg_event_id": e.get("id"),
        "title": e.get("title"),
        "datetime_local": e.get("datetime_local"),
        "datetime_utc": e.get("datetime_utc"),
        "event_type": e.get("type"),
        "opponent": opponent,
        "home_game": venue.get("name") == "Dodger Stadium",
        "venue_name": venue.get("name"),
        "venue_city": venue.get("city"),
        "venue_state": venue.get("state"),
        # Demand signals
        "listing_count": stats.get("listing_count"),
        "visible_listing_count": stats.get("visible_listing_count"),
        "lowest_price": stats.get("lowest_price"),
        "median_price": stats.get("median_price"),
        "average_price": stats.get("average_price"),
        "highest_price": stats.get("highest_price"),
        "sg_score": e.get("score"),           # SeatGeek's own popularity score
        "sg_popularity": e.get("popularity"),
        "url": e.get("url"),
        "pulled_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main():
    if not CLIENT_ID:
        raise SystemExit(f"SEATGEEK_CLIENT_ID not found in {ENV_PATH}")

    print("Fetching SeatGeek events...")
    events = fetch_events()
    print(f"Total events: {len(events)}")

    os.makedirs("raw", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(f"raw/seatgeek_{stamp}.json", "w") as f:
        json.dump(events, f, indent=2)

    df = pd.DataFrame([flatten(e) for e in events])
    df.to_csv("seatgeek_events.csv", index=False)

    with sqlite3.connect("tickets.db") as conn:
        df.to_sql("seatgeek_events", conn, if_exists="append", index=False)

    print(df[["datetime_local", "opponent", "home_game",
              "listing_count", "lowest_price", "average_price"]].head(10))
    print(f"\nRows with a price: {df['lowest_price'].notna().sum()} / {len(df)}")
    print("Saved: seatgeek_events.csv, tickets.db (seatgeek_events), raw/ JSON")


if __name__ == "__main__":
    main()