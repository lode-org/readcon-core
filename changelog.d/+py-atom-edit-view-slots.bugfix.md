Python: editing an atom's velocity or force while a NumPy view of a
parsed column (`vel`, `frc`, `velocities_array`, `forces_array`) was
alive wrote into the view and left the atom pointing at memory freed with
the view. A later edit then corrupted the heap. The edit now moves the
frame's column and its atoms to a private copy first.
