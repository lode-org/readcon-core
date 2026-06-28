module ReadCon

include("types.jl")
include("wrapper.jl")

export Atom, ConFrame, read_con, write_con,
       index_energy, composition_formula, total_mass, cell_volume, fmax,
       sections_mask, index_natoms, index_projection_json,
       atom_index_by_id, build_atom_id_index,
       has_chemfiles_support, select_on_frame, select_atom_indices, frame_bond_count

end # module
