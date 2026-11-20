const Libdl = Base.Libc.Libdl

function _lib_in_prefix(root::AbstractString)
    for dir in (joinpath(root, "lib"), joinpath(root, "bin"), root)
        for name in ("libreadcon_core.so", "libreadcon_core.dylib", "readcon_core.dll")
            candidate = joinpath(dir, name)
            isfile(candidate) && return candidate
        end
    end
    return nothing
end

function _env_lib_path()
    for key in ("READCON_CORE_LIB", "READCON_LIB_PATH", "READCON_CORE_PREFIX")
        lib_env = get(ENV, key, "")
        isempty(lib_env) && continue
        isfile(lib_env) && return lib_env
        if isdir(lib_env)
            found = _lib_in_prefix(lib_env)
            found !== nothing && return found
        end
    end
    return nothing
end

function _artifact_lib_path()
    artifacts = joinpath(dirname(@__DIR__), "Artifacts.toml")
    isfile(artifacts) || return nothing
    try
        Artifacts = Base.require(Base.PkgId(
            Base.UUID("56f22d72-fd6d-98f1-02f0-08ddc0907c33"),
            "Artifacts",
        ))
        hash = Artifacts.artifact_hash("readcon_core", artifacts)
        hash === nothing && return nothing
        Artifacts.artifact_exists(hash) || return nothing
        root = Artifacts.artifact_path(hash)
        for dir in (joinpath(root, "lib"), root)
            for name in ("libreadcon_core.so", "libreadcon_core.dylib", "readcon_core.dll")
                candidate = joinpath(dir, name)
                isfile(candidate) && return candidate
            end
        end
    catch
        return nothing
    end
    return nothing
end

"""
    _lib_handle()

Return a path to the readcon-core shared library.
Search order: `READCON_CORE_LIB`, `READCON_LIB_PATH` (alias), a filled
`Artifacts.toml` (`readcon_core` artifact from the clib tarball), then
a local `target/{release,debug}` build.
"""
function _lib_handle()
    env_path = _env_lib_path()
    env_path !== nothing && return env_path
    art_path = _artifact_lib_path()
    art_path !== nothing && return art_path
    pkg_dir = dirname(@__DIR__)
    for candidate in [
        joinpath(pkg_dir, "..", "..", "target", "release", "libreadcon_core.so"),
        joinpath(pkg_dir, "..", "..", "target", "release", "libreadcon_core.dylib"),
        joinpath(pkg_dir, "..", "..", "target", "debug", "libreadcon_core.so"),
        joinpath(pkg_dir, "..", "..", "target", "debug", "libreadcon_core.dylib"),
    ]
        if isfile(candidate)
            return candidate
        end
    end
    error("Cannot find libreadcon_core. Set READCON_CORE_LIB (or READCON_LIB_PATH), install the clib artifact, or build with cargo build --release --features capi.")
end

const _LIB = Ref{Ptr{Cvoid}}(C_NULL)

function _get_lib()
    if _LIB[] == C_NULL
        _LIB[] = Libdl.dlopen(_lib_handle())
    end
    return _LIB[]
end

function _lib_symbol(name::Symbol)
    return Libdl.dlsym(_get_lib(), name)
end

const RKR_STATUS_SUCCESS = Cint(0)
const RKR_UINT64_SENTINEL = typemax(UInt64)

const _ATOMIC_SYMBOLS = [
    "X",
    "H", "He",
    "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
    "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt",
    "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf",
    "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
]

function _atomic_symbol(atomic_number::UInt64)
    idx = Int(atomic_number) + 1
    if idx < 2 || idx > length(_ATOMIC_SYMBOLS)
        error("unsupported atomic number for writing: $atomic_number")
    end
    return _ATOMIC_SYMBOLS[idx]
end

function _status_message(status::Cint)
    c_str = ccall(_lib_symbol(:rkr_status_message), Cstring, (Cint,), status)
    c_str == C_NULL && return "unknown status"
    return unsafe_string(c_str)
end

struct RkrError
    code::Int32
    message::Ptr{UInt8}
    line::UInt32
    frame_index::UInt64
end

struct ReadConError <: Exception
    operation::String
    code::Int32
    message::String
    line::UInt32
    frame_index::UInt64
end

function Base.showerror(io::IO, err::ReadConError)
    print(io, err.operation, ": ", err.message, " (line ", err.line, ", frame ", err.frame_index, ")")
end

function last_error()
    ptr = ccall(_lib_symbol(:rkr_last_error), Ptr{RkrError}, ())
    ptr == C_NULL && return nothing
    err = unsafe_load(ptr)
    message = err.message == C_NULL ? "unknown status" : unsafe_string(err.message)
    return (code=err.code, message=message, line=err.line, frame_index=err.frame_index)
end

function clear_error()
    ccall(_lib_symbol(:rkr_clear_error), Cvoid, ())
    return nothing
end

function _throw_last(operation::String)
    err = last_error()
    if err === nothing
        throw(ReadConError(operation, Int32(-7), operation, UInt32(0), UInt64(0)))
    end
    throw(ReadConError(operation, err.code, err.message, err.line, err.frame_index))
end

function _check_status(status::Cint, operation::String)
    status == RKR_STATUS_SUCCESS && return nothing
    err = last_error()
    if err === nothing
        throw(ReadConError(operation, status, _status_message(status), UInt32(0), UInt64(0)))
    end
    throw(ReadConError(operation, err.code, err.message, err.line, err.frame_index))
end

