from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from module import Module
    from game import Game


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Card(ABC):
    def __str__(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        return self.__class__.__name__


@dataclass(frozen=True)
class StandardCard(Card):
    @abstractmethod
    def apply(self, module: 'Module', player_idx: int) -> None:
        """Apply this card's effect to the module for the given player."""
        pass


@dataclass(frozen=True)
class SpecialCard(Card):
    @abstractmethod
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        """Apply this card's effect to the game."""
        pass


# ---------------------------------------------------------------------------
# Standard cards
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Scientists(StandardCard):
    def apply(self, module: 'Module', player_idx: int) -> None:
        module.add_influence(player_idx, 1)
        module.adjust_dev(1)


@dataclass(frozen=True)
class Colonists(StandardCard):
    def apply(self, module: 'Module', player_idx: int) -> None:
        module.add_influence(player_idx, 2)


@dataclass(frozen=True)
class Military(StandardCard):
    def apply(self, module: 'Module', player_idx: int) -> None:
        module.add_influence(player_idx, 3)

    def apply_vs_military(self, module: 'Module', player_idx: int) -> None:
        """Special case when both players play Military."""
        module.add_influence(player_idx, 3)
        module.adjust_dev(-1)  # each Military contributes -1, total -2


# ---------------------------------------------------------------------------
# Special cards
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Genius(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        module.add_influence(player_idx, 1)
        module.adjust_dev(2)


@dataclass(frozen=True)
class Sabotage(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        module.adjust_dev(-1)


@dataclass(frozen=True)
class LaunchNow(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        game.trigger_launch(module)


@dataclass(frozen=True)
class DoubleAgent(SpecialCard):
    def resolve_pair(
        self,
        c1: Optional[Card],
        c2: Optional[Card],
    ) -> tuple[Optional[Card], Optional[Card]]:
        """
        Resolves a Double Agent play. Call on whichever card is a DoubleAgent.
        DA steals the rival's card: rival plays nothing, DA player plays stolen card.
        DA vs DA: both cancel.
        """
        da1 = isinstance(c1, DoubleAgent)
        da2 = isinstance(c2, DoubleAgent)

        if da1 and da2:
            return None, None
        if da1:
            return c2, None   # P1 plays P2's card; P2 plays nothing
        if da2:
            return None, c1   # P2 plays P1's card; P1 plays nothing
        return c1, c2
    
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        # DoubleAgent's effect is handled separately in replay.py, since it depends on the opponent's card
        pass

