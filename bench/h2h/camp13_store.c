/* Fresh-file stores at the camp12 byte counts.
 *
 * copy: the bytes are already hot and only the store is timed.
 * burn: each worker spends formatter-shaped work while it writes, so a
 * pre-fault has to beat faulting during that work.
 *
 * The clock is open, size, store, close, rename. The previous output is
 * unlinked outside the clock. A sample that fails exits non-zero.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef MADV_POPULATE_WRITE
#define MADV_POPULATE_WRITE 23
#endif
#ifndef MADV_HUGEPAGE
#define MADV_HUGEPAGE 14
#endif

enum {
    ST_MMAP = 1,
    ST_POPULATE,
    ST_MAP_POPULATE,
    ST_HUGE,
    ST_PWRITE,
    ST_SYNC,
    ST_DIRECT,
    ST_FALLOC_MMAP,
    ST_ANON_MMAP,
    ST_ANON_PWRITE,
    ST_FALLOC_ONCE,
    ST_FALLOC_PWRITE
};

struct job {
    int fd;
    int id;
    int store;
    int burn;
    size_t bytes;
    const unsigned char *src;
};

static volatile uint64_t g_sink;

static void die(const char *what) {
    fprintf(stderr, "%s: %s\n", what, strerror(errno));
    exit(1);
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static void pin(int id) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(id & 7, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

static void burn_copy(unsigned char *dst, const unsigned char *src, size_t n, int burn) {
    uint64_t x = 0x1234;
    size_t i = 0;
    while (i + 64 <= n) {
        for (int k = 0; k < burn; k++) {
            x = x * 1664525u + 1013904223u + src[i + (k & 63)];
        }
        memcpy(dst + i, src + i, 64);
        i += 64;
    }
    if (i < n) {
        memcpy(dst + i, src + i, n - i);
    }
    g_sink = x;
}

static void pwrite_all(int fd, const unsigned char *buf, size_t n, off_t offset) {
    size_t done = 0;
    while (done < n) {
        ssize_t wrote = pwrite(fd, buf + done, n - done, offset + (off_t)done);
        if (wrote < 0) {
            if (errno == EINTR) {
                continue;
            }
            die("pwrite");
        }
        done += (size_t)wrote;
    }
}

static void pwrite_direct(int fd, const unsigned char *buf, size_t n, off_t offset) {
    const size_t page = 4096;
    off_t start = offset;
    off_t end = offset + (off_t)n;
    off_t aligned_start = (start + (off_t)page - 1) & ~((off_t)page - 1);
    off_t aligned_end = end & ~((off_t)page - 1);
    if (start < aligned_start) {
        pwrite_all(fd, buf, (size_t)(aligned_start - start), start);
    }
    if (aligned_end > aligned_start) {
        size_t skip = (size_t)(aligned_start - start);
        size_t span = (size_t)(aligned_end - aligned_start);
        unsigned char *bounce = NULL;
        if (posix_memalign((void **)&bounce, page, span) != 0) {
            die("memalign");
        }
        memcpy(bounce, buf + skip, span);
        char link[64];
        snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
        int dfd = open(link, O_RDWR | O_DIRECT);
        if (dfd < 0) {
            pwrite_all(fd, buf + skip, span, aligned_start);
        } else {
            /* One syscall of tens of megabytes returns EINVAL here. */
            size_t at = 0;
            const size_t chunk = 1u << 20;
            while (at < span) {
                size_t step = span - at;
                if (step > chunk) {
                    step = chunk;
                }
                pwrite_all(dfd, bounce + at, step, aligned_start + (off_t)at);
                at += step;
            }
            close(dfd);
        }
        free(bounce);
    }
    if (end > aligned_end) {
        size_t skip = (size_t)(aligned_end - start);
        pwrite_all(fd, buf + skip, (size_t)(end - aligned_end), aligned_end);
    }
}

static void pwrite_sync(int fd, const unsigned char *buf, size_t n, off_t offset) {
    const size_t chunk = 1u << 20;
    size_t done = 0;
    off_t prev = -1;
    size_t prev_n = 0;
    while (done < n) {
        size_t step = n - done;
        if (step > chunk) {
            step = chunk;
        }
        pwrite_all(fd, buf + done, step, offset + (off_t)done);
        if (prev >= 0) {
            sync_file_range(fd, prev, (off_t)prev_n, SYNC_FILE_RANGE_WRITE);
        }
        prev = offset + (off_t)done;
        prev_n = step;
        done += step;
    }
    if (prev >= 0) {
        sync_file_range(fd, prev, (off_t)prev_n,
                        SYNC_FILE_RANGE_WAIT_BEFORE | SYNC_FILE_RANGE_WRITE |
                            SYNC_FILE_RANGE_WAIT_AFTER);
    }
}

