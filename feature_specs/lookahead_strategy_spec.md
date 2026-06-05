# Politics of Survival — Lookahead Strategy: Implementation Spec

**Audience:** Claude Code, working inside the `politics_of_survival_simulations`
repo. Written against the *actual* code (`card.py`, `config.py`, `module.py`,
`game.py`, `strategy.py`, `simulation.py`, `main.py`). Use the real
class/field/method names below; do not invent new representations where existing
ones exist.

**Goal:** Add a `LookaheadStrategy` that plays *mechanically* well (no social
negotiation/intent-reading) using 1-ply expected-value lookahead with a leaf
evaluator, handling the basic cards and all special cards deliberately. Build it in
the dependency order in §5. Ship it behind the existing `Strategy` interface so it
drops into `Simulation` and the pygame GUI unchanged.

---

## 0. Standing principle: the rulebook is the source of truth

The shipped rulebook (`rulebook/Politics of Survival - Official Rulebook.pdf` in the
repo) defines the game. The rules have iterated ahead of the implementation, so where
the current code contradicts the rulebook, **the code is wrong and must be fixed.**
This governs the specific fixes in §3 *and* any further discrepancy you discover
while implementing: the rulebook wins — fix the code, or flag it clearly if the fix
is non-trivial or genuinely ambiguous. Do not preserve a code behavior merely because
it is the current behavior.

---

## 1. Architecture in one paragraph

Every round, evaluate each of our legal deployments by its **expected outcome
utility**: sweep the opponent's plausible deployments, weight each by an opponent
model, resolve the round, and score the resulting board with a **leaf evaluator**.
Pick the argmax. The leaf evaluator is the *exact terminal scorer* on the last round
(round 5) and an *approximate value function* (Monte-Carlo rollout for v1, optionally
a fitted function later) on earlier rounds. The opponent model is staged across
strategy versions: v1 = uniform over the opponent's legal plays; v2 = same but with a
real opponent-hand distribution from deck accounting; v3 = a purposeful choice model
(tending toward mutual best response). Special-card *sub-choices* (Espionage
replacement, Salvage fetch, Relocation direction) are chosen optimally *inside* the
expectation, given the opponent deployment currently being considered.

Correctness facts that shape everything:
- The win condition is **win/draw/loss by module majority among launched modules** —
  not module count, not raw influence. Utility is `{0.0, 0.5, 1.0}`.
- A module's **influence lead** (signed difference) is the only influence quantity
  that matters; raw counts are irrelevant beyond their difference.
- **Catastrophe = flat 0.0** (a failed launch scores the same as a launched loss). The
  AI must never prefer crashing the ship; do not implement the rulebook's
  "fewer Military" extinction tiebreak.
- The game is **constant-sum only conditional on launch.** Catastrophe is mutual loss
  (both score 0), so a rational opponent is a *self-interested maximizer of their own
  utility*, NOT a pure minimizer of ours — they share our interest in launching. This
  matters only at v3 (mutual best response is a Nash computation, not minimax); it does
  not affect v1/v2, where the opponent model is explicit.
- **Monte-Carlo sampling appears at the first forward step** (any round earlier than
  the last), because the opponent's hand is hidden — so even the last round's value is
  an expectation over their possible hands — and the redraw in `_discard_and_refill`
  is random. This is by design, not a surprise.

---

## 2. How the existing code is structured (integration points)

- **`Strategy` (strategy.py)** — ABC. Implement these four methods:
  - `choose_deployment(view: PlayerView) -> dict[int, Card]` — one card per module,
    `set(keys) == set(range(num_modules))`, each card present in `view.hand`, each used
    at most once. Remaining hand cards are implicitly held.
  - `choose_relocation_target(view, module_idx, neighbors) -> int`
  - `choose_salvage_card(view, module_idx, available) -> Card`
  - `choose_espionage_card(view, module_idx, available) -> Card`
- **`PlayerView` (game.py)** — currently `player_idx`, `hand` (list of `Card`, *do not
  mutate*), `modules` (list of `Module`, *do not mutate*), `round_num` (1-indexed,
  1..num_rounds), `config` (`GameConfig`), `history` (list of `RoundRecord`, *previous*
  rounds only). §3B extends this.
