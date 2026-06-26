/**
 * Convenience header for metatensor-enabled C consumers of readcon-core.
 *
 * Include order matters: metatensor's cbindgen header defines `mts_block_t`
 * (typedef / incomplete struct) before readcon-core declares `rkr_*` that
 * take `mts_block_t *`. This is the sys-on-the-boundary include path.
 *
 * Link a readcon-core build with Cargo feature `metatensor` and libmetatensor.
 * After `cargo build --features metatensor`, see
 * `target/<profile>/readcon-metatensor.env` for INCLUDE and LIB_DIR.
 */
#ifndef READCON_METATENSOR_H
#define READCON_METATENSOR_H

/* metatensor-sys C ABI first (metatensor.h from READCON_METATENSOR_INCLUDE) */
#include <metatensor.h>

#ifndef READCON_CORE_HAS_METATENSOR
#define READCON_CORE_HAS_METATENSOR 1
#endif

#include "readcon-core.h"

#endif /* READCON_METATENSOR_H */
