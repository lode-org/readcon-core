/* Copy an already-filled buffer into one fresh file.
 *
 * No readcon. N threads, or N processes, each write the same number of
 * bytes at a disjoint offset. The clock is create, set_len, store,
 * optional fsync, and rename. The previous file is unlinked first and
 * is not in the clock.
 *
 *   ceiling_store MODE STORE BYTES WORKERS REPEATS DIR FSYNC
 *
 * MODE is threads or procs. STORE is mmap, pwrite, populate, huge, or
 * populate_write. FSYNC is 0 or 1.
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
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef MADV_HUGEPAGE
#define MADV_HUGEPAGE 14
#endif
#ifndef MADV_POPULATE_WRITE
#define MADV_POPULATE_WRITE 23
#endif

enum store {
    STORE_MMAP = 0,
    STORE_PWRITE,
    STORE_POPULATE,
    STORE_HUGE,
    STORE_POPULATE_WRITE
};

struct job {
    int fd;
    int id;
    int store;
    size_t bytes;
    const unsigned char *src;
};

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static void pin(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

static void die(const char *what) {
    perror(what);
    exit(2);
}

static void store_range(const struct job *job) {
    size_t offset = (size_t)job->id * job->bytes;
    if (job->store == STORE_PWRITE) {
        size_t done = 0;
        while (done < job->bytes) {
            ssize_t n = pwrite(job->fd, job->src + done, job->bytes - done,
                               (off_t)(offset + done));
            if (n < 0) {
                if (errno == EINTR) {
                    continue;
                }
                die("pwrite");
            }
            if (n == 0) {
                die("pwrite short");
            }
            done += (size_t)n;
        }
        return;
    }
    int flags = MAP_SHARED;
    if (job->store == STORE_POPULATE) {
        flags |= MAP_POPULATE;
    }
    unsigned char *map = mmap(NULL, job->bytes, PROT_READ | PROT_WRITE, flags, job->fd,
                              (off_t)offset);
    if (map == MAP_FAILED) {
        die("mmap");
    }
    if (job->store == STORE_HUGE) {
        if (madvise(map, job->bytes, MADV_HUGEPAGE) != 0) {
            die("MADV_HUGEPAGE");
        }
    }
    if (job->store == STORE_POPULATE_WRITE || job->store == STORE_HUGE) {
        if (madvise(map, job->bytes, MADV_POPULATE_WRITE) != 0) {
            die("MADV_POPULATE_WRITE");
        }
    }
    memcpy(map, job->src, job->bytes);
    if (munmap(map, job->bytes) != 0) {
        die("munmap");
    }
}

static void *thread_main(void *arg) {
    struct job *job = arg;
    pin(job->id);
    store_range(job);
    return NULL;
}

static double one_sample(int procs, int store, size_t bytes, int workers, const unsigned char *src,
                         const char *dir, int do_fsync, unsigned long stamp) {
    char tmp[512];
    char dest[512];
    snprintf(tmp, sizeof(tmp), "%s/ceiling-%d-%lu.tmp", dir, getpid(), stamp);
    snprintf(dest, sizeof(dest), "%s/ceiling-%d.out", dir, getpid());
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
    if (procs) {
        for (int id = 0; id < workers; id++) {
            pid_t child = fork();
            if (child < 0) {
                die("fork");
            }
            if (child == 0) {
                struct job job = {fd, id, store, bytes, src};
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
        pthread_t threads[64];
        struct job jobs[64];
        if (workers > 64) {
            exit(2);
        }
        for (int id = 0; id < workers; id++) {
            jobs[id] = (struct job){fd, id, store, bytes, src};
            if (pthread_create(&threads[id], NULL, thread_main, &jobs[id]) != 0) {
                die("pthread_create");
            }
        }
        for (int id = 0; id < workers; id++) {
            pthread_join(threads[id], NULL);
        }
    }
    if (do_fsync && fsync(fd) != 0) {
        die("fsync");
    }
    close(fd);
    if (rename(tmp, dest) != 0) {
        die("rename");
    }
    return now_s() - started;
}

static int parse_store(const char *text) {
    if (strcmp(text, "mmap") == 0) {
        return STORE_MMAP;
    }
    if (strcmp(text, "pwrite") == 0) {
        return STORE_PWRITE;
    }
    if (strcmp(text, "populate") == 0) {
        return STORE_POPULATE;
    }
    if (strcmp(text, "huge") == 0) {
        return STORE_HUGE;
    }
    if (strcmp(text, "populate_write") == 0) {
        return STORE_POPULATE_WRITE;
    }
    fprintf(stderr, "unknown store %s\n", text);
    exit(2);
}

int main(int argc, char **argv) {
    if (argc != 8) {
        fprintf(stderr,
                "usage: ceiling_store threads|procs STORE BYTES WORKERS REPEATS DIR FSYNC\n");
        return 2;
    }
    int procs = strcmp(argv[1], "procs") == 0;
    if (!procs && strcmp(argv[1], "threads") != 0) {
        fprintf(stderr, "mode must be threads or procs\n");
        return 2;
    }
    int store = parse_store(argv[2]);
    size_t bytes = (size_t)strtoull(argv[3], NULL, 10);
    int workers = atoi(argv[4]);
    int repeats = atoi(argv[5]);
    const char *dir = argv[6];
    int do_fsync = atoi(argv[7]);
    if (bytes == 0 || workers < 1 || workers > 64 || repeats < 1) {
        return 2;
    }
    unsigned char *src = malloc(bytes);
    if (src == NULL) {
        die("malloc");
    }
    for (size_t i = 0; i < bytes; i++) {
        src[i] = (unsigned char)(i * 131u + 17u);
    }
    /* Fault the source once, outside the clock. */
    unsigned long sink = 0;
    for (size_t i = 0; i < bytes; i += 4096) {
        sink += src[i];
    }
    if (sink == 1) {
        fprintf(stderr, "sink\n");
    }
    one_sample(procs, store, bytes, workers, src, dir, do_fsync, 0);
    printf("samples=");
    for (int rep = 0; rep < repeats; rep++) {
        double elapsed = one_sample(procs, store, bytes, workers, src, dir, do_fsync,
                                    (unsigned long)(rep + 1));
        if (rep) {
            printf(",");
        }
        printf("%.6f", elapsed);
    }
    printf("\n");
    char dest[512];
    snprintf(dest, sizeof(dest), "%s/ceiling-%d.out", argv[6], getpid());
    unlink(dest);
    free(src);
    return 0;
}
