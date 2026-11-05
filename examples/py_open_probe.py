"""Time one open-only ``read_con`` on the calling thread.

One untimed call runs first. The printed line is the timed call,
including the drop of the frames.
"""

import sys
import time

import readcon

path = sys.argv[1]
readcon.read_con(path, n_threads=1)
t0 = time.perf_counter()
frames = readcon.read_con(path, n_threads=1)
if hasattr(frames, "release_frames"):
    frames.release_frames()
else:
    del frames
print(f"{time.perf_counter() - t0:.9f}")
