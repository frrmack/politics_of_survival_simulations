import random
from dataclasses import dataclass, field
from typing import Optional

from card import (Card, StandardCard, SpecialCard,
                  Engineers, Colonists, Military,
                  Embargo, Relocation, Overtime, Genius, Propaganda)
from module import Module
from config import GameConfig


# ---------------------------------------------------------------------------
# Deck
# ---------------------------------------------------------------------------

class Deck:
    def __init__(self, config: GameConfig, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        cards: list = []
        cards.extend([Engineers()]   * config.engineers_count)
        cards.extend([Colonists()]   * config.colonists_count)
        cards.extend([Military()]    * config.military_count)
        cards.extend([Embargo()]     * config.embargo_count)
        cards.extend([Relocation()]  * config.relocation_count)
        cards.extend([Overtime()]    * config.overtime_count)
        cards.extend([Genius()]      * config.genius_count)
        cards.extend([Propaganda()]  * config.propaganda_count)
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
    deployments: dict = field(default_factory=dict)
    relocation_targets: dict = field(default_factory=dict)  # (mod_idx, player_idx) -> target_idx


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
        rng: random.Random | None = None,
    ):
        self.config = config
        self.strategies = strategies
        self._rng = rng or random.Random()

        self.deck = Deck(config, rng=self._rng)

        init = config.module_dev_level_init
        if isinstance(init, list):
            levels = list(init)
            dev_init = lambda _: levels.pop(0)
        else:
            dev_init = init

        self.modules = [
            Module(config=self.config, index=i, dev_level=dev_init(self._rng))
            for i in range(config.num_modules)
        ]

        self.hands = [
            [self.deck.draw() for _ in range(config.hand_size)]
            for _ in range(2)
        ]

        self.round_num = 0
        self.game_over = False
        self.history: list = []
        self._relocation_targets: dict = {}

    def play(self) -> GameResult:
        for round_num in range(1, self.config.num_rounds + 1):
            self.round_num = round_num
            self._play_round()
            if self.game_over:
                break
        return self._build_result()

    # ------------------------------------------------------------------
    # Round phases — can be called individually by the GUI
    # ------------------------------------------------------------------

    def _play_round(self) -> None:
        """Headless entry point: runs all phases in sequence."""
        deployments = self._collect_deployments()
        self._play_round_from_deployments(deployments)

    def _collect_deployments(self) -> list[dict]:
        """Ask each strategy for its deployment. Returns list of 2 deployment dicts."""
        deployments = []
        for player_idx, strategy in enumerate(self.strategies):
            view = self._make_view(player_idx)
            deployment = strategy.choose_deployment(view)
            self._validate_deployment(player_idx, deployment)
            deployments.append(deployment)
        return deployments

    def _play_round_from_deployments(self, deployments: list[dict]) -> None:
        """Run choices, effects, and refill given finalized deployments.
        Called by _play_round() and by the GUI after collecting human choices.
        """
        relocation_targets = self._collect_choices(deployments)
        self._apply_effects(deployments, relocation_targets)
        self._discard_and_refill(deployments)

    def _collect_choices(self, deployments: list[dict]) -> dict:
        """Collect player choices for special cards that need them.
        Returns relocation_targets: {(mod_idx, player_idx): target_idx}.
        Extended in future turns for Salvage and Espionage.
        """
        relocation_targets = {}
        for mod_idx in range(self.config.num_modules):
            for player_idx in range(2):
                card = deployments[player_idx][mod_idx]
                if isinstance(card, Relocation):
                    neighbors = self._get_neighbors(mod_idx)
                    if len(neighbors) == 1:
                        target = neighbors[0]
                    else:
                        view = self._make_view(player_idx)
                        target = self.strategies[player_idx].choose_relocation_target(
                            view, mod_idx, neighbors
                        )
                    relocation_targets[(mod_idx, player_idx)] = target
        return relocation_targets

    def _apply_effects(self, deployments: list[dict], relocation_targets: dict) -> None:
        """Resolve all modules and record the round."""
        self._relocation_targets = relocation_targets
        record = RoundRecord(
            round_num=self.round_num,
            relocation_targets=relocation_targets,
        )
        for mod_idx, module in enumerate(self.modules):
            c1 = deployments[0][mod_idx]
            c2 = deployments[1][mod_idx]
            record.deployments[mod_idx] = (c1, c2)
            self.resolve_module(module, c1, c2)
        self.history.append(record)

    def _discard_and_refill(self, deployments: list[dict]) -> None:
        """Discard played cards and refill hands to hand_size."""
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_view(self, player_idx: int) -> PlayerView:
        return PlayerView(
            player_idx=player_idx,
            hand=self.hands[player_idx],
            modules=self.modules,
            round_num=self.round_num,
            config=self.config,
            history=self.history,
        )

    def _get_neighbors(self, module_idx: int) -> list[int]:
        neighbors = []
        if module_idx > 0:
            neighbors.append(module_idx - 1)
        if module_idx < self.config.num_modules - 1:
            neighbors.append(module_idx + 1)
        return neighbors

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
            ready_modules=len(ready),
            modules_won=modules_won,
            final_modules=list(self.modules),
            history=list(self.history),
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_module(self, module: Module, card_p1: Card, card_p2: Card) -> None:
        # Embargo: either player playing it freezes the module for this round.
        # Checked on final cards (after any Espionage/Salvage substitution).
        if isinstance(card_p1, Embargo) or isinstance(card_p2, Embargo):
            return

        # Military vs Military special case
        if isinstance(card_p1, Military) and isinstance(card_p2, Military):
            card_p1.apply_vs_military(module, player_idx=0)
            card_p2.apply_vs_military(module, player_idx=1)
            return

        # Apply effects
        for card, player_idx in [(card_p1, 0), (card_p2, 1)]:
            if isinstance(card, StandardCard):
                card.apply(module, player_idx)
            elif isinstance(card, SpecialCard):
                card.resolve(module, player_idx, game=self)
