# CLAUDE.md



---

## What this is

Cubism is a 4-player (or 2-player) turn-based territory game on an 11×11 grid. Players are assigned to an edge — North, East, South, West — and spend turns placing and moving stacks of cubes. Combat is attrition: attacking stacks lose equal cubes to the defender, ties destroy both. The goal is to hold the center cells, which generate game points, for 10 cumulative turns.

Each turn allows up to 3 actions: place on your starting edge, move a stack to an empty adjacent cell, merge into a friendly stack, add cube to a stack in Home, or battle an enemy stack. Corner zones stack cubes passively at end of turn.

The game is deployed on PythonAnywhere. Testing is conducted via localhost. Players join by sharing a game ID from the lobby. Spectators can watch without a token. All authoritative state lives on the server; the client mirrors game logic only for move preview.

---

## What we are doing

We are in feature mode. Anything asked by the user should be answered with the following steps.

**1. Read back** Explain the goal back to the user for confirmation.
**2. Explore** Use the agent skill to explore relevant parts of the codebase with basic context of the ask. Agent should return 500 words of relevant context.
**3. TODO** Use the Write ToDo tool to plan out the changes.
**4. Execute** Execute the changes from the ToDo.
**5. User Test** Ask the user to test and confirm.
**6. Commit** On confirmation, commit changes to main and push to GitHub.

---