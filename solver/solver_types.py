from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


Cell = tuple[int, int]


@dataclass
class SolverResult:
    """Bundled output of a solver call.

    - safe: cells newly deduced as safe by this call
    - mines: cells newly deduced as mines by this call
    - probs: mine probability in [0, 1] for EVERY currently-unknown cell
        (cells the solver has neither revealed nor proven to be mines).
        Cells already proven safe/mine — including those just deduced this
        call — appear at exactly 0.0 / 1.0.
    """

    safe: set[Cell] = field(default_factory=set)
    mines: set[Cell] = field(default_factory=set)
    probs: dict[Cell, float] = field(default_factory=dict)


class MineGroup:
    def __init__(self, cells: set[Cell], mines: int):
        self.cells = cells
        self.mines = mines

    def mark_safe(self, cell: Cell):
        if cell in self.cells:
            self.cells.remove(cell)

    def mark_mine(self, cell: Cell):
        if cell in self.cells:
            self.cells.remove(cell)
            self.mines -= 1

    def empty(self) -> bool:
        return not self.cells

    def all_mines(self) -> bool:
        return self.mines == len(self.cells)

    def all_safe(self) -> bool:
        return self.mines == 0

    def __hash__(self):
        return hash(id(self))

    def __eq__(self, other):
        return self is other


