The bulk C API test frees each frame that `rkr_read_all_frames` returns.
It used to free only the first, and Miri reported the rest as leaked.