"""
    has_chemfiles_support() -> Bool

True when the linked `libreadcon_core` was built with the chemfiles feature
(selection + optional multi-format import). Selection APIs require this.
"""
function has_chemfiles_support()
    return ccall(_lib_symbol(:rkr_has_chemfiles_support), UInt8, ()) != 0
end

"""
    select_on_frame(frame::ConFrame, selection::String) -> NamedTuple

Evaluate a chemfiles selection-language string on `frame` via the C FFI
(`rkr_frame_select`). Requires a chemfiles-enabled library build.

Returns `(selection, context_size, matches)` where each match is a `Vector{UInt64}`
of atom indices in CON `atom_data` order (1–4 indices depending on context).

Topology contexts (`bonds:`, `angles:`, `dihedrals:`, `is_bonded`, …) need
optional frame `metadata["bonds"]` (0-based `atom_data` pairs). Without bonds,
those selectors return zero matches; name/type/`all` still work.
"""
function select_on_frame(frame::ConFrame, selection::String)
    has_chemfiles_support() || error(
        "select_on_frame requires libreadcon_core built with --features capi,chemfiles"
    )
    handle = _build_frame_handle(frame)
    try
        out = Ref{Ptr{Cvoid}}(C_NULL)
        status = ccall(
            _lib_symbol(:rkr_frame_select),
            Cint,
            (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}),
            handle,
            selection,
            out,
        )
        _check_status(status, "rkr_frame_select")
        result_handle = out[]
        result_handle == C_NULL && _throw_last("rkr_frame_select returned null result")
        try
            n = ccall(
                _lib_symbol(:rkr_selection_result_match_count),
                UInt64,
                (Ptr{Cvoid},),
                result_handle,
            )
            ctx = ccall(
                _lib_symbol(:rkr_selection_result_context_size),
                UInt32,
                (Ptr{Cvoid},),
                result_handle,
            )
            matches = Vector{Vector{UInt64}}()
            for i in 0:(n - 1)
                atoms = Vector{UInt64}(undef, 4)
                fill!(atoms, typemax(UInt64))
                size_ref = Ref{UInt32}(0)
                st = ccall(
                    _lib_symbol(:rkr_selection_result_match_at),
                    Cint,
                    (Ptr{Cvoid}, UInt64, Ptr{UInt64}, Ref{UInt32}),
                    result_handle,
                    i,
                    atoms,
                    size_ref,
                )
                _check_status(st, "rkr_selection_result_match_at")
                sz = Int(size_ref[])
                push!(matches, atoms[1:sz])
            end
            return (
                selection = selection,
                context_size = Int(ctx),
                matches = matches,
            )
        finally
            ccall(_lib_symbol(:rkr_selection_result_free), Cvoid, (Ptr{Cvoid},), result_handle)
        end
    finally
        handle != C_NULL && ccall(_lib_symbol(:free_rkr_frame), Cvoid, (Ptr{Cvoid},), handle)
    end
end

"""
    select_atom_indices(frame::ConFrame, selection::String) -> Vector{Int}

Atom-context convenience: sorted unique primary indices (e.g. `"name O"`).
Errors if the selection is not atom context (size 1).
"""
function select_atom_indices(frame::ConFrame, selection::String)
    res = select_on_frame(frame, selection)
    res.context_size == 1 || error(
        "select_atom_indices requires atom-context selection, got context_size=$(res.context_size)"
    )
    idxs = sort(unique(Int(m[1]) for m in res.matches))
    return idxs
end

"""
    frame_bond_count(frame::ConFrame) -> Int

Number of optional topology bonds in frame metadata (`rkr_frame_bond_count`).
"""
function frame_bond_count(frame::ConFrame)
    handle = _build_frame_handle(frame)
    try
        return Int(ccall(_lib_symbol(:rkr_frame_bond_count), UInt64, (Ptr{Cvoid},), handle))
    finally
        handle != C_NULL && ccall(_lib_symbol(:free_rkr_frame), Cvoid, (Ptr{Cvoid},), handle)
    end
end

function _take_string(c_str::Ptr{UInt8})
    c_str == C_NULL && return ""
    value = unsafe_string(c_str)
    ccall(_lib_symbol(:rkr_free_string), Cvoid, (Ptr{UInt8},), c_str)
    return value
end

_maybe_float(value::Float64) = isnan(value) ? nothing : value
_maybe_uint64(value::UInt64) = value == RKR_UINT64_SENTINEL ? nothing : value

function _frame_metadata(frame_handle::Ptr{Cvoid})
    spec_version = ccall(
        _lib_symbol(:rkr_frame_spec_version),
        UInt32, (Ptr{Cvoid},), frame_handle
    )
    metadata_json = _take_string(ccall(
        _lib_symbol(:rkr_frame_metadata_json),
        Ptr{UInt8}, (Ptr{Cvoid},), frame_handle
    ))
    energy = _maybe_float(ccall(
        _lib_symbol(:rkr_frame_energy),
        Float64, (Ptr{Cvoid},), frame_handle
    ))
    frame_index = _maybe_uint64(ccall(
        _lib_symbol(:rkr_frame_frame_index),
        UInt64, (Ptr{Cvoid},), frame_handle
    ))
    time = _maybe_float(ccall(
        _lib_symbol(:rkr_frame_time),
        Float64, (Ptr{Cvoid},), frame_handle
    ))
    timestep = _maybe_float(ccall(
        _lib_symbol(:rkr_frame_timestep),
        Float64, (Ptr{Cvoid},), frame_handle
    ))
    neb_bead = _maybe_uint64(ccall(
        _lib_symbol(:rkr_frame_neb_bead),
        UInt64, (Ptr{Cvoid},), frame_handle
    ))
    neb_band = _maybe_uint64(ccall(
        _lib_symbol(:rkr_frame_neb_band),
        UInt64, (Ptr{Cvoid},), frame_handle
    ))
    return (
        spec_version, metadata_json, energy, frame_index,
        time, timestep, neb_bead, neb_band,
    )
