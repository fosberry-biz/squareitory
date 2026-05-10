# CLAUDE.md

## What this is

Cubism is a 4-player (or 2-player) turn-based territory game on an 11×11 grid. Players are assigned to an edge — North, East, South, West — and spend turns placing and moving stacks of cubes. Combat is attrition: attacking stacks lose equal cubes to the defender, ties destroy both. The goal is to hold the center cell (5,5) for 10 cumulative turns.

Each turn allows up to 3 actions: place on your starting edge, move a stack to an empty adjacent cell, merge into a friendly stack, or battle an enemy stack. Corner zones generate passive income at end of turn.

The game runs fully in the browser. Players join by sharing a game ID from the lobby. Spectators can watch without a token. All authoritative state lives on the server; the client mirrors game logic only for move preview.

## Current state

All four implementation phases are complete. The game is playable end-to-end: lobby, waiting room with live player count, gameplay via SSE, spectator mode, and 2/4-player modes.

See [`PLAN.md`](PLAN.md) for architecture, schema, API routes, file responsibilities, and phase history.

## Running

```
pip install flask
python app.py
```

Runs at `http://localhost:5000`.
