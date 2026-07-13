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
        @test_throws ErrorException read_con("/nonexistent/path.con")
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
end