end

"""
    read_con(path::String) -> Vector{ConFrame}

Read all frames from a .con or .convel file.
"""
function read_con(path::String)
    iter_ptr = ccall(
        _lib_symbol(:read_con_file_iterator),
        Ptr{Cvoid}, (Cstring,), path
    )
    iter_ptr == C_NULL && _throw_last("Failed to open file: $path")

    frames = ConFrame[]

    try
        while true
            frame_handle = ccall(
                _lib_symbol(:con_frame_iterator_next),
                Ptr{Cvoid}, (Ptr{Cvoid},), iter_ptr
            )
            frame_handle == C_NULL && break

            try
                c_frame_ptr = ccall(
                    _lib_symbol(:rkr_frame_to_c_frame),
                    Ptr{CFrame}, (Ptr{Cvoid},), frame_handle
                )
                c_frame_ptr == C_NULL && continue

                try
                    c_frame = unsafe_load(c_frame_ptr)
                    n = Int(c_frame.num_atoms)
                    charges = _atom_section(frame_handle, n, :charges, 1)
                    spins = _atom_section(frame_handle, n, :spins, 1)
                    magmoms = _atom_section(frame_handle, n, :magmoms, 3)
                    displacements = _atom_section(frame_handle, n, :displacements, 3)
                    spreads = _atom_section(frame_handle, n, :spreads, 3)

                    atoms = Atom[]
                    for i in 1:n
                        c_atom = unsafe_load(c_frame.atoms, i)
                        push!(atoms, Atom(
                            c_atom.atomic_number,
                            c_atom.x, c_atom.y, c_atom.z,
                            c_atom.atom_id, c_atom.mass,
                            c_atom.is_fixed,
                            (c_atom.fixed_x, c_atom.fixed_y, c_atom.fixed_z),
                            c_atom.vx, c_atom.vy, c_atom.vz,
                            c_atom.has_velocity,
                            c_atom.fx, c_atom.fy, c_atom.fz,
                            c_atom.has_forces,
                            c_atom.energy, c_atom.has_energy;
                            charge=_section_entry(charges, i),
                            spin=_section_entry(spins, i),
                            magmom=_section_entry(magmoms, i),
                            displacement=_section_entry(displacements, i),
                            spread=_section_entry(spreads, i),
                        ))
                    end

                    prebox = _get_headers(frame_handle, true)
                    postbox = _get_headers(frame_handle, false)
                    metadata = _frame_metadata(frame_handle)

                    push!(frames, ConFrame(
                        c_frame.cell, c_frame.angles,
                        atoms, c_frame.has_velocities,
                        prebox, postbox, c_frame.has_forces,
                        c_frame.has_energies,
                        metadata...,
                    ))
                finally
                    ccall(_lib_symbol(:free_c_frame), Cvoid, (Ptr{CFrame},), c_frame_ptr)
                end
            finally
                ccall(_lib_symbol(:free_rkr_frame), Cvoid, (Ptr{Cvoid},), frame_handle)
            end
        end
    finally
        ccall(_lib_symbol(:free_con_frame_iterator), Cvoid, (Ptr{Cvoid},), iter_ptr)
    end

    return frames
end

# Values of one optional per-atom section in CON atom order, or nothing
# when the frame lacks it. Checking first keeps SECTION_ABSENT off the
# error channel that read_con leaves for its caller.
function _atom_section(frame_handle::Ptr{Cvoid}, n::Int, name::Symbol, width::Int)
    has = ccall(_lib_symbol(Symbol(:rkr_frame_has_, name)), Bool, (Ptr{Cvoid},), frame_handle)
    (has && n > 0) || return nothing
    buf = Vector{Float64}(undef, width * n)
    status = ccall(
        _lib_symbol(Symbol(:rkr_frame_copy_, name)),
        Cint, (Ptr{Cvoid}, Ptr{Float64}, Csize_t),
        frame_handle, buf, length(buf),
    )
    _check_status(status, "failed to copy $name")
    return width == 1 ? buf : [(buf[3i - 2], buf[3i - 1], buf[3i]) for i in 1:n]
end

_section_entry(::Nothing, ::Int) = nothing
_section_entry(values::AbstractVector, i::Int) = values[i]

function _get_headers(frame_handle, is_prebox::Bool)
    lines = String[]
    for idx in 0:1
        c_str = ccall(
            _lib_symbol(:rkr_frame_get_header_line_cpp),
            Ptr{UInt8}, (Ptr{Cvoid}, Bool, UInt), frame_handle, is_prebox, idx
        )
        if c_str != C_NULL
            s = unsafe_string(c_str)
            ccall(_lib_symbol(:rkr_free_string), Cvoid, (Ptr{UInt8},), c_str)
            push!(lines, s)
        else
            push!(lines, "")
        end
    end
    return (lines[1], lines[2])
end

