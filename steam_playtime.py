import argparse
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('steam_playtime')

STEAM_API_URL = 'https://api.steampowered.com'

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Steam Playtime Tracker')
    parser.add_argument('--db', default='steam_playtime.db', help='Path to SQLite database file')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO', help='Set the logging level')
    subparsers = parser.add_subparsers(dest='command', required=True)

    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument('--api-key', required=True, help='Steam Web API key')
    base_parser.add_argument('--username', required=True,
        help='Steam vanity username or 64-bit ID')
    base_parser.add_argument('--include-played-free-games',
        type=lambda x: x.lower() in ('true', '1', 'yes', 'y'), 
        default=True, help='Include free games (default: true)')
    base_parser.add_argument('--skip-unvetted-apps',
        type=lambda x: x.lower() in ('true', '1', 'yes', 'y'),
        default=False, help='Skip unvetted apps (default: false)')

    init_parser = subparsers.add_parser('init', parents=[base_parser],
        help='Initialize the database and import current data')
    init_parser.add_argument('--date', type=str,
        help='Date to attribute the data to (YYYY-MM-DD)')

    update_parser = subparsers.add_parser('update', parents=[base_parser],
        help='Update playtime data')
    update_parser.add_argument('--date', type=str,
        help='Date to attribute the data to (YYYY-MM-DD)')

    report_parser = subparsers.add_parser('report', help='Generate reports')
    report_parser.add_argument('type',
        choices=['daily', 'monthly', 'top-time', 'top-days', 'per-game'], help='Type of report')
    report_parser.add_argument('--day', type=str, help='Date (YYYY-MM-DD) for daily report')
    report_parser.add_argument('--month', type=str, help='Month (YYYY-MM) for monthly report')
    report_parser.add_argument('--appid', type=int, help='App ID for per-game report')

    return parser.parse_args()

def setup_db(db_path: str) -> None:
    """Set up the database schema if it doesn't exist."""
    try:
        if os.path.exists(db_path):
            logger.info(f"Database already exists at {db_path}")
            return
        
        logger.info(f"Creating new database at {db_path}")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute('''
            CREATE TABLE IF NOT EXISTS games (
                appid INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                date DATE NOT NULL,
                appid INTEGER NOT NULL,
                playtime_minutes INTEGER NOT NULL,
                PRIMARY KEY (date, appid),
                FOREIGN KEY (appid) REFERENCES games(appid)
            )
        ''')

        conn.commit()
        logger.info("Database schema created successfully")
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        raise

def resolve_vanity_url(api_key: str, username: str) -> int:
    """
    Resolve a Steam username to a 64-bit Steam ID if necessary.
    """
    if username.isdigit():
        logger.debug(f"Username is already a numeric ID: {username}")
        return int(username)
    
    try:
        logger.info(f"Resolving vanity URL for username: {username}")
        url = f"{STEAM_API_URL}/ISteamUser/ResolveVanityURL/v1/"
        params = {'key': api_key, 'vanityurl': username}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        
        response = resp.json().get('response', {})
        if response.get('success') != 1:
            error_msg = response.get('message', 'Unknown error')
            raise ValueError(f"Failed to resolve vanity URL: {error_msg}")
        
        steam_id = response.get('steamid')
        logger.info(f"Resolved username to Steam ID: {steam_id}")
        return int(steam_id)
    except requests.RequestException as e:
        logger.error(f"API request error: {e}")
        raise
    except (ValueError, KeyError) as e:
        logger.error(f"Failed to parse API response: {e}")
        raise

def fetch_owned_games(api_key: str, steam_id: int, include_played_free_games: bool = True,
    skip_unvetted_apps: bool = False) -> list[dict[str, Any]]:
    """Fetch the list of owned games for a Steam ID."""
    try:
        logger.info(f"Fetching owned games for Steam ID: {steam_id}")
        url = f"{STEAM_API_URL}/IPlayerService/GetOwnedGames/v1/"
        params = {
            'key': api_key,
            'steamid': str(steam_id),
            'include_appinfo': '1',
            'include_played_free_games': str(int(include_played_free_games)),
            'skip_unvetted_apps': str(int(skip_unvetted_apps)),
        }
        logger.debug(f"Params: {params}")
        
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        
        data = resp.json()
        games = data.get('response', {}).get('games') or []
        
        if not games:
            logger.warning(f"No games found for Steam ID: {steam_id}")
        else:
            logger.info(f"Found {len(games)} games for Steam ID: {steam_id}")
        
        return games
    except requests.RequestException as e:
        logger.error(f"API request error: {e}")
        raise
    except (ValueError, KeyError) as e:
        logger.error(f"Failed to parse API response: {e}")
        raise

