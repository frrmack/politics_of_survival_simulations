from typing import Callable
from dataclasses import dataclass, field


@dataclass
class GameConfig:
    # Game structure
    num_rounds: int = 5
    num_modules: int = 5
    hand_size: int = 8
    modules_needed_to_launch: int = 4

    # Module parameters
    module_min_development: int = 1
    module_max_development: int = 6
    module_ready_threshold: int = 5     # min dev level of a module ready for launch
    #--
    # This is how module dev levels are initialized at the start of each game; 
    # can be a RNG function or a list of ints for deterministic setups.
    # The default is randomly choosing between 1 and 6 for each module.
    # Examples:
    # config_default = GameConfig()
    # config_list    = GameConfig(module_dev_level_init=[1, 2, 3, 4, 5])
    # config_custom  = GameConfig(module_dev_level_init=lambda rng: rng.randint(1, 4))
    module_dev_level_init: Callable | list = field( 
        default_factory=lambda: lambda rng: rng.randint(1, 6) 
        )
    # --
    
    # Deck composition — main types (1:1:1 ratio by default)
    engineers_count: int = 10
    colonists_count: int = 10
    military_count: int = 10

    # Special cards (1 each by default)
    embargo_count: int = 1
    overtime_count: int = 1
    genius_count: int = 1
    propaganda_count: int = 1


    @property
    def deck_size(self) -> int:
        return (
            self.engineers_count
            + self.colonists_count
            + self.military_count
            + self.embargo_count
            + self.overtime_count
            + self.genius_count
            + self.propaganda_count
        )