"""
    write_con(path::String, frames::Vector{ConFrame}; precision=nothing)

Write frames to a .con file. The default numeric text round-trips binary64.
`precision` is a fixed number of digits after the decimal.

Every frame is built before `path` is opened, so a frame that cannot be
built leaves an existing file untouched. A failed write or flush throws.
"""
function write_con(path::String, frames::Vector{ConFrame}; precision::Union{Nothing,Integer}=nothing)
    handles = Ptr{Cvoid}[]
    writer = C_NULL
    try
        for frame in frames
            push!(handles, _build_frame_handle(frame))
        end
        writer = if precision === nothing
            ccall(_lib_symbol(:create_writer_from_path_c), Ptr{Cvoid}, (Cstring,), path)
        else
            ccall(
                _lib_symbol(:create_writer_from_path_with_precision_c),
                Ptr{Cvoid}, (Cstring, UInt8), path, UInt8(precision)
            )
        end
        writer == C_NULL && _throw_last("failed to create writer for file: $path")
        status = ccall(
            _lib_symbol(:rkr_writer_extend),
            Cint, (Ptr{Cvoid}, Ptr{Ptr{Cvoid}}, Csize_t),
            writer, handles, length(handles)
        )
        _check_status(status, "failed to write frames")
        # free_rkr_writer flushes too, but cannot report an error.
        status = ccall(_lib_symbol(:rkr_writer_flush), Cint, (Ptr{Cvoid},), writer)
        _check_status(status, "failed to flush frames to $path")
        return nothing
    finally
        for handle in handles
            handle != C_NULL && ccall(_lib_symbol(:free_rkr_frame), Cvoid, (Ptr{Cvoid},), handle)
        end
        writer != C_NULL && ccall(_lib_symbol(:free_rkr_writer), Cvoid, (Ptr{Cvoid},), writer)
    end
end

# True when the units object already names a non-empty time unit.
function _units_declares_time(metadata_json::AbstractString)
    m = match(r"\"units\"\s*:\s*\{", metadata_json)
    m === nothing && return false
    depth = 0
    started = false
    buf = IOBuffer()
    for c in metadata_json[m.offset:end]
        if c == '{'
            depth += 1
            started = true
        elseif c == '}'
            depth -= 1
        end
        print(buf, c)
        started && depth == 0 && break
    end
    return occursin(r"\"time\"\s*:\s*\"[^\"]+\"", String(take!(buf)))
end

const _NATURAL_TIME_UNIT = "(amu*angstrom^2/eV)^0.5"

# Insert units.time into an existing units object. An empty object gets one field.
function _inject_units_time(metadata_json::AbstractString)
    time = _NATURAL_TIME_UNIT
    replaced = replace(
        metadata_json,
        r"(\"units\"\s*:\s*)\{\s*\}" => SubstitutionString("\\1{\"time\":\"$time\"}"),
        count=1,
    )
    replaced == metadata_json || return replaced
    return replace(
        metadata_json,
        r"(\"units\"\s*:\s*\{)" => SubstitutionString("\\1\"time\":\"$time\","),
        count=1,
    )
end

# Inclusive bounds of the units object, or nothing when it is absent.
function _units_object_bounds(metadata_json::AbstractString)
    m = match(r"\"units\"\s*:\s*\{", metadata_json)
    m === nothing && return nothing
    open = findnext(==('{'), metadata_json, m.offset)
    open === nothing && return nothing
    depth = 0
    i = open
    while i <= lastindex(metadata_json)
        c = metadata_json[i]
        if c == '{'
            depth += 1
        elseif c == '}'
            depth -= 1
            depth == 0 && return (open, i)
        end
        i = nextind(metadata_json, i)
    end
    return nothing
end

# v3.0 stores velocities in the natural unit whatever units.time says
# (CON-units.9). Writing minor 1 makes that label authoritative, so replace
# a present label and insert one when it is missing.
function _ensure_natural_time(metadata_json::AbstractString)
    _units_declares_time(metadata_json) || return _inject_units_time(metadata_json)
    bounds = _units_object_bounds(metadata_json)
    bounds === nothing && return metadata_json
    open, close = bounds
    body = metadata_json[nextind(metadata_json, open):prevind(metadata_json, close)]
    time = _NATURAL_TIME_UNIT
    body = replace(
        body,
        r"(\"time\"\s*:\s*)\"[^\"]*\"" => SubstitutionString("\\1\"$time\""),
        count=1,
    )
    return metadata_json[begin:prevind(metadata_json, open)] *
        "{" * body * "}" *
        metadata_json[nextind(metadata_json, close):end]
end

const _DUPLICATE_CON_SPEC_MINOR = "duplicate con_spec_minor key"

function _is_nonneg_decimal_int(token::AbstractString)
    n = ncodeunits(token)
    n == 0 && return false
    b0 = codeunit(token, 1)
    if b0 == UInt8('0')
        return n == 1
    end
    UInt8('1') <= b0 <= UInt8('9') || return false
    for i in 2:n
        b = codeunit(token, i)
        UInt8('0') <= b <= UInt8('9') || return false
    end
    return true
end

# Same gate as Rust `is_substitutable_huge_minor`: JSON integer grammar,
# does not fit in UInt64, and parses as a finite binary64 value.
# serde_json accepts an integer that rounds to a finite Float64, including
# values above floatmax(Float64) below the half-ULP midpoint
# floor(f64::MAX) + 2^970. The midpoint itself is rejected.
function _substitutable_huge_minor(token::AbstractString)
    _is_nonneg_decimal_int(token) || return false
    tryparse(UInt64, token) !== nothing && return false
    x = tryparse(Float64, token)
    return x !== nothing && isfinite(x)
