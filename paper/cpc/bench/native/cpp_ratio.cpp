// One head-to-head cell. The first argument is the mode and the second is
// the file. The modes are the ones paper/cpc/bench/h2h.py times.
//
//   readcon-soa       position columns, sum of x
//   readcon-frames    one frame at a time, sum of x
//   readcon-soa-all   position columns plus the velocity of each atom
//   readcon-frames-vel  one frame at a time, x and vx
//   chemfiles         every step, sum of positions[][0]
//   chemfiles-vel     the same reader on a GRO file

#include "readcon-core.hpp"

#include <chemfiles.hpp>

#include <chrono>
#include <iostream>
#include <string>

namespace {

double sum_x(const readcon::PositionBlock &block) {
    double sum = 0.0;
    const double *values = block.data();
    const std::size_t n = block.size();
    for (std::size_t i = 0; i < n; i += 3) {
        sum += values[i];
    }
    return sum;
}

int run_readcon(const std::string &mode, const std::string &path, double &checksum, int &frames) {
    if (mode == "readcon-soa" || mode == "readcon-soa-all") {
        readcon::PositionBlock block = readcon::read_positions(path, 1);
        checksum = sum_x(block);
        frames = static_cast<int>(block.n_frames());
        if (mode == "readcon-soa-all") {
            readcon::ConFrameIterator iterator(path);
            for (readcon::ConFrame &frame : iterator) {
                const auto atoms = frame.atoms();
                for (const auto &atom : atoms) {
                    if (auto velocity = atom.velocity()) {
                        checksum += (*velocity)[0];
                    }
                }
            }
        }
        return 0;
    }
    if (mode == "readcon-frames" || mode == "readcon-frames-vel") {
        readcon::ConFrameIterator iterator(path);
        checksum = 0.0;
        frames = 0;
        for (readcon::ConFrame &frame : iterator) {
            const auto atoms = frame.atoms();
            for (const auto &atom : atoms) {
                checksum += atom.x;
                if (mode == "readcon-frames-vel") {
                    if (auto velocity = atom.velocity()) {
                        checksum += (*velocity)[0];
                    }
                }
            }
            frames += 1;
        }
        return 0;
    }
    return 2;
}

int run_chemfiles(const std::string &path, double &checksum, int &frames) {
    chemfiles::Trajectory trajectory(path);
    checksum = 0.0;
    frames = 0;
    const std::size_t steps = trajectory.nsteps();
    for (std::size_t step = 0; step < steps; ++step) {
        chemfiles::Frame frame = trajectory.read_step(step);
        for (const chemfiles::Vector3D &position : frame.positions()) {
            checksum += position[0];
        }
        frames += 1;
    }
    return 0;
}

}  // namespace

int main(int argc, char **argv) {
    if (argc != 3) {
        std::cerr << "usage: cpp_ratio MODE PATH\n";
        return 2;
    }
    const std::string mode = argv[1];
    const std::string path = argv[2];
    double checksum = 0.0;
    int frames = 0;
    const auto start = std::chrono::steady_clock::now();
    int status = 0;
    try {
        if (mode == "chemfiles" || mode == "chemfiles-vel") {
            status = run_chemfiles(path, checksum, frames);
        } else {
            status = run_readcon(mode, path, checksum, frames);
        }
    } catch (const std::exception &err) {
        std::cerr << err.what() << "\n";
        return 1;
    }
    if (status != 0) {
        std::cerr << "unknown mode " << mode << "\n";
        return status;
    }
    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    std::cout << "seconds " << seconds << "\nframes " << frames << "\nchecksum " << checksum << "\n";
    return 0;
}
