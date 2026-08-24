# Phase A corpus lock: Julia reads the same goldens as the Python harness.
# Valid fixtures match symbols, atom_ids, fixed, and positions.
# Invalid fixtures must fail to parse.

function _repo_root()
    env = get(ENV, "READCON_CORE_ROOT", "")
    if !isempty(env)
        return env
    end
    return dirname(dirname(dirname(@__DIR__)))
end

function _unquote(raw::AbstractString)
    s = strip(raw)
    if length(s) >= 2 && startswith(s, '"') && endswith(s, '"')
        return s[2:end-1]
    end
    return String(s)
end

function parse_manifest(text::AbstractString)
    cases = Dict{String,Any}[]
    current = nothing
    for raw in split(text, '\n')
        line = strip(raw)
        isempty(line) && continue
        startswith(line, '#') && continue
        if line == "[[valid]]" || line == "[[invalid]]"
            if current !== nothing
                push!(cases, current)
            end
            current = Dict{String,Any}(
                "kind" => line == "[[valid]]" ? "valid" : "invalid",
                "id" => "",
                "path" => "",
            )
            continue
        end
        current === nothing && continue
        eq = findfirst('=', line)
        eq === nothing && continue
        key = strip(line[1:eq-1])
        val = strip(line[eq+1:end])
        if key == "id"
            current["id"] = _unquote(val)
        elseif key == "path"
            current["path"] = _unquote(val)
        end
    end
    if current !== nothing
        push!(cases, current)
    end
    return cases
end

function _skipws(s::AbstractString, i::Int)
    n = ncodeunits(s)
    while i <= n && isspace(s[i])
        i = nextind(s, i)
    end
    return i
end

function _find_key(json::AbstractString, key::AbstractString)
    pat = "\"" * key * "\""
    p = findfirst(pat, json)
    p === nothing && return 0
    colon = findnext(':', json, last(p))
    colon === nothing && return 0
    return Int(colon) + 1
end

function _parse_json_string(json::AbstractString, i::Int)
    i = _skipws(json, i)
    n = ncodeunits(json)
    i <= n && json[i] == '"' || error("expected string")
    i += 1
    start = i
    while i <= n && json[i] != '"'
        i += 1
    end
    i <= n || error("unterminated string")
    return json[start:i-1], i + 1
end

function _parse_int_at(json::AbstractString, i::Int)
    i = _skipws(json, i)
    n = ncodeunits(json)
    stop = i
    if stop <= n && (json[stop] == '+' || json[stop] == '-')
        stop += 1
    end
    while stop <= n && isdigit(json[stop])
        stop += 1
    end
    stop > i || error("expected integer")
    return parse(Int, json[i:stop-1])
end

