import random
from dataclasses import dataclass, field
from typing import Optional

from card import Card, CardType
from module import Module
from config import GameConfig


# ---------------------------------------------------------------------------
# Deck
# ---------------------------------------------------------------------------

class Deck:
    def __init__(self, config: GameConfig, rng: random.Random = None):
        self._rng = rng or random.Random()
        cards: list = []
        cards.extend([Card(CardType.SCIENTISTS)]   * config.scientists_count)
        cards.extend([Card(CardType.COLONISTS)]    * config.colonists_count)
        cards.extend([Card(CardType.MILITARY)]     * config.military_count)
        cards.extend([Card(CardType.GENIUS)]       * config.genius_count)
        cards.extend([Card(CardType.SABOTAGE)]     * config.sabotage_count)
        cards.extend([Card(CardType.LAUNCH_NOW)]   * config.launch_now_count)
        cards.extend([Card(CardType.DOUBLE_AGENT)] * config.double_agent_count)
        self._rng.shuffle(cards)
        self._draw: list = cards
        self._discard: list = []

    def draw(self) -> Card:
        if not self._draw:
            if not self._discard:
                raise RuntimeError(
                    "Both piles are empty — increase deck size or reduce hand_size."
                )
            self._draw = self._discard
            self._discard = []
            self._rng.shuffle(self._draw)
        return self._draw.pop()

    def discard(self, cards: list) -> None:
        self._discard.extend(cards)


# ---------------------------------------------------------------------------
# Resolution logic
# ---------------------------------------------------------------------------

def _apply_card_effect(module: Module, card: Card, player_idx: int) -> None:
    """Apply one card's effect for the given player. DA and Launch Now handled upstream."""
    ct = card.card_type
    if ct == CardType.SCIENTISTS:
        module.add_influence(player_idx, 1)
        module.adjust_dev(1)
    elif ct == CardType.COLONISTS:
        module.add_influence(player_idx, 2)
    elif ct == CardType.MILITARY:
        module.add_influence(player_idx, 3)
    elif ct == CardType.GENIUS:
        module.add_influence(player_idx, 2)
        module.adjust_dev(1)
    elif ct == CardType.SABOTAGE:
        module.adjust_dev(-1)


def _resolve_double_agent(
    c1: Optional[Card], c2: Optional[Card]
) -> tuple:
    """
    Returns (effective_c1, effective_c2) after Double Agent resolution.
    DA steals the rival's card: rival plays nothing, DA player plays the stolen card.
    DA vs DA: both cancel — both play nothing.
    """
    da1 = c1 is not None and c1.card_type == CardType.DOUBLE_AGENT
    da2 = c2 is not None and c2.card_type == CardType.DOUBLE_AGENT

    if da1 and da2:
        return None, None
    if da1:
        return c2, None   # P1 plays P2's card; P2 plays nothing
    if da2:
        return None, c1   # P2 plays P1's card; P1 plays nothing
    return c1, c2


def resolve_module(module: Module, card_p1: Card, card_p2: Card) -> bool:
    """
    Apply both deployed cards' effects to the module.
    Returns True if Launch Now was triggered.
    """
    launch_now = (
        card_p1.card_type == CardType.LAUNCH_NOW
        or card_p2.card_type == CardType.LAUNCH_NOW
    )

    # Strip out Launch Now cards; they have no module effect
    c1 = None if card_p1.card_type == CardType.LAUNCH_NOW else card_p1
    c2 = None if card_p2.card_type == CardType.LAUNCH_NOW else card_p2

    if c1 is None and c2 is None:
        return launch_now

    c1, c2 = _resolve_double_agent(c1, c2)

    # Military vs Military: both get influence but development drops
    if (c1 is not None and c1.card_type == CardType.MILITARY
            and c2 is not None and c2.card_type == CardType.MILITARY):
        module.add_influence(0, 3)
        module.add_influence(1, 3)
        module.adjust_dev(-2)
        return launch_now

    if c1 is not None:
        _apply_card_effect(module, c1, player_idx=0)
    if c2 is not None:
        _apply_card_effect(module, c2, player_idx=1)

    return launch_now


# ---------------------------------------------------------------------------
# Observable state passed to strategies
# ---------------------------------------------------------------------------

@dataclass
class RoundRecord:
    """What happened in one round, fully revealed after the Consequences phase."""
    round_num: int
    # module_idx -> (card_p1, card_p2) as actually deployed (before DA resolution)
    deployments: dict = field(default_factory=dict)
    launch_triggered: bool = False


@dataclass
class PlayerView:
    """Everything a player can legitimately see when choosing their deployment."""
    player_idx: int
    hand: list                # this player's current hand (do not mutate)
    modules: list             # current module states (do not mutate)
    round_num: int
    config: GameConfig
    history: list             # list of RoundRecord from previous rounds


