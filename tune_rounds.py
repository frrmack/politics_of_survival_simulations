"""
Sweep num_rounds from 4 to 12 to find the sweet spot where:
  - Coop vs Coop:  launches reliably but not trivially
  - Agg  vs Agg:  rarely launches (mutual defection is punished)
  - Coop vs Agg:  somewhere in between — enough tension to force some cooperation
"""
from dataclasses import replace as dc_replace

from config import GameConfig
from strategy import CooperativeStrategy, AggressiveStrategy, RandomStrategy
from simulation import Simulation

N = 5000

matchups = [
    ("Coop  vs Coop ", CooperativeStrategy(), CooperativeStrategy()),
    ("Agg   vs Agg  ", AggressiveStrategy(),  AggressiveStrategy()),
    ("Coop  vs Agg  ", CooperativeStrategy(), AggressiveStrategy()),
    ("Rand  vs Rand ", RandomStrategy(),       RandomStrategy()),
]

header = f"{'Rounds':>7}  " + "  ".join(f"{label} launch%" for label, *_ in matchups)
print(header)
print("-" * len(header))

for rounds in range(4, 13):
    config = GameConfig(num_rounds=rounds)
    row = f"{rounds:>7}  "
    parts = []
    for label, s1, s2 in matchups:
        results = Simulation(config, s1, s2).run(N)
        launch_pct = 100 * results.ship_launch_rate
        parts.append(f"{label} {launch_pct:5.1f}%")
    print(row + "  ".join(parts))
