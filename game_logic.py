SIZE = 11
CX, CY = 5, 5
WIN = 10

_START = [
    lambda r, c: r == 0 and 3 <= c <= 7,              # North
    lambda r, c: c == SIZE - 1 and 3 <= r <= 7,       # East
    lambda r, c: r == SIZE - 1 and 3 <= c <= 7,       # South
    lambda r, c: c == 0 and 3 <= r <= 7,              # West
]


# (blocked, start_n, income_per_turn, farming, gp)
_B  = (True,  0, 0, False, 0)
_O  = (False, 0, 0, False, 0)
_X  = (False, 1, 0, False, 0)
_FX = (False, 1, 1, True,  0)
_I1 = (False, 1, 0, False, 1)  # middle 4: 1 game point/turn, 1 neutral defender
_I2 = (False, 3, 0, False, 2)  # center: 2 game points/turn, 3 neutral defenders
_N = _E = _S = _W = _O

_LAYOUT = [
    [_B,  _B,  _B,  _N,  _N,  _N,  _N,  _N,  _B,  _B,  _B ],
    [_B,  _FX, _X,  _O,  _O,  _O,  _O,  _O,  _X,  _FX, _B ],
    [_B,  _X,  _B,  _O,  _O,  _O,  _O,  _O,  _B,  _X,  _B ],
    [_W,  _O,  _O,  _O,  _O,  _I1, _O,  _O,  _O,  _O,  _E ],
    [_W,  _O,  _O,  _O,  _O,  _O,  _O,  _O,  _O,  _O,  _E ],
    [_W,  _O,  _O,  _I1, _O,  _I2, _O,  _I1, _O,  _O,  _E ],
    [_W,  _O,  _O,  _O,  _O,  _O,  _O,  _O,  _O,  _O,  _E ],
    [_W,  _O,  _O,  _O,  _O,  _I1, _O,  _O,  _O,  _O,  _E ],
    [_B,  _X,  _B,  _O,  _O,  _O,  _O,  _O,  _B,  _X,  _B ],
    [_B,  _FX, _X,  _O,  _O,  _O,  _O,  _O,  _X,  _FX, _B ],
    [_B,  _B,  _B,  _S,  _S,  _S,  _S,  _S,  _B,  _B,  _B ],
]


def make_board():
    board = []
    for r in range(SIZE):
        row = []
        for c in range(SIZE):
            blocked, n, income, farming, gp = _LAYOUT[r][c]
            row.append({'owner': None, 'n': n, 'blocked': blocked, 'income': income, 'farming': farming, 'gp': gp})
        board.append(row)
    return board


def _adj(r1, c1, r2, c2):
    return abs(r1 - r2) <= 1 and abs(c1 - c2) <= 1 and not (r1 == r2 and c1 == c2)


def apply_action(board, action, cur_player):
    """Returns (board, error_or_None). Mutates board in place."""
    t = action.get('type')

    if t == 'place':
        r, c = action.get('r'), action.get('c')
        if not (isinstance(r, int) and isinstance(c, int)):
            return board, 'missing coordinates'
        if not (0 <= r < SIZE and 0 <= c < SIZE):
            return board, 'out of bounds'
        if board[r][c].get('blocked'):
            return board, 'blocked cell'
        if not _START[cur_player](r, c):
            return board, 'not your starting edge'
        cell = board[r][c]
        if not ((cell['owner'] is None and cell['n'] == 0) or cell['owner'] == cur_player):
            return board, 'cannot place there'
        cell['n'] += 1
        cell['owner'] = cur_player
        return board, None

    elif t == 'move':
        fr, fc = action.get('from_r'), action.get('from_c')
        tr, tc = action.get('to_r'), action.get('to_c')
        if not all(isinstance(x, int) for x in [fr, fc, tr, tc]):
            return board, 'missing coordinates'
        if not (0 <= fr < SIZE and 0 <= fc < SIZE and 0 <= tr < SIZE and 0 <= tc < SIZE):
            return board, 'out of bounds'
        if not _adj(fr, fc, tr, tc):
            return board, 'not adjacent'
        src = board[fr][fc]
        dst = board[tr][tc]
        if dst.get('blocked'):
            return board, 'blocked cell'
        if src['owner'] != cur_player or src['n'] == 0:
            return board, 'not your stack'

        if dst['owner'] is None and dst['n'] == 0:
            dst['owner'] = cur_player
            dst['n'] = src['n']
            src['owner'] = None
            src['n'] = 0
        elif dst['owner'] == cur_player:
            dst['n'] += src['n']
            src['owner'] = None
            src['n'] = 0
        else:
            # Battle vs enemy or neutral obstacle
            if src['n'] > dst['n']:
                dst['n'] = src['n'] - dst['n']
                dst['owner'] = cur_player
            elif src['n'] == dst['n']:
                dst['owner'] = None
                dst['n'] = 0
            else:
                dst['n'] = dst['n'] - src['n']
                # dst owner unchanged — defender holds
            src['owner'] = None
            src['n'] = 0
        return board, None

    else:
        return board, f'unknown action type: {t!r}'


def cell_income(board, player):
    """Add income cubes to each cell with income > 0 owned by player."""
    count = 0
    for r in range(SIZE):
        for c in range(SIZE):
            cell = board[r][c]
            if cell.get('income', 0) > 0 and cell['owner'] == player:
                cell['n'] += cell['income']
                count += 1
    return count


def award_game_points(board, player, center_turns):
    """
    Award gp-per-turn for each special cell (middle 4 + center) owned by player.
    Returns (updated_center_turns, winner_or_None).
    """
    center_turns = list(center_turns)
    for r in range(SIZE):
        for c in range(SIZE):
            cell = board[r][c]
            if cell.get('gp', 0) > 0 and cell['owner'] == player:
                center_turns[player] += cell['gp']
    winner = player if center_turns[player] >= WIN else None
    return center_turns, winner


def get_active_players(player_count):
    """[0,1,2,3] for 4-player; [0,2] (North/South) for 2-player."""
    return [0, 1, 2, 3] if player_count == 4 else [0, 2]


def apply_turn(board, actions, cur_player, center_turns, player_count=4):
    """
    Validate and apply all actions for cur_player, then advance turn:
      1. advance cur_player → next active player
      2. corner income for next_player
      3. center check for next_player

    Returns (board, center_turns, next_player, winner_or_None, error_or_None).
    """
    if not isinstance(actions, list):
        return board, center_turns, cur_player, None, 'actions must be a list'
    if len(actions) > 3:
        return board, center_turns, cur_player, None, 'too many actions (max 3)'

    for action in actions:
        board, err = apply_action(board, action, cur_player)
        if err:
            return board, center_turns, cur_player, None, err

    active = get_active_players(player_count)
    idx = active.index(cur_player)
    next_p = active[(idx + 1) % len(active)]
    cell_income(board, next_p)
    center_turns, winner = award_game_points(board, next_p, center_turns)

    return board, center_turns, next_p, winner, None
