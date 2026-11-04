A failed populate hint no longer fails a mapped CON-bin read.
The mapping stays in place, and the pages fault on access.
When the mapping itself cannot be created, the file is read into a private mapping.
