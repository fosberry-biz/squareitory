CREATE TABLE IF NOT EXISTS accounts (
    id           TEXT PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    friend_code  TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS friendships (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    friend_id  TEXT NOT NULL REFERENCES accounts(id),
    created_at TEXT NOT NULL,
    UNIQUE(account_id, friend_id)
);

CREATE TABLE IF NOT EXISTS games (
    id           TEXT PRIMARY KEY,
    board        TEXT NOT NULL,
    cur_player   INTEGER NOT NULL DEFAULT 0,
    center_turns TEXT NOT NULL DEFAULT '[0,0,0,0]',
    turn_number  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'waiting',
    winner       INTEGER,
    player_count INTEGER NOT NULL DEFAULT 4,
    join_code    TEXT UNIQUE,
    is_public    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    token        TEXT PRIMARY KEY,
    game_id      TEXT NOT NULL REFERENCES games(id),
    player_index INTEGER NOT NULL,
    account_id   TEXT REFERENCES accounts(id),
    joined_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      TEXT NOT NULL REFERENCES games(id),
    player_index INTEGER NOT NULL,
    turn_number  INTEGER NOT NULL,
    actions      TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);