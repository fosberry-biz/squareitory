'use strict';

const SIZE = 11;
const CX = 5, CY = 5;
const WIN = 10;

const PLAYERS = [
  { name: 'North', cls: 'p0', startFn: (r, c) => r === 0 && c >= 3 && c <= 7 },
  { name: 'East',  cls: 'p1', startFn: (r, c) => c === SIZE - 1 && r >= 3 && r <= 7 },
  { name: 'South', cls: 'p2', startFn: (r, c) => r === SIZE - 1 && c >= 3 && c <= 7 },
  { name: 'West',  cls: 'p3', startFn: (r, c) => c === 0 && r >= 3 && r <= 7 },
];

// Indices of players actually in this game (set from first SSE state)
let activePlayers = PLAYER_COUNT === 2 ? [0, 2] : [0, 1, 2, 3];

let serverState  = null;
let previewBoard = null;
let pending      = [];   // actions queued this turn
let selected     = null; // {r, c} of selected cell

// timer
let _timerInterval = null;
let _turnDeadline  = null; // absolute ms when current turn expires

const _isSpectator = MY_INDEX === -1;

// --- initial UI setup ---

// rules panel toggle
document.getElementById('rules-btn').onclick = () => {
  document.getElementById('rules-panel').style.display = 'block';
};
document.getElementById('rules-close').onclick = () => {
  document.getElementById('rules-panel').style.display = 'none';
};

// hide player controls for spectators
if (_isSpectator) {
  document.getElementById('submit-btn').style.display = 'none';
  document.getElementById('undo-btn').style.display = 'none';
}

// player indicator (set once at load)
{
  const pi = document.getElementById('player-indicator');
  if (_isSpectator) {
    pi.textContent = 'SPECTATING';
  } else {
    pi.textContent = `YOU · ${PLAYERS[MY_INDEX].name.toUpperCase()}`;
    pi.classList.add('player-indicator-colored', PLAYERS[MY_INDEX].cls);
  }
}

// copy spectate link
document.getElementById('copy-spectate-btn').onclick = () => {
  const url = window.location.origin + '/game/' + GAME_ID;
  navigator.clipboard.writeText(url);
  const btn = document.getElementById('copy-spectate-btn');
  btn.textContent = 'Copied!';
  setTimeout(() => { btn.textContent = 'Copy spectate link'; }, 2000);
};