end

# Value of a con_spec_minor token the builder accepts, or nothing when the
# builder rejects it (leading zeros, sign, fraction, exponent, non-number).
function _minor_token_u64(token::AbstractString)
    _is_nonneg_decimal_int(token) || return nothing
    parsed = tryparse(UInt64, token)
    parsed !== nothing && return parsed
    return _substitutable_huge_minor(token) ? typemax(UInt64) : nothing
end

function _json_ws(b::UInt8)
    return b == UInt8(' ') || b == UInt8('\t') || b == UInt8('\r') || b == UInt8('\n')
end

function _skip_json_ws(bytes::Vector{UInt8}, i::Int)
    n = length(bytes)
    while i <= n && _json_ws(bytes[i])
        i += 1
    end
    return i
end

function _scan_json_string_end(bytes::Vector{UInt8}, start::Int)
    (start <= length(bytes) && bytes[start] == UInt8('"')) || return nothing
    i = start + 1
    n = length(bytes)
    escaped = false
    while i <= n
        b = bytes[i]
        if escaped
            escaped = false
        elseif b == UInt8('\\')
            escaped = true
        elseif b == UInt8('"')
            return i + 1
        end
        i += 1
    end
    return nothing
end

function _value_boundary(b::UInt8)
    return _json_ws(b) || b == UInt8(',') || b == UInt8('}') || b == UInt8(']')
end

function _scan_json_value_end(bytes::Vector{UInt8}, start::Int)
    start <= length(bytes) || return nothing
    first = bytes[start]
    if first == UInt8('"')
        return _scan_json_string_end(bytes, start)
    end
    if first == UInt8('{') || first == UInt8('[')
        depth = 0
        i = start
        n = length(bytes)
        while i <= n
            b = bytes[i]
            if b == UInt8('"')
                nxt = _scan_json_string_end(bytes, i)
                nxt === nothing && return nothing
                i = nxt
                continue
            elseif b == UInt8('{') || b == UInt8('[')
                depth += 1
            elseif b == UInt8('}') || b == UInt8(']')
                depth -= 1
                depth == 0 && return i + 1
            end
            i += 1
        end
        return nothing
    end
    i = start
    n = length(bytes)
    while i <= n && !_value_boundary(bytes[i])
        i += 1
    end
    return i > start ? i : nothing
end

function _hex_nibble(b::UInt8)
    if UInt8('0') <= b <= UInt8('9')
        return Int(b - UInt8('0'))
    elseif UInt8('a') <= b <= UInt8('f')
        return Int(b - UInt8('a')) + 10
    elseif UInt8('A') <= b <= UInt8('F')
        return Int(b - UInt8('A')) + 10
    end
    return nothing
end

# Decode a quoted JSON key. Invalid escapes yield nothing and that field is
# skipped, matching the Rust scanner.
function _decode_json_key(raw::AbstractString)
    n = ncodeunits(raw)
    n < 2 && return nothing
    codeunit(raw, 1) == UInt8('"') || return nothing
    codeunit(raw, n) == UInt8('"') || return nothing
    if !occursin('\\', raw)
        return raw[nextind(raw, 1):prevind(raw, n)]
    end
    out = UInt8[]
    i = 2
    last = n - 1
    while i <= last
        b = codeunit(raw, i)
        if b != UInt8('\\')
            push!(out, b)
            i += 1
            continue
        end
        i += 1
        i > last && return nothing
        e = codeunit(raw, i)
        if e == UInt8('"') || e == UInt8('\\') || e == UInt8('/')
            push!(out, e)
        elseif e == UInt8('b')
            push!(out, 0x08)
        elseif e == UInt8('f')
            push!(out, 0x0c)
        elseif e == UInt8('n')
            push!(out, 0x0a)
        elseif e == UInt8('r')
            push!(out, 0x0d)
        elseif e == UInt8('t')
            push!(out, 0x09)
        elseif e == UInt8('u')
            i + 4 > last && return nothing
            cp = 0
            for k in 1:4
                nib = _hex_nibble(codeunit(raw, i + k))
                nib === nothing && return nothing
                cp = cp * 16 + nib
            end
            i += 4
            if 0xD800 <= cp <= 0xDBFF
                nxt = i + 1
                if nxt + 5 > last || codeunit(raw, nxt) != UInt8('\\') || codeunit(raw, nxt + 1) != UInt8('u')
                    return nothing
                end
                lo = 0
                for k in 2:5
                    nib = _hex_nibble(codeunit(raw, nxt + k))
                    nib === nothing && return nothing
                    lo = lo * 16 + nib
                end
                0xDC00 <= lo <= 0xDFFF || return nothing
                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                i = nxt + 5
            elseif 0xDC00 <= cp <= 0xDFFF
                return nothing
            end
            append!(out, transcode(UInt8, string(Char(cp))))
        else
            return nothing
        end
        i += 1
    end
    return String(out)
end

