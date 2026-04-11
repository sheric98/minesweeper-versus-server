from .solver_types import Cell, MineGroup, Solver, SolverResult


class SubsetSolver(Solver):
    """Basic-solver reasoning plus subset splitting: if group A's unknown
    cells are a proper subset of group B's, split B into A and (B - A) with
    (B.mines - A.mines) mines."""

    def __init__(self, height: int, width: int, num_mines: int):
        super().__init__(height, width, num_mines)
        self.revealed_cells: dict[Cell, int] = {}
        self.known_mines: set[Cell] = set()

    def find_solved_squares(self, newly_revealed: dict[Cell, int]) -> SolverResult:
        prev_known: set[Cell] = set(self.known_mines)

        for cell, adj in newly_revealed.items():
            self.revealed_cells[cell] = adj
            self._mark_revealed(cell)

        safe_cells: set[Cell] = set()
        changed = True

        while changed:
            changed = False

            # 1. Build MineGroups + cell index from all revealed cells
            groups: list[MineGroup] = []
            cell_to_groups: dict[Cell, list[MineGroup]] = {}

            for (r, c), adjacent_mines in self.revealed_cells.items():
                unknowns: set[Cell] = set()
                known_mine_count = 0

                for nr, nc in self._neighbors(r, c):
                    nk = (nr, nc)
                    if nk in self.known_mines:
                        known_mine_count += 1
                    elif nk not in self.revealed_cells and nk not in safe_cells:
                        unknowns.add(nk)

                if not unknowns:
                    continue

                group = MineGroup(unknowns, adjacent_mines - known_mine_count)
                groups.append(group)
                for cell in unknowns:
                    cell_to_groups.setdefault(cell, []).append(group)

            # 2. Subset splitting via cell index (loop until stable)
            split_occurred = True
            while split_occurred:
                split_occurred = False

                for g in groups:
                    candidates: set[MineGroup] = set()
                    for cell in g.cells:
                        for candidate in cell_to_groups.get(cell, ()):
                            if candidate is not g:
                                candidates.add(candidate)

                    for c_group in candidates:
                        if g.cells < c_group.cells:
                            # g is a proper subset of c_group -- split c_group into g and diff
                            diff_cells = c_group.cells - g.cells
                            diff = MineGroup(diff_cells, c_group.mines - g.mines)

                            # Remove c_group from groups and cell_to_groups
                            groups = [x for x in groups if x is not c_group]
                            for cell in c_group.cells:
                                lst = cell_to_groups.get(cell)
                                if lst:
                                    cell_to_groups[cell] = [x for x in lst if x is not c_group]

                            # Add diff
                            groups.append(diff)
                            for cell in diff_cells:
                                cell_to_groups.setdefault(cell, []).append(diff)

                            split_occurred = True
                            break

                    if split_occurred:
                        break

            # 3. Check for trivially solved groups
            for group in groups:
                if group.all_safe():
                    for cell in group.cells:
                        if cell not in safe_cells:
                            safe_cells.add(cell)
                            changed = True
                elif group.all_mines():
                    for cell in group.cells:
                        if cell not in self.known_mines:
                            self.known_mines.add(cell)
                            self._mark_mine(cell)
                            changed = True

        revealed_set = set(self.revealed_cells.keys())
        probs = self._density_only_probs(revealed_set, self.known_mines, safe_cells)
        return SolverResult(
            safe=safe_cells,
            mines=self.known_mines - prev_known,
            probs=probs,
        )
