// readcon-core 0.17.3 through its C++ header: read_all_frames(path, n_threads),
// then one record per frame of the output contract. Positions, velocities and
// ids stay in the frame's binary64 and u64 columns, and ConFrame::pbc() gives
// the periodic flags, periodic in all three directions when pbc is absent
// (CON-cell.3). The 0.17.3 header has no column accessor for the atomic
// numbers or the fixed flags, so both come from ConFrame::atoms(), the
// per-atom list, and none for the cell matrix, so the frame's JSON metadata is
// scanned for lattice_vectors, which wins over lines 3-4 (CON-cell.1).
#include "protocol.hpp"
#include "readcon-core.hpp"

#include <array>
#include <cmath>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {

struct Record {
    const double *positions = nullptr;
    const double *velocities = nullptr;
    const std::uint64_t *ids = nullptr;
    std::size_t n = 0;
    std::vector<std::array<bool, 3>> fixed;
    std::vector<std::uint64_t> numbers;
    std::array<double, 9> cell{};
    std::array<bool, 3> pbc{true, true, true};
};

struct Kept {
    bool moc = true;
    std::vector<readcon::ConFrame> frames;
    std::vector<Record> records;
};

const char *after_key(const std::string &json, const char *key) {
    const std::size_t at = json.find(key);
    return at == std::string::npos ? nullptr : json.c_str() + at + std::strlen(key);
}

std::array<double, 9> cell_of(const readcon::ConFrame &frame, const std::string &json) {
    std::array<double, 9> m{};
    if (const char *p = after_key(json, "\"lattice_vectors\":")) {
        for (double &x : m) {
            while (*p == '[' || *p == ']' || *p == ',' || *p == ' ')
                ++p;
            char *end = nullptr;
            x = std::strtod(p, &end);
            if (end == p)
                throw std::runtime_error("malformed lattice_vectors");
            p = end;
        }
        return m;
    }
    const auto &len = frame.cell();
    const auto &deg = frame.angles();
    const double pi = std::acos(-1.0);
    const double ca = std::cos(deg[0] * pi / 180), cb = std::cos(deg[1] * pi / 180);
    const double cg = std::cos(deg[2] * pi / 180), sg = std::sin(deg[2] * pi / 180);
    const double cy = (ca - cb * cg) / sg;
    const double cz2 = 1.0 - cb * cb - cy * cy;
    const double cz = cz2 < 0.0 && cz2 > -1e-12 ? 0.0 : std::sqrt(cz2);
    m = {len[0], 0.0, 0.0, len[1] * cg, len[1] * sg, 0.0, len[2] * cb, len[2] * cy, len[2] * cz};
    return m;
}

Record record_of(const readcon::ConFrame &frame, bool moc) {
    Record r;
    r.positions = frame.xyz_f64(&r.n);
    if (!r.positions)
        throw std::runtime_error("positions are not binary64");
    const auto &atoms = frame.atoms();
    if (atoms.size() != r.n)
        throw std::runtime_error("atom list and position column differ in length");
    r.numbers.resize(r.n);
    for (std::size_t i = 0; i < r.n; ++i)
        r.numbers[i] = atoms[i].atomic_number;
    if (!moc)
        return r;
    std::size_t nv = 0;
    r.velocities = frame.velocities_f64(&nv);
    if (!r.velocities || nv != r.n)
        throw std::runtime_error("frame has no binary64 velocities");
    readcon::RKRArrayView view{};
    if (readcon::rkr_frame_atom_ids_view(frame.get_handle(), &view) != readcon::RKR_STATUS_SUCCESS || view.n != r.n)
        throw std::runtime_error("frame has no id column");
    r.ids = static_cast<const std::uint64_t *>(view.data);
    r.fixed.resize(r.n);
    for (std::size_t i = 0; i < r.n; ++i)
        r.fixed[i] = atoms[i].fixed_mask();
    r.cell = cell_of(frame, frame.metadata_json());
    r.pbc = frame.pbc();
    return r;
}

Checksums check(const Kept &k) {
    Checksums o;
    o.contract = k.moc ? "moc" : "coords";
    o.frames = k.records.size();
    for (const Record &r : k.records) {
        o.atoms += r.n;
        o.add3(o.positions, r.positions, r.n);
        for (std::size_t i = 0; i < r.n; ++i)
            o.sum_numbers += r.numbers[i];
        if (!k.moc)
            continue;
        o.add3(o.velocities, r.velocities, r.n);
        for (std::size_t i = 0; i < r.n; ++i) {
            o.sum_ids += r.ids[i];
            o.n_fixed += r.fixed[i][0] + r.fixed[i][1] + r.fixed[i][2];
        }
        for (double x : r.cell)
            o.cell.add(x);
        o.n_pbc += r.pbc[0] + r.pbc[1] + r.pbc[2];
    }
    return o;
}

} // namespace

int main(int argc, char **argv) {
    if (argc != 5) {
        std::fprintf(stderr, "usage: readcon_read moc|coords PATH WARM THREADS\n");
        return 2;
    }
    const int contract = contract_of(argv[1]);
    if (contract < 0)
        return 2;
    const bool moc = contract == 1;
    const unsigned threads = static_cast<unsigned>(std::strtoul(argv[4], nullptr, 10));
    auto read = [threads, moc](const char *path) {
        auto kept = std::make_unique<Kept>();
        kept->moc = moc;
        kept->frames = readcon::read_all_frames(path, threads);
        kept->records.reserve(kept->frames.size());
        for (const auto &frame : kept->frames)
            kept->records.push_back(record_of(frame, moc));
        return kept;
    };
    return run_protocol(argv[2], argv[3], threads, read, check);
}
