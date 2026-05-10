import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / 'cubism.db'
SCHEMA_PATH = Path(__file__).parent / 'schema.sql'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    # Migrate existing DBs that predate player_count column
    cols = [row[1] for row in conn.execute('PRAGMA table_info(games)').fetchall()]
    if 'player_count' not in cols:
        conn.execute('ALTER TABLE games ADD COLUMN player_count INTEGER NOT NULL DEFAULT 4')
        conn.commit()
    conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


# --- Games ---

def create_game(board, center_turns, player_count=4):
    game_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO games (id, board, cur_player, center_turns, turn_number, status, winner, player_count, created_at) '
        'VALUES (?, ?, 0, ?, 0, "waiting", NULL, ?, ?)',
        (game_id, json.dumps(board), json.dumps(center_turns), player_count, _now()),
    )
    conn.commit()
    conn.close()
    return game_id


def get_game(game_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM games WHERE id = ?', (game_id,)).fetchone()
    conn.close()
    if not row:
        return None
    g = dict(row)
    g['board'] = json.loads(g['board'])
    g['center_turns'] = json.loads(g['center_turns'])
    return g


def update_game(game_id, board, cur_player, center_turns, turn_number, status, winner):
    conn = get_db()
    conn.execute(
        'UPDATE games SET board=?, cur_player=?, center_turns=?, turn_number=?, status=?, winner=? '
        'WHERE id=?',
        (json.dumps(board), cur_player, json.dumps(center_turns), turn_number, status, winner, game_id),
    )
    conn.commit()
    conn.close()


# --- Players ---

def add_player(game_id, player_index):
    token = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO players (token, game_id, player_index, joined_at) VALUES (?, ?, ?, ?)',
        (token, game_id, player_index, _now()),
    )
    conn.commit()
    conn.close()
    return token


def get_player(token):
    conn = get_db()
    row = conn.execute('SELECT * FROM players WHERE token = ?', (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def count_players(game_id):
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) FROM players WHERE game_id = ?', (game_id,)).fetchone()[0]
    conn.close()
    return n


# --- Turns ---

def record_turn(game_id, player_index, turn_number, actions):
    conn = get_db()
    conn.execute(
        'INSERT INTO turns (game_id, player_index, turn_number, actions, submitted_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (game_id, player_index, turn_number, json.dumps(actions), _now()),
    )
    conn.commit()
    conn.close()
