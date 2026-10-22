# Same Market, Opposite Problems: LA Baseball Attendance Demand

**Dodgers vs. Angels home attendance, 2021–2026: an end-to-end demand analysis and forecasting project.**
`APIs → SQLite → SQL cleaning → Python demand model → Power BI dashboard`

> **TL;DR:** Two teams in the same market have opposite problems. The Dodgers sell out, so their lever is **pricing**. The Angels average ~13,000 empty seats in 2026, and their worst games are predictable (all Mon–Thu), so their lever is **targeted weekday promotions**. A demand model beats a simple-average forecast by **24% for the Angels** and **6% for the Dodgers**. Star-player bobbleheads were the only promotion showing a lift: **~+1,200 fans**, suggestive at p ≈ 0.10.

📄 **[View the full 5-page dashboard (PDF)](AttendanceDashboard.pdf)**

---

## 1. Executive Summary & Core Business Question

**Core business question:** *What drives attendance at Dodger Stadium and Angel Stadium, and what should each team do to grow ticket revenue?*

The Dodgers and Angels play 35 miles apart in the same media market, but their demand problems are opposite:

- **Dodgers:** demand is greater than supply. Dodger Stadium (56,000 seats) is close to full almost every night, so the question is **how to earn more from demand they already have**.
- **Angels:** supply is greater than demand. Angel Stadium (45,500 seats) has thousands of empty seats on many nights, so the question is **which games need help, and what fills them**.

The project answers seven questions a ticketing or revenue team would ask:

| # | Business question | Dashboard page |
|---|---|---|
| Q1 | How full are our games, and how many seats go empty? | Summary |
| Q2 | Can we predict attendance better than a simple guess? | Model Performance |
| Q3 | What actually drives attendance? | Demand Drivers |
| Q4 | Which opponents draw more (or fewer) fans than expected? | Demand Drivers |
| Q5 | Do promotions bring in extra fans? Which ones? | Promotions |
| Q6 | Does weather matter? | Demand Drivers |
| Q7 | Which games need action, and when do they happen? | Game Tiers |

### Headline results

| | Dodgers | Angels |
|---|---|---|
| Avg. capacity filled (2026) | **~89%** (~6,200 empty seats/game) | **~71%** (~13,000 empty seats/game) |
| Forecast error: model vs. simple guess | 2,165 vs 2,315 fans/game (**6% better**) | 4,358 vs 5,747 fans/game (**24% better**) |
| Games predicted within 10% | **90%** | **46%** |
| #1 demand driver | Start time | Day of week |
| Best-drawing opponents (vs. expected) | Angels, Yankees, Orioles (~+1K) | Dodgers (+5.9K), Yankees (+5.4K) |
| Main revenue lever | **Pricing** on peak dates | **Promotions and discounts** on weekday, low-draw games |

### Key findings
1. **The Dodgers' model gains little over a simple average, and that is itself a finding.** When nearly every game is close to full, attendance barely varies. The opportunity is pricing, not filling seats.
2. **Schedule drives demand for both teams.** Day of week, start time and month explain most game-to-game swings. For the Angels, *who the opponent is* matters almost as much as the day.
3. **Weather barely matters.** Temperature, humidity, wind and cloud cover add almost nothing once the schedule is known.
4. **Angels low-demand games are predictable.** All 17 Value-tier games in 2026 fell on **Monday–Thursday** (8 on Wednesdays) and filled only **~58%** of seats, versus **~83%** for High and Premium games, which all fell Friday–Sunday.
5. **Star-player bobbleheads were the only promotion with a lift:** about **+1,200 fans** above what the model expected. With 19 games and p ≈ 0.10, the result is suggestive but not statistically confirmed. Heritage nights, pop-culture nights, celebrity crossovers and legend bobbleheads showed no lift.
6. **The model has a seasonal blind spot.** Angels crowds beat forecasts in April–July and fell short in August (−4.2K/game), which points to the playoff race, which the model doesn't capture yet.

---

## 2. Data Pipeline & Source Architecture

```
Ticketmaster API ─┐
SeatGeek API ─────┤  (explored: no price data available)
                  │
MLB Stats API ────┼──► SQLite (tickets.db) ──► SQL view: games_clean ──► Python model ──► CSV exports ──► Power BI
Open-Meteo API ───┘        games_history                                (scikit-learn)
                           game_weather
```

### Sources

