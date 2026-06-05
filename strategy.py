import random
from abc import ABC, abstractmethod
from collections import Counter

from card import (Card, Engineers, Colonists, Military,
                  Embargo, Salvage, Espionage, Relocation, Overtime, Summit, Propaganda, Occupation)
from game import PlayerView, ResolutionView, resolve_round_pure


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

    The three conditional-special callbacks receive a ResolutionView that carries
    the current round's face-up deployments (§3A) in addition to all PlayerView fields.
    """

    @abstractmethod
    def choose_deployment(self, view: PlayerView) -> dict:
        raise NotImplementedError

    def choose_relocation_target(self, view: ResolutionView, _module_idx: int, neighbors: list[int]) -> int:
        """Default: pick the neighbor where the opponent leads most (or we're closest to losing)."""
        p, opp = view.player_idx, 1 - view.player_idx
        return max(neighbors, key=lambda i: view.modules[i].influence[opp] - view.modules[i].influence[p])

    def choose_salvage_card(self, view: ResolutionView, _module_idx: int, available: list) -> object:
        """Default: pick the highest-priority card by cooperation order."""
        type_rank = {cls: rank for rank, cls in enumerate(COOPERATION_ORDER)}
        return min(available, key=lambda c: type_rank.get(type(c), 99))

    def choose_espionage_card(self, view: ResolutionView, _module_idx: int, available: list) -> object:
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

    def choose_relocation_target(self, view: ResolutionView, _module_idx: int, neighbors: list[int]) -> int:
        return self._rng.choice(neighbors)

    def choose_salvage_card(self, view: ResolutionView, _module_idx: int, available: list) -> object:
        return self._rng.choice(available)

    def choose_espionage_card(self, view: ResolutionView, _module_idx: int, available: list) -> object:
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

    def choose_salvage_card(self, view: ResolutionView, _module_idx: int, available: list) -> object:
        type_rank = {cls: rank for rank, cls in enumerate(AGGRESSION_ORDER)}
        return min(available, key=lambda c: type_rank.get(type(c), 99))

    def choose_espionage_card(self, view: ResolutionView, _module_idx: int, available: list) -> object:
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


# ---------------------------------------------------------------------------
# Terminal scorer (§5.1)
# ---------------------------------------------------------------------------

LOSS, DRAW, WIN = 0.0, 0.5, 1.0


def score_terminal(dev, lead, *, ready_dev, n_to_launch):
    """Return {0.0, 0.5, 1.0} outcome from the perspective of the player whose lead is given.

    dev: iterable of int dev levels per module.
    lead: iterable of signed int (our_infl - opp_infl) per module.
    Catastrophe (< n_to_launch ready) → flat 0.0.
    """
    ready = ours = theirs = 0
    for d, l in zip(dev, lead):
        if d >= ready_dev:
            ready += 1
            if l > 0:
                ours += 1
            elif l < 0:
                theirs += 1
    if ready < n_to_launch:
        return LOSS
    if ours > theirs:
        return WIN
    if ours < theirs:
        return LOSS
    return DRAW


# ---------------------------------------------------------------------------
# Legal-deployment enumeration (§5.3)
# ---------------------------------------------------------------------------

def legal_deployments(hand_counter, num_modules):
    """Enumerate all distinct assignments of card types to modules.

    hand_counter: Counter of card_class -> count available.
    num_modules:  number of modules to fill (one card each).
    Yields dicts: module_idx -> card_class.
    Cards of the same type are interchangeable, so only type assignments matter.
    """
    types = [(ct, cnt) for ct, cnt in hand_counter.items() if cnt > 0]

    def _fill(mod_idx, remaining):
        if mod_idx == num_modules:
            yield {}
            return
        seen = set()
        for i, (ct, cnt) in enumerate(remaining):
            if cnt <= 0 or ct in seen:
                continue
            seen.add(ct)
            new_remaining = list(remaining)
            new_remaining[i] = (ct, cnt - 1)
            for rest in _fill(mod_idx + 1, new_remaining):
                rest[mod_idx] = ct
                yield rest

    yield from _fill(0, types)


# ---------------------------------------------------------------------------
# LookaheadStrategy (§5)
# ---------------------------------------------------------------------------

class LookaheadStrategy(Strategy):
    """1-ply expected-value lookahead strategy (v1).

    For each of our legal deployments, sweeps the opponent's plausible
    deployments (uniform over sampled hands), resolves the round with a
    pure resolver, and scores the resulting board. On the last round, uses
    the exact terminal scorer; on earlier rounds, uses a Monte-Carlo rollout.
    Special-card sub-choices (Espionage replacement, Salvage fetch, Relocation
    direction) are chosen optimally inside the expectation.

    The strategy is stateless across games: _round_plan is reset at the start
    of every choose_deployment call (§2 statelessness requirement).
    """

    def __init__(self, rng: random.Random | None = None,
                 n_hand_samples: int = 10,
                 n_rollouts: int = 20):
        self._rng = rng or random.Random()
        self.n_hand_samples = n_hand_samples
        self.n_rollouts = n_rollouts
        self._round_plan: dict | None = None  # module_idx -> card_class, set each round

    # ------------------------------------------------------------------
    # choose_deployment
    # ------------------------------------------------------------------

    def choose_deployment(self, view: PlayerView) -> dict:
        self._round_plan = None  # stateless: reset for each new round/game

        hand = Counter(type(c) for c in view.hand)
        module_states = tuple(
            (m.dev_level, m.influence[0], m.influence[1]) for m in view.modules
        )

        our_deps = list(legal_deployments(hand, view.config.num_modules))

        best_ev, best_dep = -1.0, our_deps[0]
        for dep in our_deps:
            ev = self._ev_of_deployment(dep, module_states, view)
            if ev > best_ev:
                best_ev, best_dep = ev, dep

        self._round_plan = best_dep
        return self._types_to_cards(best_dep, view.hand)

    # ------------------------------------------------------------------
    # Conditional-special callbacks — consistent with the plan
    # ------------------------------------------------------------------

    def choose_espionage_card(self, view: ResolutionView, module_idx: int, available: list) -> Card:
        opp_card_cls = None
        if hasattr(view, 'opponent_deployment'):
            opp_card = view.opponent_deployment.get(module_idx)
            if opp_card is not None:
                opp_card_cls = type(opp_card)
        module_states = tuple(
            (m.dev_level, m.influence[0], m.influence[1]) for m in view.modules
        )
        best_card = available[0]
        best_score = -1e9
        for card in available:
            score = self._score_card_at_module(
                type(card), opp_card_cls or Colonists,
                module_idx, module_states, view.config, view.player_idx)
            if score > best_score:
                best_score, best_card = score, card
        return best_card

    def choose_salvage_card(self, view: ResolutionView, module_idx: int, available: list) -> Card:
        opp_card_cls = None
        if hasattr(view, 'opponent_deployment'):
            opp_card = view.opponent_deployment.get(module_idx)
            if opp_card is not None:
                opp_card_cls = type(opp_card)
        module_states = tuple(
            (m.dev_level, m.influence[0], m.influence[1]) for m in view.modules
        )
        best_card = available[0]
        best_score = -1e9
        for card in available:
            score = self._score_card_at_module(
                type(card), opp_card_cls or Colonists,
                module_idx, module_states, view.config, view.player_idx)
            if score > best_score:
                best_score, best_card = score, card
        return best_card

    def choose_relocation_target(self, view: ResolutionView, module_idx: int, neighbors: list[int]) -> int:
        module_states = tuple(
            (m.dev_level, m.influence[0], m.influence[1]) for m in view.modules
        )
        return self._best_relocation_target(module_idx, neighbors, module_states, view.config, view.player_idx)

    # ------------------------------------------------------------------
    # EV computation core (§5.6)
    # ------------------------------------------------------------------

    def _ev_of_deployment(self, our_dep, module_states, view) -> float:
        """Average leaf value over n_hand_samples (opponent hand, deployment) pairs.

        The opponent model is v1: sample one random deployment per sampled hand
        (uniform over card orderings, which is a fast unbiased proxy for uniform
        over distinct type assignments). Full enumeration of opponent deployments
        is O(hand_size^num_modules) and prohibitively slow in practice.
        """
        config = view.config
        total_ev = 0.0
        for _ in range(self.n_hand_samples):
            opp_hand = self._sample_opponent_hand(view)
            opp_dep = self._random_deployment(opp_hand, config.num_modules)
            if not opp_dep:
                continue
            # resolve_round_pure always expects (dep0=player-0 cards, dep1=player-1 cards)
            pi = view.player_idx
            dep0_arg = our_dep if pi == 0 else opp_dep
            dep1_arg = opp_dep if pi == 0 else our_dep
            r0, r1, rl0, rl1 = self._compute_subchoices(
                dep0_arg, dep1_arg, module_states, view, opp_hand)
            new_states = resolve_round_pure(module_states, r0, r1, rl0, rl1, config)
            total_ev += self._leaf_value(new_states, view)
        return total_ev / self.n_hand_samples

    # ------------------------------------------------------------------
    # Sub-choice computation (§5.6 nested argmax)
    # ------------------------------------------------------------------

    def _compute_subchoices(self, dep0_types, dep1_types, module_states, view, opp_hand_counter):
        """Compute optimal sub-choices for a fixed (dep0, dep1) pair.

        Returns (resolved0, resolved1, reloc0, reloc1) where resolved0/1 are
        module_idx -> card_class with Espionage/Salvage substituted.
        """
        config = view.config
        pi = view.player_idx
        opp = 1 - pi

        resolved = [dict(dep0_types), dict(dep1_types)]
        reloc = [{}, {}]  # reloc[player] = {mod_idx: target_idx}

        # Available cards for sub-choices
        our_remaining = Counter(type(c) for c in view.hand)
        for ct in dep0_types.values() if pi == 0 else dep1_types.values():
            our_remaining[ct] -= 1
        our_remaining = Counter({k: v for k, v in our_remaining.items() if v > 0})

        opp_remaining = Counter(opp_hand_counter)
        for ct in (dep1_types if pi == 0 else dep0_types).values():
            opp_remaining[ct] -= 1
        opp_remaining = Counter({k: v for k, v in opp_remaining.items() if v > 0})

        discard_pool = Counter(type(c) for c in view.discard)

        for mod_idx in range(config.num_modules):
            c = [resolved[0][mod_idx], resolved[1][mod_idx]]

            if c[0] is Embargo or c[1] is Embargo:
                continue

            # Espionage first (§3C) — our player, then opponent
            for player in [pi, opp]:
                if c[player] is Espionage:
                    remaining = our_remaining if player == pi else opp_remaining
                    opp_card = c[1 - player]
                    if remaining:
                        if player == pi:
                            best = self._best_replacement(
                                remaining, mod_idx, opp_card,
                                module_states, config, pi)
                        else:
                            best = max(
                                remaining,
                                key=lambda ct: self._card_power(ct, mod_idx, module_states, config, opp))
                        if best is not None:
                            resolved[player][mod_idx] = best
                            remaining[best] -= 1
                            if remaining[best] <= 0:
                                del remaining[best]
                            discard_pool[Espionage] += 1
                            c[player] = best

            # Salvage — our player, then opponent
            for player in [pi, opp]:
                if c[player] is Salvage:
                    if discard_pool:
                        opp_card = c[1 - player]
                        if player == pi:
                            best = self._best_salvage(
                                discard_pool, mod_idx, opp_card,
                                module_states, config, pi)
                        else:
                            best = max(
                                discard_pool,
                                key=lambda ct: self._card_power(ct, mod_idx, module_states, config, opp))
                        if best is not None:
                            resolved[player][mod_idx] = best
                            discard_pool[best] -= 1
                            if discard_pool[best] <= 0:
                                del discard_pool[best]
                            discard_pool[Salvage] += 1
                            c[player] = best

            # Relocation
            for player in [pi, opp]:
                if c[player] is Relocation:
                    neighbors = [i for i in [mod_idx - 1, mod_idx + 1]
                                 if 0 <= i < config.num_modules]
                    if len(neighbors) == 1:
                        tgt = neighbors[0]
                    elif player == pi:
                        tgt = self._best_relocation_target(
                            mod_idx, neighbors, module_states, config, pi)
                    else:
                        # Opponent picks neighbor where their lead improves most
                        tgt = max(neighbors,
                                  key=lambda i: module_states[i][opp + 1] - module_states[i][pi + 1])
                    reloc[player][mod_idx] = tgt

        return resolved[0], resolved[1], reloc[0], reloc[1]

    # ------------------------------------------------------------------
    # Leaf evaluator (§5.7)
    # ------------------------------------------------------------------

    def _leaf_value(self, module_states, view) -> float:
        rounds_after = view.config.num_rounds - view.round_num  # rounds remaining after this one
        if rounds_after == 0:
            return self._score(module_states, view.player_idx, view.config)

        total = 0.0
        for _ in range(self.n_rollouts):
            total += self._rollout(module_states, view, rounds_after)
        return total / self.n_rollouts

    def _rollout(self, module_states, view, rounds_to_play) -> float:
        """Random-policy Monte-Carlo rollout for non-terminal boards."""
        config = view.config
        pi = view.player_idx
        states = list(module_states)

        # Estimate remaining pool: full deck minus our hand minus visible discard
        pool = self._full_deck_pool(config)
        for c in view.hand:
            ct = type(c)
            pool[ct] = max(0, pool[ct] - 1)
        for c in view.discard:
            ct = type(c)
            pool[ct] = max(0, pool[ct] - 1)
        pool = Counter({k: v for k, v in pool.items() if v > 0})

        for _ in range(rounds_to_play):
            draw_pool = Counter(pool)
            our_hand = self._sample_from_pool(draw_pool, config.hand_size, self._rng)
            opp_hand = self._sample_from_pool(draw_pool, config.hand_size, self._rng)

            our_dep = self._random_deployment(our_hand, config.num_modules)
            opp_dep = self._random_deployment(opp_hand, config.num_modules)
            if not our_dep or not opp_dep:
                break

            dep0 = our_dep if pi == 0 else opp_dep
            dep1 = opp_dep if pi == 0 else our_dep
            states = list(resolve_round_pure(states, dep0, dep1, {}, {}, config))

        return self._score(states, pi, config)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _score(self, module_states, player_idx, config) -> float:
        pi = player_idx
        dev = tuple(s[0] for s in module_states)
        lead = tuple(s[pi + 1] - s[2 - pi] for s in module_states)
        return score_terminal(dev, lead,
                              ready_dev=config.module_ready_threshold,
                              n_to_launch=config.modules_needed_to_launch)

    def _full_deck_pool(self, config) -> Counter:
        return Counter({
            Engineers:  config.engineers_count,
            Colonists:  config.colonists_count,
            Military:   config.military_count,
            Embargo:    config.embargo_count,
            Salvage:    config.salvage_count,
            Espionage:  config.espionage_count,
            Relocation: config.relocation_count,
            Overtime:   config.overtime_count,
            Summit:     config.summit_count,
            Propaganda: config.propaganda_count,
            # Occupation excluded (count=0 in config)
        })

    def _sample_opponent_hand(self, view) -> Counter:
        pool = self._full_deck_pool(view.config)
        for c in view.hand:
            ct = type(c)
            pool[ct] = max(0, pool[ct] - 1)
        for c in view.discard:
            ct = type(c)
            pool[ct] = max(0, pool[ct] - 1)
        pool = Counter({k: v for k, v in pool.items() if v > 0})
        available = []
        for ct, cnt in pool.items():
            available.extend([ct] * cnt)
        n = min(view.config.hand_size, len(available))
        sampled = self._rng.sample(available, n)
        return Counter(sampled)

    @staticmethod
    def _sample_from_pool(pool: Counter, n: int, rng: random.Random) -> Counter:
        """Sample n items from pool without replacement; modifies pool in place."""
        available = []
        for ct, cnt in pool.items():
            available.extend([ct] * cnt)
        rng.shuffle(available)
        sampled = available[:n]
        result = Counter(sampled)
        for ct in sampled:
            pool[ct] -= 1
        return result

    def _types_to_cards(self, dep_types: dict, hand: list) -> dict:
        """Convert module_idx -> card_class to module_idx -> card_instance."""
        hand_copy = list(hand)
        result = {}
        for mod_idx, card_cls in dep_types.items():
            for i, card in enumerate(hand_copy):
                if type(card) is card_cls:
                    result[mod_idx] = card
                    hand_copy.pop(i)
                    break
        return result

    def _card_power(self, card_cls, mod_idx, module_states, config, player_idx) -> float:
        """Quick scalar: how much does this card type benefit player_idx at mod_idx."""
        s = module_states[mod_idx]
        dev, infl_us, infl_opp = s[0], s[player_idx + 1], s[2 - player_idx]
        ready_thresh = config.module_ready_threshold
        DEV_MAX = config.module_max_development
        dev_headroom = max(0, DEV_MAX - dev)
        lead = infl_us - infl_opp

        if card_cls is Engineers:
            return min(1, dev_headroom) * 1.0
        elif card_cls is Colonists:
            return 1.0
        elif card_cls is Military:
            return 2.0  # raw power, clash risk handled elsewhere
        elif card_cls is Overtime:
            return min(2, dev_headroom) * 1.5
        elif card_cls is Summit:
            return 1.0 + min(1, dev_headroom) * 0.8
        elif card_cls is Propaganda:
            return 2.2  # +2 inf without clash risk
        elif card_cls is Embargo:
            return 0.5  # situational
        elif card_cls is Relocation:
            return 0.4
        elif card_cls is Espionage:
            return 1.2  # flexible power
        elif card_cls is Salvage:
            return 0.8  # depends on discard
        return 0.0

    def _score_card_at_module(self, our_cls, opp_cls, mod_idx, module_states, config, our_pi) -> float:
        """Simulate one module for a (our_cls, opp_cls) pair; return a local quality score."""
        s = list(module_states[mod_idx])
        DEV_MIN = config.module_min_development
        DEV_MAX = config.module_max_development

        # Build temporary single-module deployment and resolve it
        dep0 = {mod_idx: our_cls if our_pi == 0 else opp_cls}
        dep1 = {mod_idx: opp_cls if our_pi == 0 else our_cls}
        # Use a single-module resolve (pass full module_states but only mod_idx matters)
        result = resolve_round_pure(module_states, dep0, dep1, {}, {}, config)
        ns = result[mod_idx]

        ready_thresh = config.module_ready_threshold
        new_dev, new_us, new_opp = ns[0], ns[our_pi + 1], ns[2 - our_pi]
        our_lead = new_us - new_opp

        score = 0.0
        if new_dev >= ready_thresh:
            if our_lead > 0:
                score += 10.0 + min(our_lead, 3)
            elif our_lead < 0:
                score += -5.0 + our_lead
            else:
                score += 4.0
        else:
            score += new_dev * 0.5 + our_lead * 0.3

        return score

    def _best_replacement(self, available_pool, mod_idx, opp_card_cls, module_states, config, our_pi) -> type | None:
        if not available_pool:
            return None
        return max(available_pool,
                   key=lambda ct: self._score_card_at_module(
                       ct, opp_card_cls, mod_idx, module_states, config, our_pi))

    def _best_salvage(self, discard_pool, mod_idx, opp_card_cls, module_states, config, our_pi) -> type | None:
        if not discard_pool:
            return None
        return max(discard_pool,
                   key=lambda ct: self._score_card_at_module(
                       ct, opp_card_cls, mod_idx, module_states, config, our_pi))

    def _random_deployment(self, hand_counter: Counter, num_modules: int) -> dict:
        """Sample one deployment by shuffling available card types and taking the first num_modules."""
        available = []
        for ct, cnt in hand_counter.items():
            available.extend([ct] * cnt)
        self._rng.shuffle(available)
        if len(available) < num_modules:
            return {}
        return {i: available[i] for i in range(num_modules)}

    def _best_relocation_target(self, mod_idx, neighbors, module_states, config, our_pi) -> int:
        """Pick the relocation target that maximizes our lead among ready/near-ready modules."""
        opp_pi = 1 - our_pi
        ready_thresh = config.module_ready_threshold

        def target_value(tgt):
            s = module_states[tgt]
            our_lead_after = s[our_pi + 1] + 1 - s[opp_pi + 1]
            is_ready = s[0] >= ready_thresh
            return (is_ready, our_lead_after)

        return max(neighbors, key=target_value)
