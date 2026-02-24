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
    double vx;
    double vy;
    double vz;
    bool has_velocity;
};

// Forward declarations
class ConFrame;
class ConFrameWriter;

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
    friend class ConFrameWriter;

    ConFrame(const ConFrame &) = delete;
    ConFrame &operator=(const ConFrame &) = delete;
    ConFrame(ConFrame &&) = default;
    ConFrame &operator=(ConFrame &&) = default;

    const std::array<double, 3> &cell() const;
    const std::array<double, 3> &angles() const;
    const std::vector<Atom> &atoms() const;
    const std::array<std::string, 2> &prebox_header() const;
    const std::array<std::string, 2> &postbox_header() const;
    bool has_velocities() const;

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

    // --- Caching Implementation ---
    void cache_data() const;
    mutable bool is_cached_ = false;
    mutable std::vector<Atom> atoms_cache_;
    mutable std::array<double, 3> cell_cache_;
    mutable std::array<double, 3> angles_cache_;
    mutable std::array<std::string, 2> prebox_header_cache_;
    mutable std::array<std::string, 2> postbox_header_cache_;
    mutable bool has_velocities_cache_ = false;
};

/**
 * @brief A C++ wrapper for writing frames to a .con file.
 *
 * This class follows RAII to manage the underlying file handle from the Rust
 * library. It opens the file on construction and automatically closes it on
 * destruction.
 */
class ConFrameWriter {
  public:
    /**
     * @brief Constructs a writer and opens the specified file for writing.
     * @param path The path to the output .con file.
     * @throws std::runtime_error if the file cannot be created.
     */
    explicit ConFrameWriter(const std::filesystem::path &path);

    /**
     * @brief Writes all frames from a vector to the file.
     * @param frames A vector of ConFrame objects.
     * @throws std::runtime_error if the write operation fails.
     */
    void extend(const std::vector<ConFrame> &frames);

  private:
    struct WriterDeleter {
        void operator()(RKRConFrameWriter *ptr) const {
            if (ptr)
                free_rkr_writer(ptr);
        }
    };
    std::unique_ptr<RKRConFrameWriter, WriterDeleter> writer_handle_;
};

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

inline void ConFrame::cache_data() const {
    if (is_cached_) {
        return;
    }

    // Extract the C-struct once for numeric data.
    CFrame *c_frame = rkr_frame_to_c_frame(frame_handle_.get());
    if (!c_frame) {
        throw std::runtime_error(
            "Failed to extract CFrame from handle for caching.");
    }

    cell_cache_ = {c_frame->cell[0], c_frame->cell[1], c_frame->cell[2]};
    angles_cache_ = {c_frame->angles[0], c_frame->angles[1],
                     c_frame->angles[2]};

    has_velocities_cache_ = c_frame->has_velocities;

    atoms_cache_.reserve(c_frame->num_atoms);
    for (size_t i = 0; i < c_frame->num_atoms; ++i) {
        const CAtom &c_atom = c_frame->atoms[i];
        atoms_cache_.emplace_back(
            Atom{c_atom.atomic_number, c_atom.x, c_atom.y, c_atom.z,
                 c_atom.atom_id, c_atom.mass, c_atom.is_fixed,
                 c_atom.vx, c_atom.vy, c_atom.vz, c_atom.has_velocity});
    }

    free_c_frame(c_frame);

    // Cache headers using the flexible FFI that allocates and frees
    // strings. This helper lambda makes the code cleaner and ensures memory is
    // always freed.
    auto get_and_free_string =
        [frame_handle = frame_handle_.get()](bool is_prebox, size_t index) {
            char *c_str =
                rkr_frame_get_header_line_cpp(frame_handle, is_prebox, index);
            if (!c_str) {
                return std::string();
            }
            std::string result(c_str);
            rkr_free_string(c_str);
            return result;
        };

    prebox_header_cache_[0] = get_and_free_string(true, 0);
    prebox_header_cache_[1] = get_and_free_string(true, 1);
    postbox_header_cache_[0] = get_and_free_string(false, 0);
    postbox_header_cache_[1] = get_and_free_string(false, 1);

    is_cached_ = true;
}

inline const std::array<double, 3> &ConFrame::cell() const {
    cache_data();
    return cell_cache_;
}

inline const std::array<double, 3> &ConFrame::angles() const {
    cache_data();
    return angles_cache_;
}

inline const std::vector<Atom> &ConFrame::atoms() const {
    cache_data();
    return atoms_cache_;
}

inline const std::array<std::string, 2> &ConFrame::prebox_header() const {
    cache_data();
    return prebox_header_cache_;
}

inline const std::array<std::string, 2> &ConFrame::postbox_header() const {
    cache_data();
    return postbox_header_cache_;
}

inline bool ConFrame::has_velocities() const {
    cache_data();
    return has_velocities_cache_;
}

// --- Implementation of ConFrameWriter methods ---

inline ConFrameWriter::ConFrameWriter(const std::filesystem::path &path) {
    writer_handle_.reset(create_writer_from_path_c(path.c_str()));
    if (!writer_handle_) {
        throw std::runtime_error("Failed to create writer for file: " +
                                 path.string());
    }
}

inline void ConFrameWriter::extend(const std::vector<ConFrame> &frames) {
    if (frames.empty())
        return;

    std::vector<const RKRConFrame *> handles;
    handles.reserve(frames.size());
    for (const auto &frame : frames) {
        handles.push_back(frame.get_handle());
    }

    if (rkr_writer_extend(writer_handle_.get(), handles.data(),
                          handles.size()) != 0) {
        throw std::runtime_error("Failed to write multiple frames.");
    }
}

} // namespace readcon

#endif // READCON_PLUS_PLUS_H
