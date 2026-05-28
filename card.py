from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
class Engineers(StandardCard):
    def apply(self, module: 'Module', player_idx: int) -> None:
        module.adjust_dev(1)


@dataclass(frozen=True)
class Colonists(StandardCard):
    def apply(self, module: 'Module', player_idx: int) -> None:
        module.add_influence(player_idx, 1)


@dataclass(frozen=True)
class Military(StandardCard):
    def apply(self, module: 'Module', player_idx: int) -> None:
        module.add_influence(player_idx, 2)

    def apply_vs_military(self, module: 'Module', player_idx: int) -> None:
        """Special case when both players play Military."""
        module.add_influence(player_idx, 2)
        module.adjust_dev(-1)  # each Military contributes -1, total -2


# ---------------------------------------------------------------------------
# Special cards
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Embargo(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        # Resolution is short-circuited in game.resolve_module before this is reached
        pass


@dataclass(frozen=True)
class Salvage(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        # _apply_effects substitutes the chosen card before calling resolve_module,
        # so this method is never reached in normal play.
        pass


@dataclass(frozen=True)
class Espionage(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        # _apply_effects substitutes the chosen card before calling resolve_module,
        # so this method is never reached in normal play.
        pass


@dataclass(frozen=True)
class Relocation(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        target_idx = game._relocation_targets.get((module.index, player_idx))
        if target_idx is not None:
            module.add_influence(player_idx, -1)
            game.modules[target_idx].add_influence(player_idx, 1)


@dataclass(frozen=True)
class Overtime(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        module.adjust_dev(2)


@dataclass(frozen=True)
class Genius(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        module.add_influence(player_idx, 1)
        module.adjust_dev(1)


@dataclass(frozen=True)
class Propaganda(SpecialCard):
    def resolve(self, module: 'Module', player_idx: int, game: 'Game') -> None:
        module.add_influence(player_idx, 2)