- **`Module` (module.py)** — `index`, `dev_level` (int, clamped to
  `[module_min_development, module_max_development] = [1, 6]` by `adjust_dev`),
  `influence` (`list[int]` = `[p0_count, p1_count]`, monotonically increasing,
  unbounded), `is_ready` (`dev_level >= READY_THRESHOLD`), `winner()` (more influence,
  else `None`). **Our signed lead** from `view.player_idx` is
  `influence[player_idx] - influence[1 - player_idx]`.
- **`Card` (card.py)** — frozen dataclasses, *no fields*, so all instances of a type
  are `==` and hashable. Treat a hand as a **multiset of card types** (e.g.
  `collections.Counter` keyed by `type(card)`). Basic: `Engineers` (+1 dev),
  `Colonists` (+1 inf), `Military` (+2 inf; vs Military also −1 dev each → −2 total).
  Specials in the game: `Embargo`, `Salvage`, `Espionage`, `Relocation`,
  `Overtime` (+2 dev), `Summit` (+1 inf, +1 dev), `Propaganda` (+2 inf).
  **`Occupation` is cut from the game** (see §3 note and §9) — present in code but
  `occupation_count = 0`; the strategy must not use or reason about it.
- **`GameConfig` (config.py)** — `num_rounds=5`, `num_modules=5`,
  `modules_needed_to_launch=4`, `module_ready_threshold=5`, per-type counts (deck =
  10/10/10 basics + 1 each of 7 specials = 37). Read all thresholds from config;
  never hardcode 4/5/6.
- **Resolution (game.py)** — `_collect_choices` (sub-choices via callbacks, in a
  per-module priority queue), then `_apply_effects` → `resolve_module` per module in
  **index order 0→4**. Embargo (either player) freezes a module. Salvage/Espionage
  perform card *substitution* during `_collect_choices` (their `resolve()` is a
  no-op). `_discard_and_refill` discards played cards and **redraws to `hand_size`
  from a shuffled deck** (random — relevant to forward simulation).
- **`Simulation` (simulation.py)** reuses the *same* strategy instances across all
  `n_games`. Therefore **the strategy must be stateless across games.** Per-round
  scratch (e.g. a plan cached for the callbacks) must be recomputed each
  `choose_deployment` and never assumed to persist across games. A pure
  transposition/value cache keyed on board state may persist (it is just a cache).
- Accept an optional `rng: random.Random | None` in `__init__` (mirror
  `RandomStrategy`) for reproducible rollouts.

---

## 3. Required engine fixes (CONFIRMED — do these first)

All of A–C are confirmed by the designer and required before the special-card
strategy can function as designed. They are also instances of §0 (rulebook is truth).

### A. Reveal the opponent's current deployment to the conditional-special callbacks
**Problem:** `choose_espionage_card` / `choose_salvage_card` / `choose_relocation_target`
run during `_collect_choices`, but the `PlayerView` they receive exposes only
`history` (previous rounds) and *pre-resolution* module states — never the opponent's
cards *this* round. The rulebook (p.8 Round-3 example) has the Espionage player choose
their replacement *after seeing the opponent's flipped card*. As written, no strategy
can play Espionage correctly.

**Fix:** Per the rulebook, all cards are flipped simultaneously at the start of
Consequences, so by the time any module resolves, both full deployments are visible
(modules are then assessed in order). Give the three callbacks that information.
Recommended: a richer context (e.g. a `ResolutionView` dataclass, or extend
`PlayerView`) carrying, in addition to everything `PlayerView` has:
- `own_deployment` and `opponent_deployment` — the face-up cards per module, reflecting
  any substitutions already applied by earlier-assessed modules in this same
  Consequences phase (cards on not-yet-assessed modules appear in their original
  flipped form — e.g. a not-yet-resolved Espionage shows as Espionage),
- the live `modules` states as resolution proceeds in index order.

Update `RandomStrategy` and the heuristic strategies to accept the new signature (they
can ignore the extra fields). The base-class default callbacks must keep working.

### B. Expose the discard pile (contents) in `PlayerView`; keep the draw pile hidden
**Problem:** `choose_deployment` cannot see the discard pile, but (i) deciding
whether/where to play Salvage needs it, and (ii) the opponent-hand model (§5.4) is
built from "full deck − own hand − discard." `history` cannot reconstruct it across
reshuffles. The rulebook permits examining the discard pile at any time.

