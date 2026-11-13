// chemfiles C++: open the trajectory (the XYZ reader indexes every step on
// open), read every step into a vector of frames and build one record per
// frame of the output contract (`moc` on extended XYZ, `coords` on XYZ).
// `novelo` builds the `moc` record without its velocities, so the pair of
// reads times the velocity lookups. Positions stay in the frame. chemfiles
// 0.10 keeps the extended-XYZ columns velo, move_mask and id as per-atom
// properties (vector, bool, double) and the comment-line pbc="T T T" as the
// frame string property "pbc"; its cell matrix holds the lattice vectors as
// columns, so the record transposes it.
#include "protocol.hpp"

#include <array>
#include <chemfiles.hpp>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {

struct Record {
    std::vector<chemfiles::Vector3D> velocities;
    std::vector<std::int64_t> ids;
    std::vector<std::array<bool, 3>> fixed;
    std::vector<std::uint64_t> numbers;
    std::array<double, 9> cell{};
    std::array<bool, 3> pbc{};
    std::uint64_t velocity_lookups = 0;
};

struct Kept {
    bool moc = true;
    bool velocities = true;
    std::vector<chemfiles::Frame> frames;
    std::vector<Record> records;
};

template <chemfiles::Property::Kind kind>
auto required(const chemfiles::Atom &atom, const char *name) {
    auto value = atom.get<kind>(name);
    if (!value)
        throw std::runtime_error(std::string("atom without property ") + name);
    return *value;
}

std::array<bool, 3> pbc_of(const chemfiles::Frame &frame) {
    const auto text = frame.get<chemfiles::Property::STRING>("pbc");
    if (!text)
        throw std::runtime_error("frame without the pbc property");
    std::array<bool, 3> pbc{};
    std::size_t k = 0;
    for (char ch : *text) {
        if (ch == ' ')
            continue;
        if (k == 3 || (ch != 'T' && ch != 'F'))
            throw std::runtime_error("pbc property is not three of T and F: " + *text);
        pbc[k++] = ch == 'T';
    }
    if (k != 3)
        throw std::runtime_error("pbc property is not three of T and F: " + *text);
    return pbc;
}

Record record_of(const chemfiles::Frame &frame, bool moc, bool with_velocities) {
    Record r;
    const std::size_t n = frame.size();
    r.numbers.resize(n);
    const std::string *last = nullptr;
    std::uint64_t z = 0;
    for (std::size_t i = 0; i < n; ++i) {
        const auto &atom = frame[i];
        if (!last || atom.type() != *last) {
            const auto number = atom.atomic_number();
            if (!number)
                throw std::runtime_error("no atomic number for type " + atom.type());
            z = *number;
            last = &atom.type();
        }
        r.numbers[i] = z;
    }
    if (!moc)
        return r;
    if (with_velocities) {
        const auto velocities = frame.velocities();
        if (velocities) {
            r.velocities = *velocities;
        } else {
            r.velocities.resize(n);
            for (std::size_t i = 0; i < n; ++i)
                r.velocities[i] = required<chemfiles::Property::VECTOR3D>(frame[i], "velo");
            r.velocity_lookups = n;
        }
    }
    r.ids.resize(n);
    r.fixed.resize(n);
    for (std::size_t i = 0; i < n; ++i) {
        r.ids[i] = static_cast<std::int64_t>(required<chemfiles::Property::DOUBLE>(frame[i], "id"));
        const bool fixed = !required<chemfiles::Property::BOOL>(frame[i], "move_mask");
        r.fixed[i] = {fixed, fixed, fixed};
    }
    const auto m = frame.cell().matrix();
    for (std::size_t row = 0; row < 3; ++row)
        for (std::size_t col = 0; col < 3; ++col)
            r.cell[3 * row + col] = m[col][row];
    r.pbc = pbc_of(frame);
    return r;
}

Checksums check(const Kept &k) {
    Checksums o;
    o.contract = !k.moc ? "coords" : k.velocities ? "moc" : "novelo";
    o.frames = k.frames.size();
    for (std::size_t f = 0; f < k.frames.size(); ++f) {
        const auto &positions = k.frames[f].positions();
        const Record &r = k.records[f];
        o.atoms += positions.size();
        o.add3(o.positions, positions.empty() ? nullptr : &positions[0][0], positions.size());
        for (auto z : r.numbers)
            o.sum_numbers += z;
        if (!k.moc)
            continue;
        o.add3(o.velocities, r.velocities.empty() ? nullptr : &r.velocities[0][0], r.velocities.size());
        o.velocity_lookups += r.velocity_lookups;
        for (std::size_t i = 0; i < r.ids.size(); ++i) {
            o.sum_ids += static_cast<std::uint64_t>(r.ids[i]);
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
        std::fprintf(stderr, "usage: chemfiles_read moc|novelo|coords PATH WARM THREADS\n");
        return 2;
    }
    const bool velocities = std::strcmp(argv[1], "novelo") != 0;
    const int contract = velocities ? contract_of(argv[1]) : 1;
    if (contract < 0)
        return 2;
    const bool moc = contract == 1;
    const unsigned threads = static_cast<unsigned>(std::strtoul(argv[4], nullptr, 10));
    chemfiles::set_warning_callback([](const std::string &) {});
    auto read = [moc, velocities](const char *path) {
        auto kept = std::make_unique<Kept>();
        kept->moc = moc;
        kept->velocities = velocities;
        chemfiles::Trajectory traj(path, 'r', "XYZ");
        const std::size_t n = traj.nsteps();
        kept->frames.reserve(n);
        kept->records.reserve(n);
        for (std::size_t step = 0; step < n; ++step) {
            kept->frames.push_back(traj.read());
            kept->records.push_back(record_of(kept->frames.back(), moc, velocities));
        }
        return kept;
    };
    return run_protocol(argv[2], argv[3], threads, read, check);
}
