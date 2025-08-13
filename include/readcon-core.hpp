#ifndef READCON_PLUS_PLUS_H
#define READCON_PLUS_PLUS_H

#pragma once

#include <array>
#include <filesystem>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "readcon-core.h"

namespace readcon {

/**
 * @brief C++ representation of a single atom's core data.
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
 * for (auto&& frame : frames) { // Use && to allow moving
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
        using iterator_category = std::input_iterator_tag;
        using value_type = ConFrame;
        using difference_type = std::ptrdiff_t;
        // Return non-const to allow moving from the iterator
        using pointer = ConFrame *;
        using reference = ConFrame &;

        /** @brief Dereference operator to get the current frame. */
        reference operator*();
        /** @brief Member access operator. */
        pointer operator->();
        /** @brief Pre-increment operator to advance to the next frame. */
        Iterator &operator++();
        /** @brief Comparison operator to check for the end of the iteration. */
        bool operator!=(const Iterator &other) const;

      private:
        friend class ConFrameIterator;
        explicit Iterator(CConFrameIterator *iterator_ptr);
        void fetch_next_frame();
        CConFrameIterator *iterator_ptr_ = nullptr;
        std::unique_ptr<ConFrame> current_frame_;
    };

    /**
     * @brief Constructs a frame iterator from a file path.
     * @param path The path to the .con file.
     * @throws std::runtime_error if the file cannot be opened.
     */
    explicit ConFrameIterator(const std::filesystem::path &path);
    /**
     * @brief Returns an iterator to the beginning of the sequence of frames.
     */
    Iterator begin();
    /**
     * @brief Returns an iterator to the end of the sequence.
     */
    Iterator end();

  private:
    // Custom deleter for the CConFrameIterator to call the C free function.
    struct IteratorDeleter {
        void operator()(CConFrameIterator *ptr) const {
            if (ptr) {
                free_con_frame_iterator(ptr);
            }
        }
    };

    std::unique_ptr<CConFrameIterator, IteratorDeleter> iterator_ptr_;
};

/**
 * @brief A C++ wrapper for a simulation frame handle.
 *
 * This class follows RAII to manage the memory of an opaque `RKRConFrame`
 * handle. It provides accessor methods to safely retrieve data from the
 * underlying Rust object.
 */
class ConFrame {
  public:
    friend class ConFrameIterator::Iterator;

    ConFrame(const ConFrame &) = delete;
    ConFrame &operator=(const ConFrame &) = delete;
    ConFrame(ConFrame &&) = default;
    ConFrame &operator=(ConFrame &&) = default;

    /** @brief Gets the simulation cell dimensions (a, b, c). */
    std::array<double, 3> cell() const;
    /** @brief Gets the simulation cell angles (alpha, beta, gamma). */
    std::array<double, 3> angles() const;
    /** @brief Gets a vector of all atoms in the frame. */
    std::vector<Atom> atoms() const;
    /** @brief Gets the two pre-box header lines. */
    std::array<std::string, 2> prebox_header() const;
    /** @brief Gets the two post-box header lines. */
    std::array<std::string, 2> postbox_header() const;
    /** @brief Writes the current frame to a file. */
    void write(const std::filesystem::path &path) const;

    /** @brief Gets the raw opaque handle to the underlying Rust object. */
    const RKRConFrame *get_handle() const { return frame_handle_.get(); }

  private:
    struct FrameDeleter {
        void operator()(RKRConFrame *ptr) const {
            if (ptr)
                free_rkr_frame(ptr);
        }
    };
    explicit ConFrame(RKRConFrame *frame_handle);
    std::unique_ptr<RKRConFrame, FrameDeleter> frame_handle_;
};

// --- Free function for writing multiple frames ---

/**
 * @brief Writes a vector of ConFrame objects to a multi-frame .con file.
 * @param path The path to the output file.
 * @param frames A vector of ConFrame objects to write.
 * @throws std::runtime_error if writing fails.
 */
inline void write_con_file(const std::filesystem::path &path,
                           const std::vector<ConFrame> &frames) {
    if (frames.empty())
        return;

    std::vector<const RKRConFrame *> handles;
    handles.reserve(frames.size());
    for (const auto &frame : frames) {
        handles.push_back(frame.get_handle());
    }

    if (write_rkr_frames_to_file(handles.data(), handles.size(),
                                 path.c_str()) != 0) {
        throw std::runtime_error("Failed to write frames to file: " +
                                 path.string());
    }
}

// --- Implementation of ConFrameIterator and its nested Iterator ---

