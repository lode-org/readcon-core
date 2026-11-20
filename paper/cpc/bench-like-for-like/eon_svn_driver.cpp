/* Thin driver around the SVN eOn client's Matter::con2matter.

The client reads one frame per call and leaves the FILE positioned at the
next byte. This driver repeats that call until only whitespace remains, which
is how a multi-frame file is a sequence of the single-frame records
matter2con writes. A trailing blank line is not another frame.

con2matter applies the minimum-image convention when periodic boundaries are
on. They start on. deactivatePeriodicBoundaries is the client's own switch
that leaves the coordinates it just parsed unchanged, which is the positions
the harness checksums.
*/

#include "Matter.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdint.h>
#include <vector>

namespace {

const char *const kSymbols[] = {
    "Unknown", "H",  "He", "Li", "Be", "B",  "C",  "N",  "O",  "F",  "Ne",
    "Na",      "Mg", "Al", "Si", "P",  "S",  "Cl", "Ar", "K",  "Ca", "Sc",
    "Ti",      "V",  "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As",      "Se", "Br", "Kr", "Rb", "Sr", "Y",  "Zr", "Nb", "Mo", "Tc",
    "Ru",      "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I",  "Xe",
    "Cs",      "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb",
    "Dy",      "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W",  "Re", "Os",
    "Ir",      "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr",
    "Ra",      "Ac", "Th", "Pa", "U",  NULL};

const char *symbol_of(long atomic_number) {
    if (atomic_number < 0) {
        return kSymbols[0];
    }
    long count = 0;
    while (kSymbols[count] != NULL) {
        count += 1;
    }
    if (atomic_number >= count) {
        return kSymbols[0];
    }
    return kSymbols[atomic_number];
}

int frame_remains(FILE *file) {
    std::vector<int> seen;
    int byte = 0;
    while ((byte = fgetc(file)) != EOF) {
        seen.push_back(byte);
        if (byte != ' ' && byte != '\t' && byte != '\n' && byte != '\r') {
            for (int index = static_cast<int>(seen.size()) - 1; index >= 0;
                 --index) {
                ungetc(seen[index], file);
            }
            return 1;
        }
    }
    return 0;
}

double degrees_between(const Vector3d &left, const Vector3d &right, double left_norm,
                       double right_norm) {
    if (left_norm == 0.0 || right_norm == 0.0) {
        return 0.0;
    }
    double cosine = left.dot(right) / (left_norm * right_norm);
    if (cosine > 1.0) {
        cosine = 1.0;
    }
    if (cosine < -1.0) {
        cosine = -1.0;
    }
    return std::acos(cosine) * 180.0 / std::acos(-1.0);
}

void write_u32(uint32_t value) {
    if (fwrite(&value, sizeof(value), 1, stdout) != 1) {
        std::perror("write");
        std::exit(1);
    }
}

void write_f64(double value) {
    if (fwrite(&value, sizeof(value), 1, stdout) != 1) {
        std::perror("write");
        std::exit(1);
    }
}

}  // namespace

int main(int argc, char **argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: eon_svn_cxx path.con\n");
        return 2;
    }
    FILE *file = std::fopen(argv[1], "rb");
    if (!file) {
        std::perror(argv[1]);
        return 1;
    }
    Matter matter(NULL);
    matter.deactivatePeriodicBoundaries();
    std::vector<double> positions;
    std::vector<double> cells;
    std::vector<double> masses;
    std::vector<uint8_t> fixed;
    std::vector<uint16_t> atomic_numbers;
    uint32_t n_frames = 0;
    uint32_t n_atoms = 0;
    while (frame_remains(file)) {
        if (!matter.con2matter(file)) {
            std::fprintf(stderr, "con2matter failed on frame %u\n", n_frames);
            std::fclose(file);
            return 1;
        }
        uint32_t count = static_cast<uint32_t>(matter.numberOfAtoms());
        if (count == 0) {
            std::fprintf(stderr, "con2matter returned no atoms\n");
            std::fclose(file);
            return 1;
        }
        if (n_frames == 0) {
            n_atoms = count;
        } else if (count != n_atoms) {
            std::fprintf(stderr, "atom count changed at frame %u\n", n_frames);
            std::fclose(file);
            return 1;
        }
        Vector3d rows[3];
        double lengths[3];
        for (int axis = 0; axis < 3; ++axis) {
            rows[axis] = matter.getBoundary(axis);
            lengths[axis] = rows[axis].norm();
            cells.push_back(lengths[axis]);
        }
        cells.push_back(degrees_between(rows[0], rows[1], lengths[0], lengths[1]));
        cells.push_back(degrees_between(rows[0], rows[2], lengths[0], lengths[2]));
        cells.push_back(degrees_between(rows[1], rows[2], lengths[1], lengths[2]));
        for (uint32_t atom = 0; atom < n_atoms; ++atom) {
            masses.push_back(matter.getMass(atom));
            long atomic_number = matter.getAtomicNr(atom);
            if (symbol_of(atomic_number) == kSymbols[0] && atomic_number != 0) {
                std::fprintf(stderr, "unknown atomic number %ld\n", atomic_number);
                std::fclose(file);
                return 1;
            }
            atomic_numbers.push_back(static_cast<uint16_t>(atomic_number));
            int flag = matter.getFixed(atom) ? 1 : 0;
            fixed.push_back(static_cast<uint8_t>(flag));
            for (int axis = 0; axis < 3; ++axis) {
                positions.push_back(matter.getPosition(atom, axis));
            }
        }
        n_frames += 1;
    }
    std::fclose(file);
    if (n_frames == 0) {
        std::fprintf(stderr, "no frames\n");
        return 1;
    }
    static const char magic[] = "EONSVN1\n";
    if (fwrite(magic, 1, 8, stdout) != 8) {
        std::perror("write");
        return 1;
    }
    write_u32(n_frames);
    write_u32(n_atoms);
    for (uint32_t frame = 0; frame < n_frames; ++frame) {
        for (int index = 0; index < 6; ++index) {
            write_f64(cells[frame * 6 + index]);
        }
    }
    for (size_t index = 0; index < masses.size(); ++index) {
        write_f64(masses[index]);
    }
    if (fwrite(atomic_numbers.data(), sizeof(uint16_t), atomic_numbers.size(),
               stdout) != atomic_numbers.size()) {
        std::perror("write");
        return 1;
    }
    if (fwrite(fixed.data(), 1, fixed.size(), stdout) != fixed.size()) {
        std::perror("write");
        return 1;
    }
    for (size_t index = 0; index < positions.size(); ++index) {
        write_f64(positions[index]);
    }
    if (std::fflush(stdout) != 0) {
        std::perror("flush");
        return 1;
    }
    return 0;
}
