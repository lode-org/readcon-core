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
    energy::Float64
    has_energy::Bool
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
    has_energies::Bool
end

_maybe_f64(::Nothing) = nothing
_maybe_f64(value::Real) = Float64(value)
_maybe_f64(value::NTuple{3, Real}) = Float64.(value)

"""
High-level Julia representation of a single atom.

`charge`, `spin`, `magmom`, `displacement`, and `spread` hold the optional
per-atom sections of the same names, or `nothing` when the frame has none.
Pass them as keywords to the full positional constructor.
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
    energy::Float64
    has_energy::Bool
    charge::Union{Nothing, Float64}
    spin::Union{Nothing, Float64}
    magmom::Union{Nothing, NTuple{3, Float64}}
    displacement::Union{Nothing, NTuple{3, Float64}}
    spread::Union{Nothing, NTuple{3, Float64}}

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
            0.0, false,
            nothing, nothing, nothing, nothing, nothing,
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
            0.0, false,
            nothing, nothing, nothing, nothing, nothing,
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
        energy::Float64,
        has_energy::Bool;
        charge::Union{Nothing, Real}=nothing,
        spin::Union{Nothing, Real}=nothing,
        magmom::Union{Nothing, NTuple{3, Real}}=nothing,
        displacement::Union{Nothing, NTuple{3, Real}}=nothing,
        spread::Union{Nothing, NTuple{3, Real}}=nothing,
    )
        new(
            atomic_number,
            x, y, z,
            atom_id, mass,
            is_fixed, fixed,
            vx, vy, vz, has_velocity,
            fx, fy, fz, has_forces,
            energy, has_energy,
            _maybe_f64(charge), _maybe_f64(spin),
            _maybe_f64(magmom), _maybe_f64(displacement), _maybe_f64(spread),
        )
    end
end

"""
    NonFiniteValue(field, value)

Thrown by every `ConFrame` constructor for a NaN or infinite entry of `cell`
or `angles`. `field` names the entry with the 1-based index Julia uses, for
example `"cell[2]"` or `"angles[3]"`, and `value` is the entry. No frame is
built.
"""
struct NonFiniteValue <: Exception
    field::String
    value::Float64
end

function Base.showerror(io::IO, err::NonFiniteValue)
    print(io, "NonFiniteValue: non-finite value: cell field ", err.field, " is ", err.value)
end

function _check_cell_finite(cell::NTuple{3, Float64}, angles::NTuple{3, Float64})
    for (name, values) in (("cell", cell), ("angles", angles))
        for (i, value) in enumerate(values)
            isfinite(value) || throw(NonFiniteValue("$name[$i]", value))
        end
    end
    return nothing
end

"""
High-level Julia representation of a simulation frame.

Every constructor throws [`NonFiniteValue`](@ref) for a NaN or infinite
`cell` or `angles` entry.
"""
struct ConFrame
    cell::NTuple{3, Float64}
    angles::NTuple{3, Float64}
    atoms::Vector{Atom}
    has_velocities::Bool
    prebox_header::NTuple{2, String}
    postbox_header::NTuple{2, String}
    has_forces::Bool
    has_energies::Bool
    spec_version::UInt32
    metadata_json::String
    energy::Union{Nothing, Float64}
    frame_index::Union{Nothing, UInt64}
    time::Union{Nothing, Float64}
    timestep::Union{Nothing, Float64}
    neb_bead::Union{Nothing, UInt64}
    neb_band::Union{Nothing, UInt64}

    function ConFrame(
        cell::NTuple{3, Float64},
        angles::NTuple{3, Float64},
        atoms::Vector{Atom},
        has_velocities::Bool,
        prebox_header::NTuple{2, String},
        postbox_header::NTuple{2, String},
    )
        _check_cell_finite(cell, angles)
        new(
            cell, angles, atoms, has_velocities,
            prebox_header, postbox_header, false, false,
            UInt32(2), "", nothing, nothing, nothing, nothing, nothing, nothing,
        )
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
        _check_cell_finite(cell, angles)
        new(
            cell, angles, atoms, has_velocities,
            prebox_header, postbox_header, has_forces, false,
            UInt32(2), "", nothing, nothing, nothing, nothing, nothing, nothing,
        )
    end

    function ConFrame(
        cell::NTuple{3, Float64},
        angles::NTuple{3, Float64},
        atoms::Vector{Atom},
        has_velocities::Bool,
        prebox_header::NTuple{2, String},
        postbox_header::NTuple{2, String},
        has_forces::Bool,
        has_energies::Bool,
        spec_version::UInt32,
        metadata_json::String,
        energy::Union{Nothing, Float64},
        frame_index::Union{Nothing, UInt64},
        time::Union{Nothing, Float64},
        timestep::Union{Nothing, Float64},
        neb_bead::Union{Nothing, UInt64},
        neb_band::Union{Nothing, UInt64},
    )
        _check_cell_finite(cell, angles)
        new(
            cell, angles, atoms, has_velocities,
            prebox_header, postbox_header, has_forces, has_energies,
            spec_version, metadata_json, energy, frame_index,
            time, timestep, neb_bead, neb_band,
        )
    end
end
