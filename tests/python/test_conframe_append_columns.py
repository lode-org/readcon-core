"""Append and insert keep every per-atom column with its symbol."""

import readcon


def atom(symbol, x, y=0.0, z=0.0, **kwargs):
    return readcon.Atom(symbol=symbol, x=x, y=y, z=z, **kwargs)


def make_frame(*atoms):
    return readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=list(atoms),
    )


def round_trip(frame):
    text = readcon.write_con_string([frame], precision=17)
    return readcon.read_con_string(text)[0]


def columns(item):
    return (
        item.symbol,
        item.x,
        item.y,
        item.z,
        item.mass,
        tuple(item.fixed),
        item.atom_id,
        item.vx,
        item.vy,
        item.vz,
        item.fx,
        item.fy,
        item.fz,
    )


def assert_columns(frame, expected):
    assert [columns(item) for item in frame] == [columns(item) for item in expected]
    parsed = round_trip(frame)
    assert [columns(item) for item in parsed] == [columns(item) for item in expected]


def hydrogen(x, atom_id, fixed, vx, fx):
    return atom(
        "H",
        x,
        y=x + 0.5,
        z=x + 0.25,
        mass=1.0,
        atom_id=atom_id,
        fixed=fixed,
        vx=vx,
        vy=vx + 1.0,
        vz=vx + 2.0,
        fx=fx,
        fy=fx + 1.0,
        fz=fx + 2.0,
    )


def copper(x, atom_id, fixed, vx, fx):
    return atom(
        "Cu",
        x,
        y=x + 0.5,
        z=x + 0.25,
        mass=64.0,
        atom_id=atom_id,
        fixed=fixed,
        vx=vx,
        vy=vx + 1.0,
        vz=vx + 2.0,
        fx=fx,
        fy=fx + 1.0,
        fz=fx + 2.0,
    )


def helium(x, atom_id):
    return atom(
        "He",
        x,
        y=x + 0.5,
        z=x + 0.25,
        mass=4.0,
        atom_id=atom_id,
        fixed=[False, False, False],
        vx=8.0,
        vy=9.0,
        vz=10.0,
        fx=18.0,
        fy=19.0,
        fz=20.0,
    )


class TestAppendInsertColumns:
    def test_append_h_keeps_columns_with_the_symbol(self):
        first = hydrogen(0.0, 10, [True, False, False], 1.0, 10.0)
        metal = copper(1.0, 20, [False, True, False], 2.0, 20.0)
        added = hydrogen(2.0, 30, [False, False, True], 3.0, 30.0)
        frame = make_frame(first, metal)
        frame.append(added)
        assert_columns(frame, [first, added, metal])

    def test_insert_at_front_keeps_columns_with_the_symbol(self):
        first = hydrogen(0.0, 10, [True, False, False], 1.0, 10.0)
        metal = copper(1.0, 20, [False, True, False], 2.0, 20.0)
        noble = helium(3.0, 40)
        added = copper(4.0, 50, [True, True, False], 4.0, 40.0)
        frame = make_frame(first, metal, noble)
        frame.insert(0, added)
        # Cu is now the first symbol, so both copper atoms lead.
        assert_columns(frame, [added, metal, first, noble])

    def test_insert_in_the_middle_keeps_columns_with_the_symbol(self):
        first = hydrogen(0.0, 10, [True, False, False], 1.0, 10.0)
        noble = helium(3.0, 40)
        metal = copper(1.0, 20, [False, True, False], 2.0, 20.0)
        added = copper(4.0, 50, [True, True, False], 4.0, 40.0)
        frame = make_frame(first, noble, metal)
        frame.insert(1, added)
        # The inserted Cu joins the Cu group that follows He.
        assert_columns(frame, [first, added, metal, noble])

    def test_insert_at_end_keeps_columns_with_the_symbol(self):
        first = hydrogen(0.0, 10, [True, False, False], 1.0, 10.0)
        metal = copper(1.0, 20, [False, True, False], 2.0, 20.0)
        noble = helium(3.0, 40)
        added = hydrogen(2.0, 30, [False, False, True], 3.0, 30.0)
        frame = make_frame(first, metal, noble)
        frame.insert(len(frame), added)
        assert_columns(frame, [first, added, metal, noble])
