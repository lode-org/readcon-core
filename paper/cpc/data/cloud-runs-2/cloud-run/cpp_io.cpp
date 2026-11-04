// C++ wrapper round trip for one CON frame per file.
//   cpp_io write BAND.txt DIR
//   cpp_io read  DIR BAND.txt
#include "readcon-core.hpp"

#include <array>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct AtomRec {
    std::string sym;
    double x{}, y{}, z{}, mass{}, vx{}, vy{}, vz{};
    uint64_t id{};
    bool fx{}, fy{}, fz{}, hasv{};
};

struct FrameRec {
    std::array<double, 3> cell{};
    std::array<double, 3> angles{};
    int pbc[3]{-1, -1, -1};
    std::string meta;
    std::vector<AtomRec> atoms;
};

static void die(const std::string &m) {
    std::cerr << m << "\n";
    std::exit(1);
}

static std::vector<FrameRec> load_band(const std::string &path) {
    std::ifstream in(path);
    if (!in) die("cannot open " + path);
    std::vector<FrameRec> frames;
    std::string tag;
    int nframes = 0;
    in >> tag >> nframes;
    if (tag != "NFRAMES") die("bad band header");
    for (int i = 0; i < nframes; ++i) {
        FrameRec f;
        int natoms = 0;
        in >> tag;
        if (tag != "FRAME") die("expected FRAME");
        in >> tag >> natoms;
        in >> tag >> f.cell[0] >> f.cell[1] >> f.cell[2];
        in >> tag >> f.angles[0] >> f.angles[1] >> f.angles[2];
        in >> tag >> f.pbc[0] >> f.pbc[1] >> f.pbc[2];
        in >> tag;
        std::getline(in, f.meta);
        if (!f.meta.empty() && f.meta[0] == ' ') f.meta.erase(0, 1);
        in >> tag;
        if (tag != "ATOMS") die("expected ATOMS");
        for (int a = 0; a < natoms; ++a) {
            AtomRec at;
            int fx, fy, fz, hv;
            in >> at.sym >> at.x >> at.y >> at.z >> at.id >> at.mass >> fx >> fy >> fz >>
                at.vx >> at.vy >> at.vz >> hv;
            at.fx = fx != 0;
            at.fy = fy != 0;
            at.fz = fz != 0;
            at.hasv = hv != 0;
            f.atoms.push_back(at);
        }
        in >> tag;
        if (tag != "ENDFRAME") die("expected ENDFRAME");
        frames.push_back(std::move(f));
    }
    if (!in && !in.eof()) die("band parse failed");
    return frames;
}

static void store_band(const std::string &path, const std::vector<FrameRec> &frames) {
    std::ofstream out(path);
    if (!out) die("cannot write " + path);
    out.setf(std::ios::scientific);
    out.precision(17);
    out << "NFRAMES " << frames.size() << "\n";
    for (const auto &f : frames) {
        out << "FRAME\nNATOMS " << f.atoms.size() << "\n";
        out << "CELL " << f.cell[0] << " " << f.cell[1] << " " << f.cell[2] << "\n";
        out << "ANGLES " << f.angles[0] << " " << f.angles[1] << " " << f.angles[2] << "\n";
        out << "PBC " << f.pbc[0] << " " << f.pbc[1] << " " << f.pbc[2] << "\n";
        out << "META " << f.meta << "\nATOMS\n";
        for (const auto &a : f.atoms) {
            out << a.sym << " " << a.x << " " << a.y << " " << a.z << " " << a.id << " " << a.mass
                << " " << int(a.fx) << " " << int(a.fy) << " " << int(a.fz) << " " << a.vx << " "
                << a.vy << " " << a.vz << " " << int(a.hasv) << "\n";
        }
        out << "ENDFRAME\n";
    }
}

static std::array<int, 3> pbc_from_meta(const std::string &meta) {
    std::array<int, 3> p{-1, -1, -1};
    auto k = meta.find("\"pbc\"");
    if (k == std::string::npos) return p;
    auto lb = meta.find('[', k);
    if (lb == std::string::npos) return p;
    int n = 0;
    for (size_t i = lb + 1; i < meta.size() && n < 3; ++i) {
        if (meta.compare(i, 4, "true") == 0) {
            p[n++] = 1;
            i += 3;
        } else if (meta.compare(i, 5, "false") == 0) {
            p[n++] = 0;
            i += 4;
        }
    }
    return p;
}

static void do_write(const std::string &band, const std::string &dir) {
    auto frames = load_band(band);
    fs::create_directories(dir);
    {
        std::ofstream man(dir + "/manifest.txt");
        man << frames.size() << "\n";
    }
    for (size_t i = 0; i < frames.size(); ++i) {
        const auto &f = frames[i];
        char name[64];
        std::snprintf(name, sizeof(name), "/frame_%03zu.con", i);
        readcon::ConFrameBuilder b(f.cell, f.angles, {"image " + std::to_string(i), ""});
        if (!f.meta.empty()) b.set_metadata_json(f.meta);
        for (const auto &a : f.atoms) {
            std::optional<std::array<double, 3>> vel;
            if (a.hasv) vel = std::array<double, 3>{a.vx, a.vy, a.vz};
            b.add_atom(a.sym, a.x, a.y, a.z, std::array<bool, 3>{a.fx, a.fy, a.fz}, a.id, a.mass, vel);
        }
        std::vector<readcon::ConFrame> one;
        one.push_back(b.build());
        readcon::ConFrameWriter w(dir + name);
        w.extend(one);
    }
}

static void do_read(const std::string &dir, const std::string &band) {
    std::ifstream man(dir + "/manifest.txt");
    int n = 0;
    man >> n;
    if (!man) die("missing manifest");
    std::vector<FrameRec> frames;
    for (int i = 0; i < n; ++i) {
        char name[64];
        std::snprintf(name, sizeof(name), "/frame_%03d.con", i);
        auto got = readcon::read_all_frames(dir + name);
        if (got.size() != 1) die("expected one frame in " + std::string(name));
        const auto &fr = got[0];
        FrameRec f;
        f.cell = fr.cell();
        f.angles = fr.angles();
        f.meta = fr.metadata_json();
        auto p = pbc_from_meta(f.meta);
        f.pbc[0] = p[0];
        f.pbc[1] = p[1];
        f.pbc[2] = p[2];
        for (const auto &a : fr.atoms()) {
            AtomRec at;
            at.x = a.x;
            at.y = a.y;
            at.z = a.z;
            at.id = a.atom_id;
            at.mass = a.mass;
            at.fx = a.fixed_x;
            at.fy = a.fixed_y;
            at.fz = a.fixed_z;
            auto vel = a.velocity();
            at.hasv = vel.has_value();
            if (vel) {
                at.vx = (*vel)[0];
                at.vy = (*vel)[1];
                at.vz = (*vel)[2];
            }
            const char *sym = readcon::rkr_z_to_symbol(a.atomic_number);
            at.sym = sym ? sym : "X";
            f.atoms.push_back(at);
        }
        frames.push_back(std::move(f));
    }
    store_band(band, frames);
}

int main(int argc, char **argv) {
    if (argc != 4) die("usage: cpp_io write|read SRC DST");
    std::string mode = argv[1];
    try {
        if (mode == "write") do_write(argv[2], argv[3]);
        else if (mode == "read") do_read(argv[2], argv[3]);
        else die("mode must be write or read");
    } catch (const std::exception &e) {
        die(std::string("C++ exception: ") + e.what());
    }
    return 0;
}
