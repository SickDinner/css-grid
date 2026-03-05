import builtins

import punkkidoom


def _setup_single_enemy_room(game: punkkidoom.PunkkidoomGame) -> punkkidoom.Room:
    room = game.rooms[game.player.location]
    room.enemies = [punkkidoom.Enemy("Dummy", 30, (1, 1), 100, 0, "")]
    return room


def _count_enemy_attacks(room: punkkidoom.Room) -> dict:
    calls = {"enemy_attacks": 0}

    def fake_attack(_player):
        calls["enemy_attacks"] += 1
        return False, 0, "dummy miss"

    room.enemies[0].attack = fake_attack
    return calls


def _run_combat_inputs(monkeypatch, game: punkkidoom.PunkkidoomGame, commands: list[str]) -> None:
    inputs = iter(commands)
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(inputs))
    game.combat(game.rooms[game.player.location])


def test_handle_command_use_consumes_turn_only_on_success():
    game = punkkidoom.PunkkidoomGame()
    start_turn = game.turn

    game.player.drugs = [punkkidoom.Drug("Testi", "", 0, 0, 0, 0, 0, 0)]
    game.handle_command("use testi")
    assert game.turn == start_turn + 1

    game.handle_command("use puuttuva")
    assert game.turn == start_turn + 1


def test_combat_use_valid_drug_allows_enemy_phase(monkeypatch):
    game = punkkidoom.PunkkidoomGame()
    room = _setup_single_enemy_room(game)
    game.player.drugs = [punkkidoom.Drug("Testi", "", 0, 0, 0, 0, 0, 0)]

    calls = _count_enemy_attacks(room)
    _run_combat_inputs(monkeypatch, game, ["use testi", "quit"])

    assert calls["enemy_attacks"] == 1


def test_combat_use_missing_drug_does_not_give_enemy_free_turn(monkeypatch):
    game = punkkidoom.PunkkidoomGame()
    room = _setup_single_enemy_room(game)

    calls = _count_enemy_attacks(room)
    _run_combat_inputs(monkeypatch, game, ["use puuttuva", "quit"])

    assert calls["enemy_attacks"] == 0


def test_combat_use_prefix_typo_is_not_treated_as_use(monkeypatch):
    game = punkkidoom.PunkkidoomGame()
    room = _setup_single_enemy_room(game)

    calls = _count_enemy_attacks(room)
    _run_combat_inputs(monkeypatch, game, ["usee testi", "quit"])

    assert calls["enemy_attacks"] == 0


def test_combat_use_with_extra_spaces_still_uses_drug(monkeypatch):
    game = punkkidoom.PunkkidoomGame()
    room = _setup_single_enemy_room(game)
    game.player.drugs = [punkkidoom.Drug("Testi", "", 0, 0, 0, 0, 0, 0)]

    calls = _count_enemy_attacks(room)
    _run_combat_inputs(monkeypatch, game, ["use   testi", "quit"])

    assert calls["enemy_attacks"] == 1


def test_handle_command_use_with_extra_spaces_consumes_turn():
    game = punkkidoom.PunkkidoomGame()
    start_turn = game.turn

    game.player.drugs = [punkkidoom.Drug("Testi", "", 0, 0, 0, 0, 0, 0)]
    game.handle_command("use    testi")

    assert game.turn == start_turn + 1


def test_handle_command_use_with_only_spaces_in_arg_does_not_consume_turn():
    game = punkkidoom.PunkkidoomGame()
    start_turn = game.turn

    game.handle_command("use    ")

    assert game.turn == start_turn
