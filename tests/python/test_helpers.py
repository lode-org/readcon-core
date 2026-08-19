"""Symbol <-> Z helpers: H..U (Z = 92), D/T, and sentinels."""

import readcon


class TestSymbolToAtomicNumber:
    def test_known_elements(self):
        assert readcon.symbol_to_atomic_number("H") == 1
        assert readcon.symbol_to_atomic_number("He") == 2
        assert readcon.symbol_to_atomic_number("O") == 8
        assert readcon.symbol_to_atomic_number("Fe") == 26
        assert readcon.symbol_to_atomic_number("U") == 92

    def test_hydrogen_isotopes_map_to_z_one(self):
        assert readcon.symbol_to_atomic_number("D") == 1
        assert readcon.symbol_to_atomic_number("T") == 1

    def test_unknown_and_above_ceiling_return_zero(self):
        assert readcon.symbol_to_atomic_number("") == 0
        assert readcon.symbol_to_atomic_number("Xx") == 0
        assert readcon.symbol_to_atomic_number("h") == 0
        assert readcon.symbol_to_atomic_number("Np") == 0
        assert readcon.symbol_to_atomic_number("Og") == 0
        assert readcon.symbol_to_atomic_number("Gh") == 0
        assert readcon.symbol_to_atomic_number("Dum") == 0

    def test_round_trip_one_through_ceiling(self):
        for z in range(1, 93):
            symbol = readcon.atomic_number_to_symbol(z)
            assert readcon.symbol_to_atomic_number(symbol) == z


class TestAtomicNumberToSymbol:
    def test_known_z(self):
        assert readcon.atomic_number_to_symbol(1) == "H"
        assert readcon.atomic_number_to_symbol(8) == "O"
        assert readcon.atomic_number_to_symbol(92) == "U"

    def test_z_one_is_canonical_h_not_isotope(self):
        assert readcon.atomic_number_to_symbol(1) == "H"
        assert readcon.atomic_number_to_symbol(1) != "D"
        assert readcon.atomic_number_to_symbol(1) != "T"

    def test_sentinels_outside_ceiling(self):
        assert readcon.atomic_number_to_symbol(0) == "X"
        assert readcon.atomic_number_to_symbol(93) == "X"
        assert readcon.atomic_number_to_symbol(118) == "X"
        assert readcon.atomic_number_to_symbol(2**64 - 1) == "X"


class TestHelperDocstrings:
    def test_docstrings_name_ceiling_isotopes_sentinels(self):
        fwd = readcon.symbol_to_atomic_number.__doc__
        rev = readcon.atomic_number_to_symbol.__doc__
        assert fwd is not None
        assert rev is not None
        for doc in (fwd, rev):
            assert "Z = 92" in doc
            assert "``D``" in doc
            assert "``T``" in doc
        assert "sentinel 0" in fwd
        assert "sentinel ``X``" in rev
        assert "standard-mass" in fwd
        assert "standard-mass" in rev


class TestBuilderMassMismatch:
    def test_write_raises_on_same_symbol_mass_disagreement(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[
                readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0, mass=1.008, atom_id=0),
                readcon.Atom(symbol="H", x=1.0, y=0.0, z=0.0, mass=2.014, atom_id=1),
            ],
        )
        try:
            readcon.write_con_string([frame])
        except ValueError as exc:
            assert "inconsistent masses" in str(exc)
        else:
            raise AssertionError("expected ValueError on same-symbol mass mismatch")
