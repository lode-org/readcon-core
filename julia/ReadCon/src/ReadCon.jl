module ReadCon

include("types.jl")
include("wrapper.jl")

export Atom, ConFrame, read_con, write_con,
       atom_index_by_id, build_atom_id_index

end # module
