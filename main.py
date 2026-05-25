"""
Politics of Survival — baseline matchup simulations.
Current design parameters: 5 modules, 4 needed to launch, 5 rounds, 3 card types.
"""
from config import GameConfig
from strategy import RandomStrategy, CooperativeStrategy, AggressiveStrategy, BalancedStrategy
from simulation import Simulation


def matchup(config, s1, s2, n=5000):
    Simulation(config, s1, s2).run(n).print_summary()
    print()


def main():
    config = GameConfig(num_rounds=5, 
                        num_modules=5, 
                        modules_needed_to_launch=4,
                        #module_dev_level_init=lambda rng: rng.randint(1, 6)
                        module_dev_level_init=[1,2,3,4,5] # deterministic setup for easier debugging
                        )

    print("\n=== Politics of Survival — Baseline (5 modules, 5 rounds) ===\n")

    matchup(config, RandomStrategy(),      RandomStrategy())
    matchup(config, CooperativeStrategy(), CooperativeStrategy())
    matchup(config, AggressiveStrategy(),  AggressiveStrategy())
    matchup(config, CooperativeStrategy(), AggressiveStrategy())
    matchup(config, AggressiveStrategy(),  CooperativeStrategy())
    matchup(config, BalancedStrategy(),    BalancedStrategy())
    matchup(config, BalancedStrategy(),    CooperativeStrategy())
    matchup(config, BalancedStrategy(),    AggressiveStrategy())


if __name__ == "__main__":
    main()
