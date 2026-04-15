"""Tests for the in-memory board cache used by `bots.tournament.run_tournament`."""

import random

from bots.tournament import _BoardCache


def test_cache_hit_reuses_board_for_disjoint_pair():
    cache = _BoardCache(random.Random(0))
    board1, start1 = cache.get_or_generate("beginner", "a", "b")
    board2, start2 = cache.get_or_generate("beginner", "c", "d")

    # Second matchup shares no bots with the first → cache hit, same board.
    assert board2 is board1
    assert start2 == start1


def test_cache_miss_when_either_bot_already_played():
    cache = _BoardCache(random.Random(0))
    board1, _ = cache.get_or_generate("beginner", "a", "b")
    # "a" has already played on board1, so a match involving "a" forces a new
    # board to be generated.
    board2, _ = cache.get_or_generate("beginner", "a", "c")

    assert board2 is not board1


def test_cache_keys_by_difficulty():
    cache = _BoardCache(random.Random(0))
    board_beg, _ = cache.get_or_generate("beginner", "a", "b")
    board_int, _ = cache.get_or_generate("intermediate", "a", "b")

    # Different difficulty buckets are independent, even for the same bot
    # pair: the intermediate lookup cannot reuse the beginner entry.
    assert board_int is not board_beg


def test_played_set_grows_on_hit():
    cache = _BoardCache(random.Random(0))
    cache.get_or_generate("beginner", "a", "b")
    cache.get_or_generate("beginner", "c", "d")

    entries = cache._by_difficulty["beginner"]  # noqa: SLF001 — internal test
    assert len(entries) == 1
    assert entries[0].played == {"a", "b", "c", "d"}
