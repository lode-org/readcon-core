/* Per-worker STREAM-style store.
 *
 * Each worker writes BYTES of its own buffer. The buffers are allocated
 * and the warmup pass runs before the timed samples, so a sample is the
 * store bandwidth, not the first fault. Workers are pinned to cores
 * 0..N-1. The printed time is the wall clock of the parallel stores.
 *
 *   stream_write threads|procs BYTES WORKERS REPEATS
 */
#define _GNU_SOURCE
#include <errno.h>
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

struct job {
    uint64_t *buf;
    size_t words;
    int id;
    pthread_barrier_t *gate;
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

static void store_words(uint64_t *buf, size_t words, uint64_t seed) {
    for (size_t i = 0; i < words; i++) {
        buf[i] = seed + i;
    }
    asm volatile("" ::"r"(buf) : "memory");
}

static void *thread_main(void *raw) {
    struct job *job = raw;
    pin(job->id);
    for (;;) {
        pthread_barrier_wait(job->gate);
        if (job->words == 0) {
            return NULL;
        }
        store_words(job->buf, job->words, (uint64_t)job->id + 1);
        pthread_barrier_wait(job->gate);
    }
}

static double run_threads(uint64_t **bufs, size_t words, int workers) {
    pthread_barrier_t gate;
    pthread_barrier_init(&gate, NULL, (unsigned)workers + 1);
    pthread_t threads[64];
    struct job jobs[64];
    for (int id = 0; id < workers; id++) {
        jobs[id] = (struct job){bufs[id], words, id, &gate};
        if (pthread_create(&threads[id], NULL, thread_main, &jobs[id]) != 0) {
            die("pthread_create");
        }
    }
    /* Warmup, untimed. */
    pthread_barrier_wait(&gate);
    pthread_barrier_wait(&gate);
    double t0 = now_s();
    pthread_barrier_wait(&gate);
    pthread_barrier_wait(&gate);
    double elapsed = now_s() - t0;
    for (int id = 0; id < workers; id++) {
        jobs[id].words = 0;
    }
    pthread_barrier_wait(&gate);
    for (int id = 0; id < workers; id++) {
        pthread_join(threads[id], NULL);
    }
    pthread_barrier_destroy(&gate);
    return elapsed;
}

static void run_procs(uint64_t **bufs, size_t words, int workers, int repeats) {
    int go_pipe[64][2];
    int done_pipe[64][2];
    for (int id = 0; id < workers; id++) {
        if (pipe(go_pipe[id]) != 0 || pipe(done_pipe[id]) != 0) {
            die("pipe");
        }
        pid_t child = fork();
        if (child < 0) {
            die("fork");
        }
        if (child == 0) {
            pin(id);
            close(go_pipe[id][1]);
            close(done_pipe[id][0]);
            for (;;) {
                char go = 0;
                if (read(go_pipe[id][0], &go, 1) != 1) {
                    _exit(0);
                }
                if (go == 'q') {
                    _exit(0);
                }
                store_words(bufs[id], words, (uint64_t)id + 1);
                if (write(done_pipe[id][1], "d", 1) != 1) {
                    _exit(2);
                }
            }
        }
        close(go_pipe[id][0]);
        close(done_pipe[id][1]);
    }
    /* Warmup, then the timed samples. The buffers are MAP_SHARED, so a
     * child store does not copy the page aside. */
    for (int rep = -1; rep < repeats; rep++) {
        double t0 = now_s();
        for (int id = 0; id < workers; id++) {
            if (write(go_pipe[id][1], "g", 1) != 1) {
                die("go");
            }
        }
        for (int id = 0; id < workers; id++) {
            char done = 0;
            if (read(done_pipe[id][0], &done, 1) != 1) {
                die("done");
            }
        }
        if (rep >= 0) {
            if (rep) {
                printf(",");
            }
            printf("%.6f", now_s() - t0);
        }
    }
    printf("\n");
    for (int id = 0; id < workers; id++) {
        if (write(go_pipe[id][1], "q", 1) != 1) {
            die("quit");
        }
        close(go_pipe[id][1]);
        close(done_pipe[id][0]);
        wait(NULL);
    }
}

int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "usage: stream_write threads|procs BYTES WORKERS REPEATS\n");
        return 2;
    }
    int procs = strcmp(argv[1], "procs") == 0;
    if (!procs && strcmp(argv[1], "threads") != 0) {
        fprintf(stderr, "mode must be threads or procs\n");
        return 2;
    }
    size_t bytes = (size_t)strtoull(argv[2], NULL, 10);
    int workers = atoi(argv[3]);
    int repeats = atoi(argv[4]);
    if (bytes < 8 || bytes % 8 != 0 || workers < 1 || workers > 64 || repeats < 1) {
        return 2;
    }
    size_t words = bytes / sizeof(uint64_t);
    uint64_t *bufs[64];
    for (int id = 0; id < workers; id++) {
        void *mem = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
        if (mem == MAP_FAILED) {
            die("mmap");
        }
        memset(mem, 0, bytes);
        bufs[id] = mem;
    }
    if (procs) {
        printf("samples=");
        run_procs(bufs, words, workers, repeats);
    } else {
        /* Threads are created per sample so each sample has one warmup
         * inside run_threads and one timed pass. That matches n timed
         * stores. */
        printf("samples=");
        for (int rep = 0; rep < repeats; rep++) {
            double elapsed = run_threads(bufs, words, workers);
            if (rep) {
                printf(",");
            }
            printf("%.6f", elapsed);
        }
    }
    printf("\n");
    for (int id = 0; id < workers; id++) {
        munmap(bufs[id], bytes);
    }
    return 0;
}
