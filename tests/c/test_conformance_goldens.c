/*
 * Phase A corpus lock: C reads the same goldens as the Python harness.
 * Valid fixtures match symbols, atom_ids, fixed, and positions.
 * Invalid fixtures must fail to parse (typed FFI codes are not required).
 */
#include "readcon-core.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_CASES 64
#define MAX_ID 128
#define MAX_PATH 256
#define MAX_SYM 16
#define POS_ABS_TOL 1e-12

typedef struct {
    char id[MAX_ID];
    char path[MAX_PATH];
    int valid; /* 1 valid, 0 invalid */
} Case;

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        return NULL;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    long n = ftell(f);
    if (n < 0) {
        fclose(f);
        return NULL;
    }
    if (fseek(f, 0, SEEK_SET) != 0) {
        fclose(f);
        return NULL;
    }
    char *buf = (char *)malloc((size_t)n + 1);
    if (!buf) {
        fclose(f);
        return NULL;
    }
    size_t got = fread(buf, 1, (size_t)n, f);
    fclose(f);
    buf[got] = '\0';
    return buf;
}

static void unquote_into(const char *raw, char *out, size_t out_n) {
    size_t len = strlen(raw);
    if (len >= 2 && raw[0] == '"' && raw[len - 1] == '"') {
        if (len - 1 >= out_n) {
            len = out_n;
        } else {
            len = len - 1;
        }
        memcpy(out, raw + 1, len - 1);
        out[len - 1] = '\0';
        return;
    }
    strncpy(out, raw, out_n - 1);
    out[out_n - 1] = '\0';
}

static int parse_manifest(const char *text, Case *cases, int max_cases) {
    int n = 0;
    const char *p = text;
    Case *cur = NULL;
    while (*p) {
        const char *eol = strchr(p, '\n');
        size_t linelen = eol ? (size_t)(eol - p) : strlen(p);
        char line[512];
        if (linelen >= sizeof(line)) {
            linelen = sizeof(line) - 1;
        }
        memcpy(line, p, linelen);
        line[linelen] = '\0';
        char *s = line;
        while (*s && isspace((unsigned char)*s)) {
            s++;
        }
        size_t slen = strlen(s);
        while (slen > 0 && isspace((unsigned char)s[slen - 1])) {
            s[--slen] = '\0';
        }
        if (s[0] == '\0' || s[0] == '#') {
            p = eol ? eol + 1 : p + linelen;
            continue;
        }
        if (strcmp(s, "[[valid]]") == 0 || strcmp(s, "[[invalid]]") == 0) {
            if (n >= max_cases) {
                fprintf(stderr, "too many manifest cases\n");
                return -1;
            }
            cur = &cases[n++];
            memset(cur, 0, sizeof(*cur));
            cur->valid = (strcmp(s, "[[valid]]") == 0);
            p = eol ? eol + 1 : p + linelen;
            continue;
        }
        if (cur) {
            char *eq = strchr(s, '=');
            if (eq) {
                *eq = '\0';
                char *key = s;
                char *val = eq + 1;
                while (*key && isspace((unsigned char)*key)) {
                    key++;
                }
                size_t klen = strlen(key);
                while (klen > 0 && isspace((unsigned char)key[klen - 1])) {
                    key[--klen] = '\0';
                }
                while (*val && isspace((unsigned char)*val)) {
                    val++;
                }
                size_t vlen = strlen(val);
                while (vlen > 0 && isspace((unsigned char)val[vlen - 1])) {
                    val[--vlen] = '\0';
                }
                if (strcmp(key, "id") == 0) {
                    unquote_into(val, cur->id, sizeof(cur->id));
                } else if (strcmp(key, "path") == 0) {
                    unquote_into(val, cur->path, sizeof(cur->path));
                }
            }
        }
        p = eol ? eol + 1 : p + linelen;
    }
    return n;
}

static const char *skip_ws(const char *p) {
    while (p && *p && isspace((unsigned char)*p)) {
        p++;
    }
    return p;
}

static const char *find_key(const char *json, const char *key) {
    char pat[160];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p) {
        return NULL;
    }
    p = strchr(p + strlen(pat), ':');
    if (!p) {
        return NULL;
    }
    return skip_ws(p + 1);
}

static int parse_json_string(const char *p, char *out, size_t out_n) {
    p = skip_ws(p);
    if (!p || *p != '"') {
        return -1;
    }
    p++;
    size_t i = 0;
    while (*p && *p != '"') {
        if (i + 1 >= out_n) {
            return -1;
        }
        out[i++] = *p++;
    }
    if (*p != '"') {
        return -1;
    }
    out[i] = '\0';
    return 0;
}

