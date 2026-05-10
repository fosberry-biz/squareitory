import json
import os
import queue
import subprocess
import threading
import time
import urllib.request

from flask import (Flask, Response, abort, jsonify, redirect,
                   render_template, request, session, url_for)

import db
import game_logic

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'squareitory-dev-secret-change-in-prod')
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
        'join_code': game.get('join_code'),
        'turn_seconds': game.get('turn_seconds'),
        'turn_started_at': game.get('turn_started_at'),
    }


def _current_account():
    account_id = session.get('account_id')
    if not account_id:
        return None
    return db.get_account(account_id)


# --- Auth routes ---

@app.post('/auth/signup')
def signup():
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    if not username or not password:
        return redirect(url_for('home', error='Username and password required'))
    if len(username) < 2 or len(username) > 20:
        return redirect(url_for('home', error='Username must be 2–20 characters'))
    account_id, err = db.create_account(username, password)
    if err == 'username_taken':
        return redirect(url_for('home', error='Username already taken'))
    if err:
        return redirect(url_for('home', error='Signup failed, try again'))
    session['account_id'] = account_id
    return redirect(url_for('home'))


@app.post('/auth/signin')
def signin():
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    account = db.get_account_by_username(username)
    if not account or not db.verify_password(account, password):
        return redirect(url_for('home', error='Invalid username or password'))
    session['account_id'] = account['id']
    return redirect(url_for('home'))


@app.post('/auth/signout')
def signout():
    session.clear()
    return redirect(url_for('home'))


# --- Friends routes ---

@app.get('/friends')
def friends_page():
    account = _current_account()
    if not account:
        return redirect(url_for('home'))
    friends = db.get_friends(account['id'])
    error = request.args.get('error')
    msg = request.args.get('msg')
    return render_template('friends.html', account=account, friends=friends, error=error, msg=msg)


@app.post('/friends/add')
def add_friend():
    account = _current_account()
    if not account:
        return redirect(url_for('home'))
    code = (request.form.get('friend_code') or '').strip().upper()
    if not code:
        return redirect(url_for('friends_page', error='Enter a friend code'))
    if code == account['friend_code']:
        return redirect(url_for('friends_page', error="That's your own code"))
    friend = db.get_account_by_friend_code(code)
    if not friend:
        return redirect(url_for('friends_page', error='No account found with that code'))
    if db.are_friends(account['id'], friend['id']):
        return redirect(url_for('friends_page', error='Already friends'))
    db.add_friendship(account['id'], friend['id'])
    return redirect(url_for('friends_page', msg=f"Added {friend['username']} as a friend"))


# --- Stats / Games / Players ---

@app.get('/stats')
def stats_page():
    active_count = db.get_active_game_count()
    top_players = db.get_top_players_by_wins()
    return render_template('stats.html', account=_current_account(),
                           active_count=active_count, top_players=top_players)


@app.get('/stats/data')
def stats_data():
    return jsonify(
        active_count=db.get_active_game_count(),
        top_players=db.get_top_players_by_wins(),
    )


@app.get('/games')
def games_page():
    games = db.get_longest_active_games()
    return render_template('games.html', account=_current_account(), games=games)


@app.get('/game/<game_id>/detail')
def game_detail_page(game_id):
    stats = db.get_game_stats(game_id)
    if not stats:
        abort(404)
    return render_template('game_detail.html', account=_current_account(), **stats)


@app.get('/players')
def players_page():
    players = db.get_all_players_with_stats()
    return render_template('players.html', account=_current_account(), players=players)


# --- Home / lobby ---

@app.get('/')
def home():
    account = _current_account()
    error = request.args.get('error')
    return render_template('lobby.html', account=account, error=error)


# --- Game routes ---

