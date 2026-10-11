#include "eon/Dynamics.h"
#include "eon/Matter.h"
#include "eon/Parameters.h"
#include "eon/potentials/EMT/EffectiveMediumTheory.h"

#include <iostream>
#include <memory>
#include <string>

int main(int argc, char **argv) {
  const std::string dir = argc > 1 ? argv[1] : ".";
  eonc::Parameters params;
  auto &main = eonc::ParametersLoadAccess::main_options(params);
  main.randomSeed = 7;
  main.temperature = 300.0;
  main.writeConForces = true;

  auto pot = std::make_shared<EffectiveMediumTheory>(params);
  eonc::Matter matter(pot, params);
  constexpr int nx = 4, ny = 4, nz = 2;
  constexpr int n = nx * ny * nz;
  matter.resize(n);
  constexpr double a = 3.92;
  int atom = 0;
  for (int k = 0; k < nz; ++k) {
    for (int j = 0; j < ny; ++j) {
      for (int i = 0; i < nx; ++i, ++atom) {
        matter.setAtomicNr(atom, 78);
        matter.setMass(atom, 195.084);
        matter.setPosition(atom, 0, i * a);
        matter.setPosition(atom, 1, j * a);
        matter.setPosition(atom, 2, k * a);
      }
    }
  }
  Matrix3d cell = Matrix3d::Identity();
  cell(0, 0) = nx * a;
  cell(1, 1) = ny * a;
  cell(2, 2) = (nz * a) + 12.0;
  matter.setCell(cell);

  eonc::DynamicsConfig cfg;
  cfg.temperature = 300.0;
  cfg.kB = 8.6173324e-5;
  cfg.timeUnit = 10.1805055;
  eonc::Dynamics dynamics(&matter, cfg);
  dynamics.setTemperature(300.0);
  dynamics.setThermalVelocity();

  eonc::io::set_write_con_forces(false);
  auto con = matter.matter2con(dir + "/eon_slab.con");
  auto vel = matter.matter2convel(dir + "/eon_slab.convel");
  const double energy = matter.getPotentialEnergy();
  eonc::io::set_write_con_forces(true);
  auto forces = matter.matter2con(dir + "/eon_forces.con");

  std::cout << "atoms " << n << "\n";
  std::cout.setf(std::ios::fmtflags(0), std::ios::floatfield);
  std::cout.precision(16);
  std::cout << "KE_EV " << matter.getKineticEnergy() << "\n";
  std::cout << "PE_EV " << energy << "\n";
  std::cout << "status " << static_cast<int>(con) << " " << static_cast<int>(vel)
            << " " << static_cast<int>(forces) << "\n";
  return (con == eonc::io::IoStatus::Ok && vel == eonc::io::IoStatus::Ok &&
          forces == eonc::io::IoStatus::Ok)
             ? 0
             : 1;
}