static int parse_json_int(const char *p, long *out) {
    p = skip_ws(p);
    if (!p) {
        return -1;
    }
    char *end = NULL;
    long v = strtol(p, &end, 10);
    if (end == p) {
        return -1;
    }
    *out = v;
    return 0;
}

static const char *parse_json_number(const char *p, double *out) {
    p = skip_ws(p);
    if (!p) {
        return NULL;
    }
    char *end = NULL;
    *out = strtod(p, &end);
    if (end == p) {
        return NULL;
    }
    return end;
}

static const char *parse_json_bool(const char *p, int *out) {
    p = skip_ws(p);
    if (!p) {
        return NULL;
    }
    if (strncmp(p, "true", 4) == 0) {
        *out = 1;
        return p + 4;
    }
    if (strncmp(p, "false", 5) == 0) {
        *out = 0;
        return p + 5;
    }
    return NULL;
}

typedef struct {
    char id[MAX_ID];
    long n_atoms;
    long spec_version;
    int (*fixed)[3];
    double (*positions)[3];
    unsigned long long *atom_ids;
    char (*symbols)[MAX_SYM];
} Golden;

static void free_golden(Golden *g) {
    free(g->fixed);
    free(g->positions);
    free(g->atom_ids);
    free(g->symbols);
    memset(g, 0, sizeof(*g));
}

static int parse_golden(const char *json, Golden *g) {
    memset(g, 0, sizeof(*g));
    const char *p;
    if (!(p = find_key(json, "id")) || parse_json_string(p, g->id, sizeof(g->id)) != 0) {
        return -1;
    }
    if (!(p = find_key(json, "n_atoms")) || parse_json_int(p, &g->n_atoms) != 0) {
        return -1;
    }
    if (!(p = find_key(json, "spec_version")) || parse_json_int(p, &g->spec_version) != 0) {
        return -1;
    }
    if (g->n_atoms < 0 || g->n_atoms > 1024) {
        return -1;
    }
    size_t n = (size_t)g->n_atoms;
    g->fixed = (int (*)[3])calloc(n, sizeof(*g->fixed));
    g->positions = (double (*)[3])calloc(n, sizeof(*g->positions));
    g->atom_ids = (unsigned long long *)calloc(n, sizeof(*g->atom_ids));
    g->symbols = (char (*)[MAX_SYM])calloc(n, sizeof(*g->symbols));
    if (!g->fixed || !g->positions || !g->atom_ids || !g->symbols) {
        free_golden(g);
        return -1;
    }

    p = find_key(json, "fixed");
    p = skip_ws(p);
    if (!p || *p != '[') {
        free_golden(g);
        return -1;
    }
    p = skip_ws(p + 1);
    for (size_t i = 0; i < n; i++) {
        p = skip_ws(p);
        if (*p == ',') {
            p = skip_ws(p + 1);
        }
        if (*p != '[') {
            free_golden(g);
            return -1;
        }
        p = skip_ws(p + 1);
        for (int k = 0; k < 3; k++) {
            if (k > 0) {
                p = skip_ws(p);
                if (*p == ',') {
                    p = skip_ws(p + 1);
                }
            }
            int bit = 0;
            p = parse_json_bool(p, &bit);
            if (!p) {
                free_golden(g);
                return -1;
            }
            g->fixed[i][k] = bit;
        }
        p = skip_ws(p);
        if (*p != ']') {
            free_golden(g);
            return -1;
        }
        p = skip_ws(p + 1);
    }

    p = find_key(json, "positions");
    p = skip_ws(p);
    if (!p || *p != '[') {
        free_golden(g);
        return -1;
    }
    p = skip_ws(p + 1);
    for (size_t i = 0; i < n; i++) {
        p = skip_ws(p);
        if (*p == ',') {
            p = skip_ws(p + 1);
        }
        if (*p != '[') {
            free_golden(g);
            return -1;
        }
        p = skip_ws(p + 1);
        for (int k = 0; k < 3; k++) {
            if (k > 0) {
                p = skip_ws(p);
                if (*p == ',') {
                    p = skip_ws(p + 1);
                }
            }
            p = parse_json_number(p, &g->positions[i][k]);
            if (!p) {
                free_golden(g);
                return -1;
            }
        }
        p = skip_ws(p);
        if (*p != ']') {
            free_golden(g);
            return -1;
        }
        p = skip_ws(p + 1);
    }

    p = find_key(json, "atom_ids");
    p = skip_ws(p);
    if (!p || *p != '[') {
        free_golden(g);
        return -1;
    }
    p = skip_ws(p + 1);
    for (size_t i = 0; i < n; i++) {
        p = skip_ws(p);
        if (*p == ',') {
            p = skip_ws(p + 1);
        }
        char *end = NULL;
        g->atom_ids[i] = strtoull(p, &end, 10);
        if (end == p) {
            free_golden(g);
            return -1;
        }
        p = end;
    }

    p = find_key(json, "symbols");
    p = skip_ws(p);
    if (!p || *p != '[') {
        free_golden(g);
        return -1;
    }
    p = skip_ws(p + 1);
    for (size_t i = 0; i < n; i++) {
        p = skip_ws(p);
        if (*p == ',') {
            p = skip_ws(p + 1);
        }
        if (parse_json_string(p, g->symbols[i], MAX_SYM) != 0) {
            free_golden(g);
            return -1;
        }
        if (*p != '"') {
            free_golden(g);
            return -1;
        }
        p++;
        while (*p && *p != '"') {
            p++;
        }
        if (*p == '"') {
            p++;
        }
    }
    return 0;
}

