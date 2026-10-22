CREATE VIEW games_clean AS
WITH base AS (
  SELECT
    g.*,
    w.first_pitch_local,
    w.pitch_temperature_2m       AS temp_f,
    w.pitch_relative_humidity_2m AS humidity,
    w.pitch_cloud_cover          AS cloud_cover,
    w.pitch_wind_speed_10m       AS wind_mph,
    -- record BEFORE this game (remove today's result)
    team_wins   - CASE WHEN team_won = 1 THEN 1 ELSE 0 END AS team_w_pre,
    team_losses - CASE WHEN team_won = 0 THEN 1 ELSE 0 END AS team_l_pre,
    opp_wins    - CASE WHEN team_won = 0 THEN 1 ELSE 0 END AS opp_w_pre,
    opp_losses  - CASE WHEN team_won = 1 THEN 1 ELSE 0 END AS opp_l_pre
  FROM games_history g
  JOIN game_weather w ON g.game_pk = w.game_pk
  WHERE (g.team = 'dodgers' AND g.venue_name LIKE '%Dodger Stadium%')
     OR (g.team = 'angels'  AND g.venue_name LIKE '%Angel Stadium%')
)
SELECT
  team,
  game_pk,
  season,
  official_date,
  first_pitch_local,
  opponent,
  attendance,

  CAST(strftime('%w', official_date) AS INTEGER)            AS day_of_week,  -- 0 = Sunday
  CASE WHEN strftime('%w', official_date) IN ('0','5','6')
       THEN 1 ELSE 0 END                                    AS is_weekend,
  CAST(strftime('%m', official_date) AS INTEGER)            AS month,
  CAST(strftime('%H', first_pitch_local) AS INTEGER)        AS start_hour,
  CASE WHEN day_night = 'night' THEN 1 ELSE 0 END           AS is_night,

  ROUND(1.0 * team_w_pre / NULLIF(team_w_pre + team_l_pre, 0), 3) AS team_win_pct_pre,
  ROUND(1.0 * opp_w_pre  / NULLIF(opp_w_pre + opp_l_pre, 0), 3)   AS opp_win_pct_pre,
  team_w_pre + team_l_pre                                   AS games_played_pre,

  CASE
    WHEN team = 'dodgers' AND opponent IN ('San Francisco Giants','San Diego Padres',
                                           'New York Yankees','Los Angeles Angels') THEN 1
    WHEN team = 'angels'  AND (opponent IN ('Los Angeles Dodgers','Houston Astros',
                                            'Texas Rangers','Seattle Mariners')
                               OR opponent LIKE '%Athletics%') THEN 1
    ELSE 0 END                                              AS is_rival,
  CASE WHEN double_header IN ('Y','S') THEN 1 ELSE 0 END    AS is_doubleheader,
  CASE WHEN season = 2021 AND official_date < '2021-06-15'
       THEN 1 ELSE 0 END                                    AS covid_capacity_limit,

  temp_f,
  CASE WHEN temp_f >= 85 THEN 1 ELSE 0 END                  AS is_hot,
  humidity,
  cloud_cover,
  wind_mph
FROM base