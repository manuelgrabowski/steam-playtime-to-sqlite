# Steam Playtime to SQLite

A command-line tool to collect Steam playtime information into a SQLite database for easy analysis with [Datasette](#using-with-datasette). Comes with some default report options built-in.

## Requirements

- Python 3.13+
- [Steam Web API key](https://steamcommunity.com/dev/apikey)

## Installation

```shell
pip install steam-playtime-to-sqlite

# Or with uv like the cool kids
uv tool install steam-playtime-to-sqlite

# Or run with uvx for ad-hoc usage
uvx steam-playtime-to-sqlite
```

### From Source

1. Clone the repository
2. ```shell
   pip install .
   
   # Or with uv like the cool kids
   uv install .
   ```

You can also just copy the `steam_playtime.py` file from this repo and use it directly.

## Usage

### First Setup

Initialize the database and import initial state of playtime data:

```shell
steam-playtime-to-sqlite init --api-key YOUR_API_KEY --username STEAM_USERNAME
```

Notes:
- `STEAM_USERNAME` can be either your Steam vanity username or your 64-bit Steam ID
- The tool will create a SQLite database in the current directory by default

### Perpetual Updates

For accurate tracking, you'll need to run the update command daily:

```shell
steam-playtime-to-sqlite update --api-key YOUR_API_KEY --username STEAM_USERNAME
```

See the [How Steam Playtime Tracking Works](#how-steam-playtime-tracking-works) section below for more details.

#### Steam API Options

Both `init` and `update` also take the following two optional parameters:

- `--include-played-free-games true/false`
- `--skip-unvetted-apps true/false`

By default, free games are included and unvetted apps are not skipped. Use either
parameter in case you want to change that behavior. See the [unofficial API docs](https://steamapi.xpaw.me/#IPlayerService/GetOwnedGames)
for more details.

### Available Reports

#### Daily Report

View playtime sessions for a specific day:

```shell
steam-playtime-to-sqlite report daily --day 2025-04-01
```

#### Monthly Report

View playtime summary for a specific month:

```shell
steam-playtime-to-sqlite report monthly --month 2025-03
```

#### Top 10 by Time

View your top 10 most played games by total playtime:

```shell
steam-playtime-to-sqlite report top-time
```

#### Top 10 by Days

View your top 10 most played games by number of days played:

```shell
steam-playtime-to-sqlite report top-days
```

#### Per-Game Report

View detailed playtime history for a specific game:

```shell
steam-playtime-to-sqlite report per-game --appid 570  # 570 is the AppID for Dota 2
```

### Other Options

- Change the database file location:
  ```shell
  steam-playtime-to-sqlite --db /path/to/database.db [command]
  ```

- Change the logging level:
  ```shell
  steam-playtime-to-sqlite --log-level DEBUG [command]
  ```
  Available levels: DEBUG, INFO, WARNING, ERROR

## How Steam Playtime Tracking Works

### Understanding Steam API Limitations

Steam's API doesn't provide granular session data, it only offers cumulative lifetime playtime per game. To work around this limitation, this tool is intended to be run daily and keep historic data. By taking a daily snapshot of total playtime for all your games, it can calculate daily playtime per game by comparing consecutive snapshots.

### Recommended Setup: Daily Cron Job

Ideally, set up a daily cron job to run the update command. By default, the tool saves new data with the date of _yesterday_. I sometimes play a bit past midnight, but I consider that to still count for the day before midnight. By running my cronjob around 6am, I get the most accurate data for my purposes.

Example crontab entry:

```crontab
55 05 * * * steam-playtime-to-sqlite --db /path/to/database.db update --api-key YOUR_API_KEY --username STEAM_USERNAME
```

However, your mileage may vary. If you prefer running a cronjob right at 23:59 each day, you may want to use the `--date` parameter to specify the date of today for the new entries.

### What Happens If You Miss Updates?

While the `--date` parameter sounds like backfilling might be possible, Steam simply doesn't provide data with the historical accuracy needed for that. However, should better APIs or data sources become available, backfilling directly into the SQLite database will be feasible.

## Using with Datasette

This tool was designed to work well with [Datasette](https://datasette.io/) in case you want to do any more specific analysis.

1. Install Datasette:
   ```shell
   pip install datasette

   # Or run with uvx for ad-hoc usage
   uvx datasette
   ```

2. Run Datasette with your Steam playtime database:
   ```shell
   datasette steam_playtime.db
   ```

Check the queries for existing reports in the source for inspiration.

### Data Storage / Model

Data is stored locally in a SQLite database. By default, it is named `steam_playtime.db` and put in the working directory. The database contains two tables:

- `games`: Stores game metadata (app ID and name)
- `sessions`: Stores daily playtime snapshots for each game