// rematch
document.getElementById('rematch-btn').onclick = async () => {
  const btn = document.getElementById('rematch-btn');
  btn.disabled = true;
  try {
    await fetch(`/game/${GAME_ID}/rematch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: TOKEN }),
    });
  } finally {
    btn.disabled = false;
  }
};

// leave (opt out of next game)
document.getElementById('leave-btn').onclick = async () => {
  if (!confirm("Leave this game? You'll become a spectator and can rejoin via the game code.")) return;
  const res = await fetch(`/game/${GAME_ID}/leave`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: TOKEN }),
  });
  const d = await res.json();
  if (d.ok) {
    window.location = '/game/' + GAME_ID;
  }
};

// --- helpers ---

function isMyTurn() {
  return serverState
    && serverState.status === 'active'
    && serverState.cur_player === MY_INDEX;
}

function actionsLeft() { return 3 - pending.length; }

function copyBoard(b) { return JSON.parse(JSON.stringify(b)); }

function adj(r1, c1, r2, c2) {
  return Math.abs(r1 - r2) <= 1 && Math.abs(c1 - c2) <= 1 && !(r1 === r2 && c1 === c2);
}

// --- local preview logic (mirrors game_logic.py apply_action) ---

function applyAction(board, action, player) {
  board = copyBoard(board);
  if (action.type === 'place') {
    const cell = board[action.r][action.c];
    if (cell.blocked) return { board: null, error: 'blocked cell' };
    if (!((cell.owner === null && cell.n === 0) || cell.owner === player))
      return { board: null, error: 'cannot place there' };
    cell.n++;
    cell.owner = player;
    return { board, error: null };
  }
  if (action.type === 'move') {
    const { from_r: fr, from_c: fc, to_r: tr, to_c: tc } = action;
    const src = board[fr][fc];
    const dst = board[tr][tc];
    if (dst.blocked) return { board: null, error: 'blocked cell' };
    if (src.owner !== player || src.n === 0)
      return { board: null, error: 'not your stack' };
    if (dst.owner === null && dst.n === 0) {
      dst.owner = player; dst.n = src.n;
      src.owner = null;   src.n = 0;
    } else if (dst.owner === player) {
      dst.n += src.n;
      src.owner = null; src.n = 0;
    } else {
      if (src.n > dst.n) {
        dst.n = src.n - dst.n; dst.owner = player;
      } else if (src.n === dst.n) {
        dst.owner = null; dst.n = 0;
      } else {
        dst.n = dst.n - src.n;
        // defender holds; dst.owner unchanged
      }
      src.owner = null; src.n = 0;
    }
    return { board, error: null };
  }
  return { board: null, error: `unknown action: ${action.type}` };
}

// --- turn flash ---

const _FLASH_COLORS = ['#a93226', '#1f618d', '#1e8449', '#b7950b'];

function showTurnFlash(p, isDone = false, winner = null) {
  const existing = document.querySelector('.turn-flash');
  if (existing) existing.remove();

  const div = document.createElement('div');
  div.className = 'turn-flash';

  if (isDone) {
    div.style.background = winner !== null ? _FLASH_COLORS[winner] : '#333';
    div.style.color = winner === 3 ? '#111' : '#fff';
    div.textContent = winner !== null ? `${PLAYERS[winner].name.toUpperCase()} WINS!` : 'GAME OVER';
  } else {
    div.style.background = _FLASH_COLORS[p];
    div.style.color = p === 3 ? '#111' : '#fff';
    div.textContent = `${PLAYERS[p].name.toUpperCase()}'S TURN`;
  }

  document.body.appendChild(div);
  div.style.opacity = '0';
  requestAnimationFrame(() => {
    div.style.transition = 'opacity 0.3s';
    div.style.opacity = '1';
    setTimeout(() => {
      div.style.opacity = '0';
      setTimeout(() => div.remove(), 300);
    }, 1200);
  });
}

// --- timer ---

function _setCompactTimer(fraction) {
  const fill = document.getElementById('compact-timer-fill');
  const wrap = document.getElementById('compact-timer-wrap');
  if (fraction === null) { wrap.style.visibility = 'hidden'; return; }
  wrap.style.visibility = '';
  const pct = Math.max(0, Math.min(100, fraction * 100));
  fill.style.width = pct + '%';
  fill.style.background = fraction < 0.10 ? '#e74c3c'
                        : fraction < 0.50 ? '#f1c40f'
                        : '#2ecc71';
}

function startTimer(turnStartedAt, turnSeconds) {
  clearInterval(_timerInterval);
  _timerInterval = null;
  _turnDeadline = null;
  if (!turnSeconds || !turnStartedAt) { _setTimerBar(null); return; }

  const startMs = new Date(turnStartedAt).getTime();
  _turnDeadline = startMs + turnSeconds * 1000;

  _timerInterval = setInterval(() => {
    const remaining = _turnDeadline - Date.now();
    if (remaining <= 0) {
      clearInterval(_timerInterval);
      _timerInterval = null;
      _setTimerBar(0);
      if (isMyTurn()) submitTurn();
    } else {
      _setTimerBar(remaining / (turnSeconds * 1000));
    }
  }, 100);
  _setTimerBar((_turnDeadline - Date.now()) / (turnSeconds * 1000));
}

function _setTimerBar(fraction) {
  const bar  = document.getElementById('timer-bar');
  const fill = document.getElementById('timer-fill');
  if (fraction === null) { bar.style.display = 'none'; _setCompactTimer(null); return; }
  bar.style.display = '';
  const pct = Math.max(0, Math.min(100, fraction * 100));
  fill.style.width = pct + '%';
  fill.style.background = fraction < 0.10 ? '#e74c3c'
                        : fraction < 0.50 ? '#f1c40f'
                        : '#2ecc71';
  _setCompactTimer(fraction);
}

// --- click handler ---

function click(r, c) {
  if (!isMyTurn()) return;
  if (actionsLeft() <= 0) return;
  const board  = previewBoard;
  const player = MY_INDEX;
  const cell   = board[r][c];
  if (cell.blocked) return;

  if (selected) {
    const { r: sr, c: sc } = selected;

    // clicking the same cell
    if (sr === r && sc === c) {
      // reinforce if this is own stack in starting zone
      if (PLAYERS[player].startFn(r, c) && cell.owner === player && cell.n > 0) {
        const action = { type: 'place', r, c };
        const res = applyAction(board, action, player);
        if (res.error) { selected = null; render(); return; }
        pending.push(action);
        previewBoard = res.board;
        selected = null;
        if (actionsLeft() === 0) submitTurn();
        else render();
        return;
      }
      selected = null; render(); return;
    }

    if (adj(sr, sc, r, c)) {
      const action = { type: 'move', from_r: sr, from_c: sc, to_r: r, to_c: c };
      const res = applyAction(board, action, player);
      if (res.error) { selected = null; render(); return; }

      pending.push(action);
      previewBoard = res.board;
      selected = null;
      if (actionsLeft() === 0) submitTurn();
      else render();
      return;
    }

    // re-select own stack
    if (cell.owner === player && cell.n > 0) { selected = { r, c }; render(); return; }
    selected = null; render(); return;
  }

  // select own stack immediately
  if (cell.owner === player && cell.n > 0) {
    selected = { r, c }; render(); return;
  }

  // place on empty starting edge cell
  if (PLAYERS[player].startFn(r, c) && cell.owner === null && cell.n === 0) {
    const action = { type: 'place', r, c };
    const res = applyAction(board, action, player);
    if (res.error) return;
    pending.push(action);
    previewBoard = res.board;
    selected = null;
    if (actionsLeft() === 0) submitTurn();
    else render();
  }
}

// --- undo ---

function undoAction() {
  if (pending.length === 0) return;
  pending.pop();
  previewBoard = copyBoard(serverState.board);
  for (const action of pending) {
    const res = applyAction(previewBoard, action, MY_INDEX);
    if (res.board) previewBoard = res.board;
  }
  render();
}

// --- submit ---

async function submitTurn() {
  if (!serverState) return;
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;

  const elapsed_ms = _turnDeadline
    ? Math.max(0, (serverState.turn_seconds * 1000) - (_turnDeadline - Date.now()))
    : null;

  let res;
  try {
    res = await fetch(`/game/${GAME_ID}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: TOKEN, actions: pending, elapsed_ms }),
    });
  } catch {
    btn.disabled = false;
    render();
    return;
  }

  const d = await res.json();
  if (d.error) {
    // roll back preview to last known-good server state
    pending = [];
    previewBoard = copyBoard(serverState.board);
    selected = null;
    render();
    return;
  }

  pending = [];
  // SSE will push the new authoritative state
}

// --- edge bars ---

function updateEdgeBars(state) {
  const dirs = ['n', 'e', 's', 'w'];
  for (let p = 0; p < 4; p++) {
    const bar = document.getElementById(`edge-bar-${dirs[p]}`);
    if (!bar) continue;
    const isActive = activePlayers.includes(p);
    bar.style.visibility = isActive ? '' : 'hidden';
    if (!isActive) continue;

    const fill = bar.querySelector('.bar-fill');
    const label = bar.querySelector('.bar-label');
    const score = state.center_turns[p];
    const pct = Math.min(100, (score / WIN) * 100);

    fill.style.background = _FLASH_COLORS[p];
    label.textContent = `${score}/${WIN}`;

    const horiz = p === 0 || p === 2;
    if (horiz) fill.style.width = pct + '%';
    else fill.style.height = pct + '%';
  }
}

// --- render ---

function render() {
  if (!serverState) return;
  const state  = serverState;
  const board  = previewBoard;
  const cur    = state.cur_player;
  const myTurn = isMyTurn();
  const left   = actionsLeft();

  // grid
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      const cell = board[r][c];
      const div  = document.createElement('div');
      div.className = 'cell';

      if (cell.blocked) {
        div.classList.add('blocked');
      } else {
        // spawn zone tint (shows through when cell is empty)
        for (let p = 0; p < 4; p++) {
          if (PLAYERS[p].startFn(r, c)) { div.classList.add(`spawn-p${p}`); break; }
        }

        if (cell.n > 0) {
          if (cell.owner !== null) {
            div.classList.add(PLAYERS[cell.owner].cls);
          } else {
            div.classList.add('pN', 'neutral');
          }
          const countSpan = document.createElement('span');
          countSpan.className = 'cell-count';
          countSpan.textContent = cell.n;
          div.appendChild(countSpan);
        }
        if (cell.farming) div.classList.add('farming');
        if (cell.income > 0) {
          const badge = document.createElement('span');
          badge.className = 'income-badge';
          badge.textContent = `+${cell.income}`;
          div.appendChild(badge);
        }
        if (cell.gp > 0) {
          const badge = document.createElement('span');
          badge.className = 'gp-badge';
          badge.textContent = `★${cell.gp}`;
          div.appendChild(badge);
        }
        // start-hint on empty cells AND owned occupied cells in starting zone
        if (!selected && myTurn && left > 0 && PLAYERS[MY_INDEX].startFn(r, c) &&
            (cell.n === 0 || cell.owner === MY_INDEX))
          div.classList.add('start-hint');
        if (selected && selected.r === r && selected.c === c)
          div.classList.add('selected');
        if (selected && adj(selected.r, selected.c, r, c) && myTurn && left > 0)
          div.classList.add('reachable');
        if (r === CY && c === CX)
          div.classList.add('center-cell');
      }

      div.addEventListener('click', () => click(r, c));
      grid.appendChild(div);
    }
  }

  // join code — always show
  document.getElementById('join-code-val').textContent = state.join_code || '—';

  // rematch section — players only, when game is done
  if (!_isSpectator) {
    document.getElementById('rematch-section').style.display =
      state.status === 'done' ? '' : 'none';
  }

  // status bar
  let txt;
  if (state.status === 'waiting') {
    txt = `Waiting for players (${state.players_joined}/${state.player_count})`;
  } else if (state.status === 'done') {
    txt = state.winner !== null ? `${PLAYERS[state.winner].name} wins!` : 'Game over';
  } else if (myTurn) {
    txt = selected
      ? `Your turn — ${left} left — click adjacent cell to act`
      : `Your turn — ${left} left — select a stack or place on your edge`;
  } else {
    txt = `${PLAYERS[cur].name}'s turn`;
  }
  document.getElementById('status').textContent = txt;

  // edge progress bars
  updateEdgeBars(state);

  // submit / undo buttons
  const btn = document.getElementById('submit-btn');
  btn.disabled = !myTurn;
  btn.textContent = pending.length > 0 ? `End Turn (${pending.length})` : 'Pass Turn';
  document.getElementById('undo-btn').disabled = !myTurn || pending.length === 0;
}

// --- SSE ---

const es = new EventSource(`/game/${GAME_ID}/stream`);

es.onmessage = e => {
  const prevCurPlayer = serverState ? serverState.cur_player : null;
  const prevStatus    = serverState ? serverState.status : null;

  serverState   = JSON.parse(e.data);
  activePlayers = serverState.player_count === 2 ? [0, 2] : [0, 1, 2, 3];
  pending      = [];
  previewBoard = copyBoard(serverState.board);
  selected     = null;
  render();
  syncCompactStrip(serverState);
  updateDashboardMode();

  const { status, cur_player, winner } = serverState;

  if (status === 'active' && (cur_player !== prevCurPlayer || prevStatus !== 'active')) {
    showTurnFlash(cur_player);
    startTimer(serverState.turn_started_at, serverState.turn_seconds);
  } else if (status === 'done' && prevStatus !== 'done') {
    showTurnFlash(null, true, winner);
    startTimer(null, null);
  } else if (status === 'waiting') {
    startTimer(null, null);
  }
};

es.onerror = () => {
  document.getElementById('status').textContent = 'Connection lost — reconnecting…';
};

document.getElementById('submit-btn').onclick = submitTurn;
document.getElementById('undo-btn').onclick = undoAction;

// --- compact dashboard ---

function updateDashboardMode() {
  const layout = document.getElementById('game-layout');
  const isLandscape = window.innerWidth > window.innerHeight;
  if (isLandscape) {
    layout.classList.remove('compact-dash');
    return;
  }
  const boardH = document.getElementById('board-area').offsetHeight;
  const available = window.innerHeight - 16 - 8 - boardH; // body padding + gap
  if (available < 240) {
    layout.classList.add('compact-dash');
  } else {
    layout.classList.remove('compact-dash');
  }
}

function syncCompactStrip(state) {
  const cur = state.cur_player;
  const turnEl = document.getElementById('compact-turn');
  if (state.status === 'done') {
    turnEl.textContent = state.winner !== null ? `${PLAYERS[state.winner].name.toUpperCase()} WINS` : 'GAME OVER';
    turnEl.className = '';
  } else if (state.status === 'waiting') {
    turnEl.textContent = 'WAITING';
    turnEl.className = '';
  } else {
    const isMe = cur === MY_INDEX;
    turnEl.textContent = isMe ? 'YOUR TURN' : `${PLAYERS[cur].name.toUpperCase()}`;
    turnEl.className = `player-indicator-colored ${PLAYERS[cur].cls}`;
  }

  const gp = state.center_turns || [];
  const gpParts = activePlayers.map(p => `${PLAYERS[p].name[0]}:${gp[p] ?? 0}`);
  document.getElementById('compact-gp').textContent = gpParts.join('  ');
}

document.getElementById('compact-expand-btn').onclick = () => {
  document.getElementById('sidebar').classList.add('open');
};
document.getElementById('dashboard-close-btn').onclick = () => {
  document.getElementById('sidebar').classList.remove('open');
};

window.addEventListener('resize', updateDashboardMode);
updateDashboardMode();