@app.post('/game/new')
def new_game():
    body = request.get_json(silent=True) or {}
    player_count = body.get('player_count', 4)
    is_public = 1 if body.get('is_public', True) else 0
    turn_seconds = body.get('turn_seconds')
    if player_count not in (2, 4):
        return jsonify({'error': 'player_count must be 2 or 4'}), 400
    if turn_seconds is not None:
        turn_seconds = int(turn_seconds)
        if not (3 <= turn_seconds <= 60):
            return jsonify({'error': 'turn_seconds must be 3–60'}), 400
    account = _current_account()
    board = game_logic.make_board()
    center_turns = [0, 0, 0, 0]
    game_id, join_code = db.create_game(board, center_turns, player_count, is_public, turn_seconds)
    token = db.add_player(game_id, 0, account['id'] if account else None)
    return jsonify({'game_id': game_id, 'token': token, 'player_index': 0, 'join_code': join_code})


@app.post('/game/<game_id>/join')
def join_game(game_id):
    account = _current_account()
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
    token = db.add_player(game_id, player_index, account['id'] if account else None)
    if n + 1 == player_count:
        db.update_game(game_id, game['board'], active[0], game['center_turns'], 0, 'active', None,
                       turn_started_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    game = db.get_game(game_id)
    _broadcast(game_id, _public(game))
    return jsonify({'game_id': game_id, 'token': token, 'player_index': player_index})


@app.post('/game/join-by-code')
def join_by_code():
    body = request.get_json(silent=True) or {}
    code = str(body.get('code', '')).strip()
    if not code:
        return jsonify({'error': 'No code provided'}), 400
    game = db.get_game_by_join_code(code)
    if not game:
        return jsonify({'error': 'Game not found — check the code'}), 404
    account = _current_account()
    game_id = game['id']
    if game['status'] != 'waiting':
        return jsonify({'error': 'Game already started'}), 400
    n = db.count_players(game_id)
    player_count = game['player_count']
    if n >= player_count:
        return jsonify({'error': 'Game is full'}), 400
    active = game_logic.get_active_players(player_count)
    player_index = active[n]
    token = db.add_player(game_id, player_index, account['id'] if account else None)
    if n + 1 == player_count:
        db.update_game(game_id, game['board'], active[0], game['center_turns'], 0, 'active', None,
                       turn_started_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    game = db.get_game(game_id)
    _broadcast(game_id, _public(game))
    return jsonify({'game_id': game_id, 'token': token, 'player_index': player_index})


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
    elapsed_ms = body.get('elapsed_ms')

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

    db.record_turn(game_id, game['cur_player'], game['turn_number'], actions, elapsed_ms)
    status = 'done' if winner is not None else 'active'
    next_turn_started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) if status == 'active' else None
    db.update_game(game_id, board, next_player, center_turns, game['turn_number'] + 1, status, winner,
                   turn_started_at=next_turn_started)

    game = db.get_game(game_id)
    state = _public(game)
    _broadcast(game_id, state)
    return jsonify(state)


@app.post('/game/<game_id>/rematch')
def rematch(game_id):
    game = db.get_game(game_id)
    if not game:
        return jsonify({'error': 'not found'}), 404
    if game['status'] != 'done':
        return jsonify({'error': 'game not done'}), 400
    body = request.get_json(silent=True) or {}
    token = body.get('token', '')
    player = db.get_player(token) if token else None
    if not player or player['game_id'] != game_id:
        return jsonify({'error': 'invalid token'}), 403
    board = game_logic.make_board()
    center_turns = [0, 0, 0, 0]
    n = db.count_players(game_id)
    player_count = game['player_count']
    active = game_logic.get_active_players(player_count)
    if n >= player_count:
        new_status = 'active'
        turn_started_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    else:
        new_status = 'waiting'
        turn_started_at = None
    db.reset_game(game_id, board, center_turns, active[0], new_status, None, turn_started_at)
    game = db.get_game(game_id)
    state = _public(game)
    _broadcast(game_id, state)
    return jsonify(state)


@app.post('/game/<game_id>/leave')
def leave_game(game_id):
    body = request.get_json(silent=True) or {}
    token = body.get('token', '')
    player = db.get_player(token) if token else None
    if not player or player['game_id'] != game_id:
        return jsonify({'error': 'invalid token'}), 403
    game = db.get_game(game_id)
    if not game or game['status'] != 'done':
        return jsonify({'error': 'can only leave after game ends'}), 400
    db.remove_player(token)
    game = db.get_game(game_id)
    _broadcast(game_id, _public(game))
    return jsonify({'ok': True})


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