/* Time one open of an in-memory buffer and a walk of its frames.
 * usage: c_iter_bench buffer|string FILE ITERS
 * prints: name ns iters
 */
#define _POSIX_C_SOURCE 199309L
#include "readcon-core.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static long long now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static char *read_file(const char *path, size_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    long n = ftell(f);
    if (n < 0) {
        fclose(f);
        return NULL;
    }
    rewind(f);
    char *buf = (char *)malloc((size_t)n + 1);
    if (!buf) {
        fclose(f);
        return NULL;
    }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) {
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    buf[n] = 0;
    *len = (size_t)n;
    return buf;
}

static size_t walk_buffer(const uint8_t *data, size_t len) {
    CConFrameIterator *it = read_con_buffer_iterator(data, len);
    size_t n = 0;
    if (!it)
        return 0;
    for (;;) {
        RKRConFrame *frame = con_frame_iterator_next(it);
        if (!frame)
            break;
        n += rkr_frame_index_natoms(frame);
        free_rkr_frame(frame);
    }
    free_con_frame_iterator(it);
    return n;
}

static size_t walk_string(const char *text) {
    CConFrameIterator *it = read_con_string_iterator(text);
    size_t n = 0;
    if (!it)
        return 0;
    for (;;) {
        RKRConFrame *frame = con_frame_iterator_next(it);
        if (!frame)
            break;
        n += rkr_frame_index_natoms(frame);
        free_rkr_frame(frame);
    }
    free_con_frame_iterator(it);
    return n;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s buffer|string FILE ITERS\n", argv[0]);
        return 2;
    }
    size_t len = 0;
    char *text = read_file(argv[2], &len);
    if (!text) {
        perror(argv[2]);
        return 1;
    }
    int iters = atoi(argv[3]);
    if (iters < 1)
        iters = 1;
    volatile size_t sink = 0;
    long long t0 = now_ns();
    for (int i = 0; i < iters; i++) {
        if (strcmp(argv[1], "string") == 0)
            sink += walk_string(text);
        else
            sink += walk_buffer((const uint8_t *)text, len);
    }
    long long dt = now_ns() - t0;
    printf("c_%s %lld %d\n", argv[1], dt, iters);
    if (sink == 0)
        fprintf(stderr, "no atoms\n");
    free(text);
    return sink == 0 ? 1 : 0;
}
