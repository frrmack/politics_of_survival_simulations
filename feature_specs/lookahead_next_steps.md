# Lookahead Strategy — Next Steps

**Audience:** Claude Code, in the `politics_of_survival_simulations` repo. Follows
`lookahead_strategy_spec.md` (the original spec) and a code review of the pushed
`LookaheadStrategy`. The standing principle still holds: **the rulebook is the
source of truth**; where code contradicts it, fix the code.

**Process:** Do **Phase 1** first, then **STOP and report results** for review
before touching Phase 2. Keep all simulation batch sizes at **N = 3** during this
work — we are validating correctness, not measuring strength yet.

**Review status (what's already verified, don't redo):**
- `resolve_round_pure` matches the engine's `resolve_module` on 200,000 random
  per-module resolutions + a Relocation case — the per-module resolver math is sound.
- The player-index swap fix in `_ev_of_deployment` is correct and consistent through
  `_compute_subchoices` and `_score`.
- The §3 engine fixes (ResolutionView with `opponent_deployment`; PlayerView
  `discard`/`draw_pile_size`; Espionage-before-Salvage) are correctly wired.
- Baseline strategies (Random/Cooperative/Aggressive/Balanced) still hit their
  expected behavioral anchors after the §3 edits — no regression.

---

## PHASE 1 — Lock down correctness (do first, then STOP and report)

### 1.1 Tractability & process
- Default simulation batch size to **N = 3**. Make N a parameter (CLI flag or
  argument), don't hardcode large values.
- Do **not** auto-run the large multi-matchup matrix. For now, runs are small and
  targeted (e.g. just `Lookahead vs Balanced`).
- Print N alongside every result so any quoted number is interpretable.

### 1.2 Reproducibility (needed to debug any suspicious game)
- Ensure a single integer seed reproduces an entire game deterministically: the
  `Game` RNG, both strategy RNGs, and all hand draws/reshuffles must derive from it.
- Add a helper to replay a game from a seed (leverage `replay.py` if it fits).
- Verify: same seed → identical game transcript twice.

### 1.3 Resolver fidelity tests (THE gap) — add as permanent files under `tests/`
The per-module math is verified, but the **Salvage/Espionage substitution + chaining**
is reimplemented in `LookaheadStrategy._compute_subchoices` as a *separate* codepath
from the engine's `_collect_choices`, and it is **untested**. Close this.

**(a) Per-module resolver cross-check — already verified to pass; commit it as-is.**
```python
import random
from config import GameConfig
from module import Module
from game import Game, resolve_round_pure
from card import (Engineers, Colonists, Military, Embargo, Summit, Propaganda, Overtime)

config = GameConfig()
g = Game(config, [None, None])  # only g.resolve_module is used
NO_SUBCHOICE = [Engineers, Colonists, Military, Embargo, Summit, Propaganda, Overtime]

def engine_one(dev, i0, i1, A, B):
    m = Module(config=config, index=0, dev_level=dev); m.influence = [i0, i1]
    g.resolve_module(m, A(), B())
    return (m.dev_level, m.influence[0], m.influence[1])

def pure_one(dev, i0, i1, A, B):
    return resolve_round_pure([(dev, i0, i1)], {0: A}, {0: B}, {}, {}, config)[0]

rng = random.Random(0)
for _ in range(200_000):
    dev = rng.randint(1, 6); i0 = rng.randint(0, 8); i1 = rng.randint(0, 8)
    A = rng.choice(NO_SUBCHOICE); B = rng.choice(NO_SUBCHOICE)
    assert engine_one(dev, i0, i1, A, B) == pure_one(dev, i0, i1, A, B), (dev, i0, i1, A, B)
```
(Add a Relocation case too: 2 modules, P0 Relocation→target, set `g._relocation_targets`,
resolve in index order, compare to `resolve_round_pure(..., reloc0={mod: tgt}, ...)`.)

**(b) Engine special-card golden scenarios — encode the rulebook, assert the engine.**
Hand-compute the expected end state for each and assert the engine produces it:
- p.8 Round-3 Espionage example (Espionage replaced by Military vs a Summit).
- p.9 FAQ: Salvage (priority III) vs Espionage (priority II) on one module — Espionage
  resolves first, chains through a deployed card, *then* Salvage; verify the documented
  outcome (and that a swapped-in Embargo accomplishes nothing because the opponent's
  card already resolved).
- A Salvage→special chain (Salvage fetches a special from the discard, which resolves).
- Embargo edge: Embargo freezes the module's own cards but does **not** block influence
  relocated *into* it from a neighbor (confirm this matches current engine behavior; if
  the rulebook implies otherwise, flag it — designer decision).
These verify the engine's chaining matches the **rules**.