def import_data(db_path: str, api_key: str, steam_id: int, date_str: str,
    include_played_free_games: bool = True, skip_unvetted_apps: bool = False) -> None:
    """Import game data into the database for the specified date."""
    try:
        games = fetch_owned_games(api_key, steam_id, include_played_free_games, skip_unvetted_apps)
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for game in games:
            appid = game['appid']
            name = game['name']
            # playtime_forever is already in minutes according to the Steam API
            playtime = game.get('playtime_forever', 0)

            # Insert/update game info
            cur.execute('INSERT OR REPLACE INTO games (appid, name) VALUES (?, ?)', (appid, name))
            
            # Insert/update session data
            cur.execute('''
                INSERT OR REPLACE INTO sessions (date, appid, playtime_minutes) 
                VALUES (?, ?, ?)
            ''', (date_str, appid, playtime))

        conn.commit()
        logger.info(f"Successfully imported data for {len(games)} games")
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error during import: {e}")
        raise
    except Exception as e:
        logger.error(f"Error during data import: {e}")
        raise

def get_previous_playtime(db_path: str, appid: int, date_str: str) -> int:
    """Get the playtime for a game from the most recent session before a given date."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        cur = conn.cursor()
        cur.execute('''
            SELECT playtime_minutes FROM sessions 
            WHERE appid = ? AND date < ? 
            ORDER BY date DESC LIMIT 1
        ''', (appid, date_str))
        row = cur.fetchone()
        if row:
            playtime = row['playtime_minutes']
            logger.debug(f"Found previous playtime for app {appid}: {playtime} minutes")
            return int(playtime)
        else:
            logger.debug(f"No previous playtime found for app {appid}")
            return 0
    except sqlite3.Error as e:
        logger.error(f"Database error fetching previous playtime: {e}")
        raise

def report_daily(db_path: str, date_str: str) -> None:
    """Generate a session report for a specific day."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Get sessions for the specified date
        cur.execute('''
            SELECT s.appid, g.name, s.playtime_minutes 
            FROM sessions s 
            JOIN games g ON s.appid = g.appid 
            WHERE s.date = ?
        ''', (date_str,))
        rows = cur.fetchall()

        if not rows:
            print(f"No play sessions found for {date_str}")
            return

        print(f"Play sessions on {date_str}:")
        played_today = False
        
        for row in rows:
            prev = get_previous_playtime(db_path, row['appid'], date_str)
            delta = row['playtime_minutes'] - prev
            if delta > 0:
                played_today = True
                print(f"- {row['name']}: {delta} mins")
        
        if not played_today:
            print("No games were played on this date.")
            
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error in daily report: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating daily report: {e}")
        raise