# Byte ranges of the top-level `con_spec_minor` values, in order. A key
# written with JSON escapes counts. Nested keys are ignored.
function _top_level_minor_spans(json::AbstractString)
    bytes = Vector{UInt8}(codeunits(json))
    i = _skip_json_ws(bytes, 1)
    spans = UnitRange{Int}[]
    (i <= length(bytes) && bytes[i] == UInt8('{')) || return spans
    i += 1
    while true
        i = _skip_json_ws(bytes, i)
        if i > length(bytes) || bytes[i] == UInt8('}')
            break
        end
        if bytes[i] == UInt8(',')
            i += 1
            i = _skip_json_ws(bytes, i)
        end
        if i > length(bytes) || bytes[i] != UInt8('"')
            break
        end
        k_end = _scan_json_string_end(bytes, i)
        k_end === nothing && break
        raw_key = String(bytes[i:(k_end - 1)])
        i = k_end
        i = _skip_json_ws(bytes, i)
        if i > length(bytes) || bytes[i] != UInt8(':')
            break
        end
        i += 1
        i = _skip_json_ws(bytes, i)
        v_end = _scan_json_value_end(bytes, i)
        v_end === nothing && break
        if _decode_json_key(raw_key) == "con_spec_minor"
            push!(spans, i:(v_end - 1))
        end
        i = v_end
    end
    return spans
end

# Raw top-level `con_spec_minor` value tokens, in order.
function _top_level_minor_tokens(json::AbstractString)
    units = codeunits(json)
    return [String(units[span]) for span in _top_level_minor_spans(json)]
end

# Write a top-level con_spec_minor of 0 as 1. Nested keys keep their values.
function _promote_zero_minor(metadata_json::AbstractString)
    spans = _top_level_minor_spans(metadata_json)
    length(spans) == 1 || return metadata_json
    bytes = Vector{UInt8}(codeunits(metadata_json))
    bytes[spans[1]] == UInt8['0'] || return metadata_json
    bytes[first(spans[1])] = UInt8('1')
    return String(bytes)
end

function _reject_duplicate_con_spec_minor(metadata_json::AbstractString)
    if length(_top_level_minor_tokens(metadata_json)) > 1
        error(_DUPLICATE_CON_SPEC_MINOR)
    end
    return nothing
end

const _INVALID_CON_SPEC_MINOR = "con_spec_minor must be a JSON integer >= 0"

# For con_spec_minor: the value of the top-level key, which may be written
# with JSON escapes. 0 when that key is absent (a nested key does not
# count), typemax(UInt64) for an integer above it that serde_json accepts,
# and an ErrorException for a
# repeated key. Any top-level token the builder rejects throws ReadConError
# code -3 (RKR_STATUS_INVALID_JSON): leading zeros, a sign, a fraction, an
# exponent (1e0, 1e309, 1E400), a non-number, or an integer at or above
# the half-ULP midpoint floor(f64::MAX) + 2^970.
function _json_u64(metadata_json::AbstractString, key::AbstractString)
    if key == "con_spec_minor"
        tokens = _top_level_minor_tokens(metadata_json)
        if length(tokens) > 1
            error(_DUPLICATE_CON_SPEC_MINOR)
        end
        isempty(tokens) && return UInt64(0)
        value = _minor_token_u64(tokens[1])
        value === nothing && throw(ReadConError(
            "con_spec_minor", Int32(-3), _INVALID_CON_SPEC_MINOR, UInt32(0), UInt64(0),
        ))
        return value
    end
    m = match(Regex("\"$(key)\"\\s*:\\s*(\\d+)"), metadata_json)
    m === nothing && return UInt64(0)
    return parse(UInt64, m.captures[1])
end

# v1, v2, and v3.0 velocities are in the natural time unit (CON-units.8, CON-units.9).
# Returns the metadata to store, and whether the caller must set default units.
function _legacy_velocity_units(frame::ConFrame)
    metadata_json = frame.metadata_json
    if !frame.has_velocities
        return metadata_json, false
    end
    # Hand a token the builder rejects to it unchanged, so the write fails
    # as it does in the other bindings instead of being rewritten to minor 1.
    tokens = _top_level_minor_tokens(metadata_json)
    if length(tokens) == 1 && _minor_token_u64(tokens[1]) === nothing
        return metadata_json, false
    end
    minor = _json_u64(metadata_json, "con_spec_minor")
    # Minor 1 and later name the time unit. Do not invent or replace it.
    if frame.spec_version >= 3 && minor >= 1
        return metadata_json, false
    end
    # A v3.0 frame with velocities is rebuilt as minor 1. Stamp the natural
    # unit, and promote an explicit minor of 0 so that label is authoritative.
    # This matches Python's stamp_legacy_velocity_time.
    if frame.spec_version >= 3
        stamped = _promote_zero_minor(metadata_json)
        if _units_object_bounds(stamped) !== nothing
            stamped = _ensure_natural_time(stamped)
        end
        return stamped, _units_object_bounds(metadata_json) === nothing
    end
    if _units_declares_time(metadata_json)
        return metadata_json, false
    end
    if occursin(r"\"units\"\s*:", metadata_json)
        return _inject_units_time(metadata_json), false
    end
    return metadata_json, true
end

