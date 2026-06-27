const Libdl = Base.Libc.Libdl

"""
    _lib_handle()

Return a handle to the readcon-core shared library.
Searches READCON_LIB_PATH environment variable first, then falls back
to a local build path.
"""
function _lib_handle()
    lib_env = get(ENV, "READCON_LIB_PATH", "")
    if !isempty(lib_env) && isfile(lib_env)
        return lib_env
    end
    # Fall back to looking relative to this package
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
    error("Cannot find libreadcon_core. Set READCON_LIB_PATH or build with cargo build --release.")
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

function _check_status(status::Cint, operation::String)
    status == RKR_STATUS_SUCCESS && return nothing
    error("$operation: $(_status_message(status))")
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
        "select_on_frame requires libreadcon_core built with --features chemfiles"
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
        result_handle == C_NULL && error("rkr_frame_select returned null result")
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
    iter_ptr == C_NULL && error("Failed to open file: $path")

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

                    atoms = Atom[]
                    for i in 1:c_frame.num_atoms
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
                            c_atom.energy, c_atom.has_energy,
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
    write_con(path::String, frames::Vector{ConFrame}; precision=6)

Write frames to a .con file.
"""
function write_con(path::String, frames::Vector{ConFrame}; precision::Integer=6)
    writer = if precision == 6
        ccall(_lib_symbol(:create_writer_from_path_c), Ptr{Cvoid}, (Cstring,), path)
    else
        ccall(
            _lib_symbol(:create_writer_from_path_with_precision_c),
            Ptr{Cvoid}, (Cstring, UInt8), path, UInt8(precision)
        )
    end
    writer == C_NULL && error("failed to create writer for file: $path")

    handles = Ptr{Cvoid}[]
    try
        for frame in frames
            push!(handles, _build_frame_handle(frame))
        end
        status = ccall(
            _lib_symbol(:rkr_writer_extend),
            Cint, (Ptr{Cvoid}, Ptr{Ptr{Cvoid}}, Csize_t),
            writer, handles, length(handles)
        )
        _check_status(status, "failed to write frames")
        return nothing
    finally
        for handle in handles
            handle != C_NULL && ccall(_lib_symbol(:free_rkr_frame), Cvoid, (Ptr{Cvoid},), handle)
        end
        ccall(_lib_symbol(:free_rkr_writer), Cvoid, (Ptr{Cvoid},), writer)
    end
end

function _build_frame_handle(frame::ConFrame)
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
    builder == C_NULL && error("failed to create frame builder")

    try
        if !isempty(frame.metadata_json)
            status = ccall(
                _lib_symbol(:rkr_frame_builder_set_metadata_json),
                Cint, (Ptr{Cvoid}, Cstring), builder, frame.metadata_json
            )
            _check_status(status, "failed to set frame metadata")
        end

        for atom in frame.atoms
            _add_atom(builder, atom)
        end

        handle = ccall(_lib_symbol(:rkr_frame_builder_build), Ptr{Cvoid}, (Ptr{Cvoid},), builder)
        builder = C_NULL
        handle == C_NULL && error("failed to build frame")
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


"""Read all frames (batch). Prefer `read_con` for lazy iteration."""
function read_all_frames(path::String)::Vector{ConFrame}
    frames = ConFrame[]
    n = Ref{UInt}(0)
    arr = ccall(_lib_symbol(:rkr_read_all_frames), Ptr{Ptr{Cvoid}}, (Cstring, Ref{UInt}), path, n)
    arr == C_NULL && return frames
    nn = Int(n[])
    ptrs = unsafe_wrap(Array, arr, nn; own=false)
    for i in 1:nn
        push!(frames, ConFrame(ptrs[i]; own=true))
    end
    # pointer array not freed (handles owned by ConFrame); acceptable for ergonomics path
    return frames
end

"""Contiguous positions (N×3) without AoS CFrame materialization."""
function positions_matrix(frame::ConFrame)::Matrix{Float64}
    n = Int(ccall(_lib_symbol(:rkr_frame_atom_count), Csize_t, (Ptr{Cvoid},), frame.handle))
    n == 0 && return zeros(0, 3)
    buf = Vector{Float64}(undef, 3 * n)
    st = ccall(_lib_symbol(:rkr_frame_copy_positions), Cint, (Ptr{Cvoid}, Ptr{Float64}, Csize_t),
               frame.handle, buf, length(buf))
    _check_status(st, "rkr_frame_copy_positions")
    return permutedims(reshape(buf, 3, n))  # N×3
end