**(c) Resolver equivalence under identical choices — single-step substitutions.**
For random deployments where any special makes a *single-step* sub-choice (one
Espionage replacing a non-special, one Salvage fetching a non-special, one Relocation),
drive the engine with a scripted strategy that returns **fixed** deployments and
sub-choices, capture the end-of-round module states, and assert they equal
`resolve_round_pure` fed the **same** substituted deployments + reloc targets. This
proves the AI's resolver matches the engine *given identical choices* (the chooser
quality is a separate concern; chained substitutions are covered by (b)).

### 1.4 Behavioral sanity (constructed positions; fixed seed; force hands where possible)
Deterministic unit tests of "does it make the obviously-right move." Lean on **last-round**
positions (sharpest; and they become fully deterministic once Phase 2.1 lands). Use a
fixed seed and, for stability, a higher sample count in these tests than the runtime
default. Suggested assertions:
- Given two deployments on the last round, it picks the one that **clinches the module
  majority** over one that pads a lead on an already-won module.
- It defends a 1-point lead on a would-be-ready module rather than abandoning it.
- It does **not** put Engineers/Overtime on a max-development module the opponent firmly
  controls (developing a module you'll lose, for the opponent's benefit).
- It never deploys Salvage into an **empty discard** expecting an effect.
Also confirm at N = 3 (not statistics — just smoke): no crashes; ships launch against
cooperative-ish opponents; no gross seat asymmetry.

### >>> STOP after Phase 1. Report: the fidelity-test results (especially the p.9
### chaining case), any behavioral-sanity failures, and one N = 3 Lookahead-vs-Balanced
### smoke run (launch + outcome, with N stated). Wait for review before Phase 2.

---

## PHASE 2 — Spend the limited budget better (only after Phase 1 is confirmed)

Context: opponent samples / rollouts are scarce, so each must count. Two changes; keep
the existing uniform-model strategy as a **baseline control** that the new one must beat.

### 2.1 Round-5: enumerate opponent deployments (quick win)
At the **last round**, for each of our deployments, **enumerate all opponent legal
deployments** (within each sampled opponent hand), weight them by the choice model, and
score the resolved board with the exact terminal scorer. Rationale: the leaf is O(1) at
the last round, so the rollout cost that justified sampling does not exist there —
sampling is just free variance on the most decisive turn, and `argmax` over ~440 of our
deployments amplifies it. Keep **sampling the opponent's hidden hand** (many deployments
per sampled hand); raise the hand-sample count as compute allows. Bonus: with forced
hands, last-round decisions become deterministic, strengthening the 1.4 tests.

### 2.2 Informed opponent model — the next strategy (v2)
Goal: concentrate scarce opponent samples/rollouts on deployments a rational opponent
would actually consider, **without an exploitable bias**.

**Reweight, don't prune.** Model opponent play as a mixture:
`P(e) = ε · uniform(e) + (1 − ε) · softmax(u(e) / τ)`
- `u(e)` = a **cheap utility proxy for the opponent**: the resolved-board value from the
  *opponent's* seat using value-function-style features (readiness count, launched-majority
  indicator, **saturating** margin on contested would-be-ready modules), or a
  Balanced-style self-interest heuristic. Compute it **move-independently** — NOT
  conditioned on our specific deployment (the opponent can't see our move).
- `τ` = opponent rationality (low = sharper/stronger opponent). `ε` = uniform floor.
  Both are parameters.
- The floor `ε > 0` keeps **full support** — every legal opponent move retains nonzero
  probability, so the strategy is never blindsided by a "surprising" move. This is what
  makes reweighting safe where hard pruning is not.

**Why this objective (and not heuristic "sensible"-move pruning):** a utility-weighted
model is objective (the opponent's own rational self-interest) and is the *robust*
direction. Uniform is the **exploitable** model — it is exactly why the v1 strategy
over-takes Military gambles (a purposeful defender punishes them, which uniform never
anticipates). Hard-zeroing "non-sensible" moves *is* exploitable; the floor avoids that.

**Sampling:** draw the limited opponent deployments for the rollouts from this mixture.
Because the cheap proxy only steers *which* realistic moves get evaluated (the accurate
EV still comes from the rollout / terminal leaf) and the floor guarantees coverage, the
proxy's approximation cannot create a blind spot.

**(v3, later — not now):** replace the cheap proxy with the opponent's *true* recursive
EV (a fixed-point / iterated-best-response). This is the heaviest and most robust model;
defer it.

### 2.3 (Note for later) Fitted value function — the eventual rollout-killer
When rollout cost/noise dominates batch runs, replace the rollout leaf with an O(1)
fitted value function (original spec §5.7). It both makes large batches fast **and**
removes leaf sampling noise — which then lets you enumerate opponents (per 2.1) at
earlier rounds too. Build the 2.1/2.2 board-evaluation features reusably, since the fit
will use the same ones.
