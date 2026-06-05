import random
from dataclasses import dataclass, field
from typing import Optional

from card import (Card, StandardCard, SpecialCard,
                  Engineers, Colonists, Military,
                  Embargo, Salvage, Espionage, Relocation, Overtime, Summit, Propaganda, Occupation)
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
        cards.extend([Salvage()]     * config.salvage_count)
        cards.extend([Espionage()]   * config.espionage_count)
        cards.extend([Relocation()]  * config.relocation_count)
        cards.extend([Overtime()]    * config.overtime_count)
        cards.extend([Summit()]        * config.summit_count)
        cards.extend([Propaganda()]  * config.propaganda_count)
        cards.extend([Occupation()]  * config.occupation_count)
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
    deployments: dict = field(default_factory=dict)         # original hand cards
    relocation_targets: dict = field(default_factory=dict)  # (mod_idx, player_idx) -> target_idx
    salvage_choices: dict = field(default_factory=dict)     # (mod_idx, player_idx) -> chosen card
    espionage_choices: dict = field(default_factory=dict)   # (mod_idx, player_idx) -> chosen card


@dataclass
class PlayerView:
    """Everything a player can legitimately see when choosing their deployment."""
    player_idx: int
    hand: list                # this player's current hand (do not mutate)
    modules: list             # current module states (do not mutate)
    round_num: int
    config: GameConfig
    history: list             # list of RoundRecord from previous rounds
    discard: list             # visible discard pile contents (do not mutate)
    draw_pile_size: int       # number of cards remaining in the draw pile (contents hidden)


