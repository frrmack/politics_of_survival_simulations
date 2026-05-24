"""
Diagnose the P1 vs P2 win asymmetry in Coop vs Coop.
Track card compositions, influence per module, and win patterns.
"""
from collections import defaultdict

from config import GameConfig
from card import CardType
from game import Game
from strategy import CooperativeStrategy

N = 20000

config = GameConfig()
s = CooperativeStrategy()

p1_wins = p2_wins = draws = extinctions = 0

# Per-module: how often does P1 have more influence than P2 at game end?
module_p1_leads   = defaultdict(int)
module_p2_leads   = defaultdict(int)
module_tied       = defaultdict(int)

# Track average card type counts per player per round
p1_sci = p1_col = p1_mil = 0
p2_sci = p2_col = p2_mil = 0
total_rounds = 0

for _ in range(N):
    game = Game(config, [s, s])

    # Monkey-patch _play_round to track card stats
    original_play_round = game._play_round

    def tracked_play_round():
        global p1_sci, p1_col, p1_mil, p2_sci, p2_col, p2_mil, total_rounds
        for card in game.hands[0]:
            if card.card_type == CardType.SCIENTISTS:   p1_sci += 1
            elif card.card_type == CardType.COLONISTS:  p1_col += 1
            elif card.card_type == CardType.MILITARY:   p1_mil += 1
        for card in game.hands[1]:
            if card.card_type == CardType.SCIENTISTS:   p2_sci += 1
            elif card.card_type == CardType.COLONISTS:  p2_col += 1
            elif card.card_type == CardType.MILITARY:   p2_mil += 1
        total_rounds += 1
        original_play_round()

    game._play_round = tracked_play_round
    result = game.play()

    if result.extinction:
        extinctions += 1
    elif result.winner == 0:
        p1_wins += 1
    elif result.winner == 1:
        p2_wins += 1
    else:
        draws += 1

    for m in result.final_modules:
        if m.influence[0] > m.influence[1]:
            module_p1_leads[m.index] += 1
        elif m.influence[1] > m.influence[0]:
            module_p2_leads[m.index] += 1
        else:
            module_tied[m.index] += 1

print(f"=== Coop vs Coop diagnostic ({N:,} games) ===\n")
print(f"P1 wins:     {p1_wins:>7,}  ({100*p1_wins/N:.1f}%)")
print(f"P2 wins:     {p2_wins:>7,}  ({100*p2_wins/N:.1f}%)")
print(f"Draws:       {draws:>7,}  ({100*draws/N:.1f}%)")
print(f"Extinctions: {extinctions:>7,}  ({100*extinctions/N:.1f}%)")

print(f"\n--- Average hand composition per player (per round-start) ---")
r = total_rounds
print(f"           Scientists  Colonists  Military")
print(f"P1 avg:      {p1_sci/r:5.2f}      {p1_col/r:5.2f}     {p1_mil/r:5.2f}")
print(f"P2 avg:      {p2_sci/r:5.2f}      {p2_col/r:5.2f}     {p2_mil/r:5.2f}")

print(f"\n--- Per-module influence lead at game end ---")
print(f"Module  P1 leads   P2 leads   Tied")
for i in range(config.num_modules):
    total = module_p1_leads[i] + module_p2_leads[i] + module_tied[i]
    print(
        f"  {i+1}     {module_p1_leads[i]:>6,} ({100*module_p1_leads[i]/total:4.1f}%)"
        f"   {module_p2_leads[i]:>6,} ({100*module_p2_leads[i]/total:4.1f}%)"
        f"   {module_tied[i]:>6,} ({100*module_tied[i]/total:4.1f}%)"
    )