/* Map the page-aligned cover of [offset, offset+bytes). The caller's
 * bytes start at the returned delta. Neighbouring workers share a
 * boundary page and write disjoint bytes of it. */
static unsigned char *map_cover(int fd, off_t offset, size_t bytes, size_t *delta,
                                size_t *map_len, int populate) {
    const size_t page = 4096;
    off_t map_off = offset & ~((off_t)page - 1);
    *delta = (size_t)(offset - map_off);
    *map_len = *delta + bytes;
    int flags = MAP_SHARED;
    if (populate) {
        flags |= MAP_POPULATE;
    }
    unsigned char *map =
        mmap(NULL, *map_len, PROT_READ | PROT_WRITE, flags, fd, map_off);
    if (map == MAP_FAILED) {
        die("mmap");
    }
    return map;
}

static void store_range(const struct job *job) {
    off_t offset = (off_t)job->id * (off_t)job->bytes;
    if (job->store == ST_PWRITE) {
        unsigned char *anon = NULL;
        if (posix_memalign((void **)&anon, 4096, job->bytes) != 0) {
            die("anon");
        }
        burn_copy(anon, job->src, job->bytes, job->burn);
        pwrite_all(job->fd, anon, job->bytes, offset);
        free(anon);
        return;
    }
    if (job->store == ST_SYNC) {
        unsigned char *anon = NULL;
        if (posix_memalign((void **)&anon, 4096, job->bytes) != 0) {
            die("anon");
        }
        burn_copy(anon, job->src, job->bytes, job->burn);
        pwrite_sync(job->fd, anon, job->bytes, offset);
        free(anon);
        return;
    }
    if (job->store == ST_DIRECT) {
        unsigned char *anon = NULL;
        if (posix_memalign((void **)&anon, 4096, job->bytes) != 0) {
            die("anon");
        }
        burn_copy(anon, job->src, job->bytes, job->burn);
        pwrite_direct(job->fd, anon, job->bytes, offset);
        free(anon);
        return;
    }
    if (job->store == ST_FALLOC_MMAP || job->store == ST_FALLOC_PWRITE) {
        if (fallocate(job->fd, 0, offset, (off_t)job->bytes) != 0) {
            die("fallocate");
        }
    }
    if (job->store == ST_FALLOC_PWRITE) {
        unsigned char *anon = NULL;
        if (posix_memalign((void **)&anon, 4096, job->bytes) != 0) {
            die("anon");
        }
        burn_copy(anon, job->src, job->bytes, job->burn);
        pwrite_all(job->fd, anon, job->bytes, offset);
        free(anon);
        return;
    }
    if (job->store == ST_ANON_MMAP || job->store == ST_ANON_PWRITE) {
        unsigned char *anon = NULL;
        if (posix_memalign((void **)&anon, 4096, job->bytes) != 0) {
            die("anon");
        }
        burn_copy(anon, job->src, job->bytes, job->burn);
        if (job->store == ST_ANON_PWRITE) {
            pwrite_all(job->fd, anon, job->bytes, offset);
        } else {
            size_t delta = 0;
            size_t map_len = 0;
            unsigned char *map = map_cover(job->fd, offset, job->bytes, &delta, &map_len, 0);
            memcpy(map + delta, anon, job->bytes);
            munmap(map, map_len);
        }
        free(anon);
        return;
    }
    size_t delta = 0;
    size_t map_len = 0;
    unsigned char *map =
        map_cover(job->fd, offset, job->bytes, &delta, &map_len, job->store == ST_MAP_POPULATE);
    if (job->store == ST_HUGE) {
        madvise(map, map_len, MADV_HUGEPAGE);
    }
    if (job->store == ST_POPULATE || job->store == ST_HUGE) {
        if (madvise(map, map_len, MADV_POPULATE_WRITE) != 0) {
            die("MADV_POPULATE_WRITE");
        }
    }
    burn_copy(map + delta, job->src, job->bytes, job->burn);
    munmap(map, map_len);
}

static void *thread_main(void *arg) {
    struct job *job = arg;
    pin(job->id);
    store_range(job);
    return NULL;
}

static int parse_store(const char *text) {
    if (strcmp(text, "mmap") == 0) return ST_MMAP;
    if (strcmp(text, "populate") == 0) return ST_POPULATE;
    if (strcmp(text, "map_populate") == 0) return ST_MAP_POPULATE;
    if (strcmp(text, "huge") == 0) return ST_HUGE;
    if (strcmp(text, "pwrite") == 0) return ST_PWRITE;
    if (strcmp(text, "sync") == 0) return ST_SYNC;
    if (strcmp(text, "direct") == 0) return ST_DIRECT;
    if (strcmp(text, "falloc_mmap") == 0) return ST_FALLOC_MMAP;
    if (strcmp(text, "anon_mmap") == 0) return ST_ANON_MMAP;
    if (strcmp(text, "anon_pwrite") == 0) return ST_ANON_PWRITE;
    if (strcmp(text, "falloc_once") == 0) return ST_FALLOC_ONCE;
    if (strcmp(text, "falloc_pwrite") == 0) return ST_FALLOC_PWRITE;
    fprintf(stderr, "unknown store %s\n", text);
    exit(2);
}

