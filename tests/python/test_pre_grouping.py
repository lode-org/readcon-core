"""pre_grouping_indices restores pre-grouping order from column-5 ids."""

import readcon


def test_unique_ids_sort_ascending():
    assert readcon.pre_grouping_indices([2, 0, 1]) == [1, 2, 0]


def test_repeated_ids_keep_input_order():
    assert readcon.pre_grouping_indices([1, 1, 0]) == [0, 1, 2]


def test_empty_ids():
    assert readcon.pre_grouping_indices([]) == []
