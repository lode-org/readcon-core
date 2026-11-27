Armv7 Android links libc++. The androideabi triple has no android
component, and a Linux host does not put its libstdc++ directory on
LIBRARY_PATH for an Android cargo target.
