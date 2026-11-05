The Python reader moves a parsed frame into its wrapper.
It no longer clones every atom on the GIL thread after the parallel parse.