class ConnectedMineGroup:
    def __init__(self):
        self.relevant_cells: set[Cell] = set()
        self.subgroups_map: dict[Cell, set[MineGroup]] = defaultdict(set)
        self.num_groups = 0

    def add_group(self, group: MineGroup):
        if group.empty():
            return

        existing_group = self._is_subset_of_existing_group(group)
        if existing_group:
            new_group_1, new_group_2 = self._split_group(group, existing_group)
            self.delete_group(existing_group)
            self.add_group(new_group_1)
            self.add_group(new_group_2)
            return

        self.num_groups += 1
        for cell in group.cells:
            self.relevant_cells.add(cell)
            self.subgroups_map[cell].add(group)

    def delete_group(self, group: MineGroup):
        self.num_groups -= 1
        for cell in list(group.cells):
            self.subgroups_map[cell].discard(group)
            if not self.subgroups_map[cell]:
                self.relevant_cells.discard(cell)
                del self.subgroups_map[cell]

    def _is_subset_of_existing_group(self, group: MineGroup) -> Optional[MineGroup]:
        """Check if any existing subgroup has a subset/superset relationship with group."""
        for cell in group.cells:
            for existing in self.subgroups_map.get(cell, ()):
                if existing.cells < group.cells or group.cells < existing.cells:
                    return existing
        return None

    def _split_group(self, a: MineGroup, b: MineGroup) -> tuple[MineGroup, MineGroup]:
        """Given two groups where one is a subset of the other, return (subset, difference)."""
        if a.cells < b.cells:
            subset, superset = a, b
        else:
            subset, superset = b, a

        diff_cells = superset.cells - subset.cells
        diff_mines = superset.mines - subset.mines
        return (
            MineGroup(set(subset.cells), subset.mines),
            MineGroup(diff_cells, diff_mines),
        )

    def solve_groups(
        self, num_remaining_mines: int
    ) -> tuple[set[Cell], set[Cell], int, dict[Cell, float], int]:
        """Solve via backtracking over all valid mine permutations.

        For each subgroup, try every way to place its mines among its cells.
        Prune branches that contradict constraints from other groups sharing
        the same cells. Cells that are always safe or always mine across all
        valid permutations are definitively deduced.

        Returns (safe_cells, mine_cells, max_possible_mines_used, cell_probs,
        total_valid). cell_probs gives mine probability cell_mine_count/total_valid
        for every cell in the component (proven safe/mine cells overridden to
        exactly 0.0/1.0). total_valid is the number of valid permutations
        enumerated; 0 indicates contradictory constraints, in which case
        cell_probs is empty.
        """
        # Collect unique subgroups
        all_subgroups: list[MineGroup] = []
        seen: set[MineGroup] = set()
        for cell in list(self.relevant_cells):
            for g in self.subgroups_map.get(cell, ()):
                if g not in seen:
                    seen.add(g)
                    all_subgroups.append(g)

        if not all_subgroups:
            return set(), set(), 0, {}, 1

        # Phase 1: filter out trivial groups (all safe / all mines)
        safe_cells: set[Cell] = set()
        mine_cells: set[Cell] = set()
        backtrack_groups: list[MineGroup] = []

        for g in all_subgroups:
            if g.all_safe():
                safe_cells.update(g.cells)
            elif g.all_mines():
                mine_cells.update(g.cells)
            else:
                backtrack_groups.append(g)

        if not backtrack_groups:
            max_mines = len(mine_cells)
            cell_probs: dict[Cell, float] = {}
            for c in safe_cells:
                cell_probs[c] = 0.0
            for c in mine_cells:
                cell_probs[c] = 1.0
            return safe_cells, mine_cells, max_mines, cell_probs, 1

        # Phase 2: backtracking over non-trivial groups
        all_cells: set[Cell] = set()
        for g in backtrack_groups:
            all_cells.update(g.cells)

        # Pre-account for cells already determined by trivial groups
        preset: dict[Cell, bool] = {}
        for cell in mine_cells:
            if cell in all_cells:
                preset[cell] = True
        for cell in safe_cells:
            if cell in all_cells:
                preset[cell] = False

        cell_mine_count: dict[Cell, int] = defaultdict(int)
        cell_safe_count: dict[Cell, int] = defaultdict(int)
        max_mines_used = 0
        total_valid = 0

        def _generate_permutations(group: MineGroup, assignment: dict[Cell, bool]):
            """Yield all valid ways to assign mines within this group,
            respecting cells already assigned in `assignment`."""
            cells = sorted(group.cells)
            mines_needed = group.mines

            preset_mines = sum(1 for c in cells if assignment.get(c) is True)

            mines_left = mines_needed - preset_mines
            unassigned = [c for c in cells if c not in assignment]

            if mines_left < 0 or mines_left > len(unassigned):
                return  # impossible

            if not unassigned:
                if mines_left == 0:
                    yield {}
                return

            from itertools import combinations
            for combo in combinations(range(len(unassigned)), mines_left):
                mine_set = set(combo)
                perm = {}
                for i, cell in enumerate(unassigned):
                    perm[cell] = i in mine_set
                yield perm

        def backtrack(group_idx: int, assignment: dict[Cell, bool], mines_so_far: int):
            nonlocal max_mines_used, total_valid

            if group_idx == len(backtrack_groups):
                total_valid += 1
                max_mines_used = max(max_mines_used, mines_so_far)
                for cell in all_cells:
                    if assignment.get(cell, preset.get(cell, False)):
                        cell_mine_count[cell] += 1
                    else:
                        cell_safe_count[cell] += 1
                return

            group = backtrack_groups[group_idx]
            for perm in _generate_permutations(group, assignment):
                new_mines = sum(1 for v in perm.values() if v)
                if mines_so_far + new_mines > num_remaining_mines:
                    continue
                new_assignment = {**assignment, **perm}
                backtrack(group_idx + 1, new_assignment, mines_so_far + new_mines)

        backtrack(0, dict(preset), len(mine_cells))

        if total_valid > 0:
            for cell in all_cells:
                if cell in safe_cells or cell in mine_cells:
                    continue
                if cell_mine_count[cell] == total_valid:
                    mine_cells.add(cell)
                elif cell_safe_count[cell] == total_valid:
                    safe_cells.add(cell)

        cell_probs: dict[Cell, float] = {}
        if total_valid > 0:
            for cell in all_cells:
                if cell in safe_cells:
                    cell_probs[cell] = 0.0
                elif cell in mine_cells:
                    cell_probs[cell] = 1.0
                else:
                    cell_probs[cell] = cell_mine_count[cell] / total_valid

        return safe_cells, mine_cells, max_mines_used, cell_probs, total_valid

    def reassess_for_subsets(self):
        """Re-check subgroups for subset relationships and split one pair if found."""
        seen: set[MineGroup] = set()
        for cell in list(self.relevant_cells):
            for group in list(self.subgroups_map.get(cell, ())):
                if group in seen or group.empty():
                    continue
                seen.add(group)
                existing = self._is_subset_of_existing_group(group)
                if existing and existing is not group:
                    g1, g2 = self._split_group(group, existing)
                    self.delete_group(existing)
                    self.delete_group(group)
                    self.add_group(g1)
                    self.add_group(g2)
                    return

    def mark_safe(self, cell: Cell):
        for group in list(self.subgroups_map.get(cell, ())):
            group.mark_safe(cell)
            if group.empty():
                self.delete_group(group)
        self.subgroups_map.pop(cell, None)
        self.relevant_cells.discard(cell)

    def mark_mine(self, cell: Cell):
        for group in list(self.subgroups_map.get(cell, ())):
            group.mark_mine(cell)
            if group.empty():
                self.delete_group(group)
        self.subgroups_map.pop(cell, None)
        self.relevant_cells.discard(cell)

    def split_if_disjoint(self) -> list["ConnectedMineGroup"]:
        """Split this group into connected components if it has become disjoint."""
        if not self.relevant_cells:
            return []

        remaining = set(self.relevant_cells)
        components: list[ConnectedMineGroup] = []

        while remaining:
            start = next(iter(remaining))
            visited: set[Cell] = set()
            queue = deque([start])
            component_subgroups: set[MineGroup] = set()

            while queue:
                cell = queue.popleft()
                if cell in visited:
                    continue
                visited.add(cell)
                for subgroup in self.subgroups_map.get(cell, ()):
                    component_subgroups.add(subgroup)
                    for neighbor in subgroup.cells:
                        if neighbor not in visited and neighbor in remaining:
                            queue.append(neighbor)

            remaining -= visited

            if not components and not remaining:
                return [self]

            component = ConnectedMineGroup()
            component.relevant_cells = visited
            component.num_groups = len(component_subgroups)
            for cell in visited:
                component.subgroups_map[cell] = self.subgroups_map[cell]
            components.append(component)

        return components

    def is_empty(self) -> bool:
        return not self.num_groups

    def __hash__(self):
        return hash(id(self))

    def __eq__(self, other):
        return self is other


