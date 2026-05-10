# CLAUDE.md

## What this is

Cubism is a 4-player (or 2-player) turn-based territory game on an 11×11 grid. Players are assigned to an edge — North, East, South, West — and spend turns placing and moving stacks of cubes. Combat is attrition: attacking stacks lose equal cubes to the defender, ties destroy both. The goal is to hold the center cells, which generate game points, for 10 cumulative turns.

Each turn allows up to 3 actions: place on your starting edge, move a stack to an empty adjacent cell, merge into a friendly stack, add cube to a stack in Home, or battle an enemy stack. Corner zones stack cubes passively at end of turn.

The game is deployed on PythonAnywhere. Testing is conducted via localhost. Players join by sharing a game ID from the lobby. Spectators can watch without a token. All authoritative state lives on the server; the client mirrors game logic only for move preview.