import readcon


def test_missing_path_is_oserror():
    try:
        readcon.read_con("/nonexistent/readcon-missing.con")
    except OSError as exc:
        assert not isinstance(exc, readcon.ConError)
    else:
        raise AssertionError("missing path did not raise")


def test_non_utf8_path_is_oserror(tmp_path):
    # Under 64 KiB, read_to_string already fails as OSError. The mmap path
    # is the one that used to surface as InvalidNumberFormat.
    path = tmp_path / "bad.con"
    path.write_bytes(b"\xff" * (64 * 1024))
    name = str(path)
    openers = (
        lambda: readcon.read_con(name),
        lambda: readcon.read_first_frame(name),
        lambda: readcon.read_nth_frame(name, 3),
        lambda: readcon.read_all_frames(name),
        lambda: readcon.iter_con(name),
        lambda: readcon.count_frames(name),
    )
    for opener in openers:
        try:
            opener()
        except OSError as exc:
            assert not isinstance(exc, readcon.ConError)
            assert not isinstance(exc, readcon.InvalidNumberFormat)
        else:
            raise AssertionError("non-utf8 file did not raise")


def _good_frame():
    return (
        "seed\n"
        '{"con_spec_version":2}\n'
        "10 10 10\n"
        "90 90 90\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        "1\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0 0 0 0 0\n"
    )


def _bad_count_frame():
    return (
        "seed\n"
        '{"con_spec_version":2}\n'
        "10 10 10\n"
        "90 90 90\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        "-1\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0 0 0 0 0\n"
    )


def _later_frame_path(tmp_path):
    path = tmp_path / "later-frame.con"
    path.write_text(_good_frame() + _bad_count_frame())
    return str(path)


def _assert_later_invalid_count(exc):
    # Line 8 of frame 1 is file line 20.
    assert isinstance(exc, readcon.InvalidCount)
    assert isinstance(exc, readcon.ConError)
    assert exc.line == 20
    assert exc.frame_index == 1


def test_streaming_iterator_locates_the_later_frame(tmp_path):
    path = _later_frame_path(tmp_path)

    iterator = readcon.iter_con(path)
    next(iterator)
    try:
        next(iterator)
    except readcon.InvalidCount as exc:
        _assert_later_invalid_count(exc)
    else:
        raise AssertionError("next accepted the bad second frame")

    iterator = readcon.iter_con(path)
    assert iterator.forward() is True
    try:
        iterator.forward()
    except readcon.InvalidCount as exc:
        _assert_later_invalid_count(exc)
    else:
        raise AssertionError("forward accepted the bad second frame")

    iterator = readcon.iter_con(path)
    try:
        iterator.skip(3)
    except readcon.InvalidCount as exc:
        _assert_later_invalid_count(exc)
    else:
        raise AssertionError("skip accepted the bad second frame")


def test_count_frames_locates_the_later_frame(tmp_path):
    path = _later_frame_path(tmp_path)
    try:
        readcon.count_frames(path)
    except readcon.InvalidCount as exc:
        _assert_later_invalid_count(exc)
    else:
        raise AssertionError("count_frames accepted the bad second frame")


def test_non_finite_is_a_con_error_with_a_line():
    text = (
        "seed\n"
        '{"con_spec_version":2}\n'
        "10 10 10\n"
        "90 90 90\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        "1\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "nan 0 0 0 0\n"
    )
    try:
        readcon.read_con_string(text)
    except readcon.NonFiniteValue as exc:
        assert exc.line == 12
        assert exc.frame_index == 0
        assert isinstance(exc, readcon.ConError)
        assert isinstance(exc, ValueError)
    else:
        raise AssertionError("nan was accepted")
