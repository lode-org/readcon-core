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
    pkg_dir = dirname(dirname(@__DIR__))
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

const _LIB = Ref{String}("")

function _get_lib()
    if isempty(_LIB[])
        _LIB[] = _lib_handle()
    end
    return _LIB[]
end

"""
    read_con(path::String) -> Vector{ConFrame}

Read all frames from a .con or .convel file.
"""
function read_con(path::String)
    lib = _get_lib()

    iter_ptr = ccall(
        (:read_con_file_iterator, lib),
        Ptr{Cvoid}, (Cstring,), path
    )
    iter_ptr == C_NULL && error("Failed to open file: $path")

    frames = ConFrame[]

    try
        while true
            frame_handle = ccall(
                (:con_frame_iterator_next, lib),
                Ptr{Cvoid}, (Ptr{Cvoid},), iter_ptr
            )
            frame_handle == C_NULL && break

            try
                c_frame_ptr = ccall(
                    (:rkr_frame_to_c_frame, lib),
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
                            c_atom.vx, c_atom.vy, c_atom.vz,
                            c_atom.has_velocity,
                        ))
                    end

                    # Get header strings
                    prebox = _get_headers(lib, frame_handle, true)
                    postbox = _get_headers(lib, frame_handle, false)

                    push!(frames, ConFrame(
                        c_frame.cell, c_frame.angles,
                        atoms, c_frame.has_velocities,
                        prebox, postbox,
                    ))
                finally
                    ccall((:free_c_frame, lib), Cvoid, (Ptr{CFrame},), c_frame_ptr)
                end
            finally
                ccall((:free_rkr_frame, lib), Cvoid, (Ptr{Cvoid},), frame_handle)
            end
        end
    finally
        ccall((:free_con_frame_iterator, lib), Cvoid, (Ptr{Cvoid},), iter_ptr)
    end

    return frames
end

function _get_headers(lib, frame_handle, is_prebox::Bool)
    lines = String[]
    for idx in 0:1
        c_str = ccall(
            (:rkr_frame_get_header_line_cpp, lib),
            Ptr{UInt8}, (Ptr{Cvoid}, Bool, UInt), frame_handle, is_prebox, idx
        )
        if c_str != C_NULL
            s = unsafe_string(c_str)
            ccall((:rkr_free_string, lib), Cvoid, (Ptr{UInt8},), c_str)
            push!(lines, s)
        else
            push!(lines, "")
        end
    end
    return (lines[1], lines[2])
end

"""
    write_con(path::String, frames::Vector{ConFrame})

Write frames to a .con file. Frames must have been read via `read_con`.

Note: This writes through the FFI by first writing each frame via the
Rust writer. For the initial implementation, we serialize back to text
and use the Rust writer through the C API.
"""
function write_con(path::String, frames::Vector{ConFrame})
    # For a full FFI write, we would need to reconstruct RKRConFrame handles.
    # For now, use a simple approach: serialize to string via Rust
    # This requires reconstructing the text format, which is complex.
    # A simpler approach: write through the file-based API by roundtripping.
    error("write_con is not yet implemented for Julia. Use the Rust or Python API.")
end
