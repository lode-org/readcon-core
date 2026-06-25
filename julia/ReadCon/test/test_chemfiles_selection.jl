# Chemfiles selection via shipped Julia wrappers (requires chemfiles-enabled libreadcon_core).
using Test
using ReadCon

@testset "chemfiles selection (optional)" begin
    if !has_chemfiles_support()
        @test_skip "libreadcon_core without chemfiles; skip selection parity"
        return
    end

    # atomic_number: H=1, O=8; fixed=false; no velocities
    atoms = [
        Atom(UInt64(1), 0.0, 1.0, 2.0, UInt64(0), 1.0, false, 0.0, 0.0, 0.0, false),
        Atom(UInt64(8), 1.0, 2.0, 3.0, UInt64(1), 16.0, false, 0.0, 0.0, 0.0, false),
        Atom(UInt64(8), 2.0, 3.0, 4.0, UInt64(2), 16.0, false, 0.0, 0.0, 0.0, false),
        Atom(UInt64(1), 3.0, 4.0, 5.0, UInt64(3), 1.0, false, 0.0, 0.0, 0.0, false),
    ]
    # After type group H,H,O,O: bonds in data order [[0,2],[2,3],[3,1]] for chemfiles 0-1,1-2,2-3
    bonds_json = """{"con_spec_version":2,"bonds":[[0,2],[2,3],[3,1]]}"""
    frame = ConFrame(
        (10.0, 10.0, 10.0),
        (90.0, 90.0, 90.0),
        atoms,
        false,
        ("", ""),
        ("", ""),
        false,
        false,
        UInt32(2),
        bonds_json,
        nothing,
        nothing,
        nothing,
        nothing,
        nothing,
        nothing,
    )

    @test frame_bond_count(frame) == 3

    r_bonds = select_on_frame(frame, "bonds: all")
    @test r_bonds.context_size == 2
    @test length(r_bonds.matches) == 3

    r_ang = select_on_frame(frame, "angles: all")
    @test r_ang.context_size == 3
    @test length(r_ang.matches) == 2

    r_dih = select_on_frame(frame, "dihedrals: all")
    @test r_dih.context_size == 4
    @test length(r_dih.matches) == 1

    r_filt = select_on_frame(frame, "bonds: name(#1) O and type(#2) H")
    @test length(r_filt.matches) == 2

    a = select_on_frame(frame, "two: type(#1) H and name(#2) O and is_bonded(#1, #2)")
    b = select_on_frame(frame, "bonds: type(#1) H and name(#2) O")
    @test length(a.matches) == length(b.matches)

    o_idxs = select_atom_indices(frame, "name O")
    @test o_idxs == [2, 3]
end
