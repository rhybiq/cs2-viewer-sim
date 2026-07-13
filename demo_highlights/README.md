# demo_highlights

Finds highlight moments (multi-kills, aces, clutches) in a CS2 demo file
(`.dem`) using the match's own recorded game-state data -- exact kill/round
events, not video/pixel guessing. A different, more reliable data source
than `viewer_sim.py`'s raw-footage scanning (`--scan-footage`): a demo
already contains perfect ground truth for exactly the things that pipeline
has to guess at with motion/OCR/color heuristics.

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
```

## How it works

Uses [`awpy`](https://awpycs.com) (which wraps `demoparser2`, the actual
CS2/Source-2 demo parser) to get clean `kills`/`rounds` dataframes, then:

- **Multi-kill/ace**: groups kills by (round, attacker), excluding
  team-kills and world/suicide deaths. 2/3/4 kills -> a multi-kill tag; 5
  (the whole enemy team) -> `ace`. Counted regardless of round outcome.
- **Clutch**: for each side in each round, finds the moment it was reduced
  to its last player and how many enemies were alive right then. If that
  survivor's side wins the round, it's a `clutch_1v{N}` (N = 1 through 5).
- A player who qualifies for more than one tag in the same round (e.g. a
  4-kill round that's also a won clutch) collapses to their single
  highest-priority tag -- see `CATEGORY_PRIORITY` in `highlights.py`.

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
