"""Detects highlight-worthy moments (multi-kills, aces, clutches) from a
parsed CS2 demo -- perfect structured data, no video/pixel guessing. This is
the actual value-add of this module; parser.py just gets clean data here.

Known limitation: clutch alive-count tracking only accounts for deaths, not
disconnects -- awpy doesn't expose a disconnect table, so a player who
leaves mid-round without dying won't decrement their side's alive count.
Rare in practice (this only matters mid-round, not the far more common
end-of-match rage-quit), not worth the extra raw-event plumbing to close
for a first version.
"""

from collections import defaultdict
from dataclasses import dataclass

from demo_highlights.parser import parse_demo

MULTI_KILL_LABELS = {2: "multi_kill_2k", 3: "multi_kill_3k", 4: "multi_kill_4k", 5: "ace"}

# Most-to-least impressive, ties broken by round number -- plain tunable
# constants (matching viewer_sim.py's score()), not ML scoring, and an
# explicit starting guess open to reordering.
CATEGORY_PRIORITY = [
    "clutch_1v5", "clutch_1v4", "ace", "clutch_1v3", "multi_kill_4k",
    "clutch_1v2", "multi_kill_3k", "clutch_1v1", "multi_kill_2k",
]
_PRIORITY_RANK = {cat: i for i, cat in enumerate(CATEGORY_PRIORITY)}
_UNRANKED = len(CATEGORY_PRIORITY)

FOOTAGE_TOP_N_DEFAULT = 20


@dataclass
class HighlightEvent:
    round_num: int
    tick: int
    time_s: float
    category: str
    players: list  # who's involved -- the multi-killer, or the clutcher
    reason: str      # human-readable


@dataclass
class DemoScanResult:
    demo_file: str
    map_name: str
    total_rounds: int
    events: list  # list[HighlightEvent], ranked, capped to top_n


def _detect_multi_kills(round_num, kills):
    """Groups kills by attacker, excluding team-kills and world/suicide
    "kills" (no attacker) -- 2/3/4 kills upgrade to multi_kill_2k/3k/4k, 5
    (the whole enemy team) to ace. Counted regardless of round outcome -- a
    multi-kill round the player's team still lost is still a real
    multi-kill, an intentional asymmetry vs. clutches below (which require
    a round win).
    Returns [(player, category, tick, reason)].
    """
    by_attacker = defaultdict(list)
    for k in kills:
        if k.attacker_name is None or k.attacker_side == k.victim_side:
            continue  # world/suicide death, or a team-kill -- doesn't count
        by_attacker[k.attacker_name].append(k)

    out = []
    for attacker, ks in by_attacker.items():
        n = len(ks)
        if n < 2:
            continue
        category = MULTI_KILL_LABELS[min(n, 5)]
        last_tick = max(k.tick for k in ks)
        out.append((attacker, category, last_tick, f"{attacker} got a {n}-kill round (round {round_num})"))
    return out


def _detect_clutches(round_num, kills, winner):
    """For each side, finds the tick at which it was first reduced to
    exactly one survivor (its (starting_count - 1)th death, in tick order --
    alive counts only ever decrease within a round, so this happens at most
    once per side) and how many enemies were alive at that same instant.
    Only emits an event if that survivor's side went on to win the round --
    a "1vN situation" that was lost isn't a clutch.
    Returns [(player, category, tick, reason)].
    """
    roster = {"ct": set(), "t": set()}
    for k in kills:
        if k.victim_side in roster:
            roster[k.victim_side].add(k.victim_name)
        if k.attacker_side in roster and k.attacker_name:
            roster[k.attacker_side].add(k.attacker_name)

    deaths_by_side = {"ct": [], "t": []}
    for k in kills:
        if k.victim_side in deaths_by_side:
            deaths_by_side[k.victim_side].append((k.tick, k.victim_name))
    for deaths in deaths_by_side.values():
        deaths.sort(key=lambda d: d[0])

    out = []
    for side in ("ct", "t"):
        other = "t" if side == "ct" else "ct"
        starting_n = len(roster[side])
        deaths = deaths_by_side[side]
        if starting_n < 2 or len(deaths) < starting_n - 1:
            continue  # never had teammates to lose, or never reduced to 1 alive
        reduce_tick = deaths[starting_n - 2][0]
        dead_names = {name for _, name in deaths[: starting_n - 1]}
        survivors = roster[side] - dead_names
        if len(survivors) != 1:
            continue  # unexpected data shape -- bail defensively, don't guess
        if winner != side:
            continue  # only a win counts as a clutch
        survivor = next(iter(survivors))
        opp_dead_by_then = sum(1 for t, _ in deaths_by_side[other] if t <= reduce_tick)
        n_enemies = len(roster[other]) - opp_dead_by_then
        if n_enemies < 1:
            continue  # bad/ambiguous data -- skip rather than guess
        category = f"clutch_1v{min(n_enemies, 5)}"
        out.append((survivor, category, reduce_tick, f"{survivor} won a 1v{n_enemies} clutch (round {round_num})"))
    return out


def find_highlights_from_demo(path, top_n=FOOTAGE_TOP_N_DEFAULT, tick_rate_override=None):
    """Parses path and returns a DemoScanResult ranked by CATEGORY_PRIORITY,
    capped to top_n. One highlight per (round, player): a player who
    qualifies for more than one raw tag in the same round (e.g. a 4-kill
    round that's also a won 1v2 clutch) collapses to their single
    highest-priority tag.
    """
    parsed = parse_demo(path, tick_rate_override=tick_rate_override)

    kills_by_round = defaultdict(list)
    for k in parsed.kills:
        kills_by_round[k.round_num].append(k)

    raw = []  # (round_num, player, category, tick, reason)
    for round_info in parsed.rounds:
        kills = kills_by_round.get(round_info.round_num, [])
        for player, category, tick, reason in _detect_multi_kills(round_info.round_num, kills):
            raw.append((round_info.round_num, player, category, tick, reason))
        for player, category, tick, reason in _detect_clutches(round_info.round_num, kills, round_info.winner):
            raw.append((round_info.round_num, player, category, tick, reason))

    best = {}  # (round_num, player) -> (rank, category, tick, reason)
    for round_num, player, category, tick, reason in raw:
        key = (round_num, player)
        rank = _PRIORITY_RANK.get(category, _UNRANKED)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, category, tick, reason)

    events = [
        HighlightEvent(
            round_num=round_num, tick=tick, time_s=round(tick / parsed.tick_rate, 1),
            category=category, players=[player], reason=reason,
        )
        for (round_num, player), (_rank, category, tick, reason) in best.items()
    ]
    events.sort(key=lambda e: (_PRIORITY_RANK.get(e.category, _UNRANKED), e.round_num))

    return DemoScanResult(
        demo_file=path, map_name=parsed.map_name, total_rounds=len(parsed.rounds),
        events=events[:top_n],
    )
