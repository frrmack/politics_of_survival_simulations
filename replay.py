"""
Play-by-play trace of a single game.

Usage (CLI):
    python replay.py                     # CoopVsCoop, random seed
    python replay.py --seed 42           # reproducible run
    python replay.py --p1 aggr --p2 bal  # any strategy combination

Or import and call replay() from another script.
"""
import argparse
import random

from config import GameConfig
from game import Game, PlayerView, RoundRecord
from card import LaunchNow, DoubleAgent, Military
from strategy import (Strategy, CooperativeStrategy, AggressiveStrategy,
                      RandomStrategy, BalancedStrategy)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_ABBR = {
    'Scientists': 'Sci', 'Colonists': 'Col', 'Military': 'Mil',
    'Genius': 'Gen', 'Sabotage': 'Sab', 'LaunchNow': 'LNC', 'DoubleAgent': 'DA',
}

def _abbr(card) -> str:
    return _ABBR.get(type(card).__name__, type(card).__name__[:3])

def _hand_summary(hand) -> str:
    counts: dict = {}
    for c in hand:
        a = _abbr(c)
        counts[a] = counts.get(a, 0) + 1
    order = ['Sci', 'Col', 'Mil', 'Gen', 'Sab', 'DA', 'LNC']
    return '  '.join(f"{a}×{counts[a]}" for a in order if a in counts)


# ---------------------------------------------------------------------------
# Traced game subclass
# ---------------------------------------------------------------------------

