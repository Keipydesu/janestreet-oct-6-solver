"""The supplied puzzle. Coordinates in CLUES are one-based (row, column)."""
from model import GridState, Workspace

CLUES = {
    (1, 2): 8, (1, 3): 4, (1, 6): 11, (1, 10): 5,
    (2, 8): 11,
    (3, 3): 7, (3, 6): 1, (3, 11): 14,
    (4, 1): 28, (4, 4): 51, (4, 7): 1, (4, 9): 6,
    (5, 2): 22, (5, 9): 4, (5, 11): 1,
    (6, 4): 15, (6, 6): 10, (6, 8): 0,
    (7, 1): 11, (7, 3): 11, (7, 10): 9,
    (8, 3): 17, (8, 5): 14, (8, 8): 10, (8, 11): 13,
    (9, 1): 30, (9, 6): 6, (9, 9): 45,
    (10, 4): 10,
    (11, 2): 26, (11, 6): 0, (11, 9): 77, (11, 10): 61,
}

def new_workspace():
    state = GridState()
    for (row, col), value in CLUES.items():
        cell = state.grid[row-1][col-1]
        cell.starting_number = value
        if value == 0:
            cell.is_capital = True
            cell.capital_required = True
    return Workspace(state)
