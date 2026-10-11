import readcon


def test_missing_path_is_oserror():
    try:
        readcon.read_con("/nonexistent/readcon-missing.con")
    except OSError as exc:
        assert not isinstance(exc, readcon.ConError)
    else:
        raise AssertionError("missing path did not raise")


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
