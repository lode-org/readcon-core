A corrupt chemfiles file that yields a frame with no coordinate storage no longer aborts the process.
Chemfiles 0.10 builds a slice from a null pointer in that case. The importer now checks the pointer and returns an error.
