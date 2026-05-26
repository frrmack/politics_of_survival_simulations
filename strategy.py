import random
from abc import ABC, abstractmethod

from card import (Card, Engineers, Colonists, Military,
                  Genius, Sabotage, LaunchNow, DoubleAgent)
from game import PlayerView


# Ordered from most cooperative to most competitive.
# Used to sort a hand when the strategy has a clear axis preference.
# Launch Now is last in both orderings — it is never deployed unless no other
# card is available (with hand_size=8 and num_modules=6 that never happens).
COOPERATION_ORDER = [
    Engineers, Genius, Colonists, DoubleAgent, Military, Sabotage, LaunchNow
]

AGGRESSION_ORDER = [
    Military, Colonists, Genius, DoubleAgent, Engineers, Sabotage, LaunchNow
]

class Strategy(ABC):
    """
    Interface for all player strategies.

    choose_deployment receives a PlayerView (observable game state) and must
    return a dict mapping every module index to one card from the player's hand.
    Exactly config.num_modules cards must be deployed; each card used at most once.
    The remaining hand cards are implicitly held over to the next round.
    """

    @abstractmethod
    def choose_deployment(self, view: PlayerView) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _greedy_assign(module_order: list, card_order: list) -> dict:
    """
    Pair highest-priority card to highest-priority module.
    module_order: module indices, most urgent first.
    card_order:   cards to consider, most preferred first (>= len(module_order)).
    """
    pool = list(card_order)
    return {mod_idx: pool[rank] for rank, mod_idx in enumerate(module_order)}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class RandomStrategy(Strategy):
    """
    Randomly selects 6 cards and assigns them to modules at random.
    Holds back Launch Now unless forced (i.e., not enough other cards).
    """

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()

    def choose_deployment(self, view: PlayerView) -> dict:
        n = view.config.num_modules
        regular = [c for c in view.hand if not isinstance(c, LaunchNow)]
        holdout  = [c for c in view.hand if isinstance(c, LaunchNow)]
        pool = regular if len(regular) >= n else regular + holdout
        self._rng.shuffle(pool)

        modules = list(range(n))
        self._rng.shuffle(modules)
        return dict(zip(modules, pool[:n]))


class CooperativeStrategy(Strategy):
    """
    Prefers Engineers and Genius; sends them to the least-developed modules.
    Prioritizes ship completion over personal influence gain.
    """

    def choose_deployment(self, view: PlayerView) -> dict:
        n = view.config.num_modules

        # Most urgent: lowest dev level (ties broken by module index)
        module_order = sorted(
            range(n),
            key=lambda i: (view.modules[i].dev_level, i),
        )

        type_rank = {cls: rank for rank, cls in enumerate(COOPERATION_ORDER)}
        hand_sorted = sorted(view.hand, key=lambda c: type_rank.get(type(c), 99))

        return _greedy_assign(module_order, hand_sorted)


class AggressiveStrategy(Strategy):
    """
    Prefers Military; sends it to the modules where we're furthest behind in influence.
    Prioritizes personal influence over ship development.
    """

    def choose_deployment(self, view: PlayerView) -> dict:
        n = view.config.num_modules
        p, opp = view.player_idx, 1 - view.player_idx

        # Most urgent: biggest influence deficit first
        module_order = sorted(
            range(n),
            key=lambda i: (
                view.modules[i].influence[p] - view.modules[i].influence[opp],
                view.modules[i].dev_level,
            ),
        )

        type_rank = {cls: rank for rank, cls in enumerate(AGGRESSION_ORDER)}
        hand_sorted = sorted(view.hand, key=lambda c: type_rank.get(type(c), 99))

        return _greedy_assign(module_order, hand_sorted)


class BalancedStrategy(Strategy):
    """
    Tries to match each card to the module where it does the most good:
    - Engineers/Genius to modules that urgently need development
    - Military/Colonists to modules where we're behind in influence
    Uses greedy (module, card) pair scoring so the 2 held-back cards
    are whichever pair produces the lowest marginal value.
    """

    def choose_deployment(self, view: PlayerView) -> dict:
        n = view.config.num_modules
        p, opp = view.player_idx, 1 - view.player_idx
        rounds_left = max(1, view.config.num_rounds - view.round_num)

        def pair_score(mod_idx: int, card: Card) -> float:
            if isinstance(card, LaunchNow):
                return -999.0

            m = view.modules[mod_idx]
            dev_gap = max(0, view.config.module_ready_threshold - m.dev_level)
            inf_gap = m.influence[opp] - m.influence[p]

            dev_value = {
                Engineers: 1.0,
                Genius:     1.0,
            }.get(type(card), 0.0)

            inf_value = {
                Military:     3.0,
                Colonists:    2.0,
                Genius:       2.0,
                Engineers:   1.0,
                DoubleAgent:  2.0,
            }.get(type(card), 0.0)

            dev_urgency = dev_gap / rounds_left
            return dev_urgency * dev_value + max(0.0, inf_gap) * 0.4 * inf_value
        # Greedy: repeatedly pick the (module, card) pair with the highest score
        hand = list(view.hand)
        remaining_mods = list(range(n))
        deployment = {}

        for _ in range(n):
            best_score = -1.0
            best_mod = 0
            best_card_idx = 0

            for mod_idx in remaining_mods:
                for ci, card in enumerate(hand):
                    s = pair_score(mod_idx, card)
                    if s > best_score:
                        best_score, best_mod, best_card_idx = s, mod_idx, ci

            deployment[best_mod] = hand[best_card_idx]
            remaining_mods.remove(best_mod)
            hand.pop(best_card_idx)

        return deployment
