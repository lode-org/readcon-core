#include <metatensor.h>
#include <stdint.h>
#include <string.h>

int bench_block_shape(
    struct mts_block_t *block,
    size_t *rows,
    size_t *columns
) {
    mts_array_t array;
    memset(&array, 0, sizeof(array));
    if (mts_block_data(block, &array) != MTS_SUCCESS || array.shape == NULL) {
        return 1;
    }
    const uintptr_t *shape = NULL;
    uintptr_t count = 0;
    if (array.shape(array.ptr, &shape, &count) != MTS_SUCCESS || count != 2) {
        return 2;
    }
    *rows = (size_t)shape[0];
    *columns = (size_t)shape[1];
    return 0;
}

int bench_block_copy_f64(
    struct mts_block_t *block,
    double *output,
    size_t output_count
) {
    mts_array_t array;
    memset(&array, 0, sizeof(array));
    if (mts_block_data(block, &array) != MTS_SUCCESS || array.as_dlpack == NULL) {
        return 1;
    }

    DLManagedTensorVersioned *managed = NULL;
    DLDevice cpu = {kDLCPU, 0};
    DLPackVersion version = {DLPACK_MAJOR_VERSION, DLPACK_MINOR_VERSION};
    if (array.as_dlpack(array.ptr, &managed, cpu, NULL, version) != MTS_SUCCESS ||
        managed == NULL) {
        return 2;
    }

    DLTensor *tensor = &managed->dl_tensor;
    size_t count = 1;
    for (int32_t axis = 0; axis < tensor->ndim; axis++) {
        count *= (size_t)tensor->shape[axis];
    }
    int status = 0;
    if (tensor->device.device_type != kDLCPU ||
        tensor->dtype.code != kDLFloat ||
        tensor->dtype.bits != 64 ||
        tensor->dtype.lanes != 1 ||
        count != output_count ||
        tensor->data == NULL) {
        status = 3;
    } else {
        const char *data = (const char *)tensor->data + tensor->byte_offset;
        memcpy(output, data, count * sizeof(double));
    }
    managed->deleter(managed);
    return status;
}
