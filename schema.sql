CREATE TABLE IF NOT EXISTS games (
    id          TEXT PRIMARY KEY,
    board       TEXT NOT NULL,
    cur_player  INTEGER NOT NULL DEFAULT 0,
    center_turns TEXT NOT NULL DEFAULT '[0,0,0,0]',
    turn_number INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'waiting',
    winner      INTEGER,
    player_count INTEGER NOT NULL DEFAULT 4,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    token        TEXT PRIMARY KEY,
    game_id      TEXT NOT NULL REFERENCES games(id),
    player_index INTEGER NOT NULL,
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
