#!/usr/bin/env python3
"""CLI for demo_highlights: parses a CS2 demo (.dem) already on disk and
prints a ranked list of highlight moments (multi-kills, aces, clutches).

Does NOT fetch demos for you -- point it at a .dem file you already have.
See README.md for why sharecode-to-download is a deliberately separate,
not-yet-built follow-up.

Usage:
    python -m demo_highlights.cli match.dem
    python -m demo_highlights.cli match.dem --top-n 10
    python -m demo_highlights.cli match.dem --json result.json
    python -m demo_highlights.cli match.dem --tick-rate 64
    python -m demo_highlights.cli match.dem --player HyRaX
    python -m demo_highlights.cli match.dem --category knife_kill
"""

import argparse
import json
import sys
from dataclasses import asdict

from demo_highlights.highlights import CATEGORY_PRIORITY, FOOTAGE_TOP_N_DEFAULT, find_highlights_from_demo


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Find highlight moments in a CS2 demo file.")
    ap.add_argument("demo", help="path to a .dem file already on disk")
    ap.add_argument("--top-n", type=int, default=FOOTAGE_TOP_N_DEFAULT,
                    help=f"max highlight events to report (default {FOOTAGE_TOP_N_DEFAULT})")
    ap.add_argument("--tick-rate", type=float,
                    help="override the demo's own tick rate (auto-detected via awpy otherwise)")
    ap.add_argument("--player", metavar="NAME",
                    help="only show highlight events involving this player (case-insensitive, exact name)")
    ap.add_argument("--category", choices=CATEGORY_PRIORITY,
                    help="only show highlight events of this category")
    ap.add_argument("--json", metavar="PATH", help="write raw JSON report")
    args = ap.parse_args()

    result = find_highlights_from_demo(args.demo, top_n=args.top_n, tick_rate_override=args.tick_rate,
                                        player=args.player, category=args.category)

    print(f"{result.demo_file} ({result.map_name}, {result.total_rounds} rounds) -- "
          f"{len(result.events)} highlight events\n")
    for e in result.events:
        m, s = divmod(e.time_s, 60)
        players = ", ".join(e.players)
        print(f"  round {e.round_num:3d}  {int(m)}:{s:04.1f}  [{e.category:14s}]  {players:16s}  {e.reason}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(asdict(result), f, indent=2)
        print(f"\nJSON report -> {args.json}")


if __name__ == "__main__":
    main()
