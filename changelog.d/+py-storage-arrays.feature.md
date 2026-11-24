Python atom_ids_array, velocities_array, forces_array, vel, frc,
and mass_column read the parsed frame columns as read-only NumPy
views until .atoms is built. A store raises ValueError. Once the atom
list exists, those getters, composition_formula, len, and the other
getters follow that list, including an edit, a pop, an append, or an
insert. write_con writes the list and a metadata edit made before
.atoms exists. frame.symbols() returns a dtype-object NumPy array from
the interned FrameSymbols runs. ConFrameList.columns adds atom_ids,
atomic_numbers, and symbols. iter_con_string walks CON text the caller
already holds.
