from .solver_types import (
    Cell,
    ConnectedMineGroup,
    MineGroup,
    Solver,
    SolverResult,
    merge_disjointed_connected_groups,
)


class PerfectSolver(Solver):
    """Constraint-propagation solver with subset splitting, permutation
    backtracking per connected component, and global mine-count reasoning.

    When use_global_mine_count is True, the solver uses the total remaining
    mine count to prune permutations and to deduce that all unconstrained
    tiles are mines when the remaining-mine budget is exhausted.

    The returned SolverResult.probs gives a per-component mine probability
    snapshot for every currently-unknown cell. Per-component probabilities
    are correct under the per-component mine-budget constraint but are NOT
    jointly calibrated across components or against the global budget. This
    is acceptable for bot move selection; full joint calibration would
    require convolving component mine-count distributions.
    """

    def __init__(self, height: int, width: int, num_mines: int, use_global_mine_count: bool = True):
        super().__init__(height, width, num_mines)
        self.use_global_mine_count = use_global_mine_count
        self.remaining_mines = num_mines
        self.connected_groups: dict[Cell, ConnectedMineGroup] = {}
        self.all_groups: set[ConnectedMineGroup] = set()
        self.revealed_cells: set[Cell] = set()
        self.mine_cells: set[Cell] = set()
        self.tiles_without_information: set[Cell] = set(
            (r, c) for r in range(height) for c in range(width)
        )
        self._last_expected_fringe_mines: float = 0.0

    def find_solved_squares(self, newly_revealed: dict[Cell, int]) -> SolverResult:
        prev_mines: set[Cell] = set(self.mine_cells)

        # 1. Mark each revealed cell as safe internally
        for cell in newly_revealed:
            self.revealed_cells.add(cell)
            self._mark_revealed(cell)
            self.tiles_without_information.discard(cell)
            cg = self.connected_groups.get(cell)
            if cg:
                cg.mark_safe(cell)

        # 2. Clean up empty groups, reassess subsets
        self.all_groups = {g for g in self.all_groups if not g.is_empty()}
        for group in list(self.all_groups):
            group.reassess_for_subsets()

        # 3. Build constraint groups from newly revealed cells
        for (r, c), adjacent_mines in newly_revealed.items():
            if adjacent_mines == 0:
                continue

            unknown_neighbors: set[Cell] = set()
            for nr, nc in self._neighbors(r, c):
                nk = (nr, nc)
                if nk not in self.revealed_cells and nk not in self.mine_cells:
                    unknown_neighbors.add(nk)
            if not unknown_neighbors:
                continue

            for nk in unknown_neighbors:
                self.tiles_without_information.discard(nk)

            mine_count = sum(1 for nr, nc in self._neighbors(r, c) if (nr, nc) in self.mine_cells)
            mine_group = MineGroup(unknown_neighbors, adjacent_mines - mine_count)

            # Deduplicate relevant connected groups
            relevant_connected_groups = list({
                self.connected_groups[cell]
                for cell in unknown_neighbors
                if cell in self.connected_groups
            })

            if not relevant_connected_groups:
                new_group = ConnectedMineGroup()
                new_group.add_group(mine_group)
                for cell in unknown_neighbors:
                    self.connected_groups[cell] = new_group
                self.all_groups.add(new_group)
            elif len(relevant_connected_groups) == 1:
                relevant_connected_groups[0].add_group(mine_group)
                for cell in unknown_neighbors:
                    self.connected_groups[cell] = relevant_connected_groups[0]
            else:
                merged_group = merge_disjointed_connected_groups(relevant_connected_groups)
                merged_group.add_group(mine_group)
                for cell in merged_group.relevant_cells:
                    self.connected_groups[cell] = merged_group
                self.all_groups.add(merged_group)
                for group in relevant_connected_groups:
                    self.all_groups.discard(group)

        # 4. Split disjoint groups
        new_all_groups: set[ConnectedMineGroup] = set()
        for group in self.all_groups:
            for component in group.split_if_disjoint():
                new_all_groups.add(component)
                for cell in component.relevant_cells:
                    self.connected_groups[cell] = component
        self.all_groups = new_all_groups

        # 5. Solve all groups
        to_reveal: list[Cell] = []
        to_mark_mine: set[Cell] = set()
        max_mines_used = 0
        fringe_probs: dict[Cell, float] = {}
        expected_fringe_mines = 0.0
        mine_budget = self.remaining_mines if self.use_global_mine_count else float('inf')
        for group in self.all_groups:
            safe_cells, mine_cells, group_max, group_probs, _total_valid = group.solve_groups(mine_budget)
            for c in safe_cells:
                to_reveal.append(c)
            to_mark_mine.update(mine_cells)
            max_mines_used += group_max
            fringe_probs.update(group_probs)
            expected_fringe_mines += sum(group_probs.values())

        # 6. Check global mine constraint on unconstrained tiles
        if self.use_global_mine_count:
            min_mines_remaining = self.remaining_mines - max_mines_used
            if min_mines_remaining == len(self.tiles_without_information):
                to_mark_mine.update(self.tiles_without_information)

        # 7. Process deduced mines internally
        for key in to_mark_mine:
            if key in self.mine_cells:
                continue
            self.mine_cells.add(key)
            self._mark_mine(key)
            self.tiles_without_information.discard(key)
            self.remaining_mines -= 1
            cg = self.connected_groups.get(key)
            if cg:
                cg.mark_mine(key)

        self._last_expected_fringe_mines = expected_fringe_mines

        # 8. Build the SolverResult: bundle newly-deduced safe/mine cells
        # plus a per-cell probability snapshot covering every unknown cell.
        new_safe = set(to_reveal)
        new_mines = self.mine_cells - prev_mines

        probs: dict[Cell, float] = {}
        # Fringe cells from the constraint components (skip cells the solver
        # has since flagged as mines this turn — they've left their groups).
        for cell, p in fringe_probs.items():
            if cell in self.mine_cells or cell in self.revealed_cells:
                continue
            probs[cell] = p
        # Force certainty on newly-deduced safe cells (in case any lingered
        # at a fractional value before promotion).
        for cell in new_safe:
            if cell in self.revealed_cells or cell in self.mine_cells:
                continue
            probs[cell] = 0.0

        # Global density fallback for unconstrained tiles.
        if self.tiles_without_information:
            uncertain_count = len(self.tiles_without_information)
            remaining = self.remaining_mines - expected_fringe_mines
            density = remaining / uncertain_count if uncertain_count > 0 else 0.0
            density = max(0.0, min(1.0, density))
            for cell in self.tiles_without_information:
                probs[cell] = density

        return SolverResult(safe=new_safe, mines=new_mines, probs=probs)
