Meson c_link_args are passed to cargo as rustc link arguments.
Flags other than -l are kept on the static archive. A shared
soname is still only applied to the cdylib.