function parse_golden(json::AbstractString)
    i = _find_key(json, "id")
    id, _ = _parse_json_string(json, i)
    n_atoms = _parse_int_at(json, _find_key(json, "n_atoms"))
    spec_version = _parse_int_at(json, _find_key(json, "spec_version"))

    function parse_bool_rows()
        i = _skipws(json, _find_key(json, "fixed"))
        json[i] == '[' || error("fixed: expected array")
        i += 1
        rows = Vector{NTuple{3,Bool}}()
        for _ in 1:n_atoms
            i = _skipws(json, i)
            json[i] == ',' && (i = _skipws(json, i + 1))
            json[i] == '[' || error("fixed row")
            i += 1
            bits = Bool[]
            for _k in 1:3
                i = _skipws(json, i)
                json[i] == ',' && (i = _skipws(json, i + 1))
                if startswith(json[i:end], "true")
                    push!(bits, true)
                    i += 4
                elseif startswith(json[i:end], "false")
                    push!(bits, false)
                    i += 5
                else
                    error("fixed bool")
                end
            end
            push!(rows, (bits[1], bits[2], bits[3]))
            i = _skipws(json, i)
            json[i] == ']' && (i += 1)
        end
        return rows
    end

    function parse_pos_rows()
        i = _skipws(json, _find_key(json, "positions"))
        json[i] == '[' || error("positions: expected array")
        i += 1
        rows = Vector{NTuple{3,Float64}}()
        for _ in 1:n_atoms
            i = _skipws(json, i)
            json[i] == ',' && (i = _skipws(json, i + 1))
            json[i] == '[' || error("positions row")
            i += 1
            nums = Float64[]
            for _k in 1:3
                i = _skipws(json, i)
                json[i] == ',' && (i = _skipws(json, i + 1))
                stop = i
                n = ncodeunits(json)
                while stop <= n && json[stop] != ',' && json[stop] != ']'
                    stop += 1
                end
                push!(nums, parse(Float64, strip(json[i:stop-1])))
                i = stop
            end
            push!(rows, (nums[1], nums[2], nums[3]))
            i = _skipws(json, i)
            json[i] == ']' && (i += 1)
        end
        return rows
    end

    function parse_ids()
        i = _skipws(json, _find_key(json, "atom_ids"))
        json[i] == '[' || error("atom_ids")
        i += 1
        ids = UInt64[]
        for _ in 1:n_atoms
            i = _skipws(json, i)
            json[i] == ',' && (i = _skipws(json, i + 1))
            stop = i
            n = ncodeunits(json)
            while stop <= n && json[stop] != ',' && json[stop] != ']'
                stop += 1
            end
            push!(ids, parse(UInt64, strip(json[i:stop-1])))
            i = stop
        end
        return ids
    end

    function parse_syms()
        i = _skipws(json, _find_key(json, "symbols"))
        json[i] == '[' || error("symbols")
        i += 1
        syms = String[]
        for _ in 1:n_atoms
            i = _skipws(json, i)
            json[i] == ',' && (i = _skipws(json, i + 1))
            s, i = _parse_json_string(json, i)
            push!(syms, s)
        end
        return syms
    end

    return Dict(
        "id" => id,
        "n_atoms" => n_atoms,
        "spec_version" => spec_version,
        "fixed" => parse_bool_rows(),
        "positions" => parse_pos_rows(),
        "atom_ids" => parse_ids(),
        "symbols" => parse_syms(),
    )
end

function _z_to_symbol(z::Integer)
    p = ccall(ReadCon._lib_symbol(:rkr_z_to_symbol), Cstring, (UInt64,), UInt64(z))
    return p == C_NULL ? "X" : unsafe_string(p)
end

@testset "conformance goldens" begin
    root = _repo_root()
    corpus = joinpath(root, "resources", "conformance")
    manifest = joinpath(corpus, "manifest.toml")
    @test isfile(manifest)
    cases = parse_manifest(read(manifest, String))
    valids = [c for c in cases if c["kind"] == "valid"]
    invalids = [c for c in cases if c["kind"] == "invalid"]
    @test !isempty(valids) && !isempty(invalids)
    on_disk = Set(basename(p) for p in readdir(joinpath(corpus, "golden"); join=true) if endswith(p, ".json"))
    @test on_disk == Set(c["id"] * ".json" for c in valids)
    for case in invalids
        @test !isfile(joinpath(corpus, "golden", case["id"] * ".json"))
    end

    for case in cases
        fixture = joinpath(corpus, case["path"])
        @test isfile(fixture)
        if case["kind"] == "invalid"
            frames = read_con(fixture)
            @test isempty(frames)
            first = ccall(ReadCon._lib_symbol(:rkr_read_first_frame), Ptr{Cvoid}, (Cstring,), fixture)
            @test first == C_NULL
            continue
        end
        frames = read_con(fixture)
        @test length(frames) == 1
        frame = frames[1]
        golden = parse_golden(read(joinpath(corpus, "golden", case["id"] * ".json"), String))
        @test golden["id"] == case["id"]
        @test golden["n_atoms"] == length(frame.atoms)
        @test golden["spec_version"] == Int(frame.spec_version)
        atoms = frame.atoms
        @test [_z_to_symbol(a.atomic_number) for a in atoms] == golden["symbols"]
        @test [a.atom_id for a in atoms] == golden["atom_ids"]
        @test [a.fixed for a in atoms] == golden["fixed"]
        for (atom, want) in zip(atoms, golden["positions"])
            @test atom.x ≈ want[1] atol=1e-12
            @test atom.y ≈ want[2] atol=1e-12
            @test atom.z ≈ want[3] atol=1e-12
        end
    end
end
