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
    fixed_x::Bool
    fixed_y::Bool
    fixed_z::Bool
    vx::Float64
    vy::Float64
    vz::Float64
    has_velocity::Bool
    fx::Float64
    fy::Float64
    fz::Float64
    has_forces::Bool
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
    has_forces::Bool
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
    fixed::NTuple{3, Bool}
    vx::Float64
    vy::Float64
    vz::Float64
    has_velocity::Bool
    fx::Float64
    fy::Float64
    fz::Float64
    has_forces::Bool

    function Atom(
        atomic_number::UInt64,
        x::Float64,
        y::Float64,
        z::Float64,
        atom_id::UInt64,
        mass::Float64,
        is_fixed::Bool,
        vx::Float64,
        vy::Float64,
        vz::Float64,
        has_velocity::Bool,
    )
        new(
            atomic_number,
            x, y, z,
            atom_id, mass,
            is_fixed, (is_fixed, is_fixed, is_fixed),
            vx, vy, vz, has_velocity,
            0.0, 0.0, 0.0, false,
        )
    end

    function Atom(
        atomic_number::UInt64,
        x::Float64,
        y::Float64,
        z::Float64,
        atom_id::UInt64,
        mass::Float64,
        is_fixed::Bool,
        fixed::NTuple{3, Bool},
        vx::Float64,
        vy::Float64,
        vz::Float64,
        has_velocity::Bool,
        fx::Float64,
        fy::Float64,
        fz::Float64,
        has_forces::Bool,
    )
        new(
            atomic_number,
            x, y, z,
            atom_id, mass,
            is_fixed, fixed,
            vx, vy, vz, has_velocity,
            fx, fy, fz, has_forces,
        )
    end
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
    has_forces::Bool

    function ConFrame(
        cell::NTuple{3, Float64},
        angles::NTuple{3, Float64},
        atoms::Vector{Atom},
        has_velocities::Bool,
        prebox_header::NTuple{2, String},
        postbox_header::NTuple{2, String},
    )
        new(cell, angles, atoms, has_velocities, prebox_header, postbox_header, false)
    end

    function ConFrame(
        cell::NTuple{3, Float64},
        angles::NTuple{3, Float64},
        atoms::Vector{Atom},
        has_velocities::Bool,
        prebox_header::NTuple{2, String},
        postbox_header::NTuple{2, String},
        has_forces::Bool,
    )
        new(cell, angles, atoms, has_velocities, prebox_header, postbox_header, has_forces)
    end
end
