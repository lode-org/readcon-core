module ReadCon

include("types.jl")
include("wrapper.jl")

export Atom, ConFrame, read_con, write_con,
       atom_index_by_id, build_atom_id_index,
       has_chemfiles_support, select_on_frame, select_atom_indices, frame_bond_count

end # module
