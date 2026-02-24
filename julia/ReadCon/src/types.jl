"""
Julia struct mirroring the C `CAtom` from readcon-core.h.
"""
struct CAtom
    atomic_number::UInt64
    x::Float64
    y::Float64
    z::Float64
    atom_id::UInt64
    mass::Float64
    is_fixed::Bool
    vx::Float64
    vy::Float64
    vz::Float64
    has_velocity::Bool
end

"""
Julia struct mirroring the C `CFrame` from readcon-core.h.
"""
struct CFrame
    atoms::Ptr{CAtom}
    num_atoms::UInt
    cell::NTuple{3, Float64}
    angles::NTuple{3, Float64}
    has_velocities::Bool
end

"""
High-level Julia representation of a single atom.
"""
struct Atom
    atomic_number::UInt64
    x::Float64
    y::Float64
    z::Float64
    atom_id::UInt64
    mass::Float64
    is_fixed::Bool
    vx::Float64
    vy::Float64
    vz::Float64
    has_velocity::Bool
end

"""
High-level Julia representation of a simulation frame.
"""
struct ConFrame
    cell::NTuple{3, Float64}
    angles::NTuple{3, Float64}
    atoms::Vector{Atom}
    has_velocities::Bool
    prebox_header::NTuple{2, String}
    postbox_header::NTuple{2, String}
end
