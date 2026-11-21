const REPO_ROOT = dirname(dirname(dirname(@__DIR__)))

function _accepted_conformance_paths()
    root = joinpath(REPO_ROOT, "resources", "conformance")
    paths = String[]
    valid = false
    for raw in eachline(joinpath(root, "manifest.toml"))
        line = strip(raw)
        if line == "[[valid]]" || line == "[[invalid]]"
            valid = line == "[[valid]]"
        elseif valid && startswith(line, "path")
            push!(paths, joinpath(root, strip(split(line, '='; limit=2)[2], ['"', ' '])))
        end
    end
    return paths
end

function _round_trip_corpus()
    paths = _accepted_conformance_paths()
    for dir in (joinpath(REPO_ROOT, "resources", "test"), joinpath(REPO_ROOT, "resources", "examples"))
        for name in sort(readdir(dir))
            (endswith(name, ".con") || endswith(name, ".convel")) || continue
            push!(paths, joinpath(dir, name))
        end
    end
    return paths
end

# The Rust binding rewrite of `src`, written through the C API, or nothing
# when the core rejects the file.
function _rust_rewrite_bytes(src::String, dst::String)
    n = Ref{Csize_t}(0)
    frames = ccall(ReadCon._lib_symbol(:rkr_read_all_frames), Ptr{Ptr{Cvoid}},
                   (Cstring, Ref{Csize_t}), src, n)
    frames == C_NULL && return nothing
    rewritten = Ptr{Cvoid}[]
    writer = C_NULL
    try
        for i in 1:n[]
            frame = unsafe_load(frames, i)
            out = ccall(ReadCon._lib_symbol(:rkr_frame_binding_rewrite), Ptr{Cvoid}, (Ptr{Cvoid},), frame)
            out == C_NULL && error("binding rewrite failed: $src frame $(i - 1)")
            push!(rewritten, out)
        end
        writer = ccall(ReadCon._lib_symbol(:create_writer_from_path_c), Ptr{Cvoid}, (Cstring,), dst)
        writer == C_NULL && error("writer failed: $dst")
        ReadCon._check_status(ccall(ReadCon._lib_symbol(:rkr_writer_extend), Cint,
                                    (Ptr{Cvoid}, Ptr{Ptr{Cvoid}}, Csize_t),
                                    writer, rewritten, length(rewritten)), "reference write")
        ReadCon._check_status(ccall(ReadCon._lib_symbol(:rkr_writer_flush), Cint,
                                    (Ptr{Cvoid},), writer), "reference flush")
    finally
        writer != C_NULL && ccall(ReadCon._lib_symbol(:free_rkr_writer), Cvoid, (Ptr{Cvoid},), writer)
        for frame in rewritten
            ccall(ReadCon._lib_symbol(:free_rkr_frame), Cvoid, (Ptr{Cvoid},), frame)
        end
        ccall(ReadCon._lib_symbol(:free_rkr_frame_array), Cvoid, (Ptr{Ptr{Cvoid}}, Csize_t), frames, n[])
    end
    return read(dst)
end

@testset "write_con round-trips the corpus" begin
    compared = String[]
    read_frames = ConFrame[]
    mktempdir() do dir
        sources = _round_trip_corpus()
        # Without validate=true a dropped section still parses, so only a
        # byte comparison notices it.
        for name in ("tiny_cuh2_charges_spins_magmoms.con", "tiny_cuh2_displacements.con", "tiny_cuh2_spreads.con")
            text = read(joinpath(REPO_ROOT, "resources", "test", name), String)
            lenient = replace(text, ",\"validate\":true" => "")
            @test lenient != text
            path = joinpath(dir, "lenient_" * name)
            write(path, lenient)
            push!(sources, path)
        end
        for src in sources
            name = basename(src)
            expected = _rust_rewrite_bytes(src, joinpath(dir, name * ".rust"))
            expected === nothing && continue
            frames = read_con(src)
            out = joinpath(dir, name * ".jl")
            written = try
                write_con(out, frames)
                true
            catch err
                @error "write_con failed" name exception = err
                false
            end
            @test written
            written || continue
            got = read(out)
            @test got == expected
            got == expected || @info "write_con mismatch" name length(expected) length(got)
            reread = read_con(out)
            @test length(reread) == length(frames)
            for (a, b) in zip(frames, reread)
                @test a.cell === b.cell && a.angles === b.angles
                @test a.atoms == b.atoms
            end
            append!(read_frames, frames)
            push!(compared, name)
        end
    end
    @test "tiny_cuh2_charges_spins_magmoms.con" in compared
    @test "tiny_cuh2_displacements.con" in compared
    @test "tiny_cuh2_spreads.con" in compared
    @test length(compared) >= 25
    sections_seen = Set{Symbol}()
    for frame in read_frames, atom in frame.atoms, field in (:charge, :spin, :magmom, :displacement, :spread)
        getfield(atom, field) === nothing || push!(sections_seen, field)
    end
    @test sections_seen == Set([:charge, :spin, :magmom, :displacement, :spread])
end

@testset "write_con keeps per-atom sections of a built frame" begin
    atom = Atom(
        UInt64(29), 1.0, 2.0, 3.0, UInt64(0), 63.546,
        false, (false, false, false),
        0.0, 0.0, 0.0, false,
        0.0, 0.0, 0.0, false,
        0.0, false;
        charge=0.25, spin=-0.5, magmom=(0.0, 0.0, 1.25),
        displacement=(0.01, 0.02, 0.03), spread=(0.04, 0.05, 0.06),
    )
    frame = ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [atom], false, ("", ""), ("", ""))
    mktemp() do path, io
        close(io)
        write_con(path, [frame])
        text = read(path, String)
        @test occursin("\"sections\":[\"charges\",\"spins\",\"magmoms\",\"displacements\",\"spreads\"]", text)
        back = read_con(path)[1].atoms[1]
        @test back.charge === 0.25
        @test back.spin === -0.5
        @test back.magmom === (0.0, 0.0, 1.25)
        @test back.displacement === (0.01, 0.02, 0.03)
        @test back.spread === (0.04, 0.05, 0.06)
    end
end

@testset "write_con failures do not truncate silently" begin
    frames = read_con(joinpath(REPO_ROOT, "resources", "test", "tiny_cuh2.con"))
    bad_atom = Atom(UInt64(0), 0.0, 0.0, 0.0, UInt64(0), 1.0, false, 0.0, 0.0, 0.0, false)
    bad = ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [bad_atom], false, ("", ""), ("", ""))
    mktemp() do path, io
        close(io)
        write_con(path, frames)
        before = read(path)
        @test !isempty(before)
        @test_throws ErrorException write_con(path, [frames[1], bad])
        @test read(path) == before
    end
    if Sys.islinux() && ispath("/dev/full")
        @test_throws ReadCon.ReadConError write_con("/dev/full", frames)
    else
        @test_skip "no /dev/full"
    end
end
