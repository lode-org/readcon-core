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
    _morton_encode(x, y, z, cell) -> UInt64

3D Morton (Z-order) encoder mirroring `readcon_core::types::morton_encode`.
Each axis is quantised to 10 bits over the simulation cell, then the
bits are interleaved so adjacent codes correspond to spatially-close
points.
"""
function _morton_encode(x::Float64, y::Float64, z::Float64,
                        cell::NTuple{3, Float64})::UInt64
    qx = UInt32(floor(clamp(x / cell[1], 0.0, 1.0) * 1023.0))
    qy = UInt32(floor(clamp(y / cell[2], 0.0, 1.0) * 1023.0))
    qz = UInt32(floor(clamp(z / cell[3], 0.0, 1.0) * 1023.0))
    res = UInt64(0)
    for i in 0:9
        res |= (UInt64(qx) & (UInt64(1) << i)) << (2 * i)
        res |= (UInt64(qy) & (UInt64(1) << i)) << (2 * i + 1)
        res |= (UInt64(qz) & (UInt64(1) << i)) << (2 * i + 2)
    end
    return res
end

"""
    morton_sort(frame::ConFrame) -> ConFrame

Returns a new `ConFrame` whose atoms have been sorted within each type
group by 3D Morton (Z-order) curve position. Type grouping is preserved;
only the order within each species changes.
"""
function morton_sort(frame::ConFrame)::ConFrame
    cell = frame.cell
    new_atoms = copy(frame.atoms)
    # The atom buffer is type-grouped; sort each group in place.
    offset = 1
    species_seen = String[]
    counts = Int[]
    for atom in new_atoms
        sym = String(_atomic_symbol(atom.atomic_number))
        idx = findfirst(==(sym), species_seen)
        if idx === nothing
            push!(species_seen, sym)
            push!(counts, 1)
        else
            counts[idx] += 1
        end
    end
    for count in counts
        view = @view new_atoms[offset:offset + count - 1]
        sort!(view, by = a -> _morton_encode(a.x, a.y, a.z, cell))
        offset += count
    end
    return ConFrame(
        frame.cell, frame.angles, new_atoms, frame.has_velocities,
        frame.prebox_header, frame.postbox_header,
        frame.has_forces, frame.has_energies,
        frame.spec_version, frame.metadata_json, frame.energy,
        frame.frame_index, frame.time, frame.timestep,
        frame.neb_bead, frame.neb_band,
    )
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
