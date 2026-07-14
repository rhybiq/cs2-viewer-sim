"""Thin wrapper around awpy's Demo -- isolates the rest of this module from
awpy's exact dataframe schema (undocumented publicly; validated empirically
against a real CS2 demo -- see README.md for the schema notes this was built
against: awpy 2.0.2 / demoparser2 0.41.4).

Real, confirmed behavior worth remembering here (not just in commit
history): awpy already excludes an incomplete/truncated final round (one
was present in the real demo this was tested against -- the recording cut
off mid-round, with no confirmed winner) from both `.kills` and `.rounds`,
so callers never see a round with a missing winner. `.kills`' `attacker_name`/
`attacker_side` are null for world/suicide "kills" (fall damage, self-nade,
etc.) -- these still remove the victim from play but never count as
anyone's kill.

`.kills`' own `weapon` column uses internal script names (`"ak47"`,
`"hegrenade"`, presumably `"knife"` for a knife kill -- unconfirmed against
real data since the demo this was built against had none). Per-tick state
(view angle, held weapon) is a *different* convenience API,
`Demo.parse_ticks(player_props=[...])`, which resolves to human-readable
names (`"AK-47"`, `"High Explosive Grenade"`) -- a different naming scheme
from `.kills.weapon`, confirmed empirically. Unrecognized `player_props`
names fail silently (the column is just missing) rather than raising, so
any new prop name added here needs checking against
`dem.parser.list_updated_fields()` / a real sample, not assumed.
`parse_ticks` over an entire ~14-round match measured at ~0.4s for the
`yaw`/`active_weapon_name` props used below -- cheap enough to run
unconditionally, not worth gating behind a flag.
"""

import math
from dataclasses import dataclass

from awpy import Demo

# Grenade names as returned by parse_ticks(player_props=["active_weapon_name"]) --
# confirmed empirically, NOT the same strings as .kills.weapon.
GRENADE_ACTIVE_WEAPON_NAMES = {
    "Decoy Grenade", "Flashbang", "High Explosive Grenade",
    "Incendiary Grenade", "Molotov", "Smoke Grenade",
}


@dataclass
class KillEvent:
    round_num: int
    tick: int
    attacker_name: str  # None for a world/suicide death -- no one gets credit
    attacker_side: str  # "ct" | "t" | None
    victim_name: str
    victim_side: str    # "ct" | "t"
    headshot: bool
    weapon: str               # killer's weapon, .kills' own script name (e.g. "ak47")
    victim_active_weapon: str  # what the VICTIM was holding when they died (human-readable,
                                # e.g. "High Explosive Grenade") -- None if unresolved
    victim_view_diff_deg: float  # angle between the victim's facing yaw and the bearing to
                                   # their killer at death; None if unavailable (world kill,
                                   # no attacker position, or no prior tick data for them yet)


@dataclass
class RoundInfo:
    round_num: int
    winner: str  # "ct" | "t"
    reason: str  # e.g. "bomb_defused", "bomb_exploded", "ct_killed", "t_killed"


@dataclass
class ParsedDemo:
    map_name: str
    tick_rate: float
    kills: list  # list[KillEvent]
    rounds: list  # list[RoundInfo] -- only rounds awpy considers complete


def _bearing_deg(from_x, from_y, to_x, to_y):
    """Compass-style bearing in degrees from (from_x,from_y) to (to_x,to_y),
    in the same convention as Source-engine yaw (0 = +X, 90 = +Y)."""
    return math.degrees(math.atan2(to_y - from_y, to_x - from_x))


def _angle_diff_deg(a, b):
    """Smallest angle (0-180) between two headings in degrees."""
    return abs((a - b + 180) % 360 - 180)


def parse_demo(path, tick_rate_override=None):
    dem = Demo(path)
    dem.parse()

    kills_df = dem.kills.with_row_index("_kill_idx")
    ticks_df = dem.parse_ticks(player_props=["yaw", "active_weapon_name"])

    # As-of join: each kill gets the victim's most recent tick state (facing
    # yaw, held weapon) strictly BEFORE the kill tick. allow_exact_matches=False
    # matters here -- confirmed empirically that at the exact death tick itself
    # active_weapon_name already reads null (weapon cleared on death), so an
    # inclusive match would silently lose every "died holding X" case.
    joined = (
        kills_df.sort("tick")
        .join_asof(
            ticks_df.sort("tick").rename({"tick": "_state_tick"}),
            left_on="tick", right_on="_state_tick",
            by_left="victim_steamid", by_right="steamid",
            strategy="backward", allow_exact_matches=False,
            check_sortedness=False,  # both sides are explicitly .sort("tick")'d above;
                                       # polars can't verify sortedness within by-groups itself
        )
        .sort("_kill_idx")
    )

    kills = []
    for row in joined.iter_rows(named=True):
        bearing = (
            _bearing_deg(row["victim_X"], row["victim_Y"], row["attacker_X"], row["attacker_Y"])
            if row["attacker_name"] is not None and row["attacker_X"] is not None else None
        )
        view_diff = (
            _angle_diff_deg(bearing, row["yaw"])
            if bearing is not None and row["yaw"] is not None else None
        )
        kills.append(KillEvent(
            round_num=row["round_num"],
            tick=row["tick"],
            attacker_name=row["attacker_name"],
            attacker_side=row["attacker_side"],
            victim_name=row["victim_name"],
            victim_side=row["victim_side"],
            headshot=row["headshot"],
            weapon=row["weapon"],
            victim_active_weapon=row["active_weapon_name"],
            victim_view_diff_deg=view_diff,
        ))

    rounds = [
        RoundInfo(round_num=row["round_num"], winner=row["winner"], reason=row["reason"])
        for row in dem.rounds.iter_rows(named=True)
    ]
    return ParsedDemo(
        map_name=dem.header.get("map_name", "unknown"),
        tick_rate=tick_rate_override or dem.tickrate,
        kills=kills,
        rounds=rounds,
    )