# ---------------------------------------------------------------------------
# Game result
# ---------------------------------------------------------------------------

@dataclass
class GameResult:
    winner: Optional[int]     # 0 = P1, 1 = P2, None = draw or extinction
    extinction: bool          # True if fewer than modules_needed_to_launch were ready
    rounds_played: int
    early_launch: bool        # True if Launch Now ended the game before round 6
    ready_modules: int        # how many modules had dev >= ready_threshold at game end
    modules_won: list         # [p1_count, p2_count] of modules where they had more influence
    final_modules: list       # snapshot of module states at game end
    history: list             # all RoundRecords


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

class Game:
    def __init__(
        self,
        config: GameConfig,
        strategies: list,
        rng: random.Random = None,
    ):
        self.config = config
        self.strategies = strategies
        self._rng = rng or random.Random()

        self.deck = Deck(config, rng=self._rng)

        self.modules = [
            Module(index=i, dev_level=self._rng.randint(1, 6))
            for i in range(config.num_modules)
        ]

        self.hands = [
            [self.deck.draw() for _ in range(config.hand_size)]
            for _ in range(2)
        ]

        self.round_num = 0
        self.game_over = False
        self.early_launch = False
        self.history: list = []

    def play(self) -> GameResult:
        for round_num in range(1, self.config.num_rounds + 1):
            self.round_num = round_num
            self._play_round()
            if self.game_over:
                break
        return self._build_result()

    def _play_round(self) -> None:
        record = RoundRecord(round_num=self.round_num)

        # Deployment phase: each strategy picks one card per module
        deployments = []
        for player_idx, strategy in enumerate(self.strategies):
            view = PlayerView(
                player_idx=player_idx,
                hand=self.hands[player_idx],
                modules=self.modules,
                round_num=self.round_num,
                config=self.config,
                history=self.history,
            )
            deployment = strategy.choose_deployment(view)
            self._validate_deployment(player_idx, deployment)
            deployments.append(deployment)

        # Consequences phase: reveal and resolve
        launch_now = False
        for mod_idx, module in enumerate(self.modules):
            c1 = deployments[0][mod_idx]
            c2 = deployments[1][mod_idx]
            record.deployments[mod_idx] = (c1, c2)
            if resolve_module(module, c1, c2):
                launch_now = True

        record.launch_triggered = launch_now
        self.history.append(record)

        # Discard played cards, refill hands to hand_size
        for player_idx in range(2):
            played = list(deployments[player_idx].values())
            for card in played:
                self.hands[player_idx].remove(card)
            self.deck.discard(played)

        refill_order = [0, 1]
        self._rng.shuffle(refill_order)
        for player_idx in refill_order:
            while len(self.hands[player_idx]) < self.config.hand_size:
                self.hands[player_idx].append(self.deck.draw())

        if launch_now:
            self.game_over = True
            self.early_launch = True

    def _validate_deployment(self, player_idx: int, deployment: dict) -> None:
        n = self.config.num_modules
        if len(deployment) != n:
            raise ValueError(
                f"Strategy for player {player_idx} returned {len(deployment)} cards; "
                f"expected {n} (one per module)."
            )
        if set(deployment.keys()) != set(range(n)):
            raise ValueError(
                f"Strategy for player {player_idx} must deploy to modules 0..{n - 1}."
            )
        hand_copy = list(self.hands[player_idx])
        for card in deployment.values():
            if card not in hand_copy:
                raise ValueError(
                    f"Player {player_idx} attempted to deploy {card} which is not in hand."
                )
            hand_copy.remove(card)

    def _build_result(self) -> GameResult:
        ready = [m for m in self.modules if m.is_ready]
        launched = len(ready) >= self.config.modules_needed_to_launch

        if not launched:
            return GameResult(
                winner=None,
                extinction=True,
                rounds_played=self.round_num,
                early_launch=self.early_launch,
                ready_modules=len(ready),
                modules_won=[0, 0],
                final_modules=list(self.modules),
                history=list(self.history),
            )

        modules_won = [
            sum(1 for m in self.modules if m.winner() == i)
            for i in range(2)
        ]

        if modules_won[0] > modules_won[1]:
            winner = 0
        elif modules_won[1] > modules_won[0]:
            winner = 1
        else:
            winner = None  # draw

        return GameResult(
            winner=winner,
            extinction=False,
            rounds_played=self.round_num,
            early_launch=self.early_launch,
            ready_modules=len(ready),
            modules_won=modules_won,
            final_modules=list(self.modules),
            history=list(self.history),
        )
