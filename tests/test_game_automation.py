"""Offline safety/recognition tests. These never connect to X11 or send input."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("game_automation", Path(__file__).resolve().parents[1] / "tools/game_automation.py")
game = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(game)


def args(tmp_path, execute=False):
    return SimpleNamespace(artifacts=tmp_path, execute=execute, window_id=None, tessdata=None, languages="rus+eng")


@pytest.mark.parametrize("text,state", [
    ("Helldivers 2 Нажмите любую кнопку", "startup"),
    ("HELLDIVERS 2 PRESS ANY KEY", "startup"),
    ("ПРОДОЛЖИТЬ НАСТРОЙКИ ВЫЙТИ", "menu"),
    ("ARMORY EQUIPMENT WEAPONS CHARACTER", "armory"),
    ("АРСЕНАЛ СНАРЯЖЕНИЕ ОРУЖИЕ ПЕРСОНАЖ", "armory"),
    ("АРСЕНАЛ РЕЙТИНГ БРОНИ СКОРОСТЬ ВОССТ. ВЫНОСЛИВОСТИ ПРИМЕНИТЬ", "equipment"),
    ("ARMORY ARMOR RATING SPEED PASSIVE COMPARE", "equipment"),
    ("ACQUISITIONS SOCIAL", "ship"),
    ("ПРИОБРЕТЕНИЯ СВОДКИ", "ship"),
    ("КСЭ Предвестник превосходства ПРИОБРЕТ СОЦСЕТИ КОМАНДИР", "ship"),
    ("ARMOR VARIANTS Preview foundation armor is unchanged", "unknown"),
    ("АРСЕНАЛ", "unknown"),
    ("PRESS ANY KEY", "unknown"),
    ("ACQUISITIONS", "unknown"),
    ("Loading Helldivers 2", "unknown"),
    ("", "unknown"),
])
def test_classifier_requires_independent_ui_evidence(text, state):
    assert game.classify(text)["state"] == state


def test_game_identity_rejects_browser_and_shader_preparation():
    assert game.game_identity("HELLDIVERS™ 2")
    assert game.game_identity("HELLDIVERS 2")
    assert not game.game_identity("HELLDIVERS 2 - Brave", "brave-browser")
    assert not game.game_identity("HELLDIVERS 2", "brave-browser")
    assert not game.game_identity("Processing Vulkan shaders", "steam")
    assert not game.game_identity("Steam")


@pytest.mark.parametrize("action", [
    {"kind": "key", "key": "F4"},
    {"kind": "key", "key": "w", "duration": 3.01},
    {"kind": "key", "key": "w", "duration": 0},
    {"kind": "click", "x": 1.01, "y": 0},
    {"kind": "click", "x": -.01, "y": 0},
    {"kind": "click", "x": float("nan"), "y": 0},
    {"kind": "look", "dx": 601, "dy": 0},
    {"kind": "look", "dx": 0, "dy": 0.1},
    {"kind": "wait", "duration": 11},
    {"kind": "shell", "command": "arbitrary"},
])
def test_input_bounds(action):
    with pytest.raises(game.AutomationError):
        game.validate_action(action)


def word(text, x=100, y=100, confidence=90):
    return {"text": text, "confidence": confidence, "left": x, "top": y, "width": 100, "height": 20}


def test_unique_confident_text_target():
    assert game.text_target([word("СНАРЯЖЕНИЕ")], "СНАРЯЖЕНИЕ", 1000, 1000) == (.15, .11)
    with pytest.raises(game.AutomationError):
        game.text_target([word("APPLY"), word("APPLY", 300)], "APPLY", 1000, 1000)
    with pytest.raises(game.AutomationError):
        game.text_target([word("APPLY", confidence=25)], "APPLY", 1000, 1000)
    with pytest.raises(game.AutomationError):
        game.text_target([word("ARMOR"), word("RATING", y=400)], "ARMOR RATING", 1000, 1000)


def test_action_dry_run_never_opens_input_backend(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path))
    monkeypatch.setattr(session, "input_window", lambda: pytest.fail("opened input backend in dry-run"))
    result = session.action({"kind": "key", "key": "w"}, ["ship"], {"state": "ship", "path": "frame.png"})
    assert result["dry_run"]


def test_wrong_screen_never_opens_input_backend(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    monkeypatch.setattr(session, "input_window", lambda: pytest.fail("opened input backend for wrong state"))
    monkeypatch.setattr(session, "assert_focus", lambda: None)
    monkeypatch.setattr(session, "observe", lambda: {"state":"unknown","path":"frame.png"})
    with pytest.raises(game.AutomationError, match="no input sent"):
        session.action({"kind": "key", "key": "w"}, ["ship"], {"state": "unknown", "path": "frame.png"})


def test_pressed_key_always_released_on_focus_loss(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    events = []
    session.x11 = SimpleNamespace(key_event=lambda key, down: events.append((key, down)))
    monkeypatch.setattr(session, "input_window", lambda: {"id": 77})
    def lose_focus(*_):
        raise game.AutomationError("focus lost")
    monkeypatch.setattr(session, "wait_guarded", lose_focus)
    with pytest.raises(game.AutomationError, match="focus lost"):
        session.action({"kind": "key", "key": "w", "duration": 1}, ["ship"], {"state": "ship", "path": "frame.png"})
    assert events == [("w", True), ("w", False)]


def test_pressed_mouse_always_released_on_interrupt(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    events = []
    session.x11 = SimpleNamespace(geometry=lambda _: (0, 0, 1920, 1080),
        raise_window=lambda *_:None, move_to_window=lambda *_: None, button=lambda key, down: events.append((key, down)))
    monkeypatch.setattr(session, "input_window", lambda: {"id": 77})
    calls = []
    def interrupt_during_hold(*_):
        calls.append(True)
        if len(calls) == 3:
            raise KeyboardInterrupt()
    monkeypatch.setattr(session, "wait_guarded", interrupt_during_hold)
    with pytest.raises(KeyboardInterrupt):
        session.action({"kind": "click", "x": .5, "y": .5}, ["equipment"], {"state": "equipment", "path": "frame.png"})
    assert events == [(1, True), (1, False)]


def test_game_selection_ignores_tiny_wine_helpers(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path))
    monkeypatch.setattr(session, "windows", lambda: [
        {"id": 1, "title": "HELLDIVERS™ 2", "layout": {"window_size": [1920,1080]}},
        {"id": 2, "title": "", "app_id": "steam_app_553850", "layout": {"window_size": [160,20]}},
    ])
    assert session.game()["id"] == 1


def test_game_recreation_requires_new_session(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path))
    window = {"id": 1, "title": "HELLDIVERS™ 2", "layout": {"window_size": [1920,1080]}}
    monkeypatch.setattr(session, "windows", lambda: [window])
    session.game()
    window["id"] = 2
    with pytest.raises(game.AutomationError, match="changed"):
        session.game()


def route():
    return {"version": 1, "start": ["ship"], "target": ["armory"], "steps": [
        {"expect": ["ship"], "action": {"kind": "key", "key": "e"}, "after": ["armory"]}]}


def test_route_rejects_unknown_before_or_after():
    for field in ("expect", "after"):
        r = route()
        r["steps"][0][field] = ["unknown"]
        with pytest.raises(game.AutomationError):
            game.validate_route(r)


def test_route_budget_and_version():
    game.validate_route(route())
    r = route()
    r["steps"] *= 41
    with pytest.raises(game.AutomationError):
        game.validate_route(r)
    r = route()
    r["version"] = 2
    with pytest.raises(game.AutomationError):
        game.validate_route(r)


def test_tesseract_tsv_uses_parameter_not_missing_local_config(monkeypatch):
    captured = []
    def fake_run(argv, timeout):
        captured.append(argv)
        return "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t90\tАРСЕНАЛ\n"
    monkeypatch.setattr(game, "run", fake_run)
    text, words = game.read_ocr("screen.png", "/tmp/models")
    assert text == "АРСЕНАЛ"
    assert words[0]["left"] == 10
    assert "tessedit_create_tsv=1" in captured[0]
    assert captured[0][-1] != "tsv"


def test_tsv_literal_quote_cannot_consume_following_rows(monkeypatch):
    raw = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
           '5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t90\t"\n'
           '5\t1\t1\t1\t1\t2\t50\t20\t30\t40\t95\tСОЦСЕТИ\n')
    monkeypatch.setattr(game, 'run', lambda *_args, **_kwargs: raw)
    assert [w['text'] for w in game.ocr_words('unused.png')] == ['"', 'СОЦСЕТИ']


def test_wait_for_never_sends_input(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    observations = iter([{'state': 'unknown'}, {'state': 'startup'}])
    monkeypatch.setattr(session, 'observe', lambda: next(observations))
    monkeypatch.setattr(game.time, 'sleep', lambda _: None)
    monkeypatch.setattr(session, 'action', lambda *_: pytest.fail('input during wait'))
    assert session.wait_for(['startup'], 30)['reached'] == 'startup'


def test_wait_for_unknown_times_out_without_input(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    monkeypatch.setattr(session, 'observe', lambda: {'state': 'unknown'})
    monkeypatch.setattr(session, 'action', lambda *_: pytest.fail('input during wait'))
    with pytest.raises(game.AutomationError, match='no input sent while waiting'):
        session.wait_for(['ship'], 0)


def test_armory_interaction_key_must_be_near_station_label():
    assert game.armory_prompt([word('АРСЕНАЛ', x=100), word('E', x=70)], 1000, 1000)
    assert not game.armory_prompt([word('АРСЕНАЛ', x=100), word('E', x=900)], 1000, 1000)
    assert not game.armory_prompt([word('АРСЕНАЛ', x=100)], 1000, 1000)


def debug_files(tmp_path, token='current-123'):
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'debug.enabled').write_text('HD2TM_DEBUG 1\n')
    (state / 'debug.session').write_text(f'HD2TM_DEBUG_SESSION 1\n{token}\n')
    return state


def ack_text(token, request_id, status='ok', message='accepted'):
    return f'HD2TM_DEBUG_RESPONSE 1\n{token}\n{request_id}\n{status}\n{message}\n'


def test_debug_dry_run_writes_no_bridge_files(tmp_path):
    state = debug_files(tmp_path)
    before = {p.name: p.read_bytes() for p in state.iterdir()}
    result = game.debug_command('open_armory', state_dir=state)
    assert result['dry_run'] and result['menu_verified'] is False
    assert before == {p.name: p.read_bytes() for p in state.iterdir()}


def test_debug_matching_ack_and_no_menu_claim(tmp_path, monkeypatch):
    state = debug_files(tmp_path)
    def bridge_poll(_):
        request = game.parse_debug_request((state / 'debug.request').read_text())
        assert request['command'] == 'open_armory'
        assert request['payload'] == '{"equipment":true}'
        (state / 'debug.response').write_text(ack_text(request['token'], request['request_id']))
    monkeypatch.setattr(game.time, 'sleep', bridge_poll)
    result = game.debug_command('open_armory', '{"equipment":true}', state, True)
    assert result['transport_acknowledged']
    assert result['status'] == 'ok'
    assert result['menu_verified'] is False
    assert not list(state.glob('.debug.request-*'))


def test_debug_stale_response_does_not_acknowledge_new_request(tmp_path, monkeypatch):
    state = debug_files(tmp_path)
    (state / 'debug.response').write_text(ack_text('current-123', 'old-id'))
    clock = [0]
    monkeypatch.setattr(game.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(game.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))
    with pytest.raises(game.AutomationError, match='remains pending'):
        game.debug_command('inspect_api', state_dir=state, execute=True, timeout=.2)
    assert game.parse_debug_request((state / 'debug.request').read_text())['request_id'] != 'old-id'


def test_debug_unacknowledged_request_preserved(tmp_path):
    state = debug_files(tmp_path)
    prior = 'HD2TM_DEBUG_REQUEST 1\ncurrent-123\nfirst-id\nopen_armory\n'
    (state / 'debug.request').write_text(prior)
    with pytest.raises(game.AutomationError, match='Unacknowledged'):
        game.debug_command('open_armory', state_dir=state, execute=True)
    assert (state / 'debug.request').read_text() == prior


def test_debug_previous_launch_request_backed_up_and_not_replayed(tmp_path, monkeypatch):
    state = debug_files(tmp_path)
    prior = 'HD2TM_DEBUG_REQUEST 1\nold-123\nfirst-id\nopen_armory\n'
    (state / 'debug.request').write_text(prior)
    journal = game.Journal(tmp_path / 'artifacts')
    def bridge_poll(_):
        request = game.parse_debug_request((state / 'debug.request').read_text())
        assert request['token'] == 'current-123' and request['request_id'] != 'first-id'
        assert request['command'] == 'inspect_api'
        (state / 'debug.response').write_text(ack_text(request['token'], request['request_id']))
    monkeypatch.setattr(game.time, 'sleep', bridge_poll)
    game.debug_command('inspect_api', state_dir=state, execute=True, journal=journal)
    assert list(journal.path.glob('debug-prior-*.request.txt'))[0].read_text() == prior


def test_debug_session_change_aborts_without_replay(tmp_path, monkeypatch):
    state = debug_files(tmp_path)
    def restart(_):
        (state / 'debug.session').write_text('HD2TM_DEBUG_SESSION 1\nnew-456\n')
    monkeypatch.setattr(game.time, 'sleep', restart)
    with pytest.raises(game.AutomationError, match='will not be replayed'):
        game.debug_command('inspect_api', state_dir=state, execute=True)
    assert game.parse_debug_request((state / 'debug.request').read_text())['token'] == 'current-123'


def test_debug_error_ack_is_failure(tmp_path, monkeypatch):
    state = debug_files(tmp_path)
    def bridge_poll(_):
        request = game.parse_debug_request((state / 'debug.request').read_text())
        (state / 'debug.response').write_text(ack_text(request['token'], request['request_id'], 'error', 'Unknown debug command'))
    monkeypatch.setattr(game.time, 'sleep', bridge_poll)
    with pytest.raises(game.AutomationError, match='Unknown debug command'):
        game.debug_command('read_catalog', state_dir=state, execute=True)


def test_debug_concurrent_request_replacement_aborts(tmp_path, monkeypatch):
    state = debug_files(tmp_path)
    def other_client(_):
        (state / 'debug.request').write_text('different request')
    monkeypatch.setattr(game.time, 'sleep', other_client)
    with pytest.raises(game.AutomationError, match='replaced'):
        game.debug_command('inspect_api', state_dir=state, execute=True)


def test_debug_rejects_disabled_marker(tmp_path):
    state = debug_files(tmp_path)
    (state / 'debug.enabled').write_text('true\n')
    with pytest.raises(game.AutomationError, match='disabled'):
        game.debug_command('inspect_api', state_dir=state, execute=True)
    assert not (state / 'debug.request').exists()


@pytest.mark.parametrize('command,payload,timeout', [
    ('eval', '', 10), ('inspect_api', 'x'*1025, 10),
    ('inspect_api', 'я'*513, 10), ('inspect_api', '\x00', 10),
    ('inspect_api', '', 0), ('inspect_api', '', 61),
])
def test_debug_request_bounds(tmp_path, command, payload, timeout):
    state = debug_files(tmp_path)
    with pytest.raises(game.AutomationError):
        game.debug_command(command, payload, state, True, timeout)
    assert not (state / 'debug.request').exists()


def armory_session(tmp_path, monkeypatch, states, execute=True):
    session = game.Session(args(tmp_path / 'artifacts', execute))
    window = {'id': 1, 'title': 'HELLDIVERS™ 2', 'app_id': 'steam_app_553850',
              'layout': {'window_size': [1920,1080]}}
    events = []
    frames = iter(states)
    (tmp_path / 'debug.enabled').write_text('HD2TM_DEBUG 1\n')
    (tmp_path / 'debug.session').write_text('HD2TM_DEBUG_SESSION 1\ncurrent-123\n')
    monkeypatch.setattr(game, 'discover_debug_dir', lambda: tmp_path)
    monkeypatch.setattr(session, 'windows', lambda: [window])
    monkeypatch.setattr(session, 'focus', lambda: events.append(('focus',)) or window)
    monkeypatch.setattr(session, 'fit_game_window', lambda: {'changed':False,'fits':True})
    monkeypatch.setattr(session, 'assert_focus', lambda: window)
    def observe():
        frame = next(frames)
        return {'path': 'verified-frame.png', 'width': 1920,
                'height': 1080, 'words': [], 'text': '',
                **({'state': frame, **({'view':'armor_grid'} if frame=='equipment' else {})} if isinstance(frame, str) else frame)}
    monkeypatch.setattr(session, 'observe', observe)
    def key(action, expected, observation=None):
        assert observation['state'] in expected
        if observation['state']=='unknown':
            assert action['kind']=='click' and action['label']=='authorized startup movie skip'
            events.append(('startup_click',))
        else:
            events.append(('key', action['key']) if action['kind']=='key' else ('card_click',action['x'],action['y']))
        return {'after': observe()}
    def click(labels, observation):
        assert observation['state'] in ('armory','menu')
        events.append(('click', tuple(labels)))
        return {'after': observe()}
    def debug(command, **kwargs):
        kwargs['guard']()
        assert command == 'open_armory'
        events.append(('debug', command))
        (tmp_path / 'debug.request').write_text('HD2TM_DEBUG_REQUEST 1\ncurrent-123\nopen-request\nopen_armory\n')
        (tmp_path / 'debug-armory-open.txt').write_text('HD2TM_ARMORY_OPEN 1\ncurrent-123\nok\nEquipment observed\n')
        return {'state_dir': str(tmp_path), 'transport_acknowledged': True,
                'status': 'ok', 'menu_verified': False, 'session_token': 'current-123', 'request_id': 'open-request'}
    monkeypatch.setattr(session, 'action', key)
    monkeypatch.setattr(session, 'click_any', click)
    monkeypatch.setattr(game, 'debug_command', debug)
    monkeypatch.setattr(game.time, 'sleep', lambda _: None)
    return session, events


def test_armory_dry_plan_never_inspects_or_changes_desktop(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, False))
    monkeypatch.setattr(session, 'windows', lambda: pytest.fail('desktop inspected in dry-run'))
    monkeypatch.setattr(session, 'focus', lambda: pytest.fail('focus changed in dry-run'))
    monkeypatch.setattr(game, 'debug_command', lambda *_a, **_k: pytest.fail('debug transport in dry-run'))
    result = session.armory(launch=True)
    assert result['dry_run'] and result['menu_verified'] is False


def test_armory_already_equipment_is_idempotent(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['equipment'])
    result = session.armory()
    assert result['menu_verified'] and not result['open_requested']
    assert events == [('focus',)]


def test_armory_ship_requests_once_then_confirms_equipment(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['ship','unknown','equipment','equipment'])
    result = session.armory()
    assert result['menu_verified'] and result['open_requested']
    assert events == [('focus',),('debug','open_armory')]
    assert result['acknowledgement']['menu_verified'] is False


def native_armor_cards():
    return {'state':'armory','view':'armor_cards','words':[
        {'text':'БРОНЯ','confidence':96,'left':420,'top':195,'width':180,'height':32}]}


def test_armory_landing_uses_numeric_tab_then_actual_card_click_without_reopening(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch,
        ['ship','armory',native_armor_cards(),'equipment','equipment','equipment'])
    result = session.armory()
    assert result['menu_verified']
    assert [e[0] for e in events] == ['focus','debug','key','card_click','key']
    assert events[2]==('key','2') and events[-1]==('key','1')


def test_armory_already_landing_needs_no_debug_request(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['armory',native_armor_cards(),'equipment','equipment'])
    result = session.armory()
    assert result['menu_verified'] and not result['open_requested']
    assert [e[0] for e in events] == ['focus','key','card_click','key']
    assert events[1]==('key','2') and events[-1]==('key','1')


def test_armory_startup_waits_through_loading_without_blind_keys(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch,
        ['startup','unknown','unknown','ship','equipment','equipment'])
    assert session.armory()['menu_verified']
    assert events == [('focus',),('key','space'),('debug','open_armory')]


def test_armory_continue_menu_uses_observed_continue_control(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['menu','ship','equipment','equipment'])
    assert session.armory()['menu_verified']
    assert [e[0] for e in events] == ['focus','click','debug']
    assert 'CONTINUE' in events[1][1]


def test_armory_unknown_view_never_sends_any_request_or_input(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, [])
    clock = [0]
    monkeypatch.setattr(game.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(game.time, 'sleep', lambda d: clock.__setitem__(0, clock[0]+d))
    monkeypatch.setattr(session, 'observe', lambda: {'state': 'unknown'})
    with pytest.raises(game.AutomationError, match='Timed out'):
        session.armory(timeout=2)
    assert events == [('focus',)]


def test_armory_acknowledgement_alone_is_not_menu_success(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, [])
    clock = [0]
    monkeypatch.setattr(game.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(game.time, 'sleep', lambda d: clock.__setitem__(0, clock[0]+d))
    monkeypatch.setattr(session, 'observe', lambda: {'state': 'ship'})
    with pytest.raises(game.AutomationError, match='Timed out'):
        session.armory(timeout=2)
    assert events == [('focus',),('debug','open_armory')]


def test_armory_focus_loss_before_request_stops_without_refocusing(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['ship'])
    def lose_focus():
        raise game.AutomationError('Game does not have compositor focus')
    monkeypatch.setattr(session, 'assert_focus', lose_focus)
    with pytest.raises(game.AutomationError, match='focus'):
        session.armory()
    assert events == [('focus',)]


def test_armory_launch_is_explicit_once_and_waits_for_game_window(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['equipment'])
    states = iter([[], [], [{'id':1,'title':'HELLDIVERS™ 2','layout':{'window_size':[1920,1080]}}]])
    monkeypatch.setattr(session, 'windows', lambda: next(states))
    monkeypatch.setattr(game, 'run', lambda argv: events.append(('launch',tuple(argv))))
    result = session.armory(launch=True)
    assert result['launched'] and result['menu_verified']
    assert [e[0] for e in events] == ['launch','focus']


def test_armory_without_launch_flag_never_launches_absent_game(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, [])
    monkeypatch.setattr(session, 'windows', lambda: [])
    monkeypatch.setattr(game, 'run', lambda _a: pytest.fail('implicit launch'))
    with pytest.raises(game.AutomationError, match='--launch'):
        session.armory()
    assert events == []


def test_debug_focus_guard_stops_before_publishing_request(tmp_path):
    state = debug_files(tmp_path)
    def blocked():
        raise game.AutomationError('focus lost')
    with pytest.raises(game.AutomationError, match='focus lost'):
        game.debug_command('open_armory', state_dir=state, execute=True, guard=blocked)
    assert not (state / 'debug.request').exists()


def test_armory_fresh_addon_error_stops_without_repeated_open(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['ship'])
    original = game.debug_command
    def rejected(command, **kwargs):
        ack = original(command, **kwargs)
        (tmp_path / 'debug-armory-open.txt').write_text('HD2TM_ARMORY_OPEN 1\ncurrent-123\nerror\nShip context changed\n')
        return ack
    monkeypatch.setattr(game, 'debug_command', rejected)
    with pytest.raises(game.AutomationError, match='Ship context changed'):
        session.armory()
    assert events == [('focus',),('debug','open_armory')]


def test_armory_requires_actual_handler_completion_after_equipment_appears(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['ship','equipment','equipment'])
    original = game.debug_command
    def pending(command, **kwargs):
        ack = original(command, **kwargs)
        (tmp_path / 'debug-armory-open.txt').write_text('HD2TM_ARMORY_OPEN 1\ncurrent-123\npending\nQueued\n')
        return ack
    def complete(_):
        (tmp_path / 'debug-armory-open.txt').write_text('HD2TM_ARMORY_OPEN 1\ncurrent-123\nok\nNative Equipment observed\n')
    monkeypatch.setattr(game, 'debug_command', pending)
    monkeypatch.setattr(game.time, 'sleep', complete)
    result = session.armory()
    assert result['menu_verified'] and result['addon_open_status']['status'] == 'ok'
    assert events == [('focus',),('debug','open_armory')]


def test_armory_stale_same_session_ok_cannot_confirm_new_request(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['ship','equipment'])
    clock = [0]
    monkeypatch.setattr(game.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(game.time, 'sleep', lambda d: clock.__setitem__(0, clock[0]+d))
    (tmp_path / 'debug-armory-open.txt').write_text('HD2TM_ARMORY_OPEN 1\ncurrent-123\nok\nPrevious operation\n')
    def queued(command, **kwargs):
        events.append(('debug', command))
        (tmp_path / 'debug.request').write_text('HD2TM_DEBUG_REQUEST 1\ncurrent-123\nnew-request\nopen_armory\n')
        return {'state_dir': str(tmp_path), 'session_token':'current-123', 'request_id':'new-request'}
    monkeypatch.setattr(game, 'debug_command', queued)
    with pytest.raises(game.AutomationError, match='time budget exhausted'):
        session.armory(timeout=2)
    assert events == [('focus',),('debug','open_armory')]


def test_armory_concurrent_request_cannot_supply_another_requests_ui_ack(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['ship','equipment'])
    observe = session.observe
    calls = [0]
    def changed_inbox():
        result = observe()
        calls[0] += 1
        if calls[0] == 2:
            (tmp_path / 'debug.request').write_text('HD2TM_DEBUG_REQUEST 1\ncurrent-123\nforeign-request\nopen_armory\n')
        return result
    monkeypatch.setattr(session, 'observe', changed_inbox)
    with pytest.raises(game.AutomationError, match='another request'):
        session.armory()
    assert events == [('focus',),('debug','open_armory')]


def test_armory_status_token_and_shape_are_exact():
    assert game.parse_armory_status('HD2TM_ARMORY_OPEN 1\nsession-1\npending\nQueued\n', 'session-1')['status'] == 'pending'
    with pytest.raises(game.AutomationError, match='another game session'):
        game.parse_armory_status('HD2TM_ARMORY_OPEN 1\nold-session\nok\nOpened\n', 'session-1')
    with pytest.raises(game.AutomationError, match='format'):
        game.parse_armory_status('OK', 'session-1')


@pytest.mark.parametrize('text,view', [
    ('АРСЕНАЛ ПЕРСОНАЖ УСИЛИТЕЛЬ ОСНОВНОЕ ОРУЖИЕ ДОПОЛНИТЕЛЬНОЕ ОРУЖИЕ МЕТАТЕЛЬНОЕ ОРУЖИЕ ЗАКРЫТЬ ВЫБРАТЬ', 'weapons_cards'),
    ('АРСЕНАЛ ЕрСОНАЖ КАРЬЕРА БРОНЯ ШЛЕМ ПЛАЩ ВЫБРАТЬ', 'armor_cards'),
    ('ARMORY CHARACTER BOOSTER PRIMARY SECONDARY GRENADE CLOSE SELECT', 'weapons_cards'),
    ('ARMORY CHARACTER CAREER ARMOR HELMET CAPE SELECT', 'armor_cards'),
])
def test_native_armory_root_views_are_not_mistaken_for_the_armor_grid(text, view):
    result = game.classify(text)
    assert result['state'] == 'armory' and result['view'] == view


def test_armor_card_click_is_anchored_to_one_large_visible_title():
    title = {'text':'БРОНЯ','confidence':96,'left':588,'top':260,'width':241,'height':43}
    assert game.armor_card_target([title],2560,1440) == (708.5/2560,561/1440)
    with pytest.raises(game.AutomationError):
        game.armor_card_target([title,dict(title,left=788)],2560,1440)
    with pytest.raises(game.AutomationError):
        game.armor_card_target([dict(title,top=20)],2560,1440)
    with pytest.raises(game.AutomationError):
        game.armor_card_target([dict(title,confidence=35)],2560,1440)


def test_armory_native_root_uses_two_then_anchored_left_card_then_one(tmp_path, monkeypatch):
    weapons = {'state':'armory','view':'weapons_cards'}
    armors = {'state':'armory','view':'armor_cards','words':[
        {'text':'БРОНЯ','confidence':96,'left':420,'top':195,'width':180,'height':32}]}
    session, events = armory_session(tmp_path, monkeypatch,
        ['ship',weapons,weapons,armors,'equipment','equipment','equipment'])
    result = session.armory()
    assert result['menu_verified']
    assert [event[0] for event in events] == ['focus','debug','key','card_click','key']
    assert events[2] == ('key','2') and events[-1]==('key','1')
    assert .25 < events[3][1] < .30 and .35 < events[3][2] < .45


def test_click_motion_targets_window_client_not_overlapping_xwayland_root(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    events = []
    session.x11 = SimpleNamespace(
        geometry=lambda _: (9999,8888,1920,1080),
        move=lambda *_: pytest.fail('root absolute movement would target another XWayland surface'),
        raise_window=lambda *_:None, move_to_window=lambda *values: events.append(('warp',values)),
        button=lambda *values: events.append(('button',values)))
    monkeypatch.setattr(session,'input_window',lambda:{'id':77})
    monkeypatch.setattr(session,'wait_guarded',lambda *_:None)
    monkeypatch.setattr(session,'observe',lambda:{'state':'equipment'})
    monkeypatch.setattr(game.time,'sleep',lambda _:None)
    session.action({'kind':'click','x':.5,'y':.25},['equipment'],{'state':'equipment','path':'frame.png'})
    assert events == [('warp',(77,960,270)),('button',(1,True)),('button',(1,False))]


def test_arsenal_latin_lookalike_heading_keeps_independent_equipment_guards():
    assert game.classify('APCEHAN РЕИТИНГ БРОНИ СКОРОСТЬ ВЫНОСЛИВОСТИ ПАССИВНЫЙ БОНУС ПРИМЕНИТЬ')['state'] == 'equipment'
    assert game.classify('APCEHAN')['state'] == 'unknown'
    assert game.classify('xAPCEHANx SPEED STAMINA APPLY')['state'] == 'unknown'


def test_unknown_action_retries_observation_once_without_input(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path))
    frames = iter([{'state':'unknown','path':'first.png'}, {'state':'equipment','path':'second.png'}])
    seen = []
    monkeypatch.setattr(session, 'observe', lambda: seen.append(True) or next(frames))
    monkeypatch.setattr(session, 'assert_focus', lambda: None)
    monkeypatch.setattr(session, 'input_window', lambda: pytest.fail('dry-run sent input'))
    monkeypatch.setattr(game.time, 'sleep', lambda _:None)
    result = session.action({'kind':'key','key':'Escape'}, ['equipment'])
    assert len(seen) == 2 and result['dry_run'] and result['observed']=='equipment'


def test_unknown_action_stops_after_two_observations(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    seen = []
    monkeypatch.setattr(session, 'observe', lambda: seen.append(True) or {'state':'unknown','path':'frame.png'})
    monkeypatch.setattr(session, 'assert_focus', lambda: None)
    monkeypatch.setattr(session, 'input_window', lambda: pytest.fail('unrecognized view sent input'))
    monkeypatch.setattr(game.time, 'sleep', lambda _:None)
    with pytest.raises(game.AutomationError, match='no input sent'):
        session.action({'kind':'key','key':'Escape'}, ['equipment'])
    assert len(seen) == 2


def test_text_click_uses_refreshed_word_coordinates_after_unknown(tmp_path, monkeypatch):
    session = game.Session(args(tmp_path, True))
    frames = iter([
        {'state':'unknown','path':'first.png','width':1000,'height':1000,'words':[word('APPLY',x=100)]},
        {'state':'equipment','path':'second.png','width':1000,'height':1000,'words':[word('APPLY',x=500)]},
    ])
    monkeypatch.setattr(session, 'observe', lambda: next(frames))
    monkeypatch.setattr(session, 'assert_focus', lambda: None)
    monkeypatch.setattr(game.time, 'sleep', lambda _:None)
    monkeypatch.setattr(session, 'action', lambda action, expected, observation: action)
    assert session.click_text('APPLY',['equipment'])['x'] == .55


def test_cold_launch_and_startup_get_separate_bounded_stage_budgets(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path, monkeypatch, ['startup','ship','equipment','equipment'])
    clock = [0]
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    windows = iter([[],[{'id':1,'title':'HELLDIVERS™ 2','layout':{'window_size':[1920,1080]}}]])
    monkeypatch.setattr(session,'windows',lambda:next(windows))
    monkeypatch.setattr(game,'run',lambda _:clock.__setitem__(0,55))
    observe=session.observe
    def slow_observe():
        clock[0]+=8
        return observe()
    monkeypatch.setattr(session,'observe',slow_observe)
    result=session.armory(launch=True,timeout=60)
    assert clock[0]>60 and result['menu_verified']
    assert ('key','space') in events


def test_title_at_end_of_loading_wait_gets_fresh_startup_transition_budget(tmp_path, monkeypatch):
    session, events = armory_session(tmp_path,monkeypatch,['unknown','startup','ship','equipment','equipment'])
    clock=[0];times=iter([59,60,65,66,67])
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(game.time,'sleep',lambda duration:clock.__setitem__(0,clock[0]+duration))
    observe=session.observe
    def timed_observe():
        clock[0]=next(times)
        return observe()
    monkeypatch.setattr(session,'observe',timed_observe)
    result=session.armory(timeout=60)
    assert result['menu_verified'] and ('key','space') in events


@pytest.mark.parametrize('heading,view', [
    ('ТЯЖЕЛАЯ','armor_grid'), ('ЛЕГКАЯ','armor_grid'), ('СРЕДНЯЯ','armor_grid'),
    ('HEAVY','armor_grid'), ('MEDIUM','armor_grid'), ('LIGHT','armor_grid'),
    ('ШЛЕМЫ','helmet_grid'), ('HELMETS','helmet_grid'), ('ПЛАЩИ','cape_grid'), ('CAPES','cape_grid'),
])
def test_native_item_grid_kind_requires_its_own_heading(heading, view):
    text=f'АРСЕНАЛ РЕЙТИНГ БРОНИ СКОРОСТЬ ПРИМЕНИТЬ {heading}'
    words=[dict(word(heading,x=400,y=200),width=200)]
    result=game.classify(text,words,1920,1080)
    assert result['state']=='equipment' and result['view']==view


def test_heavy_armor_description_cannot_classify_helmet_view_as_armor():
    text='ARMORY ARMOR RATING SPEED APPLY A HEAVY ARMOR HELMETS'
    words=[word('HELMETS',x=400,y=200),word('HEAVY ARMOR',x=1200,y=650)]
    assert game.classify(text,words,1920,1080)['view']=='helmet_grid'
    assert game.classify(text,words[1:],1920,1080)['view']=='unclassified_grid'


def test_already_helmet_grid_uses_tab_one_without_open_request(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[{'state':'equipment','view':'helmet_grid'},'equipment'])
    result=session.armory()
    assert result['menu_verified'] and result['view']=='armor_grid'
    assert events==[('focus',),('key','1')]


def test_already_cape_grid_uses_one_direct_tab_action(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[
        {'state':'equipment','view':'cape_grid'},'equipment'])
    result=session.armory()
    assert result['menu_verified'] and result['view']=='armor_grid'
    assert events==[('focus',),('key','1')]


def test_wrong_numeric_tab_result_times_out_without_repeating_or_cycling(tmp_path,monkeypatch):
    cape={'state':'equipment','view':'cape_grid'}
    session,events=armory_session(tmp_path,monkeypatch,[cape])
    clock=[0]
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(game.time,'sleep',lambda d:clock.__setitem__(0,clock[0]+d))
    monkeypatch.setattr(session,'observe',lambda:cape)
    with pytest.raises(game.AutomationError,match='Armor navigation timed out'):
        session.armory(timeout=2)
    assert events==[('focus',),('key','1')]


def test_unclassified_equipment_picker_uses_one_then_requires_verified_armor(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[
        {'state':'equipment','view':'unclassified_grid'},'equipment'])
    assert session.armory()['menu_verified']
    assert events==[('focus',),('key','1')]


def test_final_recheck_cannot_verify_a_helmet_grid(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[
        'ship','equipment',{'state':'equipment','view':'helmet_grid'}])
    with pytest.raises(game.AutomationError,match='Final native view is not the Armor grid'):
        session.armory()
    assert events==[('focus',),('debug','open_armory')]


def test_hover_settles_for_quarter_second_before_button_press(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path,True));events=[]
    session.x11=SimpleNamespace(geometry=lambda _:(0,0,1920,1080),
        raise_window=lambda *_:None, move_to_window=lambda *_:events.append('warp'),button=lambda _,down:events.append('down' if down else 'up'))
    monkeypatch.setattr(session,'input_window',lambda:{'id':1})
    monkeypatch.setattr(session,'wait_guarded',lambda duration,_:events.append(duration))
    monkeypatch.setattr(session,'observe',lambda:{'state':'equipment','view':'armor_grid'})
    monkeypatch.setattr(game.time,'sleep',lambda _:None)
    session.action({'kind':'click','x':.3,'y':.4},['equipment'],{'state':'equipment','path':'frame.png'})
    assert events==[.1,'warp',.25,'down',.05,'up']


def test_x11_stack_alignment_is_server_ordered_before_target_warp():
    backend=object.__new__(game.X11);events=[]
    backend.display='display'
    backend.focused=lambda window:window==77
    backend.x=SimpleNamespace(
        XRaiseWindow=lambda display,window:events.append(('raise',window)),
        XSync=lambda display,discard:events.append(('sync',discard)),
        XWarpPointer=lambda *values:events.append(('warp',values[2],values[-2],values[-1])))
    backend.raise_window(77)
    backend.move_to_window(77,708,561)
    assert events==[('raise',77),('sync',0),('warp',77,708,561),('sync',0)]
    with pytest.raises(game.AutomationError,match='focus changed'):
        backend.raise_window(88)
    with pytest.raises(game.AutomationError,match='focus changed'):
        backend.move_to_window(88,1,1)
    assert len(events)==4


def test_focus_loss_during_raise_settling_prevents_warp_and_click(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path,True));events=[]
    session.x11=SimpleNamespace(geometry=lambda _:(0,0,1920,1080),
        raise_window=lambda _:events.append('raised'),
        move_to_window=lambda *_:pytest.fail('pointer moved after focus loss'),
        button=lambda *_:pytest.fail('button sent after focus loss'))
    monkeypatch.setattr(session,'input_window',lambda:{'id':77})
    def lost_focus(duration,window):
        assert duration==.1 and window==77
        raise game.AutomationError('compositor focus lost during stacking settle')
    monkeypatch.setattr(session,'wait_guarded',lost_focus)
    with pytest.raises(game.AutomationError,match='focus lost'):
        session.action({'kind':'click','x':.3,'y':.4},['equipment'],{'state':'equipment','path':'frame.png'})
    assert events==['raised']


def niri_fit_fixture(clipped=True):
    window={'id':146,'workspace_id':26,'layout':{
        'tile_pos_in_workspace_view':[0,36] if clipped else [0,0],
        'window_offset_in_tile':[0,0],
        'window_size':[2562,1442] if clipped else [2560,1440]}}
    outputs={'DP-3':{'current_mode':0,'logical':{'x':0,'y':0,'width':2560,'height':1440,'scale':1.0,'transform':'Normal'}}}
    workspaces=[{'id':26,'output':'DP-3','is_active':True}]
    return window,outputs,workspaces


def test_niri_fit_detects_actual_clipped_and_fullscreen_geometries():
    assert game.window_fit(*niri_fit_fixture(True))['fits'] is False
    result=game.window_fit(*niri_fit_fixture(False))
    assert result['fits'] is True and result['bounds']==[0,0,2560,1440]
    window,outputs,workspaces=niri_fit_fixture(False)
    window['layout']['window_size']=[800,600]
    window['layout']['tile_pos_in_workspace_view']=[100,36]
    assert game.window_fit(window,outputs,workspaces)['fits'] is True
    window['layout']['tile_pos_in_workspace_view']=[-1,36]
    assert game.window_fit(window,outputs,workspaces)['fits'] is False


@pytest.mark.parametrize('change', ['multiple_outputs','scale','rotation','workspace','bounds'])
def test_niri_fit_never_guesses_ambiguous_display_geometry(change):
    window,outputs,workspaces=niri_fit_fixture(True)
    if change=='multiple_outputs':outputs['HDMI-A-1']=outputs['DP-3'].copy()
    elif change=='scale':outputs['DP-3']['logical']['scale']=1.25
    elif change=='rotation':outputs['DP-3']['logical']['transform']='90'
    elif change=='workspace':workspaces[0]['is_active']=False
    else:window['layout']['tile_pos_in_workspace_view']=None
    assert game.window_fit(window,outputs,workspaces)['fits'] is None


def test_window_fit_dry_run_reads_no_desktop_and_sends_no_toggle(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path,False))
    monkeypatch.setattr(session,'window_fit_snapshot',lambda:pytest.fail('desktop read during fit dry-run'))
    monkeypatch.setattr(game,'run',lambda *_:pytest.fail('fullscreen toggle in dry-run'))
    assert session.fit_game_window()['dry_run']


def test_window_fit_fullscreens_once_and_verifies_before_return(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path,True));commands=[]
    clipped=game.window_fit(*niri_fit_fixture(True));fitted=game.window_fit(*niri_fit_fixture(False))
    snapshots=iter([clipped,clipped,clipped,fitted])
    monkeypatch.setattr(session,'window_fit_snapshot',lambda:next(snapshots))
    monkeypatch.setattr(game,'run',lambda command:commands.append(command))
    monkeypatch.setattr(game.time,'sleep',lambda _:None)
    result=session.fit_game_window()
    assert result['changed'] and result['fits']
    assert commands==[['niri','msg','action','fullscreen-window','--id',146]]


@pytest.mark.parametrize('fits',[True,None])
def test_window_fit_does_not_toggle_already_fitting_or_ambiguous_game(tmp_path,monkeypatch,fits):
    session=game.Session(args(tmp_path,True))
    monkeypatch.setattr(session,'window_fit_snapshot',lambda:{'window_id':146,'fits':fits,'reason':'fixture'})
    monkeypatch.setattr(game,'run',lambda *_:pytest.fail('unnecessary fullscreen toggle'))
    assert session.fit_game_window()['changed'] is False


def test_window_fit_rechecks_before_toggling_to_avoid_undoing_manual_fullscreen(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path,True))
    snapshots=iter([game.window_fit(*niri_fit_fixture(True)),game.window_fit(*niri_fit_fixture(False))])
    monkeypatch.setattr(session,'window_fit_snapshot',lambda:next(snapshots))
    monkeypatch.setattr(game,'run',lambda *_:pytest.fail('manual fullscreen was toggled back off'))
    assert session.fit_game_window()['changed'] is False


def test_window_fit_timeout_never_repeats_fullscreen_toggle(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path,True));commands=[];clock=[0]
    monkeypatch.setattr(session,'window_fit_snapshot',lambda:game.window_fit(*niri_fit_fixture(True)))
    monkeypatch.setattr(game,'run',lambda command:commands.append(command))
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(game.time,'sleep',lambda duration:clock.__setitem__(0,clock[0]+duration))
    with pytest.raises(game.AutomationError,match='3-second fullscreen wait'):
        session.fit_game_window()
    assert len(commands)==1 and clock[0]==3


def test_window_fit_focus_loss_after_toggle_stops_verification(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path,True));commands=[];calls=[0]
    def snapshot():
        calls[0]+=1
        if calls[0]>2:raise game.AutomationError('Game does not have compositor focus')
        return game.window_fit(*niri_fit_fixture(True))
    monkeypatch.setattr(session,'window_fit_snapshot',snapshot)
    monkeypatch.setattr(game,'run',lambda command:commands.append(command))
    with pytest.raises(game.AutomationError,match='compositor focus'):
        session.fit_game_window()
    assert len(commands)==1


def gameguard_splash():
    return {'id':149,'title':'','app_id':'steam_app_553850','layout':{'window_size':[320,200]}}


def actual_game_window():
    return {'id':151,'title':'HELLDIVERS™ 2','app_id':'steam_app_553850','layout':{'window_size':[2560,1440]}}


@pytest.mark.parametrize('title,size,expected', [
    ('',[320,200],False), ('HELLDIVERS™ 2',[320,200],False),
    ('',[1920,1080],False), ('GameGuard',[1920,1080],False),
    (None,[1920,1080],False), ('HELLDIVERS™ 2',[639,480],False),
    ('HELLDIVERS™ 2',[640,479],False), ('HELLDIVERS™ 2',[640,480],True),
])
def test_actual_game_candidate_requires_title_and_minimum_viewport(title,size,expected):
    window={'id':1,'title':title,'app_id':'steam_app_553850','layout':{'window_size':size}}
    assert game.game_window_candidate(window) is expected


def test_gameguard_only_never_binds_session_and_real_game_can_appear_later(tmp_path,monkeypatch):
    session=game.Session(args(tmp_path))
    windows=[gameguard_splash()]
    monkeypatch.setattr(session,'windows',lambda:windows)
    with pytest.raises(game.AutomationError,match='found 0'):
        session.game()
    assert session.bound_window is None
    windows.append(actual_game_window())
    assert session.game()['id']==151 and session.bound_window==151


def test_cold_launch_waits_past_gameguard_before_focusing_real_game(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,['equipment'])
    windows=[[],[gameguard_splash()],[gameguard_splash()],[gameguard_splash(),actual_game_window()]]
    last=[None]
    def inventory():
        if windows:last[0]=windows.pop(0)
        return last[0]
    monkeypatch.setattr(session,'windows',inventory)
    monkeypatch.setattr(game,'run',lambda command:events.append(('launch',)))
    monkeypatch.setattr(game.time,'sleep',lambda duration:events.append(('wait',duration)))
    def focus_main():
        window=session.game()
        assert window['id']==151
        events.append(('focus',151))
        return window
    monkeypatch.setattr(session,'focus',focus_main)
    result=session.armory(launch=True)
    assert result['launched'] and result['menu_verified']
    assert events==[('launch',),('wait',.5),('wait',.5),('focus',151)]


def test_permanent_gameguard_splash_times_out_without_focus_or_input(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[])
    clock=[0]
    monkeypatch.setattr(session,'windows',lambda:[gameguard_splash()])
    monkeypatch.setattr(game,'run',lambda command:events.append(('launch',)))
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(game.time,'sleep',lambda duration:clock.__setitem__(0,clock[0]+duration))
    with pytest.raises(game.AutomationError,match='during window'):
        session.armory(launch=True,timeout=2,launch_timeout=10)
    assert events==[('launch',)] and clock[0]==10


def test_shader_bootstrap_over_sixty_seconds_uses_separate_launch_budget(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,['startup','ship','equipment','equipment'])
    clock=[0];waits=[]
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    def pause(duration):
        waits.append(duration);clock[0]+=duration
    monkeypatch.setattr(game.time,'sleep',pause)
    monkeypatch.setattr(session,'windows',lambda:[gameguard_splash()] if clock[0]<75 else [actual_game_window()])
    monkeypatch.setattr(game,'run',lambda command:events.append(('launch',)))
    def focus_actual():
        assert clock[0]>=75 and session.game()['id']==151
        events.append(('focus',151))
    monkeypatch.setattr(session,'focus',focus_actual)
    action=session.action
    def guarded_action(*values,**options):
        assert clock[0]>=75,'input sent while only the splash existed'
        return action(*values,**options)
    monkeypatch.setattr(session,'action',guarded_action)
    result=session.armory(launch=True,timeout=60,launch_timeout=180)
    assert result['menu_verified'] and result['launched'] and clock[0]==75
    assert events==[('launch',),('focus',151),('key','space'),('debug','open_armory')]
    assert waits and max(waits)<=.5


@pytest.mark.parametrize('seconds',[0,9,301,float('nan')])
def test_launch_budget_is_explicitly_bounded_before_desktop_access(tmp_path,monkeypatch,seconds):
    session=game.Session(args(tmp_path,True))
    monkeypatch.setattr(session,'windows',lambda:pytest.fail('desktop accessed with invalid launch budget'))
    with pytest.raises(game.AutomationError,match='10–300'):
        session.armory(launch=True,launch_timeout=seconds)


def test_default_dry_launch_plan_reports_independent_budgets(tmp_path):
    session=game.Session(args(tmp_path,False))
    plan=session.armory(launch=True)
    assert plan['launch_timeout']==240 and plan['startup_timeout']==180 and plan['timeout']==60


@pytest.mark.parametrize('command',['variant_status','draft_variant','save_variant','select_variant','apply_variant','reset_variant','inspect_armory_grid','inspect_armory_model','inspect_armory_producers','inspect_native_callee','inspect_render_types','probe_armor','open_creator'])
def test_allowlisted_variant_and_readonly_probe_commands_parse_as_data(command):
    parsed=game.parser().parse_args(['debug',command])
    assert parsed.debug_command==command and not parsed.execute


def test_draft_transport_preserves_multiline_owned_donor_payload_and_unicode_name(tmp_path,monkeypatch):
    state=debug_files(tmp_path)
    payload='armor:00001234 native-stats:00005678 passive:exact-variant\nЛичный вариант 1'
    def respond(_):
        request=game.parse_debug_request((state/'debug.request').read_text())
        assert request['command']=='draft_variant' and request['payload']==payload
        (state/'debug.response').write_text(ack_text(request['token'],request['request_id']))
    monkeypatch.setattr(game.time,'sleep',respond)
    result=game.debug_command('draft_variant',payload,state,True)
    assert result['transport_acknowledged'] and result['menu_verified'] is False


def test_ship_fallback_requires_commander_level_orders_and_social_together():
    text='КОМАНДИР: Name СЛУГА СВОБОДЫ Уровень 137 ПРИКАЗЫ СОЦСЕТИ'
    assert game.classify(text)['state']=='ship'
    for anchor in ('КОМАНДИР','Уровень','ПРИКАЗЫ','СОЦСЕТИ'):
        assert game.classify(text.replace(anchor,''))['state']=='unknown'


def test_live_ship_hud_needs_completed_social_crop_after_garbled_primary_ocr():
    # The live frame screen-1790481497681522297.png completed as ship. Its
    # primary pass read Social as "coucem"; the HUD crop recovered СОЦСЕТИ.
    primary='КСЗ Предвестник превосходства КОМАНДИР: player ПРИОБРЕТЕНИЯ ESCAPE приказы coucem СЛУГА СВОБОДЫ Уровень 137'
    assert game.classify(primary)['state']=='unknown'
    completed=primary+' ПРИКАЗЫ ® СОЦСЕТИ 0'
    assert game.classify(completed)['state']=='ship'
    assert game.classify('ПРИКАЗЫ ® СОЦСЕТИ 0')['state']=='unknown'


def test_long_unknown_intro_gets_startup_budget_and_is_never_fit_or_clicked(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,['startup','ship','equipment','equipment'])
    clock=[0];original=session.observe
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(game.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    monkeypatch.setattr(session,'observe',lambda:{'state':'unknown'} if clock[0]<120 else original())
    def fit_after_title():
        assert clock[0]>=120,'transient black intro viewport was fit too early'
        events.append(('fit',clock[0]));return {'changed':False,'fits':True}
    monkeypatch.setattr(session,'fit_game_window',fit_after_title)
    result=session.armory(startup_timeout=180)
    assert result['menu_verified'] and clock[0]==120
    assert events==[('focus',),('fit',120),('key','space'),('debug','open_armory')]


def test_recognized_view_resize_gets_fresh_observation_without_second_toggle(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,['startup','unknown','startup','ship','equipment','equipment'])
    def fit_once():
        events.append(('fit',));return {'changed':True,'fits':True}
    monkeypatch.setattr(session,'fit_game_window',fit_once)
    assert session.armory()['menu_verified']
    assert events==[('focus',),('fit',),('key','space'),('debug','open_armory')]


@pytest.mark.parametrize('landing',['armor_grid','helmet_grid','cape_grid'])
def test_native_left_card_always_gets_explicit_one_after_picker_opens(tmp_path,monkeypatch,landing):
    session,events=armory_session(tmp_path,monkeypatch,[
        'armory',native_armor_cards(),{'state':'equipment','view':landing},'equipment'])
    assert session.armory()['menu_verified']
    assert [event[0] for event in events]==['focus','key','card_click','key']
    assert events[1]==('key','2') and events[-1]==('key','1')
    assert not any(event in [('key','q'),('key','e')] for event in events)


def test_tab_one_waits_for_visible_picker_after_real_card_click(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[
        'armory',native_armor_cards(),'unknown','unknown',
        {'state':'equipment','view':'helmet_grid'},'equipment'])
    assert session.armory()['menu_verified']
    assert [event[0] for event in events]==['focus','key','card_click','key']
    assert events[-1]==('key','1')


def test_missing_left_card_anchor_stops_before_click_or_picker_shortcut(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[
        'armory',{'state':'armory','view':'armor_cards','words':[]}])
    with pytest.raises(game.AutomationError,match='Armor card title'):
        session.armory()
    assert events==[('focus',),('key','2')]


def test_explicit_current_startup_clicks_stop_at_title_and_do_not_resume_in_loading(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[
        'unknown','unknown','startup','unknown','ship','equipment','equipment'])
    result=session.armory(startup_clicks=True)
    assert result['menu_verified']
    assert events==[('focus',),('startup_click',),('startup_click',),('key','space'),('debug','open_armory')]


@pytest.mark.parametrize('recognized',['ship','menu','equipment'])
def test_opening_burst_stops_after_first_click_that_reveals_known_ui(tmp_path,monkeypatch,recognized):
    session,events=armory_session(tmp_path,monkeypatch,[recognized])
    result=session.wait_startup_view(30,{'state':'unknown','path':'movie.png'},True)
    assert result['state']==recognized and events==[('startup_click',)]


def test_fresh_launch_automatically_allows_startup_movie_clicks(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,['unknown','ship','equipment','equipment'])
    windows=iter([[],[actual_game_window()]])
    monkeypatch.setattr(session,'windows',lambda:next(windows))
    monkeypatch.setattr(game,'run',lambda command:events.append(('launch',)))
    assert session.armory(launch=True)['menu_verified']
    assert events==[('launch',),('focus',),('startup_click',),('debug','open_armory')]


def test_startup_bursts_have_hard_click_limit_then_wait_without_input(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,['unknown']*24)
    clock=[0]
    monkeypatch.setattr(game.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(game.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    monkeypatch.setattr(session,'observe',lambda:{'state':'unknown','path':'movie.png'})
    with pytest.raises(game.AutomationError,match='click budget was bounded'):
        session.wait_startup_view(180,{'state':'unknown','path':'movie.png'},True)
    assert events==[('startup_click',)]*24 and clock[0]==180


def test_startup_focus_loss_stops_before_any_click(tmp_path,monkeypatch):
    session,events=armory_session(tmp_path,monkeypatch,[])
    def lose_focus():
        raise game.AutomationError('startup game focus lost')
    monkeypatch.setattr(session,'assert_focus',lose_focus)
    with pytest.raises(game.AutomationError,match='focus lost'):
        session.wait_startup_view(30,{'state':'unknown','path':'movie.png'},True)
    assert events==[]


def test_startup_click_confirmation_is_explicit_for_existing_game_and_dry_run(tmp_path,monkeypatch):
    parsed=game.parser().parse_args(['armory','--startup-clicks'])
    assert parsed.startup_clicks
    session=game.Session(args(tmp_path,False))
    monkeypatch.setattr(session,'windows',lambda:pytest.fail('dry startup inspected desktop'))
    assert session.armory(startup_clicks=True)['startup_clicks']


def test_custom_variant_category_is_an_armor_grid_only_with_native_detail_anchors():
    assert game.classify('ARMORY ARMOR RATING SPEED PASSIVE APPLY CUSTOM VARIANTS')['view']=='armor_grid'
    assert game.classify('CUSTOM VARIANTS')['state']=='unknown'