function _build_frame_handle(frame::ConFrame)
    _reject_duplicate_con_spec_minor(frame.metadata_json)
    cell = Float64[frame.cell...]
    angles = Float64[frame.angles...]
    builder = ccall(
        _lib_symbol(:rkr_frame_new),
        Ptr{Cvoid},
        (Ptr{Float64}, Ptr{Float64}, Cstring, Cstring, Cstring, Cstring),
        cell, angles,
        frame.prebox_header[1], frame.prebox_header[2],
        frame.postbox_header[1], frame.postbox_header[2],
    )
    builder == C_NULL && _throw_last("failed to create frame builder")

    try
        metadata_json, stamp_default_units = _legacy_velocity_units(frame)
        if !isempty(metadata_json)
            status = ccall(
                _lib_symbol(:rkr_frame_builder_set_metadata_json),
                Cint, (Ptr{Cvoid}, Cstring), builder, metadata_json
            )
            _check_status(status, "failed to set frame metadata")
        end
        if stamp_default_units
            # v1, v2, and v3.0 velocities are in the natural time unit.
            # The builder writes minor 1, which requires units.time (CON-units.11).
            status = ccall(
                _lib_symbol(:rkr_frame_builder_set_units),
                Cint, (Ptr{Cvoid}, Cstring),
                builder,
                "{\"length\":\"angstrom\",\"energy\":\"eV\",\"mass\":\"amu\",\"time\":\"(amu*angstrom^2/eV)^0.5\"}",
            )
            _check_status(status, "failed to set units")
        end

        for atom in frame.atoms
            _add_atom(builder, atom)
        end

        builder_ref = Ref(builder)
        handle = ccall(
            _lib_symbol(:rkr_frame_builder_build),
            Ptr{Cvoid},
            (Ref{Ptr{Cvoid}},),
            builder_ref,
        )
        builder = builder_ref[]
        handle == C_NULL && _throw_last("failed to build frame")
        return handle
    finally
        builder != C_NULL && ccall(_lib_symbol(:free_rkr_frame_builder), Cvoid, (Ptr{Cvoid},), builder)
    end
end

function _add_atom(builder::Ptr{Cvoid}, atom::Atom)
    symbol = _atomic_symbol(atom.atomic_number)
    fixed_x, fixed_y, fixed_z = atom.fixed

    status = if atom.has_velocity && atom.has_forces
        ccall(
            _lib_symbol(:rkr_frame_add_atom_with_velocity_and_forces_fixed_mask),
            Cint,
            (
                Ptr{Cvoid}, Cstring,
                Float64, Float64, Float64,
                Bool, Bool, Bool,
                UInt64, Float64,
                Float64, Float64, Float64,
                Float64, Float64, Float64,
            ),
            builder, symbol,
            atom.x, atom.y, atom.z,
            fixed_x, fixed_y, fixed_z,
            atom.atom_id, atom.mass,
            atom.vx, atom.vy, atom.vz,
            atom.fx, atom.fy, atom.fz,
        )
    elseif atom.has_velocity
        ccall(
            _lib_symbol(:rkr_frame_add_atom_with_velocity_fixed_mask),
            Cint,
            (
                Ptr{Cvoid}, Cstring,
                Float64, Float64, Float64,
                Bool, Bool, Bool,
                UInt64, Float64,
                Float64, Float64, Float64,
            ),
            builder, symbol,
            atom.x, atom.y, atom.z,
            fixed_x, fixed_y, fixed_z,
            atom.atom_id, atom.mass,
            atom.vx, atom.vy, atom.vz,
        )
    elseif atom.has_forces
        ccall(
            _lib_symbol(:rkr_frame_add_atom_with_forces_fixed_mask),
            Cint,
            (
                Ptr{Cvoid}, Cstring,
                Float64, Float64, Float64,
                Bool, Bool, Bool,
                UInt64, Float64,
                Float64, Float64, Float64,
            ),
            builder, symbol,
            atom.x, atom.y, atom.z,
            fixed_x, fixed_y, fixed_z,
            atom.atom_id, atom.mass,
            atom.fx, atom.fy, atom.fz,
        )
    else
        ccall(
            _lib_symbol(:rkr_frame_add_atom_with_fixed_mask),
            Cint,
            (
                Ptr{Cvoid}, Cstring,
                Float64, Float64, Float64,
                Bool, Bool, Bool,
                UInt64, Float64,
            ),
            builder, symbol,
            atom.x, atom.y, atom.z,
            fixed_x, fixed_y, fixed_z,
            atom.atom_id, atom.mass,
        )
    end

    _check_status(status, "failed to add atom")

    if atom.has_energy
        e_status = ccall(
            _lib_symbol(:rkr_frame_builder_set_last_energy),
            Cint,
            (Ptr{Cvoid}, Float64),
            builder, atom.energy,
        )
        _check_status(e_status, "failed to attach per-atom energy")
    end

    for (name, value) in (("charge", atom.charge), ("spin", atom.spin))
        value === nothing && continue
        status = ccall(
            _lib_symbol(Symbol(:rkr_frame_builder_set_last_, name)),
            Cint, (Ptr{Cvoid}, Float64), builder, value,
        )
        _check_status(status, "failed to attach per-atom $name")
    end
    for (name, value) in (
        ("magmom", atom.magmom),
        ("displacement", atom.displacement),
        ("spread", atom.spread),
    )
        value === nothing && continue
        status = ccall(
            _lib_symbol(Symbol(:rkr_frame_builder_set_last_, name)),
            Cint, (Ptr{Cvoid}, Ptr{Float64}), builder, Float64[value...],
        )
        _check_status(status, "failed to attach per-atom $name")
    end
end

"""
    atom_index_by_id(frame::ConFrame, atom_id::Integer) -> Union{Int, Nothing}

Returns the 1-based position of the atom in `frame.atoms` whose
`atom_id` equals the given id, or `nothing` if no such atom exists.
O(N) per call. For repeated lookups, build a dictionary once with
`build_atom_id_index`.
"""
function atom_index_by_id(frame::ConFrame, atom_id::Integer)::Union{Int, Nothing}
    target = UInt64(atom_id)
    for (i, atom) in enumerate(frame.atoms)
        if atom.atom_id == target
            return i
        end
    end
    return nothing
