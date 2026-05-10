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

let serverState    = null;
let previewBoard   = null;
let pending        = [];   // actions queued this turn
let selected       = null; // {r, c} of selected cell
let logs           = [];
let _pendingSelect = null; // debounce state for double-click-to-reinforce

function _cancelPendingSelect() {
  if (_pendingSelect) { clearTimeout(_pendingSelect.timer); _pendingSelect = null; }
}

// rules panel toggle
document.getElementById('rules-btn').onclick = () => {
  document.getElementById('rules-panel').style.display = 'block';
};
document.getElementById('rules-close').onclick = () => {
  document.getElementById('rules-panel').style.display = 'none';
};

// spectator setup (MY_INDEX === -1 means no token)
if (MY_INDEX === -1) {
  document.getElementById('spectator-badge').style.display = '';
  document.getElementById('submit-btn').style.display = 'none';
}

// player indicator
{
  const pi = document.getElementById('player-indicator');
  if (MY_INDEX === -1) {
    pi.textContent = 'Spectating';
  } else {
    pi.textContent = `You are: ${PLAYERS[MY_INDEX].name}`;
    pi.classList.add('player-indicator-colored', PLAYERS[MY_INDEX].cls);
  }
}

document.getElementById('copy-join-btn').onclick = () => {
  const code = document.getElementById('waiting-join-code').textContent;
  if (code) navigator.clipboard.writeText(code);
  const btn = document.getElementById('copy-join-btn');
  btn.textContent = 'Copied!';
  setTimeout(() => { btn.textContent = 'Copy code'; }, 2000);
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

// --- log ---

function logMsg(msg) {
  logs.push(msg);
  if (logs.length > 30) logs.shift();
  document.getElementById('log').innerHTML =
    logs.slice().reverse().map(l => `<div>${l}</div>`).join('');
}

// --- click handler ---

function click(r, c) {
  if (!isMyTurn()) return;
  if (actionsLeft() <= 0) { logMsg('No actions remaining'); return; }
  const board  = previewBoard;
  const player = MY_INDEX;
  const cell   = board[r][c];
  if (cell.blocked) return;

  // cancel pending select when clicking a different cell
  if (_pendingSelect && !(_pendingSelect.r === r && _pendingSelect.c === c)) {
    _cancelPendingSelect();
  }

  if (selected) {
    const { r: sr, c: sc } = selected;

    if (sr === r && sc === c) { selected = null; render(); return; }

    if (adj(sr, sc, r, c)) {
      const src = board[sr][sc];
      const dst = board[r][c];
      const action = { type: 'move', from_r: sr, from_c: sc, to_r: r, to_c: c };
      const res = applyAction(board, action, player);
      if (res.error) { logMsg(`Error: ${res.error}`); selected = null; render(); return; }

      if (dst.owner === null && dst.n === 0)
        logMsg(`${PLAYERS[player].name} moves (${sr},${sc}) → (${r},${c})`);
      else if (dst.owner === player)
        logMsg(`${PLAYERS[player].name} merges → (${r},${c}) now ${res.board[r][c].n}`);
      else {
        const before = dst.n, atk = src.n;
        const after  = res.board[r][c];
        if (after.n === 0)
          logMsg(`${PLAYERS[player].name} ties at (${r},${c}) — both destroyed`);
        else if (after.owner === player)
          logMsg(`${PLAYERS[player].name} captures (${r},${c})! ${atk} vs ${before} → ${after.n}`);
        else
          logMsg(`${PLAYERS[player].name} attacks (${r},${c}) — fails, defender: ${after.n}`);
      }

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

  // select own stack; double-click/tap on starting-zone cell to reinforce
  if (cell.owner === player && cell.n > 0) {
    if (PLAYERS[player].startFn(r, c)) {
      if (_pendingSelect && _pendingSelect.r === r && _pendingSelect.c === c) {
        // second click within window — reinforce
        _cancelPendingSelect();
        const action = { type: 'place', r, c };
        const res = applyAction(board, action, player);
        if (res.error) { logMsg(`Error: ${res.error}`); return; }
        logMsg(`${PLAYERS[player].name} reinforces (${r},${c}) — stack ${res.board[r][c].n}`);
        pending.push(action);
        previewBoard = res.board;
        selected = null;
        if (actionsLeft() === 0) submitTurn();
        else render();
        return;
      }
      // first click — wait to see if double-click arrives
      _cancelPendingSelect();
      _pendingSelect = {
        r, c,
        timer: setTimeout(() => {
          _pendingSelect = null;
          selected = { r, c };
          render();
        }, 280)
      };
      return;
    }
    selected = { r, c }; render(); return;
  }

  // place on empty starting edge cell
  if (PLAYERS[player].startFn(r, c) && cell.owner === null && cell.n === 0) {
    const action = { type: 'place', r, c };
    const res = applyAction(board, action, player);
    if (res.error) { logMsg(`Error: ${res.error}`); return; }
    logMsg(`${PLAYERS[player].name} places at (${r},${c}) — stack ${res.board[r][c].n}`);
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

  let res;
  try {
    res = await fetch(`/game/${GAME_ID}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: TOKEN, actions: pending }),
    });
  } catch {
    logMsg('Network error — try again');
    btn.disabled = false;
    render();
    return;
  }

  const d = await res.json();
  if (d.error) {
    logMsg(`Server: ${d.error}`);
    // roll back preview to last known-good server state
    pending = [];
    previewBoard = copyBoard(serverState.board);
    selected = null;
    render();
    return;
  }

  logMsg(`Turn submitted (${pending.length} action${pending.length !== 1 ? 's' : ''})`);
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

  // waiting-info panel
  const waitingInfo = document.getElementById('waiting-info');
  if (state.status === 'waiting') {
    waitingInfo.style.display = '';
    document.getElementById('waiting-join-code').textContent = state.join_code || GAME_ID;
  } else {
    waitingInfo.style.display = 'none';
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
  pending       = [];
  previewBoard  = copyBoard(serverState.board);
  selected      = null;
  _cancelPendingSelect();
  render();

  const { status, cur_player, winner } = serverState;

  if (status === 'active' && cur_player !== prevCurPlayer) {
    showTurnFlash(cur_player);
  } else if (status === 'done' && prevStatus !== 'done') {
    showTurnFlash(null, true, winner);
  }

  if (status === 'waiting') {
    logMsg('Waiting for more players to join…');
  } else if (status === 'done') {
    logMsg(`*** ${PLAYERS[winner].name} WINS! ***`);
  } else if (cur_player === MY_INDEX) {
    logMsg('--- Your turn ---');
  } else {
    logMsg(`--- ${PLAYERS[cur_player].name}'s turn ---`);
  }
};

es.onerror = () => {
  document.getElementById('status').textContent = 'Connection lost — reconnecting…';
};

document.getElementById('submit-btn').onclick = submitTurn;
document.getElementById('undo-btn').onclick = undoAction;
