The chemfiles scan follows the libstdc++ string ABI of the linked
libchemfiles. The prebuilt GCC 4.8 archive uses the old string, so an
atom is 80 bytes; a from-source build uses the cxx11 string, 128 bytes.
nm chooses the macro. A missing nm, both __cxx11 and ERKSs, or a
CXXFLAGS -D_GLIBCXX_USE_CXX11_ABI that disagrees, fails the build.
