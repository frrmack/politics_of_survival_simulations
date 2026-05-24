from enum import Enum
from dataclasses import dataclass


class CardType(Enum):
    SCIENTISTS   = "Scientists"
    COLONISTS    = "Colonists"
    MILITARY     = "Military"
    GENIUS       = "Genius"
    SABOTAGE     = "Sabotage"
    LAUNCH_NOW   = "Launch Now"
    DOUBLE_AGENT = "Double Agent"


@dataclass(frozen=True)
class Card:
    card_type: CardType

    def __str__(self) -> str:
        return self.card_type.value

    def __repr__(self) -> str:
        return self.card_type.value
