On free-threaded Python, threads sharing one `ConFrame`, its `frame.atoms`, its atom views, or an `Atom` from it wait for each other instead of panicking with `Already mutably borrowed`.
A call that reenters a frame its own thread is still editing raises `RuntimeError`, as it does with the GIL.