def merge_disjointed_connected_groups(groups: list[ConnectedMineGroup]) -> ConnectedMineGroup:
    merged = ConnectedMineGroup()
    for group in groups:
        merged.relevant_cells.update(group.relevant_cells)
        merged.num_groups += group.num_groups
        for cell, subgroups in group.subgroups_map.items():
            merged.subgroups_map[cell].update(subgroups)
    return merged


class Solver(ABC):
    """Abstract base class for minesweeper solvers.

    Subclasses maintain their own internal state (revealed cells, known mines,
    constraint groups). Each call to find_solved_squares is given the map of
    cells newly revealed since the previous call, and returns a SolverResult
    bundling newly-deduced safe cells, newly-deduced mine cells, and a per-cell
    mine probability snapshot for every currently-unknown cell.
    """

    def __init__(self, height: int, width: int, num_mines: int):
        self.height = height
        self.width = width
        self.num_mines = num_mines

    def _neighbors(self, r: int, c: int) -> list[Cell]:
        return [
            (r + dr, c + dc)
            for dr in range(-1, 2)
            for dc in range(-1, 2)
            if (dr != 0 or dc != 0) and 0 <= r + dr < self.height and 0 <= c + dc < self.width
        ]

    def _density_only_probs(
        self,
        revealed: set[Cell],
        known_mines: set[Cell],
        safe_cells: set[Cell],
    ) -> dict[Cell, float]:
        """Build a probability snapshot using only global mine density.

        Used by solver tiers (Basic, Subset) that don't decompose the fringe
        into constraint components. Cells in safe_cells are reported as 0.0,
        cells in known_mines are excluded from the key set, and every other
        unknown cell shares the global density (num_mines - len(known_mines))
        / unknown_count, clamped to [0, 1].
        """
        probs: dict[Cell, float] = {}
        unknown_cells: list[Cell] = []
        for r in range(self.height):
            for c in range(self.width):
                cell = (r, c)
                if cell in revealed or cell in known_mines:
                    continue
                unknown_cells.append(cell)

        if not unknown_cells:
            return probs

        remaining_mines = self.num_mines - len(known_mines)
        # Cells already proven safe contribute zero mines to the remaining
        # density, so subtract them from both numerator-context and the
        # divisor's "uncertain" pool.
        uncertain_count = len(unknown_cells) - len(safe_cells)
        if uncertain_count > 0:
            density = remaining_mines / uncertain_count
            density = max(0.0, min(1.0, density))
        else:
            density = 0.0

        for cell in unknown_cells:
            if cell in safe_cells:
                probs[cell] = 0.0
            else:
                probs[cell] = density
        return probs

    @abstractmethod
    def find_solved_squares(self, newly_revealed: dict[Cell, int]) -> SolverResult:
        """Given cells newly revealed since last call (cell -> adjacentMines),
        return a SolverResult with newly-deduced safe/mine cells and a
        per-cell mine probability snapshot for every currently-unknown cell."""
        ...
