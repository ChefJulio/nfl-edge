# Historical data kept in the repo

- `538_playoff_games.csv`: playoff games 1933-1998 (the `playoff == 1` rows, seasons before 1999) of FiveThirtyEight's
  `nfl_games.csv` (https://github.com/fivethirtyeight/nfl-elo-game, MIT license, (c) ABC News Internet Ventures).
  Columns: date, season, neutral, team1 (home), team2, score1, score2. Team codes are today's franchises; AFL and AAFC
  games are included (labeled by tools/playoffs_build.py).
- `seeds_1975_1998.json`: playoff seeds per season from each season's Wikipedia "NFL playoffs" page (seeds block),
  fetched once by `tools/playoffs_build.py --fetch-seeds`.
