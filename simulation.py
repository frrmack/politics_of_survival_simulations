import statistics
from dataclasses import dataclass

from config import GameConfig
from game import Game, GameResult
from strategy import Strategy


@dataclass
class SimulationResults:
    results: list
    strategy_names: list

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def p1_wins(self) -> int:
        return sum(1 for r in self.results if r.winner == 0)

    @property
    def p2_wins(self) -> int:
        return sum(1 for r in self.results if r.winner == 1)

    @property
    def draws(self) -> int:
        return sum(1 for r in self.results if r.winner is None and not r.extinction)

    @property
    def extinctions(self) -> int:
        return sum(1 for r in self.results if r.extinction)

    @property
    def ship_launch_rate(self) -> float:
        return 1.0 - self.extinctions / self.n

    @property
    def avg_ready_modules(self) -> float:
        return statistics.mean(r.ready_modules for r in self.results)

    @property
    def avg_rounds_played(self) -> float:
        return statistics.mean(r.rounds_played for r in self.results)

    @property
    def early_launch_rate(self) -> float:
        return sum(1 for r in self.results if r.early_launch) / self.n

    def print_summary(self) -> None:
        n = self.n
        s1, s2 = self.strategy_names
        bar = "=" * 52
        print(bar)
        print(f"  {s1}  vs  {s2}")
        print(f"  {n:,} games simulated")
        print(bar)
        print(f"  P1 wins:        {self.p1_wins:>7,}  ({100 * self.p1_wins / n:5.1f}%)")
        print(f"  P2 wins:        {self.p2_wins:>7,}  ({100 * self.p2_wins / n:5.1f}%)")
        print(f"  Draws:          {self.draws:>7,}  ({100 * self.draws / n:5.1f}%)")
        print(f"  Extinctions:    {self.extinctions:>7,}  ({100 * self.extinctions / n:5.1f}%)")
        print("  " + "-" * 48)
        print(f"  Ship launch rate:       {100 * self.ship_launch_rate:5.1f}%")
        print(f"  Early launch rate:      {100 * self.early_launch_rate:5.1f}%")
        print(f"  Avg ready modules:      {self.avg_ready_modules:.2f} / {len(self.results[0].final_modules)}")
        print(f"  Avg rounds played:      {self.avg_rounds_played:.2f}")
        print(bar)


class Simulation:
    def __init__(
        self,
        config: GameConfig,
        strategy_p1: Strategy,
        strategy_p2: Strategy,
    ):
        self.config = config
        self.strategies = [strategy_p1, strategy_p2]

    def run(self, n_games: int) -> SimulationResults:
        results = []
        for _ in range(n_games):
            game = Game(self.config, self.strategies)
            results.append(game.play())

        return SimulationResults(
            results=results,
            strategy_names=[type(s).__name__ for s in self.strategies],
        )
