#ifndef READCON_PLUS_PLUS_H
#define READCON_PLUS_PLUS_H

#pragma once

#include <array>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

#include "readcon-core.h"

namespace readcon {

/**
 * @brief C++ representation of a Rust single atom.
 */
struct Atom {
    uint64_t atomic_number;
    double x;
    double y;
    double z;
    uint64_t atom_id;
    double mass;
    bool is_fixed;
};

/**
 * @brief A C++ wrapper for a simulation frame loaded from a .con file.
 *
 * This class follows the RAII principle to manage the memory of the C-style
 * `CFrame` struct. It acquires the resource in its factory function and
 * automatically releases it in its destructor, preventing memory leaks.
 */
class ConFrame {
  public:
    /**
     * @brief Factory function to parse a .con file and create a ConFrame
     * object.
     *
     * @param path The path to the .con file.
     * @return A ConFrame object.
     * @throws std::runtime_error if the file cannot be parsed.
     */
    static ConFrame from_file(const std::filesystem::path &path) {
        CFrame *frame_ptr = read_con_file(path.c_str());
        if (!frame_ptr) {
            throw std::runtime_error("Failed to read or parse .con file: " +
                                     path.string());
        }
        return ConFrame(frame_ptr);
    }

    // Disable copy constructor and copy assignment.
    ConFrame(const ConFrame &) = delete;
    ConFrame &operator=(const ConFrame &) = delete;

    // Enable move constructor and move assignment (default is fine).
    ConFrame(ConFrame &&) = default;
    ConFrame &operator=(ConFrame &&) = default;

    /**
     * @brief Gets the simulation cell dimensions (a, b, c).
     * @return An array of 3 doubles.
     */
    std::array<double, 3> cell() const {
        return {frame_ptr_->cell[0], frame_ptr_->cell[1], frame_ptr_->cell[2]};
    }

    /**
     * @brief Gets the simulation cell angles (alpha, beta, gamma).
     * @return An array of 3 doubles.
     */
    std::array<double, 3> angles() const {
        return {frame_ptr_->angles[0], frame_ptr_->angles[1],
                frame_ptr_->angles[2]};
    }

    /**
     * @brief Gets a vector of all atoms in the frame.
     *
     * The result is cached on the first call for efficiency.
     * @return A const reference to a vector of Atom objects.
     */
    const std::vector<Atom> &atoms() const {
        // Lazily populate the C++ vector from the C array on first access.
        if (atoms_cache_.empty() && frame_ptr_->num_atoms > 0) {
            atoms_cache_.reserve(frame_ptr_->num_atoms);
            for (size_t i = 0; i < frame_ptr_->num_atoms; ++i) {
                const CAtom &c_atom = frame_ptr_->atoms[i];
                atoms_cache_.emplace_back(Atom{
                    .atomic_number = c_atom.atomic_number,
                    .x = c_atom.x,
                    .y = c_atom.y,
                    .z = c_atom.z,
                    .atom_id = c_atom.atom_id,
                    .mass = c_atom.mass,
                    .is_fixed = c_atom.is_fixed,
                });
            }
        }
        return atoms_cache_;
    }

  private:
    // Custom deleter for the unique_ptr to call the C-style free function.
    struct FrameDeleter {
        void operator()(CFrame *ptr) const {
            if (ptr) {
                free_con_frame(ptr);
            }
        }
    };

    // Private constructor to enforce creation via the `from_file` factory.
    explicit ConFrame(CFrame *frame_ptr) : frame_ptr_(frame_ptr) {}

    std::unique_ptr<CFrame, FrameDeleter> frame_ptr_;
    mutable std::vector<Atom> atoms_cache_;
};

/**
 * @brief A C++ wrapper for the symbol-to-atomic-number utility function.
 *
 * @param symbol An element symbol (e.g., "H", "Cu").
 * @return The corresponding atomic number.
 */
inline uint64_t symbol_to_atomic_number(std::string_view symbol) {
    return rust_symbol_to_atomic_number(symbol.data());
}

} // namespace readcon

#endif // READCON_PLUS_PLUS_H
