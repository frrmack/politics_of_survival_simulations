import random
from abc import ABC, abstractmethod

from card import (Card, Engineers, Colonists, Military,
                  Embargo, Salvage, Espionage, Relocation, Overtime, Summit, Propaganda, Occupation)
from game import PlayerView


# Ordered from most cooperative to most competitive.
COOPERATION_ORDER = [Engineers, Overtime, Summit, Colonists, Relocation, Salvage, Espionage, Embargo, Propaganda, Military, Occupation]

AGGRESSION_ORDER = [Occupation, Military, Propaganda, Colonists, Relocation, Salvage, Espionage, Embargo, Summit, Engineers, Overtime]

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

    def choose_relocation_target(self, view: PlayerView, _module_idx: int, neighbors: list[int]) -> int:
        """Default: pick the neighbor where the opponent leads most (or we're closest to losing)."""
        p, opp = view.player_idx, 1 - view.player_idx
        return max(neighbors, key=lambda i: view.modules[i].influence[opp] - view.modules[i].influence[p])

    def choose_salvage_card(self, _view: PlayerView, _module_idx: int, available: list) -> object:
        """Default: pick the highest-priority card by cooperation order."""
        type_rank = {cls: rank for rank, cls in enumerate(COOPERATION_ORDER)}
        return min(available, key=lambda c: type_rank.get(type(c), 99))

    def choose_espionage_card(self, _view: PlayerView, _module_idx: int, available: list) -> object:
        """Default: pick the highest-priority card by cooperation order."""
        type_rank = {cls: rank for rank, cls in enumerate(COOPERATION_ORDER)}
        return min(available, key=lambda c: type_rank.get(type(c), 99))


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
    """Randomly selects cards and assigns them to modules at random."""

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()

    def choose_deployment(self, view: PlayerView) -> dict:
        n = view.config.num_modules
        pool = list(view.hand)
        self._rng.shuffle(pool)
        modules = list(range(n))
        self._rng.shuffle(modules)
        return dict(zip(modules, pool[:n]))

    def choose_relocation_target(self, view: PlayerView, _module_idx: int, neighbors: list[int]) -> int:
        return self._rng.choice(neighbors)

    def choose_salvage_card(self, _view: PlayerView, _module_idx: int, available: list) -> object:
        return self._rng.choice(available)

    def choose_espionage_card(self, _view: PlayerView, _module_idx: int, available: list) -> object:
        return self._rng.choice(available)


class CooperativeStrategy(Strategy):
    """
    Prefers Engineers and Summit; sends them to the least-developed modules.
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

    def choose_salvage_card(self, _view: PlayerView, _module_idx: int, available: list) -> object:
        type_rank = {cls: rank for rank, cls in enumerate(AGGRESSION_ORDER)}
        return min(available, key=lambda c: type_rank.get(type(c), 99))

    def choose_espionage_card(self, _view: PlayerView, _module_idx: int, available: list) -> object:
        type_rank = {cls: rank for rank, cls in enumerate(AGGRESSION_ORDER)}
        return min(available, key=lambda c: type_rank.get(type(c), 99))


class BalancedStrategy(Strategy):
    """
    Tries to match each card to the module where it does the most good:
    - Engineers/Summit to modules that urgently need development
    - Military/Colonists to modules where we're behind in influence
    Uses greedy (module, card) pair scoring so the 2 held-back cards
    are whichever pair produces the lowest marginal value.
    """

    def choose_deployment(self, view: PlayerView) -> dict:
        n = view.config.num_modules
        p, opp = view.player_idx, 1 - view.player_idx
        rounds_left = max(1, view.config.num_rounds - view.round_num)

        def pair_score(mod_idx: int, card: Card) -> float:
            m = view.modules[mod_idx]
            dev_gap = max(0, view.config.module_ready_threshold - m.dev_level)
            inf_gap = m.influence[opp] - m.influence[p]

            dev_value = {
                Engineers: 1.0,
                Overtime:  2.0,
                Summit:    1.0,
            }.get(type(card), 0.0)

            inf_value = {
                Occupation: 3.0,
                Military:   2.0,
                Propaganda: 2.0,
                Colonists:  1.0,
                Summit:     1.0,
                Engineers:  0.0,
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
