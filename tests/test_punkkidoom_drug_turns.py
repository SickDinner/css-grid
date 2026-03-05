from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import builtins

import punkkidoom


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
    room = game.rooms[game.player.location]
    room.enemies = [punkkidoom.Enemy("Dummy", 30, (1, 1), 100, 0, "")]
    game.player.drugs = [punkkidoom.Drug("Testi", "", 0, 0, 0, 0, 0, 0)]

    calls = {"enemy_attacks": 0}

    def fake_attack(_player):
        calls["enemy_attacks"] += 1
        return False, 0, "dummy miss"

    room.enemies[0].attack = fake_attack

    inputs = iter(["use testi", "quit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(inputs))

    game.combat(room)

    assert calls["enemy_attacks"] == 1


def test_combat_use_missing_drug_does_not_give_enemy_free_turn(monkeypatch):
    game = punkkidoom.PunkkidoomGame()
    room = game.rooms[game.player.location]
    room.enemies = [punkkidoom.Enemy("Dummy", 30, (1, 1), 100, 0, "")]

    calls = {"enemy_attacks": 0}

    def fake_attack(_player):
        calls["enemy_attacks"] += 1
        return False, 0, "dummy miss"

    room.enemies[0].attack = fake_attack

    inputs = iter(["use puuttuva", "quit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(inputs))

    game.combat(room)

    assert calls["enemy_attacks"] == 0


def test_combat_use_prefix_typo_is_not_treated_as_use(monkeypatch):
    game = punkkidoom.PunkkidoomGame()
    room = game.rooms[game.player.location]
    room.enemies = [punkkidoom.Enemy("Dummy", 30, (1, 1), 100, 0, "")]

    calls = {"enemy_attacks": 0}

    def fake_attack(_player):
        calls["enemy_attacks"] += 1
        return False, 0, "dummy miss"

    room.enemies[0].attack = fake_attack

    inputs = iter(["usee testi", "quit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(inputs))

    game.combat(room)

    assert calls["enemy_attacks"] == 0


def test_combat_use_with_extra_spaces_still_uses_drug(monkeypatch):
    game = punkkidoom.PunkkidoomGame()
    room = game.rooms[game.player.location]
    room.enemies = [punkkidoom.Enemy("Dummy", 30, (1, 1), 100, 0, "")]
    game.player.drugs = [punkkidoom.Drug("Testi", "", 0, 0, 0, 0, 0, 0)]

    calls = {"enemy_attacks": 0}

    def fake_attack(_player):
        calls["enemy_attacks"] += 1
        return False, 0, "dummy miss"

    room.enemies[0].attack = fake_attack

    inputs = iter(["use   testi", "quit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(inputs))

    game.combat(room)

    assert calls["enemy_attacks"] == 1
