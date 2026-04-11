from .perfect_solver import PerfectSolver


class ProbabilisticSolver(PerfectSolver):
    """Perfect-solver reasoning without the global mine-count constraint."""

    def __init__(self, height: int, width: int, num_mines: int):
        super().__init__(height, width, num_mines, use_global_mine_count=False)
