from collections import defaultdict, deque
from typing import Optional

from config import ROWS, COLS, MINE_COUNT


class MineGroup:
    def __init__(self, cells: set[tuple[int, int]], mines: int):
        self.cells = cells
        self.mines = mines

    def mark_safe(self, cell: tuple[int, int]):
        if cell in self.cells:
            self.cells.remove(cell)

    def mark_mine(self, cell: tuple[int, int]):
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
        self.relevant_cells: set[tuple[int, int]] = set()
        self.subgroups_map = defaultdict(set)
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

    def solve_groups(self, num_remaining_mines: int) -> tuple[set[tuple[int, int]], set[tuple[int, int]], int]:
        """Solve via backtracking over all valid mine permutations.

        For each subgroup, try every way to place its mines among its cells.
        Prune branches that contradict constraints from other groups sharing
        the same cells. Cells that are always safe or always mine across all
        valid permutations are definitively deduced.

        Returns (safe_cells, mine_cells, max_possible_mines_used).
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
            return set(), set(), 0

        # Phase 1: filter out trivial groups (all safe / all mines)
        safe_cells: set[tuple[int, int]] = set()
        mine_cells: set[tuple[int, int]] = set()
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
            return safe_cells, mine_cells, max_mines

        # Phase 2: backtracking over non-trivial groups
        # For each cell, track how many mines are required by groups that
        # have already been assigned in the current trial.
        # cell_mine_status: cell -> True (mine), False (safe), or absent (unassigned)
        all_cells = set()
        for g in backtrack_groups:
            all_cells.update(g.cells)

        # Pre-account for cells already determined by trivial groups
        preset: dict[tuple[int, int], bool] = {}
        for cell in mine_cells:
            if cell in all_cells:
                preset[cell] = True
        for cell in safe_cells:
            if cell in all_cells:
                preset[cell] = False

        # Track: for each cell, how many valid permutations had it as mine vs safe
        cell_mine_count: dict[tuple[int, int], int] = defaultdict(int)
        cell_safe_count: dict[tuple[int, int], int] = defaultdict(int)
        max_mines_used = 0
        total_valid = 0

        def _generate_permutations(group: MineGroup, assignment: dict[tuple[int, int], bool]):
            """Yield all valid ways to assign mines within this group,
            respecting cells already assigned in `assignment`."""
            cells = sorted(group.cells)  # deterministic order
            mines_needed = group.mines

            # Count cells already assigned as mine/safe from prior groups
            preset_mines = sum(1 for c in cells if assignment.get(c) is True)
            preset_safe = sum(1 for c in cells if assignment.get(c) is False)

            mines_left = mines_needed - preset_mines
            unassigned = [c for c in cells if c not in assignment]

            if mines_left < 0 or mines_left > len(unassigned):
                return  # impossible

            if not unassigned:
                if mines_left == 0:
                    yield {}
                return

            # Generate combinations of `mines_left` mines among `unassigned`
            from itertools import combinations
            for combo in combinations(range(len(unassigned)), mines_left):
                mine_set = set(combo)
                perm = {}
                for i, cell in enumerate(unassigned):
                    perm[cell] = i in mine_set
                yield perm

        def backtrack(group_idx: int, assignment: dict[tuple[int, int], bool], mines_so_far: int):
            nonlocal max_mines_used, total_valid

            if group_idx == len(backtrack_groups):
                # Valid complete assignment — record it
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

        # max_mines_used accounts for trivially-determined mines too
        return safe_cells, mine_cells, max_mines_used

    def reassess_for_subsets(self):
        """Re-check subgroups for subset relationships and split one pair if found.

        Only needs to split one pair per call — add_group handles cascading splits,
        and the outer solving loop will call this again next iteration.
        """
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

    def mark_safe(self, cell: tuple[int, int]):
        for group in list(self.subgroups_map.get(cell, ())):
            group.mark_safe(cell)
            if group.empty():
                self.delete_group(group)
        # Clean up cell from tracking
        self.subgroups_map.pop(cell, None)
        self.relevant_cells.discard(cell)

    def mark_mine(self, cell: tuple[int, int]):
        for group in list(self.subgroups_map.get(cell, ())):
            group.mark_mine(cell)
            if group.empty():
                self.delete_group(group)
        # Clean up cell from tracking
        self.subgroups_map.pop(cell, None)
        self.relevant_cells.discard(cell)

    def split_if_disjoint(self) -> list["ConnectedMineGroup"]:
        """Split this group into connected components if it has become disjoint.

        Two cells are connected if they share at least one MineGroup.
        Returns a list of ConnectedMineGroups — just [self] if already connected.
        """
        if not self.relevant_cells:
            return []

        remaining = set(self.relevant_cells)
        components: list[ConnectedMineGroup] = []

        while remaining:
            # BFS from an arbitrary cell
            start = next(iter(remaining))
            visited: set[tuple[int, int]] = set()
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
                # Only one component — it's the whole group, no split needed
                return [self]

            # Build a new ConnectedMineGroup for this component
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


def _merge_disjointed_connected_groups(groups: list[ConnectedMineGroup]) -> ConnectedMineGroup:
    merged = ConnectedMineGroup()
    for group in groups:
        merged.relevant_cells.update(group.relevant_cells)
        merged.num_groups += group.num_groups
        for cell, subgroups in group.subgroups_map.items():
            merged.subgroups_map[cell].update(subgroups)

    return merged


def _neighbors(r: int, c: int) -> list[tuple[int, int]]:
    return [
        (r + dr, c + dc)
        for dr in range(-1, 2)
        for dc in range(-1, 2)
        if (dr != 0 or dc != 0) and 0 <= r + dr < ROWS and 0 <= c + dc < COLS
    ]


def is_solvable(board: list[list[dict]], start_row: int, start_col: int) -> bool:
    """Check if a board can be solved without guessing.

    Uses constraint propagation with subset analysis:
    1. Basic rules: trivial mine/safe deductions from single cells
    2. Subset rule: if constraint A's unknowns are a subset of B's,
       the difference cells have exactly (B.mines_remaining - A.mines_remaining) mines.
    """
    state = [["unknown"] * COLS for _ in range(ROWS)]
    total_safe = ROWS * COLS - MINE_COUNT
    revealed_count = 0
    remaining_mines = MINE_COUNT

    connected_groups: dict[tuple[int, int], ConnectedMineGroup] = {}  # cell -> ConnectedMineGroup it belongs to
    all_groups: set[ConnectedMineGroup] = set()  # set of all ConnectedMineGroups for easy iteration

    tiles_without_information = set((r, c) for r in range(ROWS) for c in range(COLS))

    def reveal_single(r, c):
        nonlocal revealed_count
        if state[r][c] != "unknown":
            return
        state[r][c] = board[r][c]["adjacentMines"]
        tiles_without_information.discard((r, c))
        revealed_count += 1
        if (r, c) in connected_groups:
            connected_groups[(r, c)].mark_safe((r, c))

    def reveal(r, c):
        """Reveal a cell and flood-fill if zero. Returns list of newly revealed cells."""
        q = deque([(r, c)])
        revealed = []
        while q:
            rr, cc = q.popleft()
            if state[rr][cc] != "unknown":
                continue
            reveal_single(rr, cc)
            revealed.append((rr, cc))
            if board[rr][cc]["adjacentMines"] == 0:
                for nr, nc in _neighbors(rr, cc):
                    if state[nr][nc] == "unknown":
                        q.append((nr, nc))
        return revealed

    def mark_mine(r, c):
        nonlocal remaining_mines
        tiles_without_information.discard((r, c))
        state[r][c] = "mine"
        remaining_mines -= 1
        if (r, c) in connected_groups:
            connected_groups[(r, c)].mark_mine((r, c))

    # Initial reveal from starting square
    revealed = reveal(start_row, start_col)

    # Main solving loop
    while revealed:
        # Remove empty connected groups
        all_groups = {g for g in all_groups if not g.is_empty()}

        # Optimize subgroups
        for group in list(all_groups):
            group.reassess_for_subsets()

        # Update connected groups with constraints from newly revealed cells
        for r, c in revealed:
            if state[r][c] == 0:
                continue

            unknown_neighbors = set((nr, nc) for nr, nc in _neighbors(r, c) if state[nr][nc] == "unknown")
            if not unknown_neighbors:
                continue

            for nr, nc in unknown_neighbors:
                tiles_without_information.discard((nr, nc))
            mine_count = sum(1 for nr, nc in _neighbors(r, c) if state[nr][nc] == "mine")
            mine_group = MineGroup(unknown_neighbors, state[r][c] - mine_count)

            # Deduplicate: multiple unknown neighbors may share the same ConnectedMineGroup
            relevant_connected_groups = list({
                connected_groups[cell] for cell in unknown_neighbors if cell in connected_groups
            })

            if not relevant_connected_groups:
                new_group = ConnectedMineGroup()
                new_group.add_group(mine_group)
                for cell in unknown_neighbors:
                    connected_groups[cell] = new_group
                all_groups.add(new_group)
            elif len(relevant_connected_groups) == 1:
                relevant_connected_groups[0].add_group(mine_group)
                for cell in unknown_neighbors:
                    connected_groups[cell] = relevant_connected_groups[0]
            else:
                merged_group = _merge_disjointed_connected_groups(relevant_connected_groups)
                merged_group.add_group(mine_group)
                for cell in merged_group.relevant_cells:
                    connected_groups[cell] = merged_group
                all_groups.add(merged_group)
                for group in relevant_connected_groups:
                    all_groups.discard(group)

        # Split any connected groups that have become disjoint
        new_all_groups: set[ConnectedMineGroup] = set()
        for group in all_groups:
            for component in group.split_if_disjoint():
                new_all_groups.add(component)
                for cell in component.relevant_cells:
                    connected_groups[cell] = component
        all_groups = new_all_groups

        # Solve groups to find new safe/mine cells
        # TODO: Consider more correct solution of tracking all possible number of mines used by each group
        #  then filtering out any group permutations that contradict the global remaining mines count.
        to_reveal: set[tuple[int, int]] = set()
        to_mark_mine: set[tuple[int, int]] = set()
        max_mines_used = 0
        for group in all_groups:
            safe_cells, mine_cells, max_mines_used_group = group.solve_groups(remaining_mines)
            to_reveal.update(safe_cells)
            to_mark_mine.update(mine_cells)
            max_mines_used += max_mines_used_group

        min_mines_remaining = remaining_mines - max_mines_used
        if min_mines_remaining == len(tiles_without_information):
            to_mark_mine.update(tiles_without_information)

        for r, c in to_mark_mine:
            mark_mine(r, c)

        all_revealed: set[tuple[int, int]] = set()
        for r, c in to_reveal:
            all_revealed.update(reveal(r, c))

        revealed = list(all_revealed)

    return revealed_count == total_safe