end

"""
    build_atom_id_index(frame::ConFrame) -> Dict{UInt64, Int}

Builds a fresh dictionary mapping `atom_id` to the 1-based position of
the atom inside `frame.atoms`.
"""
function build_atom_id_index(frame::ConFrame)::Dict{UInt64, Int}
    Dict{UInt64, Int}(atom.atom_id => i for (i, atom) in enumerate(frame.atoms))
end


"""Read all frames (batch). Prefer `read_con` for the same materialization path."""
function read_all_frames(path::String)::Vector{ConFrame}
    # ConFrame is a pure Julia value type (no native handle field). The C batch
    # API returns opaque handles; reuse the iterator path so materialization stays
    # consistent with `read_con`.
    return read_con(path)
end

"""Contiguous positions (N×3) via C ABI `rkr_frame_copy_positions`."""
function positions_matrix(frame::ConFrame)::Matrix{Float64}
    _with_frame_handle(frame) do handle
        n = Int(ccall(_lib_symbol(:rkr_frame_atom_count), Csize_t, (Ptr{Cvoid},), handle))
        n == 0 && return zeros(0, 3)
        buf = Vector{Float64}(undef, 3 * n)
        st = ccall(
            _lib_symbol(:rkr_frame_copy_positions),
            Cint,
            (Ptr{Cvoid}, Ptr{Float64}, Csize_t),
            handle,
            buf,
            length(buf),
        )
        _check_status(st, "rkr_frame_copy_positions")
        return permutedims(reshape(buf, 3, n))  # N×3
    end
end

function _section_matrix_3(frame::ConFrame, sym::Symbol)::Matrix{Float64}
    _with_frame_handle(frame) do handle
        n = Int(ccall(_lib_symbol(:rkr_frame_atom_count), Csize_t, (Ptr{Cvoid},), handle))
        n == 0 && return zeros(0, 3)
        buf = Vector{Float64}(undef, 3 * n)
        st = ccall(
            _lib_symbol(sym),
            Cint,
            (Ptr{Cvoid}, Ptr{Float64}, Csize_t),
            handle,
            buf,
            length(buf),
        )
        _check_status(st, String(sym))
        return permutedims(reshape(buf, 3, n))
    end
end

function velocities_matrix(frame::ConFrame)::Matrix{Float64}
    _section_matrix_3(frame, :rkr_frame_copy_velocities)
end

function forces_matrix(frame::ConFrame)::Matrix{Float64}
    _section_matrix_3(frame, :rkr_frame_copy_forces)
end

function masses_vector(frame::ConFrame)::Vector{Float64}
    _with_frame_handle(frame) do handle
        n = Int(ccall(_lib_symbol(:rkr_frame_atom_count), Csize_t, (Ptr{Cvoid},), handle))
        n == 0 && return Float64[]
        buf = Vector{Float64}(undef, n)
        st = ccall(
            _lib_symbol(:rkr_frame_copy_masses),
            Cint,
            (Ptr{Cvoid}, Ptr{Float64}, Csize_t),
            handle,
            buf,
            length(buf),
        )
        _check_status(st, "rkr_frame_copy_masses")
        return buf
    end
end

# --- Campaign index projection (readcon_core::index_proj via C ABI) ---

# Do-block friendly: `_with_frame_handle(frame) do h ... end`
function _with_frame_handle(f, frame::ConFrame)
    handle = _build_frame_handle(frame)
    try
        return f(handle)
    finally
        handle != C_NULL && ccall(_lib_symbol(:free_rkr_frame), Cvoid, (Ptr{Cvoid},), handle)
    end
end

"""Finite campaign energy (NaN → nothing); aligns with readcon-db energy index."""
function index_energy(frame::ConFrame)
    _with_frame_handle(h -> _maybe_float(ccall(_lib_symbol(:rkr_frame_index_energy), Float64, (Ptr{Cvoid},), h)), frame)
end

function composition_formula(frame::ConFrame)
    _with_frame_handle(h -> _take_string(ccall(_lib_symbol(:rkr_frame_composition_formula), Ptr{UInt8}, (Ptr{Cvoid},), h)), frame)
end

function total_mass(frame::ConFrame)
    _with_frame_handle(h -> _maybe_float(ccall(_lib_symbol(:rkr_frame_total_mass), Float64, (Ptr{Cvoid},), h)), frame)
end

function cell_volume(frame::ConFrame)
    _with_frame_handle(h -> _maybe_float(ccall(_lib_symbol(:rkr_frame_cell_volume), Float64, (Ptr{Cvoid},), h)), frame)
end

function fmax(frame::ConFrame)
    _with_frame_handle(h -> _maybe_float(ccall(_lib_symbol(:rkr_frame_fmax), Float64, (Ptr{Cvoid},), h)), frame)
end

function sections_mask(frame::ConFrame)
    _with_frame_handle(h -> ccall(_lib_symbol(:rkr_frame_sections_mask), UInt8, (Ptr{Cvoid},), h), frame)
end

function index_natoms(frame::ConFrame)
    _with_frame_handle(h -> ccall(_lib_symbol(:rkr_frame_index_natoms), UInt32, (Ptr{Cvoid},), h), frame)
end

function index_projection_json(frame::ConFrame)
    _with_frame_handle(h -> _take_string(ccall(_lib_symbol(:rkr_frame_index_projection_json), Ptr{UInt8}, (Ptr{Cvoid},), h)), frame)
end