| Source | Type | What it provided | Script |
|---|---|---|---|
| **MLB Stats API** (`statsapi.mlb.com`) | REST API, no key | Every home game 2021–2026: date, opponent, records, scores, start time, and **attendance** (parsed from boxscores) | `mlbteam_attendance_pull.py dodgers` / `angels` |
| **Open-Meteo Archive API** | REST API, no key | Hourly weather at each stadium's coordinates, matched to first pitch | `weather_pull.py dodgers` / `angels` |
| **Ticketmaster Discovery API** | REST API, key | Upcoming events; **no price ranges returned** | `ticketmaster_pull.py` |
| **SeatGeek API** | REST API, client ID | Upcoming events and popularity scores; **prices returned null** | `seatgeek_pull.py` |
| **Team promotion schedules** | Manual collection | Dodgers 2025–2026 promotions hand-tagged into 11 categories | `dodgers_promos_2025_2026.csv` |

> **Pivot:** The original plan was ticket-price modeling. Neither Ticketmaster nor SeatGeek exposed price data through their public APIs, so the project switched to **attendance demand**, which is public, reliable and available for every game.

### Storage
Raw API pulls land in a local **SQLite** database (`tickets.db`): `games_history` (one row per home game, both teams) and `game_weather` (one row per game). The scripts are re-runnable, replacing only one team's rows at a time, and API keys are loaded from a git-ignored `.env` file.

### Cleaning (SQL: `sql/games_clean.sql`)
Real-world data issues found and fixed:
- **Stadium rename:** Dodger Stadium became "UNIQLO Field at Dodger Stadium" in 2026, so venue filters use `LIKE '%Dodger Stadium%'`.
- **Neutral-site game:** removed the 2024 Seoul Series game (Gocheok Sky Dome).
- **Duplicate games:** the API listed some Angels games twice, so rows are de-duplicated on `game_pk`.
- **Team renames:** "Oakland Athletics" became "Athletics" and "Cleveland Indians" became "Cleveland Guardians". Names were unified so opponent stats aren't split.
- **Data leakage:** API win-loss records *include* that day's result, so pre-game win % subtracts the game's own outcome.
- **COVID capacity limits:** 2021 games before June 15 were flagged and excluded.

**Final dataset: 904 home games** across both teams.

### Modeling (Python: `mlb_explore.ipynb`)
- **Time-based split:** train on 2021–2025, test on 2026, so the model never sees the future.
- **Baseline:** predict every 2026 game at the team's 2025 average.
- **Models:** Linear Regression and Histogram Gradient Boosting in a scikit-learn `Pipeline` (imputation, scaling, one-hot encoding). **Metric:** MAE, the average miss in fans per game.
- **Opponent draw:** a schedule-adjusted "fans above/below expected" score per opponent, learned from training seasons only and shrunk toward zero for small samples (K = 10). This was the biggest single improvement for the Angels.
- **Driver ranking:** permutation importance, i.e. how much MAE increases when each feature is scrambled.
- **Demand tiers:** 2026 games ranked by predicted attendance into Value (bottom 20%), Standard, High and Premium (top 20%).
- **Promotion analysis:** actual vs. model-expected attendance on promo nights, with each season predicted by a model trained only on earlier seasons, tested with Welch's t-tests.

| Team | Best model | Features | Baseline MAE | Model MAE | Improvement |
|---|---|---|---|---|---|
| Dodgers | Linear Regression | Core | 2,315 | 2,165 | 6.5% |
| Angels | Gradient Boosting | Core + opponent draw | 5,747 | 4,358 | 24.2% |

---

## 3. Tools & Tech Stack Used