@dataclass
class ResolutionView:
    """Richer context passed to conditional-special callbacks (§3A).

    Carries everything PlayerView has plus the face-up deployments for the
    current round (reflecting any substitutions already applied by
    earlier-resolved modules) and the live module states.
    """
    player_idx: int
    hand: list
    modules: list             # live module states as resolution proceeds (do not mutate)
    round_num: int
    config: GameConfig
    history: list
    discard: list
    draw_pile_size: int
    own_deployment: dict      # this player's face-up cards per module (post-substitution so far)
    opponent_deployment: dict # opponent's face-up cards per module (post-substitution so far)


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
        rel_tgt, sal_ch, esp_ch, esp_used, resolved = self._collect_choices(deployments)
        self._apply_effects(deployments, rel_tgt, sal_ch, resolved, esp_ch)
        self._discard_and_refill(deployments,
                                 salvage_used=list(sal_ch.values()),
                                 espionage_used=esp_used)

    def _collect_choices(self, deployments: list[dict]) -> tuple:
        """Module-by-module choice collection with full Salvage/Espionage chaining.

        Priority within a module: Embargo (skip) > Salvage > Espionage > Relocation.
        P1 before P2 within each type.  Chaining: when a Salvage or Espionage choice
        resolves to another Salvage/Espionage, that follow-up is inserted immediately
        after the current item so the entire chain completes before the next special card.

        Returns (relocation_targets, salvage_choices, espionage_choices, espionage_used, resolved).
        espionage_used contains hand-cards removed by Espionage that need to be discarded.
        """
        resolved = [{**dep} for dep in deployments]
        salvage_choices: dict = {}
        espionage_choices: dict = {}
        espionage_used: list = []
        relocation_targets: dict = {}

        for mod_idx in range(self.config.num_modules):
            if isinstance(deployments[0][mod_idx], Embargo) or \
               isinstance(deployments[1][mod_idx], Embargo):
                continue

            # Per-module choice queue: (player_idx, 'espionage'|'salvage')
            # Priority order: Espionage before Salvage (§3C), P1 before P2 each.
            mod_queue: list = []
            for cls, tag in [(Espionage, 'espionage'), (Salvage, 'salvage')]:
                for pi in range(2):
                    if isinstance(deployments[pi][mod_idx], cls):
                        mod_queue.append((pi, tag))

            qi = 0
            while qi < len(mod_queue):
                pi, tag = mod_queue[qi]
                if tag == 'espionage':
                    dep_set = list(deployments[pi].values())
                    hand_copy = list(self.hands[pi])
                    for dep in dep_set:
                        if dep in hand_copy:
                            hand_copy.remove(dep)
                    available = hand_copy  # non-deployed hand cards
                    if available:
                        rview = self._make_resolution_view(pi, resolved)
                        chosen = self.strategies[pi].choose_espionage_card(
                            rview, mod_idx, available)
                        espionage_choices[(mod_idx, pi)] = chosen
                        resolved[pi][mod_idx] = chosen
                        self.hands[pi].remove(chosen)
                        espionage_used.append(chosen)
                        if isinstance(chosen, Espionage):
                            mod_queue.insert(qi + 1, (pi, 'espionage'))
                        elif isinstance(chosen, Salvage):
                            mod_queue.insert(qi + 1, (pi, 'salvage'))
                elif tag == 'salvage':
                    available = list(self.deck._discard)
                    if available:
                        rview = self._make_resolution_view(pi, resolved)
                        chosen = self.strategies[pi].choose_salvage_card(
                            rview, mod_idx, available)
                        salvage_choices[(mod_idx, pi)] = chosen
                        resolved[pi][mod_idx] = chosen
                        self.deck._discard.remove(chosen)
                        if isinstance(chosen, Espionage):
                            mod_queue.insert(qi + 1, (pi, 'espionage'))
                        elif isinstance(chosen, Salvage):
                            mod_queue.insert(qi + 1, (pi, 'salvage'))
                qi += 1

            # Relocation — on resolved cards after all chains; re-check for Embargo
            if isinstance(resolved[0][mod_idx], Embargo) or \
               isinstance(resolved[1][mod_idx], Embargo):
                continue
            for pi in range(2):
                if isinstance(resolved[pi][mod_idx], Relocation):
                    neighbors = self._get_neighbors(mod_idx)
                    if len(neighbors) == 1:
                        target = neighbors[0]
                    else:
                        rview = self._make_resolution_view(pi, resolved)
                        target = self.strategies[pi].choose_relocation_target(
                            rview, mod_idx, neighbors)
                    relocation_targets[(mod_idx, pi)] = target

        return relocation_targets, salvage_choices, espionage_choices, espionage_used, resolved

    def _apply_effects(self, deployments: list[dict], relocation_targets: dict,
                       salvage_choices: dict | None = None,
                       resolved_deployments: list[dict] | None = None,
                       espionage_choices: dict | None = None) -> None:
        """Resolve all modules and record the round.

        deployments          — original hand cards (stored in the record for display)
        resolved_deployments — after Salvage/Espionage substitution (used for resolve_module)
        """
        self._relocation_targets = relocation_targets
        if resolved_deployments is None:
            resolved_deployments = deployments
        record = RoundRecord(
            round_num=self.round_num,
            relocation_targets=relocation_targets,
            salvage_choices=salvage_choices or {},
            espionage_choices=espionage_choices or {},
        )
        for mod_idx, module in enumerate(self.modules):
            record.deployments[mod_idx] = (deployments[0][mod_idx], deployments[1][mod_idx])
            self.resolve_module(module,
                                resolved_deployments[0][mod_idx],
                                resolved_deployments[1][mod_idx])
        self.history.append(record)

    def _discard_and_refill(self, deployments: list[dict],
                             salvage_used: list | None = None,
                             espionage_used: list | None = None) -> None:
        """Discard played cards and refill hands to hand_size.

        salvage_used   — cards taken from the discard pile by Salvage; returned to discard.
        espionage_used — cards taken from hand by Espionage; already removed from hand,
                         just need to be added to the discard pile.
        """
        for player_idx in range(2):
            played = list(deployments[player_idx].values())
            for card in played:
                self.hands[player_idx].remove(card)
            self.deck.discard(played)

        if salvage_used:
            self.deck.discard(salvage_used)
        if espionage_used:
            self.deck.discard(espionage_used)

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
            discard=list(self.deck._discard),
            draw_pile_size=len(self.deck._draw),
        )

    def _make_resolution_view(self, player_idx: int, resolved: list) -> ResolutionView:
        """Build a ResolutionView for conditional-special callbacks (§3A)."""
        opp = 1 - player_idx
        return ResolutionView(
            player_idx=player_idx,
            hand=self.hands[player_idx],
            modules=self.modules,
            round_num=self.round_num,
            config=self.config,
            history=self.history,
            discard=list(self.deck._discard),
            draw_pile_size=len(self.deck._draw),
            own_deployment=dict(resolved[player_idx]),
            opponent_deployment=dict(resolved[opp]),
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


# ---------------------------------------------------------------------------
# Pure round resolver (§3E) — used by LookaheadStrategy for forward simulation.
# Works on card *classes* (types), not instances. dep0/dep1 must already have
# Espionage/Salvage substituted (resolved deployments). Relocation targets are
# passed separately because they affect other modules.
# ---------------------------------------------------------------------------

def resolve_round_pure(
    module_states: list,    # list of (dev, infl0, infl1) tuples
    dep0: dict,             # module_idx -> card class for player 0 (resolved)
    dep1: dict,             # module_idx -> card class for player 1 (resolved)
    reloc0: dict,           # module_idx -> target_idx for player 0 Relocations
    reloc1: dict,           # module_idx -> target_idx for player 1 Relocations
    config,
) -> list:
    """Return new list of (dev, infl0, infl1) tuples after resolving one round.

    Replicates resolve_module semantics exactly: Embargo freeze; both-Military
    special case with per-step dev clamping; StandardCard effects; Relocation
    cross-module transfer. Modules processed in index order 0..num_modules-1.
    """
    DEV_MIN = config.module_min_development
    DEV_MAX = config.module_max_development

    states = [[s[0], s[1], s[2]] for s in module_states]

    for mod_idx in range(config.num_modules):
        c0 = dep0.get(mod_idx)
        c1 = dep1.get(mod_idx)
        if c0 is None or c1 is None:
            continue
        s = states[mod_idx]

        if c0 is Embargo or c1 is Embargo:
            continue

        if c0 is Military and c1 is Military:
            # Both-Military: +2 inf each, -1 dev each (per-step clamped)
            s[1] += 2
            s[0] = max(DEV_MIN, min(DEV_MAX, s[0] - 1))
            s[2] += 2
            s[0] = max(DEV_MIN, min(DEV_MAX, s[0] - 1))
            continue

        for card_cls, pi in [(c0, 0), (c1, 1)]:
            infl_idx = pi + 1  # s[1]=infl0, s[2]=infl1
            if card_cls is Engineers:
                s[0] = max(DEV_MIN, min(DEV_MAX, s[0] + 1))
            elif card_cls is Colonists:
                s[infl_idx] += 1
            elif card_cls is Military:
                s[infl_idx] += 2
            elif card_cls is Overtime:
                s[0] = max(DEV_MIN, min(DEV_MAX, s[0] + 2))
            elif card_cls is Summit:
                s[infl_idx] += 1
                s[0] = max(DEV_MIN, min(DEV_MAX, s[0] + 1))
            elif card_cls is Propaganda:
                s[infl_idx] += 2
            elif card_cls is Relocation:
                tgt = reloc0.get(mod_idx) if pi == 0 else reloc1.get(mod_idx)
                if tgt is not None:
                    s[infl_idx] -= 1
                    states[tgt][infl_idx] += 1
            # Embargo already handled above; Espionage/Salvage are pre-resolved;
            # Occupation is cut from the game (count=0).

    return [tuple(s) for s in states]
