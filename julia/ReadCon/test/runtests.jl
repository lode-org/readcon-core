using Test
using ReadCon

const TEST_DIR = joinpath(dirname(dirname(dirname(@__DIR__))), "resources", "test")

function read_tiny_con_with_metadata(metadata_json::String)
    contents = read(joinpath(TEST_DIR, "tiny_cuh2.con"), String)
    lines = split(contents, '\n'; keepempty=true)
    lines[2] = metadata_json

    mktemp() do path, io
        write(io, join(lines, "\n"))
        close(io)
        return read_con(path)
    end
end

@testset "ReadCon.jl" begin
    @testset "C ABI mirror" begin
        @test fieldnames(ReadCon.CAtom) == (
            :atomic_number, :x, :y, :z, :atom_id, :mass,
            :is_fixed, :fixed_x, :fixed_y, :fixed_z,
            :vx, :vy, :vz, :has_velocity,
            :fx, :fy, :fz, :has_forces,
            :energy, :has_energy,
        )
        @test fieldnames(ReadCon.CFrame) == (
            :atoms, :num_atoms, :cell, :angles,
            :has_velocities, :has_forces, :has_energies,
        )
    end

    @testset "Read .con file" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))
        @test length(frames) == 1
        frame = frames[1]
        @test frame.cell[1] ≈ 15.3456 atol=1e-4
        @test frame.angles[1] ≈ 90.0
        @test length(frame.atoms) == 4
        @test !frame.has_velocities
    end

    @testset "Read multi-frame .con" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_multi_cuh2.con"))
        @test length(frames) == 2
        @test length(frames[1].atoms) == 4
        @test length(frames[2].atoms) == 4
    end

    @testset "Read .convel file" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.convel"))
        @test length(frames) == 1
        frame = frames[1]
        @test frame.has_velocities
        atom = frame.atoms[1]
        @test atom.has_velocity
        @test atom.vx ≈ 0.001234 atol=1e-6
    end

    @testset "Read force section" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2_forces.con"))
        @test length(frames) == 1
        frame = frames[1]
        @test frame.has_forces
        @test frame.spec_version == 2
        @test frame.energy ≈ -42.5
        @test occursin("\"energy\":-42.5", frame.metadata_json)
        @test occursin("\"potential\"", frame.metadata_json)
        atom = frame.atoms[1]
        @test atom.has_forces
        @test atom.fixed == (true, true, true)
        @test atom.fx ≈ 0.123456 atol=1e-6
        @test atom.fy ≈ 0.234567 atol=1e-6
        @test atom.fz ≈ -0.345678 atol=1e-6
    end

    @testset "Metadata helpers" begin
        frames = read_tiny_con_with_metadata(
            "{\"con_spec_version\":2,\"frame_index\":7,\"time\":3.5,\"timestep\":0.2,\"neb_bead\":4,\"neb_band\":2,\"energy\":-1.25}"
        )
        frame = frames[1]

        @test frame.spec_version == 2
        @test frame.metadata_json isa String
        @test occursin("\"con_spec_version\":2", frame.metadata_json)
        @test frame.energy ≈ -1.25
        @test frame.frame_index == 7
        @test frame.time ≈ 3.5
        @test frame.timestep ≈ 0.2
        @test frame.neb_bead == 4
        @test frame.neb_band == 2

        plain = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))[1]
        @test plain.spec_version == 2
        @test isnothing(plain.energy)
        @test isnothing(plain.frame_index)
        @test isnothing(plain.time)
        @test isnothing(plain.timestep)
        @test isnothing(plain.neb_bead)
        @test isnothing(plain.neb_band)
    end

    @testset "Read multi-frame .convel" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_multi_cuh2.convel"))
        @test length(frames) == 2
        @test frames[1].has_velocities
        @test frames[2].has_velocities
    end

    @testset "Error handling" begin
        @test_throws ReadCon.ReadConError read_con("/nonexistent/path.con")
    end

    @testset "v3.0 velocity rewrite stamps natural time" begin
        natural = "(amu*angstrom^2/eV)^0.5"
        function velocity_frame(metadata_line::String)
            lines = [
                "seed",
                metadata_line,
                "10 10 10",
                "90 90 90",
                "0 0",
                "0 0 0",
                "1",
                "1",
                "1.0",
                "H",
                "Coordinates of Component 1",
                "0 0 0 0 0",
                "",
                "H",
                "Velocities of Component 1",
                "0.1 0.2 0.3 0 0",
            ]
            return join(lines, '\n') * "\n"
        end
        function round_trip(metadata_line::String)
            mktemp() do src, io
                write(io, velocity_frame(metadata_line))
                close(io)
                frames = read_con(src)
                mktemp() do dst, out
                    close(out)
                    write_con(dst, frames)
                    return (read(dst, String), read_con(dst))
                end
            end
        end

        missing = "{\"con_spec_version\":3,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}"
        written, reread = round_trip(missing)
        @test occursin("\"time\":\"$natural\"", written)
        @test occursin("\"con_spec_minor\":1", written)
        @test reread[1].atoms[1].vx ≈ 0.1

        labelled = "{\"con_spec_version\":3,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
        written_fs, reread_fs = round_trip(labelled)
        @test occursin("\"time\":\"$natural\"", written_fs)
        @test !occursin("\"time\":\"fs\"", written_fs)
        @test reread_fs[1].atoms[1].vx ≈ 0.1

        minor0 = "{\"con_spec_version\":3,\"con_spec_minor\":0,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
        written0, reread0 = round_trip(minor0)
        @test occursin("\"time\":\"$natural\"", written0)
        @test occursin("\"con_spec_minor\":1", written0)
        @test !occursin("\"con_spec_minor\":0", written0)
        @test reread0[1].atoms[1].vx ≈ 0.1

        minor1 = "{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
        written_minor, _ = round_trip(minor1)
        @test occursin("\"time\":\"fs\"", written_minor)
        @test !occursin(natural, written_minor)

        # A multi-byte unit label is inside the units object. The scan must
        # step by character, not by byte, or rewriting the time label throws.
        angstrom = "{\"con_spec_version\":3,\"units\":{\"length\":\"Å\",\"energy\":\"eV\"}}"
        written_ang, reread_ang = round_trip(angstrom)
        @test occursin("\"time\":\"$natural\"", written_ang)
        @test occursin("\"length\":\"angstrom\"", written_ang)
        @test reread_ang[1].atoms[1].vx ≈ 0.1
    end

    @testset "Header strings" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))
        @test frames[1].prebox_header[1] == "Random Number Seed"
        @test frames[1].prebox_header[2] == "{\"con_spec_version\":2}"
    end

    @testset "Write frames read from CON" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2_forces.con"))

        mktemp() do path, io
            close(io)
            write_con(path, frames)
            reread = read_con(path)

            @test length(reread) == 1
            @test reread[1].has_forces
            @test reread[1].energy ≈ -42.5
            @test reread[1].atoms[1].fx ≈ frames[1].atoms[1].fx
        end
    end

    @testset "Write Julia-constructed frames through builder FFI" begin
        atom = Atom(
            UInt64(29),
            1.0, 2.0, 3.0,
            UInt64(7), 63.546,
            true,
            (true, false, true),
            0.1, 0.2, 0.3,
            true,
            -0.1, -0.2, -0.3,
            true,
        )
        frame = ConFrame(
            (10.0, 10.0, 10.0),
            (90.0, 90.0, 90.0),
            [atom],
            true,
            ("", ""),
            ("", ""),
            true,
        )

        mktemp() do path, io
            close(io)
            write_con(path, [frame]; precision=8)
            reread = read_con(path)

            @test length(reread) == 1
            @test reread[1].has_velocities
            @test reread[1].has_forces
            @test reread[1].atoms[1].fixed == (true, false, true)
            @test reread[1].atoms[1].atom_id == 7
            @test reread[1].atoms[1].vx ≈ 0.1
            @test reread[1].atoms[1].fx ≈ -0.1
        end
    end

    @testset "Non-finite cell in a constructor" begin
        atom = Atom(
            UInt64(29), 1.0, 2.0, 3.0, UInt64(0), 63.546,
            false, (false, false, false),
            0.0, 0.0, 0.0, false,
            0.0, 0.0, 0.0, false,
        )
        finite_cell = (10.0, 11.0, 12.0)
        finite_angles = (90.0, 91.0, 92.0)
        constructors = [
            (cell, angles) -> ConFrame(cell, angles, [atom], false, ("", ""), ("", "")),
            (cell, angles) -> ConFrame(cell, angles, [atom], false, ("", ""), ("", ""), false),
            (cell, angles) -> ConFrame(
                cell, angles, [atom], false, ("", ""), ("", ""), false, false,
                UInt32(2), "", nothing, nothing, nothing, nothing, nothing, nothing,
            ),
        ]
        for make in constructors, (name, slot) in [("cell", 1), ("cell", 2), ("cell", 3),
                                                  ("angles", 1), ("angles", 2), ("angles", 3)],
            value in (NaN, Inf, -Inf)

            cell = collect(finite_cell)
            angles = collect(finite_angles)
            (name == "cell" ? cell : angles)[slot] = value
            err = try
                make(Tuple(cell), Tuple(angles))
                nothing
            catch e
                e
            end
            @test err isa NonFiniteValue
            @test err.field == "$name[$slot]"
            @test isequal(err.value, value)
            @test sprint(showerror, err) ==
                  "NonFiniteValue: non-finite value: cell field $name[$slot] is $value"
        end
        for make in constructors
            frame = make(finite_cell, finite_angles)
            @test frame.cell == finite_cell
            @test frame.angles == finite_angles
        end

        frame = constructors[2](finite_cell, finite_angles)
        mktemp() do path, io
            close(io)
            write_con(path, [frame, frame])
            reread = read_con(path)
            @test length(reread) == 2
            @test reread[2].cell == finite_cell
            @test reread[2].angles == finite_angles
        end
    end

    @testset "Non-finite value in a file" begin
        text = read(joinpath(TEST_DIR, "tiny_multi_cuh2.con"), String)
        lines = split(text, '\n'; keepempty=true)
        frame_starts = findall(==("Random Number Seed"), lines)
        @test length(frame_starts) >= 2
        second = frame_starts[2]
        box_line = second + 2
        angle_line = second + 3
        first_atom = second + 11
        @test startswith(lines[box_line], "15.3456")
        @test startswith(lines[angle_line], "90.0")
        @test startswith(strip(lines[first_atom]), "0.6394")
        cases = []
        for token in ("NaN", "inf", "-inf"), slot in 1:3
            push!(cases, (box_line, slot, token, "cell field boxl[$(slot - 1)] of frame 1 is $token"))
            push!(cases, (angle_line, slot, token, "cell field angles[$(slot - 1)] of frame 1 is $token"))
            push!(cases, (first_atom, slot, token, "non-finite value: $token"))
        end
        for (line, slot, token, expected) in cases
            bad = copy(lines)
            fields = split(strip(bad[line]))
            fields[slot] = token
            bad[line] = join(fields, " ")
            mktemp() do path, io
                close(io)
                write(path, join(bad, "\n"))
                # read_con keeps its contract: a frame that fails to parse ends the
                # read, the frames before it are returned, and the error stays on the
                # C channel.
                ReadCon.clear_error()
                frames = read_con(path)
                @test length(frames) == 1
                err = ReadCon.last_error()
                @test err !== nothing
                @test err.code == Int32(-14)
                @test err.frame_index == 1
                @test occursin("NonFiniteValue", err.message)
                @test occursin(expected, err.message)
            end
        end
    end

    @testset "Campaign index projection" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))
        frame = frames[1]
        @test index_natoms(frame) == UInt32(length(frame.atoms))
        form = composition_formula(frame)
        @test occursin(":", form)
        @test occursin("|", form) || !occursin("H", form)  # multiset has | when multi-species
        @test !isempty(form)
        @test total_mass(frame) isa Union{Nothing,Float64}
        @test total_mass(frame) !== nothing
        @test cell_volume(frame) !== nothing
        j = index_projection_json(frame)
        @test occursin("\"formula\"", j)
        @test occursin(form, j) || occursin(replace(form, ":" => "\\:"), j)
        # forces fixture
        ff = read_con(joinpath(TEST_DIR, "tiny_cuh2_forces.con"))[1]
        @test sections_mask(ff) != 0x00 || ff.has_forces
        @test fmax(ff) !== nothing || !ff.has_forces
        ie = index_energy(ff)
        @test ie === nothing || ie isa Float64
    end

    @testset "Helpers and matrices" begin
        frames = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))
        frame = frames[1]
        @test has_chemfiles_support() isa Bool
        @test atom_index_by_id(frame, frame.atoms[1].atom_id) isa Union{Int, Nothing}
        @test atom_index_by_id(frame, typemax(UInt64)) === nothing
        idx = build_atom_id_index(frame)
        @test idx isa Dict
        @test !isempty(idx)
        P = ReadCon.positions_matrix(frame)
        @test size(P, 1) == 3 || size(P, 2) == 3
        M = ReadCon.masses_vector(frame)
        @test length(M) == length(frame.atoms)
        # forces / velocities section matrices
        ff = read_con(joinpath(TEST_DIR, "tiny_cuh2_forces.con"))[1]
        F = ReadCon.forces_matrix(ff)
        @test size(F, 1) == 3 || size(F, 2) == 3
        @test frame_bond_count(ff) isa Integer
        vf = read_con(joinpath(TEST_DIR, "tiny_cuh2.convel"))[1]
        V = ReadCon.velocities_matrix(vf)
        @test size(V, 1) == 3 || size(V, 2) == 3
        allf = ReadCon.read_all_frames(joinpath(TEST_DIR, "tiny_multi_cuh2.con"))
        @test length(allf) == 2
    end

    @testset "Chemfiles selection when enabled" begin
        if has_chemfiles_support()
            frame = read_con(joinpath(TEST_DIR, "tiny_cuh2.con"))[1]
            sel = select_on_frame(frame, "all")
            @test haskey(sel, :matches) || haskey(sel, :context_size) || sel isa NamedTuple
            idxs = select_atom_indices(frame, "all")
            @test idxs isa AbstractVector
            @test !isempty(idxs)
        else
            @test_skip "chemfiles not linked"
        end
    end

    @testset "Atom constructors" begin
        a1 = Atom(UInt64(8), 0.0, 0.0, 0.0, UInt64(0), 15.999, false, 0.0, 0.0, 0.0, false)
        @test a1.atomic_number == 8
        a2 = Atom(
            UInt64(1), 1.0, 0.0, 0.0, UInt64(1), 1.008, true, (true, false, false),
            0.1, 0.0, 0.0, true, 0.0, 0.1, 0.0, true,
        )
        @test a2.has_velocity && a2.has_forces
        a3 = Atom(
            UInt64(1), 1.0, 0.0, 0.0, UInt64(1), 1.008, false, (false, false, false),
            0.0, 0.0, 0.0, false, 0.0, 0.0, 0.0, false, -0.5, true,
        )
        @test a3.has_energy
    end

    @testset "huge con_spec_minor saturates and duplicate keys are rejected" begin
        two64 = "18446744073709551616"
        forty = "1000000000000000000000000000000000000007"
        three_hundred = "1" * "0"^298 * "7"
        four_hundred = "1" * "0"^398 * "7"
        natural = "(amu*angstrom^2/eV)^0.5"

        @test ReadCon._json_u64("{\"con_spec_minor\":7}", "con_spec_minor") == UInt64(7)
        @test ReadCon._json_u64("{}", "con_spec_minor") == UInt64(0)
        @test ReadCon._json_u64("{\"con_spec_minor\":$two64}", "con_spec_minor") == typemax(UInt64)
        @test ReadCon._json_u64("{\"con_spec_minor\":$forty}", "con_spec_minor") == typemax(UInt64)
        @test ReadCon._json_u64(
            "{\"con_spec_minor\":$three_hundred}", "con_spec_minor",
        ) == typemax(UInt64)
        # An integer that neither fits in UInt64 nor parses as a finite Float64 stays 0.
        @test ReadCon._json_u64(
            "{\"con_spec_minor\":$four_hundred}", "con_spec_minor",
        ) == UInt64(0)
        # floor(f64::MAX) = (2^53 - 1) * 2^971. serde_json accepts integers
        # through one less than the half-ULP step and rejects the next one.
        fmax = (BigInt(2)^53 - 1) << 971
        plus1 = string(fmax + 1)
        last_finite = string(fmax + (BigInt(2)^970) - 1)
        overflow = string(fmax + BigInt(2)^970)
        @test ReadCon._json_u64(
            "{\"con_spec_minor\":$plus1}", "con_spec_minor",
        ) == typemax(UInt64)
        @test ReadCon._json_u64(
            "{\"con_spec_minor\":$last_finite}", "con_spec_minor",
        ) == typemax(UInt64)
        @test ReadCon._json_u64(
            "{\"con_spec_minor\":$overflow}", "con_spec_minor",
        ) == UInt64(0)
        # Nested key is the first literal match when the top-level token is in range.
        @test ReadCon._json_u64(
            "{\"x\":{\"con_spec_minor\":2},\"con_spec_minor\":0}", "con_spec_minor",
        ) == UInt64(2)
        # A substitutable huge top-level token saturates even if a nested key is earlier.
        @test ReadCon._json_u64(
            "{\"x\":{\"con_spec_minor\":2},\"con_spec_minor\":$two64}", "con_spec_minor",
        ) == typemax(UInt64)
        @test ReadCon._json_u64(
            "{\"\\u0063on_spec_minor\":$two64}", "con_spec_minor",
        ) == typemax(UInt64)
        @test_throws ErrorException(ReadCon._DUPLICATE_CON_SPEC_MINOR) ReadCon._json_u64(
            "{\"con_spec_minor\":0,\"con_spec_minor\":1}", "con_spec_minor",
        )
        @test_throws ErrorException(ReadCon._DUPLICATE_CON_SPEC_MINOR) ReadCon._json_u64(
            "{\"con_spec_minor\":1,\"\\u0063on_spec_minor\":2}", "con_spec_minor",
        )

        function velocity_text(metadata_line::String)
            lines = [
                "seed",
                metadata_line,
                "10 10 10",
                "90 90 90",
                "0 0",
                "0 0 0",
                "1",
                "1",
                "1.0",
                "H",
                "Coordinates of Component 1",
                "0 0 0 0 0",
                "",
                "H",
                "Velocities of Component 1",
                "0.1 0.2 0.3 0 0",
            ]
            return join(lines, '\n') * "\n"
        end
        function round_trip(metadata_line::String)
            mktemp() do src, io
                write(io, velocity_text(metadata_line))
                close(io)
                frames = read_con(src)
                mktemp() do dst, out
                    close(out)
                    write_con(dst, frames)
                    return read(dst, String)
                end
            end
        end

        huge_meta = "{\"con_spec_version\":3,\"con_spec_minor\":$two64,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
        written = round_trip(huge_meta)
        @test occursin("\"con_spec_minor\":$two64", written)
        @test occursin("\"time\":\"fs\"", written)
        @test !occursin(natural, written)

        for digits in (plus1, last_finite)
            with_time = "{\"con_spec_version\":3,\"con_spec_minor\":$digits,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
            written = round_trip(with_time)
            @test occursin("\"con_spec_minor\":$digits", written)
            @test occursin("\"time\":\"fs\"", written)
            @test !occursin(natural, written)

            no_time = "{\"con_spec_version\":3,\"con_spec_minor\":$digits,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}"
            frames = mktemp() do src, io
                write(io, velocity_text(no_time))
                close(io)
                read_con(src)
            end
            @test isempty(frames)
            err = ReadCon.last_error()
            @test occursin("InvalidUnits", err.message)
            @test occursin("units.time", err.message)
        end
        frames = mktemp() do src, io
            over = "{\"con_spec_version\":3,\"con_spec_minor\":$overflow,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
            write(io, velocity_text(over))
            close(io)
            read_con(src)
        end
        @test isempty(frames)
        over_err = ReadCon.last_error()
        @test occursin("number out of range", over_err.message)

        atom = Atom(
            UInt64(1), 0.0, 0.0, 0.0, UInt64(0), 1.0,
            false, (false, false, false),
            0.1, 0.2, 0.3, true,
            0.0, 0.0, 0.0, false,
        )
        dup_meta = "{\"con_spec_version\":3,\"con_spec_minor\":0,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
        dup_frame = ConFrame(
            (10.0, 10.0, 10.0),
            (90.0, 90.0, 90.0),
            [atom],
            true,
            ("", ""),
            ("", ""),
            false,
            false,
            UInt32(3),
            dup_meta,
            nothing, nothing, nothing, nothing, nothing, nothing,
        )
        @test_throws ErrorException(ReadCon._DUPLICATE_CON_SPEC_MINOR) mktemp() do path, io
            close(io)
            write_con(path, [dup_frame])
        end
        quiet = ConFrame(
            (10.0, 10.0, 10.0),
            (90.0, 90.0, 90.0),
            [atom],
            false,
            ("", ""),
            ("", ""),
            false,
            false,
            UInt32(3),
            dup_meta,
            nothing, nothing, nothing, nothing, nothing, nothing,
        )
        @test_throws ErrorException(ReadCon._DUPLICATE_CON_SPEC_MINOR) mktemp() do path, io
            close(io)
            write_con(path, [quiet])
        end

        function constructed(metadata_line::String, velocities::Bool)
            return ConFrame(
                (10.0, 10.0, 10.0),
                (90.0, 90.0, 90.0),
                [atom],
                velocities,
                ("", ""),
                ("", ""),
                false,
                false,
                UInt32(3),
                metadata_line,
                nothing, nothing, nothing, nothing, nothing, nothing,
            )
        end
        for digits in (plus1, last_finite)
            with_time = "{\"con_spec_version\":3,\"con_spec_minor\":$digits,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
            written = mktemp() do path, io
                close(io)
                write_con(path, [constructed(with_time, true)])
                read(path, String)
            end
            @test occursin("\"con_spec_minor\":$digits", written)
            @test occursin("\"time\":\"fs\"", written)
            @test !occursin(natural, written)

            no_time = "{\"con_spec_version\":3,\"con_spec_minor\":$digits,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}"
            err = try
                mktemp() do path, io
                    close(io)
                    write_con(path, [constructed(no_time, true)])
                end
                nothing
            catch e
                e
            end
            @test err isa ReadCon.ReadConError
            @test occursin("units.time", err.message)
        end
        over_meta = "{\"con_spec_version\":3,\"con_spec_minor\":$overflow,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}}"
        over_write = try
            mktemp() do path, io
                close(io)
                write_con(path, [constructed(over_meta, true)])
            end
            nothing
        catch e
            e
        end
        @test over_write isa ReadCon.ReadConError
        @test occursin("invalid JSON", over_write.message)
    end

    include("test_conformance_goldens.jl")
    include("test_write_con_roundtrip.jl")
end