static int failf(int *nfail, const char *fmt, const char *a) {
    fprintf(stderr, "FAIL: ");
    fprintf(stderr, fmt, a);
    fprintf(stderr, "\n");
    (*nfail)++;
    return 1;
}

static int check_valid(const char *root, const Case *c) {
    char fixture[1024];
    char golden_path[1024];
    snprintf(fixture, sizeof(fixture), "%s/resources/conformance/%s", root, c->path);
    snprintf(golden_path, sizeof(golden_path), "%s/resources/conformance/golden/%s.json", root,
             c->id);

    RKRConFrame *frame = rkr_read_first_frame(fixture);
    if (!frame) {
        fprintf(stderr, "FAIL %s: valid fixture failed to parse\n", c->id);
        return 1;
    }
    CFrame *cf = rkr_frame_to_c_frame(frame);
    if (!cf) {
        fprintf(stderr, "FAIL %s: rkr_frame_to_c_frame returned NULL\n", c->id);
        free_rkr_frame(frame);
        return 1;
    }

    char *gtext = slurp(golden_path);
    if (!gtext) {
        fprintf(stderr, "FAIL %s: missing golden %s\n", c->id, golden_path);
        free_c_frame(cf);
        free_rkr_frame(frame);
        return 1;
    }
    Golden g;
    if (parse_golden(gtext, &g) != 0) {
        fprintf(stderr, "FAIL %s: golden JSON parse failed\n", c->id);
        free(gtext);
        free_c_frame(cf);
        free_rkr_frame(frame);
        return 1;
    }
    free(gtext);

    int nfail = 0;
    if (strcmp(g.id, c->id) != 0) {
        fprintf(stderr, "FAIL %s: golden id %s\n", c->id, g.id);
        nfail++;
    }
    if ((size_t)g.n_atoms != cf->num_atoms) {
        fprintf(stderr, "FAIL %s: n_atoms golden=%ld got=%zu\n", c->id, g.n_atoms, cf->num_atoms);
        nfail++;
    }
    uint32_t spec = rkr_frame_spec_version(frame);
    if ((uint32_t)g.spec_version != spec) {
        fprintf(stderr, "FAIL %s: spec_version golden=%ld got=%u\n", c->id, g.spec_version, spec);
        nfail++;
    }
    size_t n = cf->num_atoms;
    if ((size_t)g.n_atoms != n) {
        free_golden(&g);
        free_c_frame(cf);
        free_rkr_frame(frame);
        return 1;
    }
    for (size_t i = 0; i < n; i++) {
        const CAtom *a = &cf->atoms[i];
        const char *sym = rkr_z_to_symbol(a->atomic_number);
        if (!sym || strcmp(sym, g.symbols[i]) != 0) {
            fprintf(stderr, "FAIL %s: symbols[%zu] golden=%s got=%s\n", c->id, i, g.symbols[i],
                    sym ? sym : "(null)");
            nfail++;
        }
        if (a->atom_id != g.atom_ids[i]) {
            fprintf(stderr, "FAIL %s: atom_ids[%zu] golden=%llu got=%llu\n", c->id, i,
                    g.atom_ids[i], (unsigned long long)a->atom_id);
            nfail++;
        }
        int got_fixed[3] = {a->fixed_x ? 1 : 0, a->fixed_y ? 1 : 0, a->fixed_z ? 1 : 0};
        if (got_fixed[0] != g.fixed[i][0] || got_fixed[1] != g.fixed[i][1] ||
            got_fixed[2] != g.fixed[i][2]) {
            fprintf(stderr, "FAIL %s: fixed[%zu] golden=[%d,%d,%d] got=[%d,%d,%d]\n", c->id, i,
                    g.fixed[i][0], g.fixed[i][1], g.fixed[i][2], got_fixed[0], got_fixed[1],
                    got_fixed[2]);
            nfail++;
        }
        if (fabs(a->x - g.positions[i][0]) > POS_ABS_TOL ||
            fabs(a->y - g.positions[i][1]) > POS_ABS_TOL ||
            fabs(a->z - g.positions[i][2]) > POS_ABS_TOL) {
            fprintf(stderr, "FAIL %s: positions[%zu] golden=[%g,%g,%g] got=[%g,%g,%g]\n", c->id, i,
                    g.positions[i][0], g.positions[i][1], g.positions[i][2], a->x, a->y, a->z);
            nfail++;
        }
    }

    free_golden(&g);
    free_c_frame(cf);
    free_rkr_frame(frame);
    return nfail;
}

