import random
from dataclasses import dataclass, field
from typing import Optional

from card import (Card, StandardCard, SpecialCard,
                  Scientists, Colonists, Military,
                  Genius, Sabotage, LaunchNow, DoubleAgent)
from module import Module
from config import GameConfig


# ---------------------------------------------------------------------------
# Deck
# ---------------------------------------------------------------------------

class Deck:
    def __init__(self, config: GameConfig, rng: random.Random = None):
        self._rng = rng or random.Random()
        cards: list = []
        cards.extend([Scientists()]   * config.scientists_count)
        cards.extend([Colonists()]    * config.colonists_count)
        cards.extend([Military()]     * config.military_count)
        cards.extend([Genius()]       * config.genius_count)
        cards.extend([Sabotage()]     * config.sabotage_count)
        cards.extend([LaunchNow()]    * config.launch_now_count)
        cards.extend([DoubleAgent()]  * config.double_agent_count)
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
            Module(config=self.config,
                   index=i, 
                   dev_level=self.config.module_dev_level_init(self._rng))
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
            if self.resolve_module(module, c1, c2):
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
    
    def trigger_launch(self, module: Module) -> None:
        """Called by LaunchNow card during resolution."""
        self.game_over = True
        self.early_launch = True

    # resolution logic
    def resolve_module(self, module: Module, card_p1: Card, card_p2: Card) -> bool:
        launch_now = isinstance(card_p1, LaunchNow) or isinstance(card_p2, LaunchNow)

        c1 = None if isinstance(card_p1, LaunchNow) else card_p1
        c2 = None if isinstance(card_p2, LaunchNow) else card_p2

        if launch_now:
            if isinstance(card_p1, LaunchNow):
                card_p1.resolve(module, player_idx=0, game=self)
            if isinstance(card_p2, LaunchNow):
                card_p2.resolve(module, player_idx=1, game=self)

        if c1 is None and c2 is None:
            return launch_now

        # Double Agent resolution
        if isinstance(c1, DoubleAgent):
            c1, c2 = c1.resolve_pair(c1, c2)
        elif isinstance(c2, DoubleAgent):
            c1, c2 = c2.resolve_pair(c1, c2)

        # Military vs Military special case
        if isinstance(c1, Military) and isinstance(c2, Military):
            c1.apply_vs_military(module, player_idx=0)
            c2.apply_vs_military(module, player_idx=1)
            return launch_now

        # Apply effects
        for card, player_idx in [(c1, 0), (c2, 1)]:
            if card is None:
                continue
            if isinstance(card, StandardCard):
                card.apply(module, player_idx)
            elif isinstance(card, SpecialCard):
                card.resolve(module, player_idx, game=self)

        return launch_now