inline ConFrameIterator::ConFrameIterator(const std::filesystem::path &path) {
    CConFrameIterator *iter_ptr = read_con_file_iterator(path.c_str());
    if (!iter_ptr) {
        throw std::runtime_error("Failed to open .con file for iteration: " +
                                 path.string());
    }
    iterator_ptr_.reset(iter_ptr);
}

inline ConFrameIterator::Iterator ConFrameIterator::begin() {
    return Iterator(iterator_ptr_.get());
}
inline ConFrameIterator::Iterator ConFrameIterator::end() {
    return Iterator(nullptr);
}
inline bool
ConFrameIterator::Iterator::operator!=(const Iterator &other) const {
    return current_frame_ != other.current_frame_;
}
inline ConFrameIterator::Iterator::Iterator(CConFrameIterator *iterator_ptr)
    : iterator_ptr_(iterator_ptr) {
    if (iterator_ptr_)
        fetch_next_frame();
}

inline void ConFrameIterator::Iterator::fetch_next_frame() {
    RKRConFrame *frame_handle = con_frame_iterator_next(iterator_ptr_);
    if (frame_handle) {
        current_frame_ = std::unique_ptr<ConFrame>(new ConFrame(frame_handle));
    } else {
        current_frame_ = nullptr;
    }
}

inline ConFrame &ConFrameIterator::Iterator::operator*() {
    return *current_frame_;
}
inline ConFrame *ConFrameIterator::Iterator::operator->() {
    return current_frame_.get();
}
inline ConFrameIterator::Iterator &ConFrameIterator::Iterator::operator++() {
    fetch_next_frame();
    return *this;
}

// --- Implementation of ConFrame methods ---

inline ConFrame::ConFrame(RKRConFrame *frame_handle)
    : frame_handle_(frame_handle) {}

inline std::array<double, 3> ConFrame::cell() const {
    CFrame *c_frame = rkr_frame_to_c_frame(frame_handle_.get());
    if (!c_frame)
        throw std::runtime_error("Failed to extract CFrame from handle.");
    std::array<double, 3> result = {c_frame->cell[0], c_frame->cell[1],
                                    c_frame->cell[2]};
    free_c_frame(c_frame);
    return result;
}

inline std::array<double, 3> ConFrame::angles() const {
    CFrame *c_frame = rkr_frame_to_c_frame(frame_handle_.get());
    if (!c_frame)
        throw std::runtime_error("Failed to extract CFrame from handle.");
    std::array<double, 3> result = {c_frame->angles[0], c_frame->angles[1],
                                    c_frame->angles[2]};
    free_c_frame(c_frame);
    return result;
}

inline std::vector<Atom> ConFrame::atoms() const {
    CFrame *c_frame = rkr_frame_to_c_frame(frame_handle_.get());
    if (!c_frame)
        throw std::runtime_error("Failed to extract CFrame from handle.");
    std::vector<Atom> atoms_vec;
    atoms_vec.reserve(c_frame->num_atoms);
    for (size_t i = 0; i < c_frame->num_atoms; ++i) {
        const CAtom &c_atom = c_frame->atoms[i];
        atoms_vec.emplace_back(Atom{c_atom.atomic_number, c_atom.x, c_atom.y,
                                    c_atom.z, c_atom.atom_id, c_atom.mass,
                                    c_atom.is_fixed});
    }
    free_c_frame(c_frame);
    return atoms_vec;
}

inline std::array<std::string, 2> ConFrame::prebox_header() const {
    std::array<std::string, 2> headers;
    char buffer[256];
    rkr_frame_get_header_line(frame_handle_.get(), true, 0, buffer, 256);
    headers[0] = buffer;
    rkr_frame_get_header_line(frame_handle_.get(), true, 1, buffer, 256);
    headers[1] = buffer;
    return headers;
}

inline std::array<std::string, 2> ConFrame::postbox_header() const {
    std::array<std::string, 2> headers;
    char buffer[256];
    rkr_frame_get_header_line(frame_handle_.get(), false, 0, buffer, 256);
    headers[0] = buffer;
    rkr_frame_get_header_line(frame_handle_.get(), false, 1, buffer, 256);
    headers[1] = buffer;
    return headers;
}

inline void ConFrame::write(const std::filesystem::path &path) const {
    if (write_single_rkr_frame(frame_handle_.get(), path.c_str()) != 0) {
        throw std::runtime_error("Failed to write frame to file: " +
                                 path.string());
    }
}

} // namespace readcon

#endif // READCON_PLUS_PLUS_H