static int check_invalid(const char *root, const Case *c) {
    char fixture[1024];
    char extra[1024];
    snprintf(fixture, sizeof(fixture), "%s/resources/conformance/%s", root, c->path);
    snprintf(extra, sizeof(extra), "%s/resources/conformance/golden/%s.json", root, c->id);
    FILE *gf = fopen(extra, "rb");
    if (gf) {
        fclose(gf);
        fprintf(stderr, "FAIL %s: invalid case must not have a golden\n", c->id);
        return 1;
    }
    RKRConFrame *frame = rkr_read_first_frame(fixture);
    if (frame) {
        fprintf(stderr, "FAIL %s: invalid fixture parsed\n", c->id);
        free_rkr_frame(frame);
        return 1;
    }
    uintptr_t nframes = 0;
    struct RKRConFrame **frames = rkr_read_all_frames(fixture, &nframes);
    if (frames != NULL) {
        fprintf(stderr, "FAIL %s: rkr_read_all_frames succeeded n=%zu\n", c->id, (size_t)nframes);
        free_rkr_frame_array(frames, nframes);
        return 1;
    }
    return 0;
}

static int file_exists(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        return 0;
    }
    fclose(f);
    return 1;
}

int main(int argc, char **argv) {
    const char *root = NULL;
    if (argc > 1 && argv[1][0] != '\0') {
        root = argv[1];
    } else {
        root = getenv("READCON_CORE_ROOT");
    }
    if (!root || root[0] == '\0') {
        root = ".";
    }

    char manifest_path[1024];
    snprintf(manifest_path, sizeof(manifest_path), "%s/resources/conformance/manifest.toml", root);
    char *text = slurp(manifest_path);
    if (!text) {
        fprintf(stderr, "cannot read %s (set READCON_CORE_ROOT or pass repo root)\n",
                manifest_path);
        return 2;
    }
    Case cases[MAX_CASES];
    int ncases = parse_manifest(text, cases, MAX_CASES);
    free(text);
    if (ncases <= 0) {
        fprintf(stderr, "manifest.toml lists no cases\n");
        return 2;
    }

    int nvalid = 0;
    int ninvalid = 0;
    int nfail = 0;
    for (int i = 0; i < ncases; i++) {
        if (cases[i].id[0] == '\0' || cases[i].path[0] == '\0') {
            fprintf(stderr, "FAIL: manifest case missing id/path\n");
            nfail++;
            continue;
        }
        if (cases[i].valid) {
            nvalid++;
            char gpath[1024];
            snprintf(gpath, sizeof(gpath), "%s/resources/conformance/golden/%s.json", root,
                     cases[i].id);
            if (!file_exists(gpath)) {
                failf(&nfail, "%s: missing golden", cases[i].id);
                continue;
            }
            nfail += check_valid(root, &cases[i]);
        } else {
            ninvalid++;
            nfail += check_invalid(root, &cases[i]);
        }
    }
    if (nvalid == 0 || ninvalid == 0) {
        fprintf(stderr, "FAIL: expected both valid and invalid cases\n");
        nfail++;
    }
    if (nfail != 0) {
        fprintf(stderr, "c conformance goldens: FAIL %d  (%d valid, %d invalid)\n", nfail, nvalid,
                ninvalid);
        return 1;
    }
    printf("c conformance goldens: OK  %d valid, %d invalid\n", nvalid, ninvalid);
    return 0;
}