class ReplayGame(Game):
    """Game subclass that prints a round-by-round play-by-play trace."""

    def _play_round(self) -> None:
        rn, total = self.round_num, self.config.num_rounds

        # Round header
        print(f"\n{'━'*64}")
        print(f"  ROUND {rn} of {total}")
        print(f"{'━'*64}")

        # Module states before
        print("\n  Modules (start of round):")
        for m in self.modules:
            status = "READY" if m.is_ready else f"need +{m.READY_THRESHOLD - m.dev_level}"
            d = m.influence[0] - m.influence[1]
            lead = f"  P1 +{d}" if d > 0 else (f"  P2 +{-d}" if d < 0 else "")
            print(f"    M{m.index+1}  dev= {m.dev_level}  [{status:>9}]"
                  f"  P1={m.influence[0]:>3}  P2={m.influence[1]:>3}{lead}")

        # Hands before deployment
        print("\n  Hands:")
        for pi in range(2):
            print(f"    P{pi+1}: {_hand_summary(self.hands[pi])}")

        # Deployment phase
        record = RoundRecord(round_num=rn)
        deployments = []
        for player_idx, strategy in enumerate(self.strategies):
            view = PlayerView(
                player_idx=player_idx,
                hand=self.hands[player_idx],
                modules=self.modules,
                round_num=rn,
                config=self.config,
                history=self.history,
            )
            dep = strategy.choose_deployment(view)
            self._validate_deployment(player_idx, dep)
            deployments.append(dep)

        # Resolution with per-module tracing
        print("\n  Resolution:")
        launch_now = False
        for mod_idx, module in enumerate(self.modules):
            c1_raw = deployments[0][mod_idx]
            c2_raw = deployments[1][mod_idx]
            record.deployments[mod_idx] = (c1_raw, c2_raw)

            dev_before = module.dev_level
            inf_before = list(module.influence)

            triggered = self.resolve_module(module, c1_raw, c2_raw)
            if triggered:
                launch_now = True

            d1 = module.influence[0] - inf_before[0]
            d2 = module.influence[1] - inf_before[1]
            dd = module.dev_level - dev_before

            effects = []
            if d1:  effects.append(f"P1: +{d1}")
            if d2:  effects.append(f"P2: +{d2}")
            if dd > 0: effects.append(f"dev +{dd}")
            if dd < 0: effects.append(f"dev {dd}")
            if not effects: effects.append("no effect")

            notes = []
            if isinstance(c1_raw, Military) and isinstance(c2_raw, Military):
                notes.append("MvM")
            elif isinstance(c1_raw, DoubleAgent) and isinstance(c2_raw, DoubleAgent):
                notes.append("DA×DA cancel")
            elif isinstance(c1_raw, DoubleAgent):
                notes.append(f"P1 DA steals {_abbr(c2_raw)}")
            elif isinstance(c2_raw, DoubleAgent):
                notes.append(f"P2 DA steals {_abbr(c1_raw)}")
            if triggered:
                notes.append("LAUNCH NOW!")
            note_str = f"  [{', '.join(notes)}]" if notes else ""

            status = "READY" if module.is_ready else f"need +{module.READY_THRESHOLD - module.dev_level}"
            print(f"    M{mod_idx+1}  P1: {_abbr(c1_raw):<3}  P2: {_abbr(c2_raw):<3}"
                  f"  →  {'  '.join(effects):<26}"
                  f"   [{status:>8}   P1= {module.influence[0]:>2}  P2= {module.influence[1]:>2}]   {note_str}")

        record.launch_triggered = launch_now
        self.history.append(record)

        # Discard played cards
        for player_idx in range(2):
            played = list(deployments[player_idx].values())
            for card in played:
                self.hands[player_idx].remove(card)
            self.deck.discard(played)

        # Refill hands (randomised order, same as Game._play_round)
        refill_order = [0, 1]
        self._rng.shuffle(refill_order)
        for player_idx in refill_order:
            while len(self.hands[player_idx]) < self.config.hand_size:
                self.hands[player_idx].append(self.deck.draw())

        if launch_now:
            self.game_over = True
            self.early_launch = True

        # Hands after redraw
        print("\n  Hands after redraw:")
        for pi in range(2):
            print(f"    P{pi+1}: {_hand_summary(self.hands[pi])}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def replay(
    strategy_p1: Strategy,
    strategy_p2: Strategy,
    config: GameConfig = None,
    seed: int = None,
) -> object:
    """
    Run and trace a single game between two strategies.
    Returns the GameResult.
    """
    if config is None:
        config = GameConfig()
    rng = random.Random(seed)

    s1 = type(strategy_p1).__name__
    s2 = type(strategy_p2).__name__
    seed_str = f"  (seed={seed})" if seed is not None else ""

    print(f"\n{'═'*64}")
    print(f"  {s1} (P1)  vs  {s2} (P2){seed_str}")
    print(f"  Modules: {config.num_modules}   Rounds: {config.num_rounds}"
          f"   Need {config.modules_needed_to_launch} ready to launch")
    print(f"{'═'*64}")

    game = ReplayGame(config, [strategy_p1, strategy_p2], rng=rng)

    print("\n  Initial module dev levels:")
    for m in game.modules:
        status = "READY" if m.is_ready else f"need +{m.READY_THRESHOLD - m.dev_level}"
        print(f"    M{m.index+1}  dev= {m.dev_level}  [{status}]")

    result = game.play()

    # Final summary
    print(f"\n{'━'*64}")
    print("  FINAL STATE:")
    for m in result.final_modules:
        status = "READY" if m.is_ready else "NOT READY"
        w = m.winner()
        win_str = f"P{w+1} wins" if w is not None else "tied"
        print(f"    M{m.index+1}  dev={m.dev_level}  [{status:<9}]"
              f"  P1={m.influence[0]:>3}  P2={m.influence[1]:>3}  → {win_str}")

    print()
    if result.extinction:
        print(f"  OUTCOME: EXTINCTION  "
              f"({result.ready_modules}/{config.modules_needed_to_launch} modules ready — not enough)")
    else:
        if result.winner is not None:
            print(f"  OUTCOME: P{result.winner+1} WINS"
                  f"  (modules: P1={result.modules_won[0]}  P2={result.modules_won[1]})")
        else:
            print(f"  OUTCOME: DRAW"
                  f"  (modules: P1={result.modules_won[0]}  P2={result.modules_won[1]})")
        if result.early_launch:
            print("  (game ended by Launch Now card)")

    print(f"{'═'*64}\n")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _STRATEGIES = {
        "coop": CooperativeStrategy,
        "aggr": AggressiveStrategy,
        "rand": RandomStrategy,
        "bal":  BalancedStrategy,
    }

    parser = argparse.ArgumentParser(description="Play-by-play game trace")
    parser.add_argument("--seed", type=int, default=None,
                        help="RNG seed for a reproducible game")
    parser.add_argument("--p1", default="coop", choices=_STRATEGIES,
                        help="Strategy for P1 (default: coop)")
    parser.add_argument("--p2", default="coop", choices=_STRATEGIES,
                        help="Strategy for P2 (default: coop)")
    args = parser.parse_args()

    replay(
        _STRATEGIES[args.p1](),
        _STRATEGIES[args.p2](),
        seed=args.seed,
    )