def report_monthly(db_path: str, month_str: str) -> None:
    """Generate a playtime report for a specific month."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Find the first and last day of the month
        month_start = f"{month_str}-01"
        
        # Get the next month to calculate the end date
        year, month = map(int, month_str.split('-'))
        if month == 12:
            next_month = f"{year+1}-01-01"
        else:
            next_month = f"{year}-{month+1:02d}-01"
        
        # Get all game sessions in the month, ordered by date
        cur.execute('''
            WITH monthly_data AS (
                SELECT 
                    g.name, 
                    s.appid,
                    s.date,
                    s.playtime_minutes,
                    LAG(s.playtime_minutes) OVER (
                        PARTITION BY s.appid
                        ORDER BY s.date
                    ) AS prev_playtime
                FROM sessions s
                JOIN games g ON s.appid = g.appid
                WHERE s.date >= ? AND s.date < ?
                ORDER BY s.date
            )
            SELECT 
                name, 
                appid,
                SUM(CASE WHEN prev_playtime IS NULL THEN playtime_minutes 
                     ELSE MAX(0, playtime_minutes - prev_playtime) END) AS total_minutes
            FROM monthly_data
            GROUP BY appid
            HAVING total_minutes > 0
            ORDER BY total_minutes DESC
        ''', (month_start, next_month))
        
        rows = cur.fetchall()
        
        if not rows:
            print(f"No play sessions found for {month_str}")
            return
            
        print(f"Monthly report for {month_str}:")
        for row in rows:
            print(f"- {row['name']}: {row['total_minutes']} mins")
        
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error in monthly report: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating monthly report: {e}")
        raise

def report_top_time(db_path: str) -> None:
    """Generate a report of the top 10 most played games by total playtime."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute('''
            SELECT g.name, MAX(s.playtime_minutes) as max_playtime
            FROM sessions s
            JOIN games g ON s.appid = g.appid
            GROUP BY s.appid
            ORDER BY max_playtime DESC
            LIMIT 10
        ''')

        rows = cur.fetchall()
        
        if not rows:
            print("No playtime data found")
            return
            
        print("Top 10 most played games by total time:")
        for row in rows:
            print(f"- {row['name']}: {row['max_playtime']} mins")
        
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error in top-time report: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating top-time report: {e}")
        raise

def report_top_days(db_path: str) -> None:
    """Generate a report of the top 10 games by number of days played."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Find days where playtime increased for each game
        cur.execute('''
            WITH daily_deltas AS (
                SELECT 
                    s1.appid,
                    s1.date,
                    s1.playtime_minutes - COALESCE((
                        SELECT s2.playtime_minutes 
                        FROM sessions s2 
                        WHERE s2.appid = s1.appid AND s2.date < s1.date 
                        ORDER BY s2.date DESC LIMIT 1
                    ), 0) AS daily_minutes
                FROM sessions s1
            )
            SELECT g.name, COUNT(*) AS days_played
            FROM daily_deltas d
            JOIN games g ON d.appid = g.appid
            WHERE d.daily_minutes > 0
            GROUP BY d.appid
            ORDER BY days_played DESC
            LIMIT 10
        ''')

        rows = cur.fetchall()
        
        if not rows:
            print("No playtime data found")
            return
            
        print("Top 10 most played games by number of days played:")
        for row in rows:
            print(f"- {row['name']}: {row['days_played']} days")
        
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error in top-days report: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating top-days report: {e}")
        raise

def report_per_game(db_path: str, appid: int) -> None:
    """Generate a detailed report for a specific game."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Get game name
        cur.execute('SELECT name FROM games WHERE appid = ?', (appid,))
        name_row = cur.fetchone()
        if not name_row:
            print(f"Game with appid {appid} not found in the database.")
            return
            
        name = name_row['name']
        
        # Get all sessions for this game, ordered by date
        cur.execute('''
            SELECT 
                s1.date, 
                s1.playtime_minutes,
                s1.playtime_minutes - COALESCE((
                    SELECT s2.playtime_minutes 
                    FROM sessions s2 
                    WHERE s2.appid = s1.appid AND s2.date < s1.date 
                    ORDER BY s2.date DESC LIMIT 1
                ), 0) AS daily_minutes
            FROM sessions s1
            WHERE s1.appid = ?
            ORDER BY s1.date
        ''', (appid,))
        
        rows = cur.fetchall()
        
        if not rows:
            print(f"No session data found for {name}")
            return
            
        print(f"Sessions for {name} (AppID: {appid}):")
        total_played = 0
        days_played = 0
        
        for row in rows:
            delta = row['daily_minutes']
            if delta > 0:
                days_played += 1
                total_played += delta
                print(f"- {row['date']}: {delta} mins")
        
        if days_played == 0:
            print("No play sessions recorded.")
        else:
            print("\nSummary:")
            print(f"Total days played: {days_played}")
            print(f"Total playtime: {total_played} mins")
            print(f"Average session: {total_played / days_played:.1f} mins")
        
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error in per-game report: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating per-game report: {e}")
        raise

def main() -> None:
    """Main entry point for Steam Playtime to SQLite."""
    try:
        args = parse_args()
        db_path = args.db
        
        if hasattr(args, 'log_level'):
            logger.setLevel(getattr(logging, args.log_level))
        
        if args.command in ('init', 'update'):
            # By default, use yesterday's date
            update_date = args.date or (datetime.today() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            if args.command == 'init':
                logger.info("Initializing database")
                setup_db(db_path)
            
            logger.info(f"Updating playtime data for {update_date}")
            steam_id = resolve_vanity_url(args.api_key, args.username)
            import_data(db_path, args.api_key, steam_id, update_date, 
                       args.include_played_free_games, args.skip_unvetted_apps)
            logger.info("Update completed successfully")
            
        elif args.command == 'report':
            if args.type == 'daily':
                if not args.day:
                    logger.error("--day YYYY-MM-DD required for daily report")
                    return
                report_daily(db_path, args.day)
                
            elif args.type == 'monthly':
                if not args.month:
                    logger.error("--month YYYY-MM required for monthly report")
                    return
                report_monthly(db_path, args.month)
                
            elif args.type == 'top-time':
                report_top_time(db_path)
                
            elif args.type == 'top-days':
                report_top_days(db_path)
                
            elif args.type == 'per-game':
                if not args.appid:
                    logger.error("--appid required for per-game report")
                    return
                report_per_game(db_path, args.appid)
    
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
