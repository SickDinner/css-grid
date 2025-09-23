#!/usr/bin/env python3
"""ASCII-pohjainen Doom-tyylinen roguelike, jossa päihteet ja pultsarit hallitsevat."""

from __future__ import annotations

import os
import random
import textwrap
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional, Tuple


# ----------------------------- Perusdata ----------------------------- #


def clamp(value: int, low: int, high: int) -> int:
    """Rajoittaa arvon välille [low, high]."""

    return max(low, min(high, value))


@dataclass
class Weapon:
    name: str
    damage: Tuple[int, int]
    accuracy: int
    description: str
    mania_synergy: int = 0
    brutal: bool = False

    def stat_line(self) -> str:
        dmg = f"{self.damage[0]}-{self.damage[1]}"
        brutal = " | BRUTAL" if self.brutal else ""
        return f"DMG {dmg} | ACC {self.accuracy}{brutal}"


@dataclass
class Drug:
    name: str
    description: str
    mania_boost: int
    intox_boost: int
    heal: int
    adrenaline: int
    crash_delay: int
    crash_mania: int
    crash_health: int = 0
    detox: int = 0

    def use(self, player: "Player", _log: Iterable[str]) -> List[str]:
        msgs = [f"Nautit {self.name}! {self.description}"]
        start_health = player.health
        player.health = clamp(player.health + self.heal, 0, player.max_health)
        healed = player.health - start_health
        if healed:
            msgs.append(f"\t>>> Palautui {healed} HP")

        player.mania = clamp(player.mania + self.mania_boost, 0, 100)
        if self.mania_boost:
            msgs.append(f"\t>>> Mania +{self.mania_boost}")

        if self.detox:
            before = player.intoxication
            player.intoxication = clamp(player.intoxication - self.detox, 0, 100)
            if before != player.intoxication:
                msgs.append(f"\t>>> Puudutus taso laskee -> {player.intoxication}")
        else:
            player.intoxication = clamp(player.intoxication + self.intox_boost, 0, 100)
            if self.intox_boost:
                msgs.append(f"\t>>> Puudutus +{self.intox_boost}")

        player.adrenaline = clamp(player.adrenaline + self.adrenaline, 0, 50)
        if self.adrenaline:
            msgs.append(f"\t>>> Adrenaliini +{self.adrenaline}")

        if self.crash_delay > 0:
            player.schedule_crash(self)
            msgs.append(f"\t>>> {self.name} iskee takaraivolle {self.crash_delay} vuoron kuluttua")

        if player.mania >= 90:
            msgs.append("\t>>> Kuulostaa kuin helvetin bassorumpu syttyisi! Mania rajamailla.")
        return msgs


@dataclass
class Enemy:
    name: str
    health: int
    damage: Tuple[int, int]
    accuracy: int
    ferocity: int
    description: str
    mania_drain: int = 0
    brutal: bool = False

    def is_alive(self) -> bool:
        return self.health > 0

    def attack(self, player: "Player") -> Tuple[bool, int, str]:
        if not self.is_alive():
            return False, 0, f"{self.name} on jo maitohapoilla."

        hit_chance = clamp(self.accuracy - player.guard_bonus(), 25, 95)
        roll = random.randint(1, 100)
        if roll > hit_chance:
            return False, 0, f"{self.name} huitoo ohi - bassotärinä sekoitti tähtäyksen."

        damage = random.randint(*self.damage)
        damage = int(damage * (1.0 + self.ferocity / 100))
        if self.brutal and random.random() < 0.2:
            damage += 6
            flavour = " tekee kieltoalueen roundhouse-iskun!"
        else:
            flavour = random.choice([
                " sylkee kipinöitä päin naamaasi!",
                " takoo polkupyöränrungolla!",
                " iskee kahden euron oluttölkillä!",
            ])
        dealt = player.take_damage(damage)
        msg = f"{self.name}{flavour} -> {dealt} vahinkoa"
        if self.mania_drain:
            player.mania = clamp(player.mania - self.mania_drain, 0, 100)
            msg += f" ja imee maniasi -{self.mania_drain}!"
        return True, dealt, msg


