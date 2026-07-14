# demo_highlights

Finds highlight moments (multi-kills, aces, clutches, knife kills, dying
holding a grenade, blindside kills) in a CS2 demo file (`.dem`) using the
match's own recorded game-state data -- exact kill/round events, not
video/pixel guessing. A different, more reliable data source than
`viewer_sim.py`'s raw-footage scanning (`--scan-footage`): a demo already
contains perfect ground truth for exactly the things that pipeline has to
guess at with motion/OCR/color heuristics.

Deliberately a separate, independent module -- no imports either direction
with `viewer_sim.py`/`app/`. This is CS2-demo parsing, not video analysis.

## Scope: what this does and doesn't do

**Does:** given a `.dem` file already on disk, parses it and returns a
ranked list of highlight events (round number, in-demo timestamp, category,
players involved, a human-readable reason).

**Does NOT (yet):**
- **Fetch a demo for you.** Getting a demo in the first place (matchmaking
  sharecode -> Steam Game Coordinator -> download) needs an authenticated
  Steam session, which carries real account-risk tradeoffs (a dedicated bot
  account vs. your real one) worth deciding on deliberately, not bundling in
  silently. That's an explicit, separate follow-up -- not started.
- **Generate video.** This produces a list of moments and timestamps, not
  clips. There's no ffmpeg-cutting or replay-rendering capability here.

## Usage

```bash
pip install -r requirements-demo.txt

python -m demo_highlights.cli match.dem
python -m demo_highlights.cli match.dem --top-n 10
python -m demo_highlights.cli match.dem --json result.json
python -m demo_highlights.cli match.dem --tick-rate 64   # override auto-detected tick rate
python -m demo_highlights.cli match.dem --player HyRaX   # only this player's events
```

## How it works

Uses [`awpy`](https://awpycs.com) (which wraps `demoparser2`, the actual
CS2/Source-2 demo parser) to get clean `kills`/`rounds` dataframes, plus a
per-tick `yaw`/`active_weapon_name` query for the "funny moment" categories
below, then:

- **Multi-kill/ace**: groups kills by (round, attacker), excluding
  team-kills and world/suicide deaths. 2/3/4 kills -> a multi-kill tag; 5
  (the whole enemy team) -> `ace`. Counted regardless of round outcome.
- **Clutch**: for each side in each round, finds the moment it was reduced
  to its last player and how many enemies were alive right then. If that
  survivor's side wins the round, it's a `clutch_1v{N}` (N = 1 through 5).
- **Knife kill** (`knife_kill`): a kill made with a knife. Credited to the
  killer.
- **Caught with a nade** (`caught_with_nade`): the victim's own held weapon
  at the moment of death was a grenade -- they never got it thrown.
  Credited to the victim; it's their embarrassing moment, not the killer's.
- **Blindside kill** (`blindside_kill`): the victim's facing yaw was more
  than `BLINDSIDE_ANGLE_THRESHOLD_DEG` (100°) off the bearing to their
  killer at the moment of death -- a flank/backstab they never saw coming.
  Credited to the killer.
- A player who qualifies for more than one tag in the same round (e.g. a
  4-kill round that's also a won clutch) collapses to their single
  highest-priority tag -- see `CATEGORY_PRIORITY` in `highlights.py`. This
  applies across *all* categories, including the three above: e.g. a player
  who gets a 2-kill round and also dies holding a grenade later in the same
  round will only show the 2-kill tag, since `caught_with_nade` ranks
  lowest priority. A real, non-obvious way a "funny moment" can go
  unreported.
- **Player filter**: `find_highlights_from_demo(..., player="name")` (or
  `--player NAME` on the CLI) restricts results to one player,
  case-insensitive exact match. `filter_events_by_player()` is exposed
  separately so a UI can re-filter an already-scanned result locally instead
  of rescanning per keystroke/selection.

## Known limitations

- **Clutch alive-count tracking only accounts for deaths, not
  disconnects.** `awpy` doesn't expose a disconnect table, so a player who
  leaves mid-round without dying won't decrement their side's alive count.
  Rare in practice.
- **Tick rate**: `awpy` exposes the demo's own tick rate directly and this
  is used by default; `--tick-rate` is available as a manual override if a
  particular demo/awpy version doesn't report it correctly.
- The category-priority ranking (`CATEGORY_PRIORITY` in `highlights.py`) is
  a plain, tunable starting guess, not a rigorously derived "impressiveness"
  score.
- **`knife_kill` string match is unconfirmed against real data.** `.kills`'
  `weapon` column is checked for the exact value `"knife"`, following
  `demoparser2`'s internal script-name convention -- but the demo this
  module was built and tested against had zero knife kills, so this exact
  string has never actually been observed, only inferred by convention.
  Worth a spot-check against a demo with a real knife kill.
- **`victim_active_weapon`/`victim_view_diff_deg` needed a real empirical
  fix, not a guess.** An as-of join against the victim's most recent tick
  state landed on the exact death tick by default -- but at that exact tick,
  `active_weapon_name` already reads `null` (the game clears/drops the held
  weapon on death), silently losing every `caught_with_nade` case. Fixed
  with `allow_exact_matches=False` on the join so it lands on the tick
  strictly before death instead. Confirmed via a real match: before the fix,
  0 of 88 kills resolved a victim weapon; after, all 88 did, including one
  genuine "died holding an Incendiary Grenade" moment.