| Category | Tools |
|---|---|
| **Languages** | Python, SQL, DAX |
| **Data collection** | REST APIs (MLB Stats, Open-Meteo, Ticketmaster, SeatGeek), `requests`, `python-dotenv` |
| **Database** | SQLite, DB Browser for SQLite |
| **Analysis & modeling** | pandas, scikit-learn (Pipeline, ColumnTransformer, LinearRegression, HistGradientBoosting, permutation importance), SciPy (Welch's t-test) |
| **Visualization & BI** | Power BI Desktop (star-schema model, DAX measures, dynamic text, conditional formatting, page navigation), matplotlib |
| **Workflow** | Jupyter, VS Code, Git/GitHub, virtual environments |

---

## 4. Visual Highlights & Dashboard Snippets

Five pages, with a synced team slicer and Home-button navigation:

| Page | Answers | Highlights |
|---|---|---|
| **Summary** | Q1 | % capacity KPI vs. last season, empty seats per game, top-drawing opponents, attendance by day of week, weakest day |
| **Demand Drivers** | Q3, Q4, Q6 | Driver ranking, best and worst drawing opponents (green/red), attendance by start window, temperature vs. attendance |
| **Game Tiers** | Q7 | Predicted vs. actual by tier, Value vs. High+Premium capacity, empty seats per Value game, tier × day-of-week heatmap |
| **Promotions** | Q5 | Star bobblehead lift, promo vs. non-promo nights, fans vs. expected by promo type, star bobblehead game log |
| **Model Performance** | Q2 | Baseline vs. model error, % of games within 10%, actual vs. predicted, miss-size distribution, over/under-prediction by month |

📄 **[Open the full dashboard (PDF)](AttendanceDashboard.pdf)** to see every page.

---

## 5. Actionable Business Recommendations

Each recommendation follows **finding → so what → action**:

| Finding (technical) | So what (business meaning) | Recommended action |
|---|---|---|
| Dodgers fill ~89% of seats; the model only beats a flat average by 6% | Demand barely varies, so there are few seats left to sell | **Dodgers:** shift focus from filling seats to **dynamic pricing**, raising prices on Premium-tier games |
| All 17 Angels Value-tier games fell Mon–Thu at ~58% capacity (~19K empty seats/game) | Low-demand games are **predictable months in advance** | **Angels:** schedule weekday promotions, discounts and group sales on Value-tier games when the schedule is released |
| Angels opponent draw: Dodgers +5.9K, Yankees +5.4K above expected | Some opponents sell tickets on their own | **Angels:** price Dodgers and Yankees games higher, and save promotions for low-draw opponents |
| Star bobbleheads: +1,200 fans vs. expected (n = 19, p ≈ 0.10); other promo types flat or negative | Star giveaways are the only promising promotion; theme nights don't add attendance | **Dodgers:** move star bobbleheads off nights that would sell out anyway and onto softer dates; **both teams:** A/B test star giveaways for another season to confirm the lift |
| Weather has near-zero effect once schedule is known | Weather isn't a useful planning input | Skip weather-based pricing or staffing changes for attendance |
| Angels forecasts run high in August (−4.2K/game) | Late-season demand falls when playoff hopes fade | Plan August promotions conservatively, and add standings to the model |

---

## 6. Data Limitations & Future Next Steps

### Limitations
- **Attendance is tickets sold, not people in seats.** A season-ticket holder who skips a game still counts, so promo lift mostly reflects **extra ticket buyers**.
- **No price data.** Ticketmaster and SeatGeek public APIs didn't return prices, so pricing recommendations are directional, not revenue estimates.
- **Promotion data:** Dodgers only; 2025 covers giveaways only, while 2026 includes theme nights. Several categories have fewer than 5 games.
- **Ceiling effect for the Dodgers:** near-capacity crowds limit how much any model can explain.
- **Missing context features:** standings, playoff odds, star-player injuries and opponent star power.

### Next steps
- Add **standings or playoff-odds** features to fix the late-season bias.
- Add **secondary-market price data** if an accessible source becomes available, to turn the recommendations into revenue estimates.
- Extend the **promotion analysis** to the Angels and to more seasons to confirm the star bobblehead lift.
- Automate the pipeline (scheduled pulls and refresh) so the dashboard updates during the season.

---

## Repository Structure

```
├── README.md
├── AttendanceDashboard.pdf                      ← full dashboard export
├── AttendanceDashboard.pbix                     ← Power BI file
├── requirements.txt
├── mlbteam_attendance_pull.py                   ← MLB Stats API → games_history
├── weather_pull.py                              ← Open-Meteo → game_weather
├── ticketmaster_pull.py / seatgeek_pull.py      ← price exploration (no prices returned)
├── mlb_explore.ipynb                            ← EDA, modeling, promo analysis, exports
├── sql/games_clean.sql                          ← cleaning view
├── dodgers_promos_2025_2026.csv                 ← hand-tagged promotions
├── dodgers_2025_2026_predictions_with_promos.csv
├── dodgers_home_games.csv / angels_home_games.csv
└── powerbi/                                     ← model output CSVs loaded into Power BI
```

## How to Run

```bash
python -m venv .venv
.venv\Scripts\activate             # Windows
pip install -r requirements.txt

python mlbteam_attendance_pull.py dodgers
python mlbteam_attendance_pull.py angels
python weather_pull.py dodgers
python weather_pull.py angels
```

Then run `sql/games_clean.sql` against `tickets.db` (e.g. in DB Browser for SQLite), run the notebook top to bottom, and open the `.pbix` in Power BI Desktop. The Ticketmaster and SeatGeek scripts need keys in a local `.env` file, which is git-ignored.

---

*Built by Mario Perez · Computer Science, Data Science minor, CSUSB · [GitHub](https://github.com/MariosGIT3526)*
