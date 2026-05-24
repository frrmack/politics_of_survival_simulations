from dataclasses import dataclass


@dataclass
class GameConfig:
    # Game structure
    num_rounds: int = 5
    num_modules: int = 5
    hand_size: int = 8
    modules_needed_to_launch: int = 4
    ready_threshold: int = 5          # minimum dev level for a module to be "ready"

    # Deck composition — main types (1:1:1 ratio by default)
    scientists_count: int = 10
    colonists_count: int = 10
    military_count: int = 10

    # Special cards (excluded from play; set > 0 to reintroduce individually)
    genius_count: int = 0
    sabotage_count: int = 0
    launch_now_count: int = 0
    double_agent_count: int = 0

    @property
    def deck_size(self) -> int:
        return (
            self.scientists_count
            + self.colonists_count
            + self.military_count
            + self.genius_count
            + self.sabotage_count
            + self.launch_now_count
            + self.double_agent_count
        )