@dataclass
class Room:
    name: str
    description: str
    glyph: str
    enemies: List[Enemy] = field(default_factory=list)
    loot: List[object] = field(default_factory=list)
    story: Optional[str] = None
    visited: bool = False

    def alive_enemies(self) -> List[Enemy]:
        return [e for e in self.enemies if e.is_alive()]


# ----------------------------- Pelaaja ----------------------------- #


class Player:
    def __init__(self, name: str, weapon: Weapon):
        self.name = name
        self.health = 85
        self.max_health = 100
        self.armor = 18
        self.mania = 12
        self.intoxication = 0
        self.adrenaline = 0
        self.location = (0, 0)
        self.current_weapon = weapon
        self.armory: Dict[str, Weapon] = {weapon.name.lower(): weapon}
        self.drugs: List[Drug] = []
        self.crash_timers: List[Dict[str, int]] = []
        self.guard_timer = 0

    # ------------------- Statukset ------------------- #

    def is_alive(self) -> bool:
        return self.health > 0

    def guard_bonus(self) -> int:
        return 25 if self.guard_timer else 0

    def status_block(self) -> str:
        return " | ".join(
            [
                f"HP {self.health}/{self.max_health}",
                f"ARM {self.armor}",
                f"MANIA {self.mania}",
                f"PUD {self.intoxication}",
                f"ADR {self.adrenaline}",
                f"ASE: {self.current_weapon.name}",
            ]
        )

    def bar(self, label: str, current: int, maximum: int, length: int = 20) -> str:
        filled = clamp(int((current / maximum) * length), 0, length)
        return f"{label:<7}[" + "#" * filled + "-" * (length - filled) + "]"

    # ------------------- Taistelufunktiot ------------------- #

    def attack(self, enemy: Enemy, mode: str = "blast") -> Tuple[bool, str]:
        weapon = self.current_weapon
        base_accuracy = weapon.accuracy
        base_accuracy += self.adrenaline * 3
        base_accuracy += self.mania // 7
        base_accuracy -= self.intoxication // 3
        aggressive = False
        multi = False
        mania_cost = 0
        if mode == "slam":
            aggressive = True
            base_accuracy -= 8
            mania_cost = 8
        elif mode == "spray":
            multi = True
            base_accuracy -= 15
            mania_cost = 5
        base_accuracy = clamp(base_accuracy, 10, 98)
        roll = random.randint(1, 100)
        if roll > base_accuracy:
            self.mania = clamp(self.mania - 2, 0, 100)
            return False, f"Ohi! Maniasi notkahtaa -> {self.mania}."

        damage = random.randint(*weapon.damage)
        damage += (self.mania * (3 + weapon.mania_synergy)) // 60
        damage += self.adrenaline // 2
        if aggressive:
            damage += 6
        if weapon.brutal:
            damage += 3
        crit_chance = 0.05 + self.mania / 150 + (0.05 if aggressive else 0)
        if random.random() < crit_chance:
            damage = int(damage * 1.6) + 4
            flavour = "KRITTI!"
        else:
            flavour = random.choice([
                "ratisee bassopulttina",
                "sähisee kipinäsateena",
                "kajahtaa neon-tomahawkkina",
            ])
        enemy.health -= damage
        mania_gain = 4 + damage // 7
        self.mania = clamp(self.mania + mania_gain - mania_cost, 0, 120)
        self.adrenaline = clamp(self.adrenaline + 2, 0, 50)
        log = f"Isket {enemy.name} -> {damage} dmg ({flavour})"
        if multi:
            log += " ja paineaalto järisyttää muuta huonetta!"
        if self.mania >= 100:
            log += " / MANIABURST!"
        return True, log

    def take_damage(self, raw: int) -> int:
        guard = 6 if self.guard_timer else 0
        armor_block = random.randint(self.armor // 6, self.armor // 3)
        adrenaline_block = self.adrenaline // 4
        mitigated = clamp(raw - armor_block - adrenaline_block - guard, 1, raw)
        self.health -= mitigated
        self.mania = clamp(self.mania + mitigated // 2 + 1, 0, 120)
        self.adrenaline = clamp(self.adrenaline + 1, 0, 50)
        return mitigated

    def howl(self) -> str:
        mania_gain = random.randint(6, 14)
        self.mania = clamp(self.mania + mania_gain, 0, 120)
        self.adrenaline = clamp(self.adrenaline + 3, 0, 50)
        self.guard_timer = 1
        return f"Ulvoit metallisen sotahuudon! Mania +{mania_gain}, adrenaliini +3. Väliaikainen suoja."

    def guard(self) -> str:
        self.guard_timer = 2
        self.mania = clamp(self.mania + 1, 0, 120)
        self.adrenaline = clamp(self.adrenaline + 1, 0, 50)
        return "Asetat romukilpesi ja valmistaudut väistämään - guard aktivoitu!"

    # ------------------- Inventaario ------------------- #

    def add_drug(self, drug: Drug) -> str:
        self.drugs.append(drug)
        return f"Taskuihin sujahtaa {drug.name}."

    def add_weapon(self, weapon: Weapon) -> str:
        key = weapon.name.lower()
        self.armory[key] = weapon
        return f"Saat käyttöösi aseen {weapon.name}! ({weapon.stat_line()})"

    def equip(self, weapon_name: str) -> str:
        weapon = self.armory.get(weapon_name.lower())
        if not weapon:
            return f"Et tunne asetta nimeltä {weapon_name}."
        self.current_weapon = weapon
        return f"Napsautat käyttöön aseen {weapon.name}."

    def schedule_crash(self, drug: Drug) -> None:
        self.crash_timers.append(
            {
                "name": drug.name,
                "remaining": drug.crash_delay,
                "mania": drug.crash_mania,
                "health": drug.crash_health,
            }
        )

    def process_crashes(self) -> List[str]:
        triggered: List[str] = []
        for crash in list(self.crash_timers):
            crash["remaining"] -= 1
            if crash["remaining"] <= 0:
                self.crash_timers.remove(crash)
                if crash["mania"]:
                    self.mania = clamp(self.mania - crash["mania"], 0, 120)
                if crash["health"]:
                    self.health = clamp(self.health - crash["health"], 0, self.max_health)
                triggered.append(
                    f"{crash['name']} kääntyy kylmäksi hiilenmuruksi! Mania -{crash['mania']} / HP -{crash['health']}"
                )
        return triggered

    def decay(self) -> List[str]:
        msgs: List[str] = []
        if self.intoxication:
            before = self.intoxication
            self.intoxication = clamp(self.intoxication - 1, 0, 100)
            if before != self.intoxication and self.intoxication % 5 == 0:
                msgs.append(f"Päihdekuorma tasaantuu -> {self.intoxication}")
        if self.adrenaline:
            self.adrenaline = clamp(self.adrenaline - 1, 0, 50)
        if self.guard_timer:
            self.guard_timer -= 1
        if self.mania > 0:
            self.mania = clamp(self.mania - 1, 0, 120)
        return msgs


# ----------------------------- Peli ----------------------------- #


class PunkkidoomGame:
    def __init__(self) -> None:
        random.seed()
        base_weapon = Weapon(
            name="Hiilikuitu-Nyrkki",
            damage=(6, 11),
            accuracy=72,
            description="Sähköistetty knuckleduster, jonka runko on salvattu raitiovaunusta.",
            mania_synergy=3,
        )
        self.player = Player(name="Rankka-Jeesus", weapon=base_weapon)
        self.rooms: Dict[Tuple[int, int], Room] = {}
        self.turn = 0
        self.messages: Deque[str] = deque(maxlen=8)
        self.running = True
        self.build_world()
        self.total_enemies = sum(len(room.enemies) for room in self.rooms.values())

    # ------------------- Maailman generointi ------------------- #

    def build_world(self) -> None:
        self.rooms = {
            (0, 0): Room(
                name="Graffitimetro",
                description="Hylätty asemalaituri täynnä neon-inkiväärin tuoksuista savua.",
                glyph="◎",
                story="Kuulut valitun rokkisissin klaaniin - Doom kuuluu nyt punkkareille.",
                loot=[
                    Drug(
                        name="Venttiili-Speedball",
                        description="Muinaisesta Dostojevski-kahvilasta jäänyt shokkiseos.",
                        mania_boost=16,
                        intox_boost=12,
                        heal=4,
                        adrenaline=6,
                        crash_delay=4,
                        crash_mania=20,
                        crash_health=4,
                    )
                ],
            ),
            (1, 0): Room(
                name="Kumikatu",
                description="Sateessa kimmeltävä kaistale, jossa pultsarit treenaavat nyrkkeilyä varjona.",
                glyph="=",
                enemies=[
                    Enemy(
                        name="Pultsari Virtanen",
                        health=32,
                        damage=(6, 10),
                        accuracy=65,
                        ferocity=15,
                        description="Vanha nyrkkeilijä, jonka pullonkorkit toimivat nyrkkiraudan tapaan.",
                    ),
                    Enemy(
                        name="Rälläkkä-Keijo",
                        health=28,
                        damage=(5, 9),
                        accuracy=60,
                        ferocity=10,
                        description="Kulmahiomakone aina käynnissä, kipinäsateet seuraavat.",
                        brutal=True,
                    ),
                ],
                loot=[
                    Weapon(
                        name="Rälläkkä-Remmi",
                        damage=(9, 16),
                        accuracy=63,
                        description="Kierrätetty moottorisaha, jota käytetään kuin kitaraa.",
                        mania_synergy=4,
                        brutal=True,
                    )
                ],
            ),
            (1, 1): Room(
                name="Basso-Kellari",
                description="Kellarissa kajahtelee subwoofer, joka pitää seinät hengissä.",
                glyph="♩",
                enemies=[
                    Enemy(
                        name="BassPapitar",
                        health=38,
                        damage=(7, 12),
                        accuracy=68,
                        ferocity=20,
                        description="Hallitsee resonansseja, jotka imevät maniasi.",
                        mania_drain=6,
                    )
                ],
                loot=[
                    Drug(
                        name="Subwoofer-Salmiakki",
                        description="Bassotaajuuksilla kyllästetty suolakide.",
                        mania_boost=12,
                        intox_boost=8,
                        heal=10,
                        adrenaline=4,
                        crash_delay=5,
                        crash_mania=22,
                        crash_health=0,
                    )
                ],
            ),
            (0, 1): Room(
                name="Biojätekuja",
                description="Ruosteiset biojätekontit tihkuvat hallusinoivaa kompostiteetä.",
                glyph="☣",
                enemies=[
                    Enemy(
                        name="Kompostikommandon",
                        health=30,
                        damage=(6, 11),
                        accuracy=62,
                        ferocity=18,
                        description="Räjähtävä biojätesäkki kädessä - varo mätää osumaa.",
                    )
                ],
                loot=[
                    Drug(
                        name="Kompostitee",
                        description="Etova mutta puhdistava; vie myrkkyjä mutta imee manian.",
                        mania_boost=-8,
                        intox_boost=0,
                        heal=16,
                        adrenaline=2,
                        crash_delay=0,
                        crash_mania=0,
                        crash_health=0,
                        detox=18,
                    )
                ],
            ),
            (-1, 0): Room(
                name="Vinyylihylly-labyrintti",
                description="Vinyylit muodostavat muurin, jonka välistä soi analoginen teurastus.",
                glyph="♬",
                enemies=[
                    Enemy(
                        name="DJ Resonaattori",
                        health=35,
                        damage=(5, 9),
                        accuracy=70,
                        ferocity=25,
                        description="Kääntelee levyjä kuin moottorisahoja.",
                        mania_drain=4,
                    )
                ],
                loot=[
                    Weapon(
                        name="Bassohaulikko",
                        damage=(12, 20),
                        accuracy=66,
                        description="Rakennettu katukartiosta; jokainen laukaus on drop-kick.",
                        mania_synergy=5,
                    )
                ],
            ),
            (0, -1): Room(
                name="Sähkökäytävä",
                description="Pimeä tunnelma, kaapeleista roiskuu valokaarta ja amfetamiinia.",
                glyph="⚡",
                enemies=[
                    Enemy(
                        name="Shokkijengi",
                        health=40,
                        damage=(8, 12),
                        accuracy=58,
                        ferocity=25,
                        description="Yhdessä iskevät kuin oikosulku.",
                        brutal=True,
                    )
                ],
                loot=[
                    Drug(
                        name="Oikosulku",
                        description="Polttaa hermot auki mutta jättää hurmoksen.",
                        mania_boost=22,
                        intox_boost=14,
                        heal=0,
                        adrenaline=9,
                        crash_delay=3,
                        crash_mania=28,
                        crash_health=6,
                    )
                ],
            ),
            (2, 0): Room(
                name="Neon-Morgue",
                description="Lakkautettu kylmiö, johon on rakennettu rave-laboratorio.",
                glyph="☠",
                enemies=[
                    Enemy(
                        name="Suonipappi",
                        health=46,
                        damage=(9, 13),
                        accuracy=70,
                        ferocity=30,
                        description="Kastelee ruiskulla jokaista, joka uskaltaa häiritä rituaalia.",
                        brutal=True,
                    )
                ],
                loot=[
                    Drug(
                        name="Kyytsishotti",
                        description="Kylmän ja kuuman synkroniainen sykäys.",
                        mania_boost=18,
                        intox_boost=10,
                        heal=12,
                        adrenaline=8,
                        crash_delay=4,
                        crash_mania=24,
                        crash_health=8,
                    )
                ],
            ),
            (2, 1): Room(
                name="Plasma-Areena",
                description="Entinen ostoskeskus, jonka keskellä on plasmapilari ja yleisö huutaa.",
                glyph="✶",
                enemies=[
                    Enemy(
                        name="MegaPultsari",
                        health=75,
                        damage=(12, 18),
                        accuracy=72,
                        ferocity=35,
                        description="Kaupunki legendaarinen keulakuva, joka huutaa Doom-hymnejä.",
                        brutal=True,
                    )
                ],
                loot=[
                    Weapon(
                        name="Plasma-Karbidikeppi",
                        damage=(15, 23),
                        accuracy=68,
                        description="Valokaarella sykkivä keppi, joka muuntuu riffiksi.",
                        mania_synergy=6,
                        brutal=True,
                    ),
                    Drug(
                        name="Pyhä Melodraama",
                        description="Kyynelehtivä psykoosi, joka nostaa mutta ei koskaan laske kauniisti.",
                        mania_boost=25,
                        intox_boost=16,
                        heal=20,
                        adrenaline=10,
                        crash_delay=5,
                        crash_mania=36,
                        crash_health=12,
                    ),
                ],
            ),
        }

    # ------------------- Tulostus ------------------- #

    def log(self, message: str) -> None:
        wrapped = textwrap.wrap(message, 78) or [""]
        for line in wrapped:
            self.messages.append(line)

    def render_map(self) -> str:
        xs = [pos[0] for pos in self.rooms]
        ys = [pos[1] for pos in self.rooms]
        min_x, max_x = min(xs) - 1, max(xs) + 1
        min_y, max_y = min(ys) - 1, max(ys) + 1
        rows = []
        for y in range(max_y, min_y - 1, -1):
            row = []
            for x in range(min_x, max_x + 1):
                if (x, y) == self.player.location:
                    char = "@"
                elif (x, y) in self.rooms:
                    room = self.rooms[(x, y)]
                    if room.alive_enemies():
                        char = "!"
                    elif room.visited:
                        char = room.glyph
                    else:
                        char = "?"
                else:
                    char = " "
                row.append(char)
            rows.append(" ".join(row))
        return "\n".join(rows)

    def status_panel(self) -> str:
        player = self.player
        parts = [
            player.bar("HP", player.health, player.max_health),
            player.bar("MANIA", player.mania, 120),
            player.bar("PUD", player.intoxication, 100),
            player.bar("ADR", player.adrenaline, 50),
            "ASE: " + player.current_weapon.name,
        ]
        return "\n".join(parts)

    def print_intro(self) -> None:
        art = r"""
   ____            _        _    ____                          
  |  _ \ _   _ ___| |_ ___ | | _|  _ \  ___   ___  _ __  _   _ 
  | |_) | | | / __| __/ _ \| |/ / | | |/ _ \ / _ \| '_ \| | | |
  |  __/| |_| \__ \ || (_) |   <| |_| | (_) | (_) | | | | |_| |
  |_|    \__,_|___/\__\___/|_|\_\____/ \___/ \___/|_| |_|\__, |
                                                         |___/ 
        """
        print(art)
        print("PUNK-DOOM RPG: Neon-kuumottava pultsarisota")
        print("Komentotyyli: kirjaile komento ja paina enter. 'help' kertoo vaihtoehdot.")
        print()
        start_room = self.rooms[self.player.location]
        print(start_room.description)
        if start_room.story:
            print(textwrap.fill(start_room.story, 78))
        print()
        self.display()

    def display(self) -> None:
        os.system("clear" if os.name != "nt" else "cls")
        print(self.render_map())
        print("-" * 78)
        print(self.status_panel())
        print("-" * 78)
        for msg in self.messages:
            print(msg)

    def describe_room(self, room: Room) -> None:
        self.log(f"{room.name}: {room.description}")
        if room.story and not room.visited:
            self.log(room.story)
        if room.loot:
            loot_names = ", ".join(item.name for item in room.loot)
            self.log(f"Näet mahdollisesti: {loot_names}.")
        enemies = room.alive_enemies()
        if enemies:
            names = ", ".join(e.name for e in enemies)
            self.log(f"Varo! Täällä väijyy: {names}.")
        room.visited = True

    # ------------------- Komennot ------------------- #

    def handle_command(self, raw: str) -> None:
        if not raw.strip():
            self.log("... seisot hetken hiljaa.")
            self.end_turn()
            return
        cmd, *rest = raw.strip().split()
        cmd = cmd.lower()
        arg = " ".join(rest)
        if cmd in {"north", "n"}:
            self.move((0, 1))
        elif cmd in {"south", "s"}:
            self.move((0, -1))
        elif cmd in {"east", "e"}:
            self.move((1, 0))
        elif cmd in {"west", "w"}:
            self.move((-1, 0))
        elif cmd == "look":
            room = self.rooms.get(self.player.location)
            if room:
                self.describe_room(room)
        elif cmd == "map":
            self.log("Tutkit karttaa.")
        elif cmd == "status":
            self.log(self.player.status_block())
        elif cmd == "inventory":
            self.show_inventory()
        elif cmd == "equip":
            if not arg:
                self.log("Minkä aseen haluat varustaa?")
            else:
                self.log(self.player.equip(arg))
        elif cmd == "use":
            if not arg:
                self.log("Mitä ainetta vedät?")
            else:
                self.consume_drug(arg)
        elif cmd in {"rest", "wait"}:
            self.log("Hengität syvään neon-höyryjä.")
            self.end_turn()
        elif cmd == "help":
            self.show_help()
        elif cmd == "quit":
            self.running = False
            self.log("Päätät poistua ennen kuin viranomaiset ehtivät paikalle.")
        else:
            self.log(f"Komento '{cmd}' ei ole tuttu. Kirjoita 'help'.")

    def show_inventory(self) -> None:
        if not self.player.drugs and len(self.player.armory) <= 1:
            self.log("Taskut kolisevat vain pulteista.")
            return
        if self.player.drugs:
            drugs = ", ".join(drug.name for drug in self.player.drugs)
            self.log(f"Huumevarasto: {drugs}")
        weapons = [w for w in self.player.armory.values() if w is not self.player.current_weapon]
        if weapons:
            listing = "; ".join(f"{w.name} ({w.stat_line()})" for w in weapons)
            self.log(f"Varalla aseita: {listing}")

    def show_help(self) -> None:
        commands = [
            "Liiku: north/south/east/west (tai n/s/e/w)",
            "look - kuvaus huoneesta",
            "map - kartta",
            "status - tilanne",
            "inventory - varusteet",
            "use <nimi> - nautitaan huume",
            "equip <ase> - vaihda ase",
            "rest - huilaa",
            "help - tämä lista",
            "quit - poistu",
        ]
        if self.rooms[self.player.location].alive_enemies():
            commands.extend([
                "blast - perusisku",
                "slam - mania-syöksy",
                "spray - ammu hajalle, epätarkka",
                "howl - suoja ja mania",
                "guard - puolustus",
            ])
        for line in commands:
            self.log(line)

    def consume_drug(self, name: str) -> None:
        for i, drug in enumerate(self.player.drugs):
            if drug.name.lower().startswith(name.lower()):
                self.player.drugs.pop(i)
                for msg in drug.use(self.player, self.messages):
                    self.log(msg)
                self.end_turn()
                return
        self.log(f"Et löydä mitään nimeltään {name}.")

    def move(self, delta: Tuple[int, int]) -> None:
        new_pos = (self.player.location[0] + delta[0], self.player.location[1] + delta[1])
        room = self.rooms.get(new_pos)
        if not room:
            self.log("Törmäät betoniseinään; tää suunta on lukossa.")
            return
        if self.rooms[self.player.location].alive_enemies():
            self.log("Et voi karata kesken tapposoolon!")
            return
        self.player.location = new_pos
        self.describe_room(room)
        self.end_turn()

    def loot_room(self, room: Room) -> None:
        if not room.loot:
            self.log("Mitään kiinnostavaa ei näy, vain pölyisiä c-kasetteja.")
            return
        gained: List[str] = []
        for item in list(room.loot):
            if isinstance(item, Drug):
                gained.append(self.player.add_drug(item))
            elif isinstance(item, Weapon):
                gained.append(self.player.add_weapon(item))
            room.loot.remove(item)
        for msg in gained:
            self.log(msg)

    def check_room_clear(self, room: Room) -> None:
        if not room.alive_enemies():
            self.log(f"Huone {room.name} hiljenee - keräät saaliin.")
            self.loot_room(room)

    def end_turn(self) -> None:
        self.turn += 1
        for msg in self.player.decay():
            self.log(msg)
        for msg in self.player.process_crashes():
            self.log(msg)
        if self.player.mania >= 105:
            surge_damage = random.randint(10, 18)
            self.player.health = clamp(self.player.health - surge_damage, 0, self.player.max_health)
            self.player.mania = clamp(self.player.mania - 20, 0, 120)
            self.log(
                f"Maniapurkaus repii sinut sisältäpäin! \n\t>>> HP -{surge_damage}, Mania laskee." 
            )

    # ------------------- Taistelu ------------------- #

    def combat(self, room: Room) -> None:
        self.log(f"Taisto alkaa: {room.name}")
        while self.player.is_alive() and room.alive_enemies() and self.running:
            self.display_combat(room)
            command = input("taistelu> ").strip().lower()
            if not command:
                command = "blast"
            if command in {"blast", "shoot"}:
                self.player.guard_timer = 0
                target = room.alive_enemies()[0]
                hit, log = self.player.attack(target, mode="blast")
                self.log(log)
                if hit and not target.is_alive():
                    self.log(f"{target.name} rojahtaa neon-soralle!")
                    self.total_enemies -= 1
            elif command == "slam":
                target = room.alive_enemies()[0]
                hit, log = self.player.attack(target, mode="slam")
                self.log(log)
                if hit and not target.is_alive():
                    self.log(f"{target.name} sulaa moottoriöljyksi!")
                    self.total_enemies -= 1
            elif command == "spray":
                targets = room.alive_enemies()
                if not targets:
                    continue
                hit_any = False
                for enemy in targets:
                    hit, log = self.player.attack(enemy, mode="spray")
                    if hit:
                        hit_any = True
                    self.log(log)
                    if not enemy.is_alive():
                        self.log(f"{enemy.name} kaatuu rytmistä ulos!")
                        self.total_enemies -= 1
                if not hit_any:
                    self.log("Harmittava ohi - spray vain herättää pölyn.")
            elif command == "howl":
                self.log(self.player.howl())
            elif command == "guard":
                self.log(self.player.guard())
            elif command.startswith("use"):
                _, _, rest = command.partition(" ")
                if rest:
                    self.consume_drug(rest)
                else:
                    self.log("Mitä vedät?")
                continue
            elif command == "status":
                self.log(self.player.status_block())
                continue
            elif command == "help":
                self.show_help()
                continue
            elif command == "run":
                self.log("Yleisö buuaa - et pääse pakoon! Taistelun on päätyttävä.")
            elif command == "quit":
                self.running = False
                return
            else:
                self.log("Epämääräinen liike - komento tuntematon.")
                continue

            # Vihollisten vuoro
            for enemy in list(room.alive_enemies()):
                hit, _, msg = enemy.attack(self.player)
                self.log(msg)
                if not self.player.is_alive():
                    break

            self.end_turn()

        if self.player.is_alive():
            self.check_room_clear(room)

    def display_combat(self, room: Room) -> None:
        os.system("clear" if os.name != "nt" else "cls")
        print(self.render_map())
        print("-" * 78)
        print(self.status_panel())
        print("-" * 78)
        print(f"Huone: {room.name}")
        print(textwrap.fill(room.description, 78))
        print()
        enemies = room.alive_enemies()
        if enemies:
            for enemy in enemies:
                print(f"- {enemy.name}: HP {enemy.health} | {enemy.description}")
        else:
            print("Ei vastusta jäljellä.")
        print("-" * 78)
        for msg in self.messages:
            print(msg)
        self.messages.clear()

    # ------------------- Päälooppi ------------------- #

    def run(self) -> None:
        self.print_intro()
        while self.running and self.player.is_alive() and self.total_enemies > 0:
            room = self.rooms[self.player.location]
            if room.alive_enemies():
                self.combat(room)
                continue
            command = input("komento> ")
            if command.strip().lower() == "loot":
                self.loot_room(room)
                self.end_turn()
            else:
                self.handle_command(command)
            self.display()
        if not self.player.is_alive():
            print("\nVERHO LASKEUTUU. Rankka-Jeesus kaatui kuin kaatopaikan patsas.")
        elif self.total_enemies <= 0:
            print("\nKaikki pultsarit nujerrettu! Doom on jälleen sinun kitarassasi.")
        else:
            print("\nPeli päättyy kesken - mutta kadut humisevat edelleen.")


def main() -> None:
    try:
        game = PunkkidoomGame()
        game.run()
    except KeyboardInterrupt:
        print("\nKeskeytit neon-soiton.")


if __name__ == "__main__":
    main()
