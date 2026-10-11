/*
 * A CON 3.1 file reports con_spec_version from parsed metadata, and
 * writing that frame twice yields the same bytes.
 */
#include "readcon-core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char TEXT[] =
    "CON 3.1\n"
    "{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":"
    "\"eV\",\"mass\":\"amu\"}}\n"
    "10.000000 10.000000 10.000000\n"
    "90.000000 90.000000 90.000000\n"
    "\n"
    "\n"
    "1\n"
    "1\n"
    "1.007940\n"
    "H\n"
    "Coordinates of Component 1\n"
    "0.000000 0.000000 0.000000 0 0\n";

static int write_text(const char *path, const char *text) {
    FILE *file = fopen(path, "wb");
    if (!file) {
        return 1;
    }
    if (fputs(text, file) == EOF) {
        fclose(file);
        return 1;
    }
    return fclose(file) == 0 ? 0 : 1;
}

static char *slurp(const char *path, size_t *len) {
    FILE *file = fopen(path, "rb");
    if (!file) {
        return NULL;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return NULL;
    }
    long n = ftell(file);
    if (n < 0 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return NULL;
    }
    char *buf = malloc((size_t)n + 1);
    if (!buf) {
        fclose(file);
        return NULL;
    }
    if (fread(buf, 1, (size_t)n, file) != (size_t)n) {
        free(buf);
        fclose(file);
        return NULL;
    }
    fclose(file);
    buf[n] = '\0';
    *len = (size_t)n;
    return buf;
}

static int write_frame(const char *path, struct RKRConFrame *frame) {
    struct RKRConFrameWriter *writer = create_writer_from_path_c(path);
    if (!writer) {
        return 1;
    }
    const struct RKRConFrame *handles[1] = {frame};
    enum RKRStatus status = rkr_writer_extend(writer, handles, 1);
    rkr_writer_flush(writer);
    free_rkr_writer(writer);
    return status == RKR_STATUS_SUCCESS ? 0 : 1;
}

static int reports_major(struct RKRConFrame *frame) {
    if (rkr_frame_spec_version(frame) != 3) {
        fprintf(stderr, "spec_version is not 3\n");
        return 1;
    }
    char *json = rkr_frame_metadata_json(frame);
    if (!json || !strstr(json, "\"con_spec_version\":3")) {
        fprintf(stderr, "metadata json missing con_spec_version 3: %s\n", json ? json : "(null)");
        rkr_free_string(json);
        return 1;
    }
    rkr_free_string(json);
    return 0;
}

int main(void) {
    const char *src = "/tmp/readcon-spec-src.con";
    const char *first = "/tmp/readcon-spec-a.con";
    const char *second = "/tmp/readcon-spec-b.con";

    int rc = 1;
    if (write_text(src, TEXT) != 0) {
        fprintf(stderr, "failed to write source fixture\n");
        goto done;
    }
    struct RKRConFrame *frame = rkr_read_nth_frame(src, 0);
    if (!frame || reports_major(frame) != 0) {
        fprintf(stderr, "failed to read CON 3.1 fixture\n");
        free_rkr_frame(frame);
        goto done;
    }
    if (write_frame(first, frame) != 0) {
        fprintf(stderr, "first write failed\n");
        free_rkr_frame(frame);
        goto done;
    }
    free_rkr_frame(frame);

    frame = rkr_read_nth_frame(first, 0);
    if (!frame || reports_major(frame) != 0) {
        fprintf(stderr, "re-read lost con_spec_version\n");
        free_rkr_frame(frame);
        goto done;
    }
    if (write_frame(second, frame) != 0) {
        fprintf(stderr, "second write failed\n");
        free_rkr_frame(frame);
        goto done;
    }
    free_rkr_frame(frame);

    size_t n1 = 0;
    size_t n2 = 0;
    char *b1 = slurp(first, &n1);
    char *b2 = slurp(second, &n2);
    if (!b1 || !b2 || n1 != n2 || memcmp(b1, b2, n1) != 0) {
        fprintf(stderr, "write then read then write changed the bytes\n");
        free(b1);
        free(b2);
        goto done;
    }
    free(b1);
    free(b2);
    rc = 0;
    printf("c con_spec_version: OK\n");

done:
    remove(src);
    remove(first);
    remove(second);
    return rc;
}
