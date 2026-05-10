import json
import queue
import subprocess
import threading
import time
import urllib.request

from flask import Flask, Response, abort, jsonify, render_template, request

import db
import game_logic

app = Flask(__name__)
db.init_db()

# SSE: game_id -> [Queue, ...]
_subs: dict[str, list[queue.Queue]] = {}
_lock = threading.Lock()


def _subscribe(game_id):
    q = queue.Queue(maxsize=20)
    with _lock:
        _subs.setdefault(game_id, []).append(q)
    return q


def _unsubscribe(game_id, q):
    with _lock:
        lst = _subs.get(game_id, [])
        if q in lst:
            lst.remove(q)


def _broadcast(game_id, state):
    with _lock:
        for q in _subs.get(game_id, []):
            try:
                q.put_nowait(state)
            except queue.Full:
                pass


def _public(game):
    return {
        'board': game['board'],
        'cur_player': game['cur_player'],
        'center_turns': game['center_turns'],
        'turn_number': game['turn_number'],
        'status': game['status'],
        'winner': game['winner'],
        'player_count': game['player_count'],
        'players_joined': db.count_players(game['id']),
    }


# --- Routes ---

@app.get('/')
def lobby():
    return render_template('lobby.html')


@app.post('/game/new')
def new_game():
    body = request.get_json(silent=True) or {}
    player_count = body.get('player_count', 4)
    if player_count not in (2, 4):
        return jsonify({'error': 'player_count must be 2 or 4'}), 400
    board = game_logic.make_board()
    center_turns = [0, 0, 0, 0]
    game_id = db.create_game(board, center_turns, player_count)
    token = db.add_player(game_id, 0)
    return jsonify({'game_id': game_id, 'token': token, 'player_index': 0})


@app.post('/game/<game_id>/join')
def join_game(game_id):
    game = db.get_game(game_id)
    if not game:
        return jsonify({'error': 'game not found'}), 404
    if game['status'] != 'waiting':
        return jsonify({'error': 'game not in waiting state'}), 400
    n = db.count_players(game_id)
    player_count = game['player_count']
    if n >= player_count:
        return jsonify({'error': 'game is full'}), 400
    active = game_logic.get_active_players(player_count)
    player_index = active[n]
    token = db.add_player(game_id, player_index)
    if n + 1 == player_count:
        db.update_game(game_id, game['board'], active[0], game['center_turns'], 0, 'active', None)
    game = db.get_game(game_id)
    _broadcast(game_id, _public(game))
    return jsonify({'token': token, 'player_index': player_index})


@app.get('/game/<game_id>')
def game_page(game_id):
    game = db.get_game(game_id)
    if not game:
        abort(404)
    token = request.args.get('token', '')
    player = db.get_player(token) if token else None
    player_index = player['player_index'] if player else -1
    return render_template('game.html', game_id=game_id, token=token,
                           player_index=player_index, player_count=game['player_count'])


@app.get('/game/<game_id>/state')
def game_state(game_id):
    game = db.get_game(game_id)
    if not game:
        return jsonify({'error': 'not found'}), 404
    return jsonify(_public(game))


@app.post('/game/<game_id>/move')
def submit_move(game_id):
    game = db.get_game(game_id)
    if not game:
        return jsonify({'error': 'game not found'}), 404
    if game['status'] != 'active':
        return jsonify({'error': 'game not active'}), 400

    body = request.get_json(silent=True) or {}
    token = body.get('token', '')
    actions = body.get('actions', [])

    player = db.get_player(token)
    if not player or player['game_id'] != game_id:
        return jsonify({'error': 'invalid token'}), 403
    if player['player_index'] != game['cur_player']:
        return jsonify({'error': 'not your turn'}), 403

    board, center_turns, next_player, winner, err = game_logic.apply_turn(
        game['board'], actions, game['cur_player'], game['center_turns'], game['player_count']
    )
    if err:
        return jsonify({'error': err}), 400

    db.record_turn(game_id, game['cur_player'], game['turn_number'], actions)
    status = 'done' if winner is not None else 'active'
    db.update_game(game_id, board, next_player, center_turns, game['turn_number'] + 1, status, winner)

    game = db.get_game(game_id)
    state = _public(game)
    _broadcast(game_id, state)
    return jsonify(state)


@app.get('/game/<game_id>/stream')
def stream(game_id):
    game = db.get_game(game_id)
    if not game:
        abort(404)

    initial = _public(game)
    q = _subscribe(game_id)

    def generate():
        yield f'data: {json.dumps(initial)}\n\n'
        try:
            while True:
                try:
                    state = q.get(timeout=25)
                    yield f'data: {json.dumps(state)}\n\n'
                except queue.Empty:
                    yield ': keepalive\n\n'
        finally:
            _unsubscribe(game_id, q)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


def start_ngrok(port=5000):
    try:
        proc = subprocess.Popen(
            ['ngrok', 'http', str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print('ngrok not found on PATH — running locally only')
        return None

    for _ in range(40):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=2) as r:
                data = json.loads(r.read())
            tunnels = data.get('tunnels', [])
            url = next(
                (t['public_url'] for t in tunnels if t.get('proto') == 'https'),
                next((t['public_url'] for t in tunnels), None),
            )
            if url:
                print(f'\nPublic URL: {url}\n')
                return proc
        except Exception:
            pass

    print('ngrok started but URL not available — check http://127.0.0.1:4040')
    return proc


if __name__ == '__main__':
    ngrok_proc = start_ngrok()
    try:
        app.run(debug=True, threaded=True, use_reloader=False)
    finally:
        if ngrok_proc:
            ngrok_proc.terminate()
