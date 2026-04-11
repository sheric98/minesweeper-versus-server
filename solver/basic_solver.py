from .solver_types import Cell, Solver, SolverResult


class BasicSolver(Solver):
    """Single-cell constraint propagation: for each revealed number, if the
    count of known-mine neighbors equals the number, the rest are safe; if
    the count of unknown+known-mine neighbors equals the number, the unknowns
    are all mines."""

    def __init__(self, height: int, width: int, num_mines: int):
        super().__init__(height, width, num_mines)
        self.revealed_cells: dict[Cell, int] = {}
        self.known_mines: set[Cell] = set()

    def find_solved_squares(self, newly_revealed: dict[Cell, int]) -> SolverResult:
        prev_known: set[Cell] = set(self.known_mines)

        for cell, adj in newly_revealed.items():
            self.revealed_cells[cell] = adj

        safe_cells: set[Cell] = set()
        changed = True

        while changed:
            changed = False

            for (r, c), adjacent_mines in self.revealed_cells.items():
                unknown_neighbors: list[Cell] = []
                known_mine_count = 0

                for nr, nc in self._neighbors(r, c):
                    nk = (nr, nc)
                    if nk in self.known_mines:
                        known_mine_count += 1
                    elif nk not in self.revealed_cells and nk not in safe_cells:
                        unknown_neighbors.append(nk)

                if not unknown_neighbors:
                    continue

                # Rule 1: all unknown neighbors are mines
                if adjacent_mines - known_mine_count == len(unknown_neighbors):
                    for nk in unknown_neighbors:
                        if nk not in self.known_mines:
                            self.known_mines.add(nk)
                            changed = True

                # Rule 2: all unknown neighbors are safe
                if adjacent_mines == known_mine_count:
                    for nk in unknown_neighbors:
                        if nk not in safe_cells:
                            safe_cells.add(nk)
                            changed = True

        revealed_set = set(self.revealed_cells.keys())
        probs = self._density_only_probs(revealed_set, self.known_mines, safe_cells)
        return SolverResult(
            safe=safe_cells,
            mines=self.known_mines - prev_known,
            probs=probs,
        )
