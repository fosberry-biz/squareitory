import json
import random
import sqlite3
import string
import uuid
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

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
    # Migrate existing DBs that predate added columns
    cols = [row[1] for row in conn.execute('PRAGMA table_info(games)').fetchall()]
    if 'player_count' not in cols:
        conn.execute('ALTER TABLE games ADD COLUMN player_count INTEGER NOT NULL DEFAULT 4')
    if 'join_code' not in cols:
        conn.execute('ALTER TABLE games ADD COLUMN join_code TEXT')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_games_join_code ON games(join_code)')
    if 'is_public' not in cols:
        conn.execute('ALTER TABLE games ADD COLUMN is_public INTEGER NOT NULL DEFAULT 1')
    if 'turn_seconds' not in cols:
        conn.execute('ALTER TABLE games ADD COLUMN turn_seconds INTEGER')
    if 'turn_started_at' not in cols:
        conn.execute('ALTER TABLE games ADD COLUMN turn_started_at TEXT')
    tcols = [row[1] for row in conn.execute('PRAGMA table_info(turns)').fetchall()]
    if 'elapsed_ms' not in tcols:
        conn.execute('ALTER TABLE turns ADD COLUMN elapsed_ms INTEGER')
    pcols = [row[1] for row in conn.execute('PRAGMA table_info(players)').fetchall()]
    if 'account_id' not in pcols:
        conn.execute('ALTER TABLE players ADD COLUMN account_id TEXT REFERENCES accounts(id)')
    conn.commit()
    conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


# --- Accounts ---

def _random_friend_code():
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=6))


def create_account(username, password):
    account_id = str(uuid.uuid4())
    password_hash = generate_password_hash(password)
    conn = get_db()
    # Retry friend_code on collision (extremely rare)
    for _ in range(10):
        friend_code = _random_friend_code()
        try:
            conn.execute(
                'INSERT INTO accounts (id, username, password_hash, friend_code, created_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (account_id, username, password_hash, friend_code, _now()),
            )
            conn.commit()
            conn.close()
            return account_id, None
        except sqlite3.IntegrityError as e:
            if 'username' in str(e):
                conn.close()
                return None, 'username_taken'
            # friend_code collision — retry
    conn.close()
    return None, 'error'


def get_account(account_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM accounts WHERE id = ?', (account_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_account_by_username(username):
    conn = get_db()
    row = conn.execute('SELECT * FROM accounts WHERE username = ?', (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_account_by_friend_code(friend_code):
    conn = get_db()
    row = conn.execute('SELECT * FROM accounts WHERE friend_code = ?', (friend_code.upper(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_password(account, password):
    return check_password_hash(account['password_hash'], password)


# --- Friendships ---

def add_friendship(account_id, friend_id):
    conn = get_db()
    now = _now()
    try:
        conn.execute(
            'INSERT OR IGNORE INTO friendships (account_id, friend_id, created_at) VALUES (?, ?, ?)',
            (account_id, friend_id, now),
        )
        conn.execute(
            'INSERT OR IGNORE INTO friendships (account_id, friend_id, created_at) VALUES (?, ?, ?)',
            (friend_id, account_id, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_friends(account_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT a.id, a.username, a.friend_code FROM accounts a '
        'JOIN friendships f ON f.friend_id = a.id '
        'WHERE f.account_id = ? ORDER BY a.username',
        (account_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def are_friends(account_id, friend_id):
    conn = get_db()
    row = conn.execute(
        'SELECT 1 FROM friendships WHERE account_id = ? AND friend_id = ?',
        (account_id, friend_id),
    ).fetchone()
    conn.close()
    return row is not None


# --- Games ---

def _random_join_code():
    return str(random.randint(1000, 9999))


def create_game(board, center_turns, player_count=4, is_public=1, turn_seconds=None):
    game_id = str(uuid.uuid4())
    conn = get_db()
    # Find unused 4-digit code
    for _ in range(20):
        code = _random_join_code()
        existing = conn.execute(
            "SELECT 1 FROM games WHERE join_code = ? AND status != 'done'", (code,)
        ).fetchone()
        if not existing:
            break
    else:
        code = None  # fallback: no code if all exhausted (extremely unlikely)
    conn.execute(
        'INSERT INTO games (id, board, cur_player, center_turns, turn_number, status, winner, '
        'player_count, join_code, is_public, turn_seconds, created_at) '
        'VALUES (?, ?, 0, ?, 0, "waiting", NULL, ?, ?, ?, ?, ?)',
        (game_id, json.dumps(board), json.dumps(center_turns), player_count, code, is_public, turn_seconds, _now()),
    )
    conn.commit()
    conn.close()
    return game_id, code


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


def get_game_by_join_code(code):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM games WHERE join_code = ? AND status != 'done'", (code,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    g = dict(row)
    g['board'] = json.loads(g['board'])
    g['center_turns'] = json.loads(g['center_turns'])
    return g


def update_game(game_id, board, cur_player, center_turns, turn_number, status, winner, turn_started_at=None):
    conn = get_db()
    conn.execute(
        'UPDATE games SET board=?, cur_player=?, center_turns=?, turn_number=?, status=?, winner=?, turn_started_at=? '
        'WHERE id=?',
        (json.dumps(board), cur_player, json.dumps(center_turns), turn_number, status, winner, turn_started_at, game_id),
    )
    conn.commit()
    conn.close()


def recycle_join_code(game_id):
    conn = get_db()
    conn.execute('UPDATE games SET join_code = NULL WHERE id = ?', (game_id,))
    conn.commit()
    conn.close()


# --- Players ---

def add_player(game_id, player_index, account_id=None):
    token = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO players (token, game_id, player_index, account_id, joined_at) VALUES (?, ?, ?, ?, ?)',
        (token, game_id, player_index, account_id, _now()),
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

def record_turn(game_id, player_index, turn_number, actions, elapsed_ms=None):
    conn = get_db()
    conn.execute(
        'INSERT INTO turns (game_id, player_index, turn_number, actions, elapsed_ms, submitted_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (game_id, player_index, turn_number, json.dumps(actions), elapsed_ms, _now()),
    )
    conn.commit()
    conn.close()


def remove_player(token):
    conn = get_db()
    conn.execute('DELETE FROM players WHERE token = ?', (token,))
    conn.commit()
    conn.close()


def reset_game(game_id, board, center_turns, cur_player, status, winner, turn_started_at):
    conn = get_db()
    conn.execute(
        'UPDATE games SET board=?, center_turns=?, cur_player=?, turn_number=0, '
        'status=?, winner=?, turn_started_at=? WHERE id=?',
        (json.dumps(board), json.dumps(center_turns), cur_player,
         status, winner, turn_started_at, game_id),
    )
    conn.commit()
    conn.close()