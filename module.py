from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Module:
    index: int
    dev_level: int
    influence: list = field(default_factory=lambda: [0, 0])

    DEV_MIN = 1
    DEV_MAX = 6
    READY_THRESHOLD = 5

    @property
    def is_ready(self) -> bool:
        return self.dev_level >= self.READY_THRESHOLD

    def adjust_dev(self, delta: int) -> None:
        self.dev_level = max(self.DEV_MIN, min(self.DEV_MAX, self.dev_level + delta))

    def add_influence(self, player_idx: int, amount: int) -> None:
        self.influence[player_idx] += amount

    def winner(self) -> Optional[int]:
        """Returns player index (0 or 1) with more influence, or None for a tie."""
        if self.influence[0] > self.influence[1]:
            return 0
        if self.influence[1] > self.influence[0]:
            return 1
        return None

    def __repr__(self) -> str:
        status = "READY" if self.is_ready else f"needs +{self.READY_THRESHOLD - self.dev_level}"
        return (
            f"Module{self.index + 1}(dev={self.dev_level} [{status}], "
            f"P1={self.influence[0]}, P2={self.influence[1]})"
        )
