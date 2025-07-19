#ifndef READCON_PLUS_PLUS_H
#define READCON_PLUS_PLUS_H

#pragma once

#include <array>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>
#include <iterator>

#include "readcon-core.h"

namespace readcon {

/**
 * @brief C++ representation of a single atom.
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

// Forward declaration for use in ConFrameIterator
class ConFrame;

/**
 * @brief An iterator for lazily reading frames from a .con file.
 *
 * This class provides a C++-idiomatic way to iterate over frames in a file.
 * It implements the necessary methods to be used in a range-based for loop.
 *
 * Example:
 *
 * readcon::ConFrameIterator frames("path/to/file.con");
 * for (const auto& frame : frames) {
 * // use frame
 * }
 */
class ConFrameIterator {
public:
    /**
     * @brief The nested iterator class that conforms to C++ iterator concepts.
     */
    class Iterator {
    public:
        // C++ iterator traits to make this compatible with standard algorithms
        using iterator_category = std::input_iterator_tag;
        using value_type = ConFrame;
        using difference_type = std::ptrdiff_t;
        using pointer = const ConFrame*;
        using reference = const ConFrame&;

        // Dereference operator to get the current frame.
        reference operator*() const;
        pointer operator->() const;

        // Pre-increment operator to advance to the next frame.
        Iterator& operator++();

        // Comparison operator to check for the end of the iteration.
        bool operator!=(const Iterator& other) const {
            // The only "other" we should compare to is the end iterator,
            // which has a null current_frame_.
            return current_frame_ != other.current_frame_;
        }

    private:
        friend class ConFrameIterator; // Allow the container to create iterators

        // Private constructor for creating begin/end iterators.
        explicit Iterator(CConFrameIterator* iterator_ptr);

        void fetch_next_frame();

        CConFrameIterator* iterator_ptr_ = nullptr;
        std::unique_ptr<ConFrame> current_frame_;
    };

    /**
     * @brief Constructs a frame iterator from a file path.
     * @param path The path to the .con file.
     * @throws std::runtime_error if the file cannot be opened.
     */
    explicit ConFrameIterator(const std::filesystem::path& path);

    /**
     * @brief Returns an iterator to the beginning of the sequence of frames.
     */
    Iterator begin();

    /**
     * @brief Returns an iterator to the end of the sequence.
     */
    Iterator end();

    /**
     * @brief Skips the next frame in the file without parsing it.
     * @return true if a frame was successfully skipped, false otherwise.
     */
    bool forward();

private:
    // Custom deleter for the CConFrameIterator to call the C free function.
    struct IteratorDeleter {
        void operator()(CConFrameIterator* ptr) const {
            if (ptr) {
                free_con_frame_iterator(ptr);
            }
        }
    };

    std::unique_ptr<CConFrameIterator, IteratorDeleter> iterator_ptr_;
};


/**
 * @brief A C++ wrapper for a simulation frame loaded from a .con file.
 *
 * This class follows the RAII principle to manage the memory of the C-style
 * `CFrame` struct. It acquires the resource in its constructor and
 * automatically releases it in its destructor, preventing memory leaks.
 */
class ConFrame {
public:
    // FIX: Allow ConFrameIterator::Iterator to access the private constructor.
    friend class ConFrameIterator::Iterator;

    /**
     * @brief Factory function to parse the first frame of a .con file.
     *
     * @param path The path to the .con file.
     * @return A ConFrame object.
     * @throws std::runtime_error if the file cannot be parsed.
     */
    static ConFrame from_file(const std::filesystem::path& path) {
        CFrame* frame_ptr = read_single_frame(path.c_str());
        if (!frame_ptr) {
            throw std::runtime_error("Failed to read or parse .con file: " +
                                     path.string());
        }
        return ConFrame(frame_ptr);
    }

    // Disable copy constructor and copy assignment.
    ConFrame(const ConFrame&) = delete;
    ConFrame& operator=(const ConFrame&) = delete;

    // Enable move constructor and move assignment (default is fine).
    ConFrame(ConFrame&&) = default;
    ConFrame& operator=(ConFrame&&) = default;

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
    const std::vector<Atom>& atoms() const {
        // Lazily populate the C++ vector from the C array on first access.
        if (atoms_cache_.empty() && frame_ptr_->num_atoms > 0) {
            atoms_cache_.reserve(frame_ptr_->num_atoms);
            for (size_t i = 0; i < frame_ptr_->num_atoms; ++i) {
                const CAtom& c_atom = frame_ptr_->atoms[i];
                atoms_cache_.emplace_back(Atom{
                    /* .atomic_number = */ c_atom.atomic_number,
                    /* .x = */ c_atom.x,
                    /* .y = */ c_atom.y,
                    /* .z = */ c_atom.z,
                    /* .atom_id = */ c_atom.atom_id,
                    /* .mass = */ c_atom.mass,
                    /* .is_fixed = */ c_atom.is_fixed,
                });
            }
        }
        return atoms_cache_;
    }

private:
    // Custom deleter for the unique_ptr to call the C-style free function.
    struct FrameDeleter {
        void operator()(CFrame* ptr) const {
            if (ptr) {
                free_con_frame(ptr);
            }
        }
    };

    // Private constructor to enforce creation via the `from_file` factory or friend iterator.
    explicit ConFrame(CFrame* frame_ptr) : frame_ptr_(frame_ptr) {}

    std::unique_ptr<CFrame, FrameDeleter> frame_ptr_;
    mutable std::vector<Atom> atoms_cache_;
};

// --- Implementation of ConFrameIterator and its nested Iterator ---

inline ConFrameIterator::ConFrameIterator(const std::filesystem::path& path) {
    CConFrameIterator* iter_ptr = read_con_file_iterator(path.c_str());
    if (!iter_ptr) {
        throw std::runtime_error("Failed to open .con file for iteration: " + path.string());
    }
    iterator_ptr_.reset(iter_ptr);
}

inline ConFrameIterator::Iterator ConFrameIterator::begin() {
    return Iterator(iterator_ptr_.get());
}

inline ConFrameIterator::Iterator ConFrameIterator::end() {
    return Iterator(nullptr); // End iterator is represented by a null pointer
}

inline bool ConFrameIterator::forward() {
    return con_frame_iterator_forward(iterator_ptr_.get()) == 0;
}

inline ConFrameIterator::Iterator::Iterator(CConFrameIterator* iterator_ptr)
    : iterator_ptr_(iterator_ptr) {
    if (iterator_ptr_) {
        fetch_next_frame();
    }
}

inline void ConFrameIterator::Iterator::fetch_next_frame() {
    CFrame* frame_ptr = con_frame_iterator_next(iterator_ptr_);
    if (frame_ptr) {
        current_frame_.reset(new ConFrame(frame_ptr));
    } else {
        current_frame_ = nullptr;
    }
}

inline const ConFrame& ConFrameIterator::Iterator::operator*() const {
    return *current_frame_;
}

inline const ConFrame* ConFrameIterator::Iterator::operator->() const {
    return current_frame_.get();
}

inline ConFrameIterator::Iterator& ConFrameIterator::Iterator::operator++() {
    fetch_next_frame();
    return *this;
}

/**
 * @brief A C++ wrapper for the symbol-to-atomic-number utility function.
 *
 * @param symbol An element symbol (e.g., "H", "Cu").
 * @return The corresponding atomic number.
 */
inline uint64_t symbol_to_atomic_number(std::string_view symbol) {
    return rust_symbol_to_atomic_number(std::string(symbol).c_str());
}

} // namespace readcon

#endif // READCON_PLUS_PLUS_H
