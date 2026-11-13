Importing a chemfiles frame no longer allocates a name, a type, and a property map for every atom.
Repeated symbols share one string, and the name sidecar is stored only when a display name differs from the CON symbol.
A million-atom XYZ import stays within 1.3 times a raw chemfiles read.
