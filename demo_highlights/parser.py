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
"""

from dataclasses import dataclass

from awpy import Demo


@dataclass
class KillEvent:
    round_num: int
    tick: int
    attacker_name: str  # None for a world/suicide death -- no one gets credit
    attacker_side: str  # "ct" | "t" | None
    victim_name: str
    victim_side: str    # "ct" | "t"
    headshot: bool


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


def parse_demo(path, tick_rate_override=None):
    dem = Demo(path)
    dem.parse()

    kills = [
        KillEvent(
            round_num=row["round_num"],
            tick=row["tick"],
            attacker_name=row["attacker_name"],
            attacker_side=row["attacker_side"],
            victim_name=row["victim_name"],
            victim_side=row["victim_side"],
            headshot=row["headshot"],
        )
        for row in dem.kills.iter_rows(named=True)
    ]
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
