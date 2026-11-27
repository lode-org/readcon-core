Meson passes its C compiler on to cargo only when that command is not
plain cc. A ccache prefix is left off, extra arguments are kept, and
the linker variable is named for the cargo target.
