// Read a CON file through eOn's ConFileIO and con2matter.
// `all` (the default) reads every frame with readcon::read_all_frames and
// converts each one. `first` reads one frame with read_first_frame.
// The coordinate check is the second loop and is outside the clock.

#include "eon/ConFileIO.h"
#include "eon/Matter.h"
#include "eon/Parameters.h"
#include "eon/Potential.h"

#include <readcon-core.hpp>

#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

int hwm_kib() {
  std::ifstream status("/proc/self/status");
  std::string line;
  while (std::getline(status, line)) {
    if (line.rfind("VmHWM:", 0) == 0) {
      return std::stoi(line.substr(line.find_first_of("0123456789")));
    }
  }
  return 0;
}

double expected(std::size_t frame, std::size_t atom, int axis) {
  const double raw =
      std::fmod(static_cast<double>(frame) * 17.0 +
                    static_cast<double>(atom) * 3.0 + static_cast<double>(axis),
                10000.0) /
      1000.0;
  return std::round(raw * 1e8) / 1e8;
}

} // namespace

int main(int argc, char **argv) {
  if (argc != 2 && argc != 3) {
    std::cerr << "usage: eon_allframes FILE [all|first]\n";
    return 2;
  }
  const bool first_only = argc == 3 && std::string(argv[2]) == "first";
  if (argc == 3 && std::string(argv[2]) != "first" && std::string(argv[2]) != "all") {
    std::cerr << "usage: eon_allframes FILE [all|first]\n";
    return 2;
  }
  eonc::Parameters parameters;
  auto potential =
      eonc::helpers::sharePotential(eonc::helpers::makePotential(eonc::PotType::LJ, parameters));
  eonc::Matter matter(potential, parameters);
  const int before = hwm_kib();
  const auto t0 = std::chrono::steady_clock::now();
  std::vector<readcon::ConFrame> frames;
  if (first_only) {
    frames.push_back(readcon::read_first_frame(argv[1]));
  } else {
    frames = readcon::read_all_frames(argv[1]);
  }
  double checksum = 0.0;
  int natoms = 0;
  for (const auto &frame : frames) {
    const auto status = eonc::io::con2matter(matter, frame, nullptr);
    if (!eonc::io::io_ok(status)) {
      std::cerr << "con2matter failed\n";
      return 1;
    }
    const auto &positions = matter.getPositions();
    natoms = static_cast<int>(positions.rows());
    checksum += positions.sum();
  }
  const auto t1 = std::chrono::steady_clock::now();
  const int after = hwm_kib();
  const double seconds = std::chrono::duration<double>(t1 - t0).count();

  int matched = 0;
  std::size_t index = 0;
  for (const auto &frame : frames) {
    const auto status = eonc::io::con2matter(matter, frame, nullptr);
    if (!eonc::io::io_ok(status)) {
      break;
    }
    const auto &positions = matter.getPositions();
    bool ok = positions.rows() > 0;
    for (Eigen::Index atom = 0; atom < positions.rows() && ok; ++atom) {
      for (int axis = 0; axis < 3; ++axis) {
        const double got = positions(atom, axis);
        if (std::abs(got - expected(index, static_cast<std::size_t>(atom), axis)) > 1e-5) {
          ok = false;
        }
      }
    }
    if (ok) {
      ++matched;
    }
    ++index;
  }
  std::cout << seconds << " " << before << " " << after << " " << matched << " " << frames.size()
            << " " << checksum << " " << natoms << "\n";
  return 0;
}