**Fix:** Add to `PlayerView`:
- `discard` — the cards currently in `deck._discard` (contents visible, per rules).
- `draw_pile_size` — `len(deck._draw)` as a **count only**. The draw pile's *contents*
  and order remain hidden (per the rulebook, players cannot see what is in the draw
  pile). Exposing the size leaks nothing: it is physically observable (stack height)
  and already derivable from public info (`deck_size − 2·hand_size − len(discard)`).
Populate in `Game._make_view`. Treat both as read-only.

### C. Espionage resolves before Salvage (priority fix)
**Problem:** `_collect_choices` builds the per-module queue as
`[(Salvage,…),(Espionage,…)]`, resolving **Salvage before Espionage.** The rulebook
ranks **Espionage II above Salvage III**, and the p.9 FAQ depends on Espionage
resolving first.

**Fix:** Swap to `[(Espionage,…),(Salvage,…)]` and adjust the chaining-insert logic so
a follow-up resolves immediately after the current item in the corrected order. Add a
test for the p.9 edge case (Salvage(III) deployed vs Espionage(II): Espionage resolves
first; the player discards Espionage, deploys another card, that card resolves as part
of Espionage; only then does Salvage resolve — so a swapped-in Embargo would
accomplish nothing because the opponent's card has already resolved).

### D. (Low-priority discrepancy) Module assessment order
The rulebook (setup step 4) lets players pick which module is assessed first, fixed for
the whole game; the engine hardcodes index order 0→4. This barely affects outcomes
(modules resolve independently except for Relocation's cross-module ±1 and rare
Embargo/cross-module timing; influence addition is commutative). For full fidelity,
make the first-assessed module (or the full order) configurable in `GameConfig`. **The
lookahead must use whatever order the engine uses** — read it from config if made
configurable, else index order. Low priority; flag for the designer.

### E. Recommended refactor — a single pure resolver shared by engine and AI
**Why:** The lookahead must predict the engine's outcomes *exactly*; the whole strategy
is "predict the resolved board and score it." If the AI reimplements resolution
independently, the two can silently diverge (dev-clamp ordering, the both-Military
special case, Embargo short-circuit, substitution effects) — a subtle correctness bug,
not a crash.

**Refactor:** Extract a pure function

```
resolve_round(module_states, dep0, dep1, subchoices0, subchoices1, config)
    -> new_module_states
```

`module_states`: a lightweight immutable representation (e.g. tuple of
`(dev, infl0, infl1)` per module — fast to copy, hashable for caching). `dep0/dep1`:
module→card-type. `subchoicesN`: resolved sub-choices (Espionage replacement type,
Salvage fetched type, Relocation target index, per module). Must reproduce
`resolve_module` semantics exactly: Embargo freeze; both-Military special case
(+2/+2 inf, −2 dev total, per-step clamping); `StandardCard.apply`;
`SpecialCard.resolve`; Relocation's cross-module −1/+1; and the engine's ordering.
Then:
- Refactor `Game._apply_effects` to collect sub-choices via callbacks (as now) and then
  call `resolve_round`. Engine behavior must be unchanged — lock with the existing
  `main.py` matchups under a fixed seed (golden test).
- The lookahead calls `resolve_round` directly, passing sub-choices it computes by
  optimization rather than via callbacks.

**Fallback if not refactoring now:** implement the lookahead's resolver separately and
add the cross-check test in §7.1 (assert it matches the engine on a large random
sample). The refactor is preferred; the cross-check is the minimum.

---

## 4. The board state the AI reasons over

Define a canonical, immutable state extracted from `view` (never mutate `view`):
- `dev`: tuple of 5 ints (1..6) from `module.dev_level`.
- `lead`: tuple of 5 signed ints, `influence[me] - influence[opp]`, from our seat.
- For resolution you also need raw `infl0/infl1`; keep them in the lightweight
  `module_states` used by `resolve_round`. `lead` is the derived quantity the
  *evaluator* consumes.

`rounds_remaining` (INCLUDING the current round) = `config.num_rounds - view.round_num
+ 1`. At round 5 this is 1 (the last round). NB: `BalancedStrategy` uses
`num_rounds - round_num` (off by one) — do **not** copy that; use the inclusive count
and be consistent everywhere.

---

## 5. Build plan, in dependency order

### 5.1 Terminal scorer (pure, validated)
Deterministic; returns `{0.0, 0.5, 1.0}` from our seat. Reference (already unit-tested;
adapt input types):

```python
LOSS, DRAW, WIN = 0.0, 0.5, 1.0

def score_terminal(dev, lead, *, ready_dev, n_to_launch):
    ready = ours = theirs = 0
    for d, l in zip(dev, lead):
        if d >= ready_dev:
            ready += 1
            if l > 0:   ours += 1
            elif l < 0: theirs += 1
    if ready < n_to_launch:          # launch gate: catastrophe == loss (flat 0.0)
        return LOSS
    if ours > theirs: return WIN     # majority among launched modules only
    if ours < theirs: return LOSS
    return DRAW                      # equal control (incl. all-neutral) -> draw
```

`ready_dev = config.module_ready_threshold`, `n_to_launch =
config.modules_needed_to_launch`. Provide `board_from_view(view) -> (dev, lead)`.
**Deterministic: no averaging inside.**

### 5.2 Pure resolver (§3E) + cross-check
Implement `resolve_round(...)` (or reuse the refactored engine one). Single source of
truth for "what a round does to the board."

### 5.3 Legal-deployment enumeration
From a hand-as-multiset, enumerate all distinct assignments of one card type per
module, each type used at most its available count. Enumerate over *type multisets*,
not permutations (identical cards are indistinguishable). Small for real 8-card hands;
at most a few hundred for the generous "5 of each." Provide
`legal_deployments(hand_multiset, num_modules) -> iterator[dict]`.

### 5.4 Opponent hand model
- The opponent holds `hand_size` cards from the **unseen pool** = full deck (config) −
  our hand − `view.discard`. Under max-entropy, the opponent's hand is a uniform random
  `hand_size`-subset of that pool. This already encodes single-copy specials: if
  Propaganda is in our hand or the discard, the opponent cannot hold it.
- Provide `unseen_pool(view) -> Counter` and `sample_opponent_hand(view, rng) ->
  Counter`. (Later: condition on `history` for tells.)

### 5.5 Opponent choice model (staged — the version axis)
Given a (sampled or marginal) opponent hand, produce a distribution over their
deployments:
- **v1 — uniform over legal plays.** Name it honestly: *best response to a
  uniform-random opponent*, not "EV vs an uncertain opponent." Expect a known artifact:
  systematic over-aggression on high-variance plays (e.g. taking the round-4/5 Military
  gamble on a contested ready module, because the clash disaster is under-weighted at
  uniform odds). v2/v3 fix this; it is the expected progression, not a bug.
- **v2 — same, but opponent hand distribution from §5.4** (choice still
  uniform-over-legal). Sharpens *which cards they can even play*.
- **v3 — purposeful choice model:** weight the opponent's deployments by their own
  expected utility (same machinery, their seat), tending toward mutual best response.
  **Not minimax** (constant-sum only conditional on launch) — model them as maximizing
  *their* utility, which includes wanting to launch.
Interface: `opponent_deployment_distribution(view, opp_hand) -> list[(deployment,
prob)]`. Swappable so the three versions are separate, comparable objects.

### 5.6 The 1-ply expected-value core
For each of our legal deployments `d`:
```
EV(d) = sum over sampled/enumerated opponent hands H (weighted),
          sum over opponent deployments e ~ choice_model(H) (weighted by prob),
            leaf_value( resolve_round(state, d, e, subchoices(d,e), subchoices(e,d)) )
```
Return `argmax_d EV(d)`. Notes:
- **Sub-choices live inside the expectation.** For fixed `(d, e)`, choose our Espionage
  replacement / Salvage fetch / Relocation target to **maximize** the resulting leaf
  value (a nested argmax over our legal sub-options). Model the opponent's sub-choices
  as maximizing *their* leaf value (v1/v2 may use a simple default; the nested argmax is
  preferred for our own cards). Never treat a special's sub-choice as fixed — that is
  what made the old code play Salvage into a basic card.
- Cache `leaf_value` on the resulting board state (transposition table); many `(d,e)`
  pairs converge to the same board.

### 5.7 Leaf evaluator
- **Round 5 (rounds_remaining == 1):** `leaf_value = score_terminal(...)`. Exact for a
  given resolved board; the averaging over opponent plays already happens in §5.6.
- **Rounds < 5:** the resolved board is the *start* of the next round; value it by the
  game played from it. For v1 use a **Monte-Carlo rollout**:
  1. Sample the redraw for both players to refill to `hand_size` from the modeled deck
     (redraw is random in `_discard_and_refill`), and sample the opponent's hand (§5.4).
  2. Play out the remaining rounds. The *final* round uses the exact §5.6 core;
     intermediate rounds may use a cheap fixed policy (the eventual v1 policy or a fast
     heuristic) to bound cost/variance — bias is confined to those rounds since the last
     round is solved properly.
  3. Average `score_terminal` over `N` rollouts.
  Expose `n_rollouts`. **This is where Monte-Carlo sampling first appears** — earlier
  than round 3 — because the opponent hand is hidden and redraws are random. Expected.
- **Upgrade path (later):** replace rollouts with a **fitted value function.** Generate
  `(board, rounds_remaining) -> value` samples via rollout/recursion; fit `value =
  f(features; θ)`. Features ARE the strategic principles: count of modules at `dev >=
  ready_dev`; the launched-majority indicator; a **saturating** function of `lead` on
  each contested would-be-ready module (margin matters to ~1–2, then flattens); all
  conditioned on `rounds_remaining`. The launch gate is a sharp cliff (4-of-5 is a
  discontinuity) — encode threshold features explicitly or use a small MLP; linear on
  raw features will smear it. Fitting calibrates the weights on these principles.

### 5.8 The `LookaheadStrategy` class
Implement `choose_deployment` via §5.6, plus the three callbacks consistently. After
the §3A fix, each callback knows the opponent's revealed deployment, so it can recompute
the same optimal sub-choice the lookahead assumed for the realized `(d, e)`. Keep the
callback logic and the in-search sub-choice logic in a **single shared helper** so they
cannot drift. Statelessness: do not let per-round caches leak across games (§2).

### 5.9 Wire-up
Add `LookaheadStrategy` to `strategy.py`, import in `main.py`, add matchups
(`Lookahead vs Balanced`, `vs Cooperative`, `vs Aggressive`, `vs Lookahead`). Keep `n`
modest at first (rollouts are slower than the heuristics).

---

## 6. Per-special-card strategic logic (priors / tie-breakers + sub-choice objectives)

The EV core will *discover* good play if the leaf is good; encode these as priors and
as the sub-choice objectives. Reason "ideal use, else hold."

- **Easy specials (treat as premium basics; the search handles placement):**
  - **Overtime** = double Engineers (+2 dev). Development is *sticky* (only a mutual
    Military clash reduces it, which needs our own Military), so banking Overtime
    **early on a launch-critical lagging module** is strong launch insurance — do not
    reflexively hold it for round 5.
  - **Propaganda** = safe Military (+2 inf, no clash risk). Influence is *erodable*, so
    holding Propaganda for **round 5's no-counter window** is a strong default.
  - **Summit** = Colonists + Engineers in one (+1 inf, +1 dev).
  - All three: never waste the effect against the dev cap (6) or gift development to a
    module we will not control.
- **Embargo (denial):** play only to deny the opponent's single highest-value influence
  play on a module we would otherwise lose (defend a 1-point lead vs their Military;
  kill a Propaganda/Summit on a deciding module late). Never Embargo a cooperative
  (development) play we both need. Default: hold for a pivotal moment; target by
  opponent incentive (contested, would-be-ready, late-game modules).
- **Espionage (informed best-response):** value is choosing the replacement *after*
  seeing the opponent's card (requires §3A). Best on the highest-variance contested
  module — where seeing their actual card most changes our right answer. Cost = the card
  + one extra draw; don't spend it where we'd play the same thing regardless. In the
  search: for each opponent deployment, Espionage picks our best legal replacement
  (nested argmax).
- **Salvage (delayed power):** value rises as the discard fills with specials. Fetch the
  best **special**, not a basic, and only when the discard holds something worth more
  than our alternative on that module. Strong combo to encode: play a strong special
  this round (Propaganda/Overtime) and Salvage it back next round (a second copy). Hold
  early when the discard is thin. Handle empty discard: Salvage then has no effect —
  never deploy it expecting one.
- **Relocation (efficiency/denial):** moves one point of lead to an adjacent module.
  Worth it only when that adjacency flips an adjacent module from tied/behind to
  controlled, ideally pulling the point from a module with spare lead or a doomed module
  where the lead is wasted. Otherwise weak — hold.
- **Occupation:** cut from the game (§9). Not in the deck; the strategy does not handle
  it.

Cross-cutting priors the leaf should already imply (verify they emerge; add as
tie-breakers if not):
- Influence past a safe margin on a contested would-be-ready module is near-worthless —
  redirect to swing modules.
- Don't develop a module the opponent firmly controls and will leave behind; nominate a
  **sacrificial module** (only 4 of 5 must launch), ideally opponent-held or already
  doomed, to deny them a module at no cost. Creates the chicken dynamic on a contested
  underdeveloped module.
- Military is a gamble hedged by development buffer: prefer Military on *high*-dev
  contested modules (a 6 absorbs a clash to 4; a 3 cannot). If you only want the +2
  without clash risk and hold it, Propaganda is the safer tool.
- Time modulation: early rounds favor development/position (leads still reversible; hold
  reactive specials); round 5 is the cash-in (influence plays final, overkill pure waste,
  anticipate the opponent's simultaneous last swing — a "safe" R5 lead is ~3 or a
  defended lead).

---

## 7. Testing & validation

### 7.1 Resolver fidelity (mandatory)
Cross-check `resolve_round` against the engine's `resolve_module`/`_apply_effects` on a
large random sample (random module states; random deployments incl. specials, the
both-Military case, and Embargo; random sub-choices). Assert identical resulting module
states. If §3E refactor is done, instead add a golden test that engine behavior is
unchanged (run `main.py` matchups before/after with a fixed seed and diff summary
stats).

### 7.2 Rulebook-fix tests
- **§3A:** the conditional-special callbacks receive the opponent's revealed deployment
  and the running module states.
- **§3B:** `view.discard` shows discarded cards; the draw pile's contents are not
  exposed (only `draw_pile_size`).
- **§3C:** the p.9 FAQ edge case resolves Espionage(II) before Salvage(III) with the
  documented outcome.

### 7.3 Terminal scorer (already covered)
Reuse existing unit tests (win/draw/loss; launch gate; neutral handling;
unready-lead-ignored; all-neutral draw; constant-sum-conditional-on-launch: launched
outcomes sum to 1.0, catastrophe sums to 0.0).

### 7.4 Behavioral sanity (simulation)
- `Lookahead` should beat `Balanced`, `Cooperative`, `Aggressive` head-to-head
  (win + ½·draw share well above 50%) and not crater launch rate against cooperative-ish
  opponents.
- `Lookahead vs Lookahead` should launch reliably and split roughly evenly (mirror
  match), absent a structural first/second-player asymmetry.
- v1's expected artifact: more aggression/variance on contested ready modules than
  v2/v3. Confirm v2 (real hand model) and v3 (purposeful choice model) reduce
  self-inflicted Military-clash losses.
- Fixed seed, enough games for tight intervals; reuse `SimulationResults.print_summary`.

### 7.5 Performance
Confirm a single `choose_deployment` is well under a human's decision time with real
8-card hands (enumeration shrinks fast vs the generous upper bound). If rollouts are
slow: tune `n_rollouts`, add the §5.6 transposition cache, consider vectorized batch
board scoring before reaching for the fitted value function.

---

## 8. Settled design decisions (for the record)
1. **Rulebook is the source of truth** over the code, always (§0).
2. **Catastrophe = flat 0.0**; no extinction tiebreak. Utility is win/draw/loss
   `{1.0, 0.5, 0.0}`, not module count.
3. **Espionage resolves before Salvage** (§3C).
4. **Discard pile contents are visible; draw pile contents are hidden** (size only)
   (§3B).
5. **Conditional-special callbacks see the opponent's revealed deployment** (§3A).
6. **Module assessment order:** low-priority discrepancy; engine index order for now,
   make configurable for fidelity (§3D). Lookahead uses whatever the engine uses.

## 9. Occupation (cut)
`Occupation` (+3 inf / −3 dev) was removed from the game after playtesting. The
implementation remains in `card.py` but `config.occupation_count = 0`, so it is not in
the deck. The strategy must not use, weight, or reason about it. (It need not be deleted
from the code — leaving it disabled is fine — but it is not part of the game.)