static double one_sample(int procs, int store, int burn, size_t bytes, int workers,
                         const unsigned char *src, const char *dir, unsigned long stamp) {
    char tmp[512];
    char dest[512];
    snprintf(tmp, sizeof(tmp), "%s/camp13-%d-%lu.tmp", dir, getpid(), stamp);
    snprintf(dest, sizeof(dest), "%s/camp13-%d.out", dir, getpid());
    unlink(dest);
    double started = now_s();
    int fd = open(tmp, O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        die("open");
    }
    size_t total = bytes * (size_t)workers;
    if (ftruncate(fd, (off_t)total) != 0) {
        die("ftruncate");
    }
    if (store == ST_FALLOC_ONCE && fallocate(fd, 0, 0, (off_t)total) != 0) {
        die("fallocate");
    }
    if (procs) {
        for (int id = 0; id < workers; id++) {
            pid_t child = fork();
            if (child < 0) {
                die("fork");
            }
            if (child == 0) {
                struct job job = {fd, id, store, burn, bytes, src};
                pin(id);
                store_range(&job);
                _exit(0);
            }
        }
        for (int id = 0; id < workers; id++) {
            int status = 0;
            if (wait(&status) < 0) {
                die("wait");
            }
            if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
                exit(2);
            }
        }
    } else {
        pthread_t threads[16];
        struct job jobs[16];
        for (int id = 0; id < workers; id++) {
            jobs[id] = (struct job){fd, id, store, burn, bytes, src};
            if (pthread_create(&threads[id], NULL, thread_main, &jobs[id]) != 0) {
                die("pthread");
            }
        }
        for (int id = 0; id < workers; id++) {
            pthread_join(threads[id], NULL);
        }
    }
    close(fd);
    if (rename(tmp, dest) != 0) {
        die("rename");
    }
    unlink(dest);
    return now_s() - started;
}

static int calibrate(size_t bytes) {
    /* One worker of CON text at the measured 0.76 GB/s. */
    double target = (double)bytes / 0.76e9;
    unsigned char *src = malloc(bytes);
    unsigned char *dst = malloc(bytes);
    if (src == NULL || dst == NULL) {
        die("malloc");
    }
    memset(src, 0x5a, bytes);
    int burn = 1;
    for (int step = 0; step < 12; step++) {
        double started = now_s();
        burn_copy(dst, src, bytes, burn);
        double elapsed = now_s() - started;
        if (elapsed >= target * 0.9 && elapsed <= target * 1.1) {
            break;
        }
        if (elapsed < 1e-4) {
            burn *= 2;
            continue;
        }
        double scale = target / elapsed;
        int next = (int)((double)burn * scale);
        if (next < 1) {
            next = 1;
        }
        if (next == burn) {
            break;
        }
        burn = next;
    }
    free(src);
    free(dst);
    return burn;
}

int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "calibrate") == 0) {
        size_t bytes = strtoull(argv[2], NULL, 10);
        int burn = calibrate(bytes);
        printf("burn=%d\n", burn);
        return 0;
    }
    if (argc != 8) {
        fprintf(stderr,
                "usage: camp13_store threads|procs STORE BYTES WORKERS REPEATS DIR BURN\n"
                "       camp13_store calibrate BYTES\n");
        return 2;
    }
    int procs = strcmp(argv[1], "procs") == 0;
    int store = parse_store(argv[2]);
    size_t bytes = strtoull(argv[3], NULL, 10);
    int workers = atoi(argv[4]);
    int repeats = atoi(argv[5]);
    const char *dir = argv[6];
    int burn = atoi(argv[7]);
    if (workers < 1 || workers > 8 || repeats < 1) {
        return 2;
    }
    unsigned char *src = malloc(bytes);
    if (src == NULL) {
        die("malloc");
    }
    memset(src, 0x5a, bytes);
    /* One warmup, then the recorded samples. */
    one_sample(procs, store, burn, bytes, workers, src, dir, 0);
    printf("samples=");
    for (int i = 0; i < repeats; i++) {
        double sample = one_sample(procs, store, burn, bytes, workers, src, dir, (unsigned)i + 1);
        if (i) {
            printf(",");
        }
        printf("%.6f", sample);
    }
    printf("\n");
    free(src);
    return 0;
}
