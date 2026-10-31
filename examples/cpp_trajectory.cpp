// readcon::Trajectory against readcon::read_all_frames on one file.
#include "readcon-core.hpp"
#include <cstring>
#include <iostream>

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " FILE\n";
        return 2;
    }
    auto all = readcon::read_all_frames(argv[1]);
    readcon::Trajectory traj(argv[1], false);
    int bad = traj.size() != all.size();
    for (std::size_t i = 0; i < all.size(); ++i) {
        auto got = traj[i];
        const auto &a = got.atoms(), &b = all[i].atoms();
        bad += a.size() != b.size() || got.metadata_json() != all[i].metadata_json();
        for (std::size_t k = 0; k < a.size() && k < b.size(); ++k)
            bad += a[k].atom_id != b[k].atom_id ||
                   std::memcmp(&a[k].x, &b[k].x, sizeof(double)) != 0 ||
                   std::memcmp(&a[k].y, &b[k].y, sizeof(double)) != 0 ||
                   std::memcmp(&a[k].z, &b[k].z, sizeof(double)) != 0;
    }
    const std::string n = std::to_string(traj.size());
    try {
        traj.at(traj.size());
        bad++;
    } catch (const std::out_of_range &e) {
        bad += std::string(e.what()) != "frame index " + n +
                                            " is out of range for a trajectory of " +
                                            n + " frames";
    }
    try {
        readcon::Trajectory missing("/nonexistent/x.con");
        bad++;
    } catch (const std::runtime_error &) {
    }
    std::cout << "cpp_trajectory: " << traj.size() << " frames, "
              << (bad ? "FAIL" : "ok") << "\n";
    return bad ? 1 : 0;
}
