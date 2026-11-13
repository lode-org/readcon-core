/* XTC through libxtc's unpack_frame, the C++ kernel of its XTCReader, with the
 * framing of libxtc/__init__.py: a 56-byte header (magic, atoms, step, time,
 * box, atoms), then for more than nine atoms the 36-byte block of precision,
 * minint, maxint, smallidx and byte count, then the payload padded to four
 * bytes, read into a buffer whose length is rounded up to eight bytes as
 * unpack_frame requires.  frame_data.nt is THREADS; the kernel runs that many
 * OpenMP threads, at most the processor count.
 */
#include "bf_driver.h"

#include <vector>

#include "xtc_unpack.h"

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static float be_float(const unsigned char *p) {
    uint32_t u = be32(p);
    float f;
    memcpy(&f, &u, sizeof f);
    return f;
}

struct Reader {
    FILE *fp;
    frame_data fd;
    std::vector<uint64_t> packed;
    int natoms = 0;

    /* The next frame into `x`, which holds 3 * natoms floats; false at the end of the file. */
    bool next(float *x, double lengths[3]) {
        unsigned char head[56];
        size_t got = fread(head, 1, sizeof head, fp);
        if (got == 0) return false;
        if (got != sizeof head || be32(head) != 1995u) bf_die("bad XTC frame header");
        int atoms = (int)be32(head + 4);
        if (atoms != natoms) bf_die("the atom count changed between frames");
        for (int k = 0; k < 3; k++) lengths[k] = be_float(head + 16 + 16 * k);
        uint32_t lsize = be32(head + 52);
        if (lsize <= 9) {
            unsigned char raw[9 * 12];
            if (fread(raw, 1, lsize * 12u, fp) != lsize * 12u) bf_die("short XTC frame");
            for (uint32_t i = 0; i < 3 * lsize; i++) x[i] = be_float(raw + 4 * i);
            return true;
        }
        unsigned char block[36];
        if (fread(block, 1, sizeof block, fp) != sizeof block) bf_die("short XTC frame");
        int32_t ints[8];
        for (int i = 0; i < 8; i++) ints[i] = (int32_t)be32(block + 4 + 4 * i);
        uint32_t datalen = ((uint32_t)ints[7] + 3u) & ~3u;
        size_t count8 = ((size_t)datalen + 7u) & ~(size_t)7u;
        if (packed.size() < count8 / 8) packed.resize(count8 / 8);
        unsigned char *bytes = reinterpret_cast<unsigned char *>(packed.data());
        if (fread(bytes, 1, datalen, fp) != datalen) bf_die("short XTC payload");
        memset(bytes + datalen, 0, count8 - datalen);
        fd.inv_p = 1.0f / be_float(block);
        for (int k = 0; k < 3; k++) {
            fd.minint[k] = ints[k];
            fd.maxint[k] = ints[3 + k];
        }
        fd.smli = (uint32_t)ints[6];
        fd.natoms = natoms;
        if (!unpack_frame(fd, packed.data(), x)) bf_die("unpack_frame failed");
        return true;
    }
};

int main(int argc, char **argv) {
    BfRun run;
    bf_args(argc, argv, &run);

    double t0 = bf_now();
    Reader reader;
    reader.fp = fopen(run.path, "rb");
    if (!reader.fp) bf_die("cannot open the XTC file");
    memset(&reader.fd, 0, sizeof reader.fd);
    reader.fd.nt = run.threads;
    unsigned char head[8];
    if (fread(head, 1, sizeof head, reader.fp) != sizeof head) bf_die("empty XTC file");
    reader.natoms = (int)be32(head + 4);
    if (reader.natoms < 1) bf_die("no atoms");
    rewind(reader.fp);
    const size_t floats = 3 * (size_t)reader.natoms;
    double lengths[3];
    if (run.mode == BF_FRAMES_MODE) {
        float *x = (float *)malloc(floats * sizeof(float));
        if (!x) bf_die("out of memory");
        while (reader.next(x, lengths)) bf_frame_xyz(&run, x, reader.natoms, lengths, 10.0);
        free(x);
    } else {
        std::vector<float *> frames;
        std::vector<double> held;
        for (;;) {
            float *x = (float *)malloc(floats * sizeof(float));
            if (!x) bf_die("out of memory");
            if (!reader.next(x, lengths)) {
                free(x);
                break;
            }
            frames.push_back(x);
            held.insert(held.end(), lengths, lengths + 3);
        }
        for (size_t f = 0; f < frames.size(); f++) bf_frame_xyz(&run, frames[f], reader.natoms, &held[3 * f], 10.0);
        for (float *x : frames) free(x);
    }
    fclose(reader.fp);
    bf_report(&run, bf_now() - t0);
    return 0;
}
