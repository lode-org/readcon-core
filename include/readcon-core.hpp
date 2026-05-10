#ifndef READCON_PLUS_PLUS_H
#define READCON_PLUS_PLUS_H

#pragma once

// readcon-core C++ wrapper. Header-only RAII layer over the C API in
// readcon-core.h. Requires C++17 (uses std::optional, std::filesystem,
// and structured bindings).
#if defined(__cplusplus) && __cplusplus < 201703L
#error "readcon-core.hpp requires C++17 or later"
#endif

#include <array>
#include <cmath>
#include <filesystem>
#include <iterator>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "readcon-core.h"

namespace readcon {

/**
 * @brief C++ representation of a single atom's core data.
 *
 * Velocity and force components are exposed as a single
 * `std::optional<std::array<double, 3>>` each, matching the Rust
 * `AtomDatum::velocity` / `AtomDatum::force` shape. The legacy
 * per-axis fields (`vx`, `vy`, ..., `has_velocity`, ...) are still
 * present for backward compatibility with existing C++ consumers and
 * are kept in sync on construction.
 */
struct Atom {
    uint64_t atomic_number;
    double x;
    double y;
    double z;
    uint64_t atom_id;
    double mass;
    /// Legacy aggregate fixed flag. True when any axis is fixed.
    /// Prefer `fixed_x`/`fixed_y`/`fixed_z` or `fixed_mask()`.
    [[deprecated("Use fixed_x/fixed_y/fixed_z or fixed_mask() instead")]]
    bool is_fixed;
    bool fixed_x;
    bool fixed_y;
    bool fixed_z;
    [[deprecated("Use velocity() (returns std::optional) instead")]]
    double vx;
    [[deprecated("Use velocity() (returns std::optional) instead")]]
    double vy;
    [[deprecated("Use velocity() (returns std::optional) instead")]]
    double vz;
    [[deprecated("Use velocity() (returns std::optional) instead")]]
    bool has_velocity;
    [[deprecated("Use force() (returns std::optional) instead")]]
    double fx;
    [[deprecated("Use force() (returns std::optional) instead")]]
    double fy;
    [[deprecated("Use force() (returns std::optional) instead")]]
    double fz;
    [[deprecated("Use force() (returns std::optional) instead")]]
    bool has_forces;

    std::array<bool, 3> fixed_mask() const {
        return {fixed_x, fixed_y, fixed_z};
    }

    /// Velocity vector if present, else std::nullopt.
    std::optional<std::array<double, 3>> velocity() const {
        // Suppress the deprecation warning for the internal conversion;
        // public callers reaching the legacy fields directly will still
        // see it.
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
        if (has_velocity)
            return std::array<double, 3>{vx, vy, vz};
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif
        return std::nullopt;
    }

    /// Force vector if present, else std::nullopt.
    std::optional<std::array<double, 3>> force() const {
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
        if (has_forces)
            return std::array<double, 3>{fx, fy, fz};
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif
        return std::nullopt;
    }
};

// Forward declarations
class ConFrame;
class ConFrameWriter;
class ConFrameBuilder;

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
        /** @brief Equality. Both iterators are equal when both reference the
         *  same iterator handle and both have an empty current frame
         *  (the post-end / sentinel state). */
        bool operator==(const Iterator &other) const;
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
    friend class ConFrameBuilder;
    friend ConFrame read_first_frame(const std::filesystem::path &);
    friend std::vector<ConFrame> read_all_frames(const std::filesystem::path &);

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
    bool has_forces() const;

    uint32_t spec_version() const;
    std::string metadata_json() const;

    /// Per-frame total energy. Returns NaN if absent (legacy, prefer
    /// `energy_opt()`).
    double energy() const;
    /// Zero-based frame index. Returns UINT64_MAX if absent (legacy,
    /// prefer `frame_index_opt()`).
    uint64_t frame_index() const;
    /// Simulation time. Returns NaN if absent (legacy, prefer
    /// `time_opt()`).
    double time() const;
    /// Integration timestep. Returns NaN if absent (legacy, prefer
    /// `timestep_opt()`).
    double timestep() const;
    /// NEB bead index. Returns UINT64_MAX if absent (legacy, prefer
    /// `neb_bead_opt()`).
    uint64_t neb_bead() const;
    /// NEB band index. Returns UINT64_MAX if absent (legacy, prefer
    /// `neb_band_opt()`).
    uint64_t neb_band() const;

    /// Per-frame total energy if present, else nullopt.
    std::optional<double> energy_opt() const;
    /// Zero-based frame index if present, else nullopt.
    std::optional<uint64_t> frame_index_opt() const;
    /// Simulation time if present, else nullopt.
    std::optional<double> time_opt() const;
    /// Integration timestep if present, else nullopt.
    std::optional<double> timestep_opt() const;
    /// NEB bead index if present, else nullopt.
    std::optional<uint64_t> neb_bead_opt() const;
    /// NEB band index if present, else nullopt.
    std::optional<uint64_t> neb_band_opt() const;
    /// Potential type string (e.g. "EMT") if present, else nullopt.
    std::optional<std::string> potential_type() const;

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
    mutable bool has_forces_cache_ = false;
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
     * @param precision Number of decimal places for floating-point output (default 6).
     * @throws std::runtime_error if the file cannot be created.
     */
    explicit ConFrameWriter(const std::filesystem::path &path,
                            uint8_t precision = 6);

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

/**
 * @brief A builder for constructing ConFrame objects from in-memory data.
 *
 * Atoms are accumulated and grouped by symbol on build() to compute
 * the header fields.
 *
 * Example:
 *
 * readcon::ConFrameBuilder builder({10.0, 10.0, 10.0}, {90.0, 90.0, 90.0});
 * builder.add_atom("Cu", 0.0, 0.0, 0.0, true, 0, 63.546);
 * auto frame = builder.build();
 */
class ConFrameBuilder {
  public:
    /**
     * @brief Constructs a builder with cell dimensions, angles, and optional headers.
     */
    ConFrameBuilder(const std::array<double, 3> &cell,
                    const std::array<double, 3> &angles,
                    const std::array<std::string, 2> &prebox = {"", ""},
                    const std::array<std::string, 2> &postbox = {"", ""});

    ~ConFrameBuilder();
    ConFrameBuilder(const ConFrameBuilder &) = delete;
    ConFrameBuilder &operator=(const ConFrameBuilder &) = delete;
    ConFrameBuilder(ConFrameBuilder &&other) noexcept;
    ConFrameBuilder &operator=(ConFrameBuilder &&other) noexcept;

    /**
     * @brief Parses and sets JSON metadata for the generated header line 2.
     *
     * The JSON must be an object. `con_spec_version` and `sections` are
     * managed automatically by the writer and ignored if present.
     */
    ConFrameBuilder &set_metadata_json(const std::string &metadata_json);

    /// Sets a numeric metadata key.
    ConFrameBuilder &set_scalar_metadata(const std::string &key, double value);
    /// Sets a string metadata key.
    ConFrameBuilder &set_string_metadata(const std::string &key,
                                         const std::string &value);
    /// Sets the per-frame total energy metadata.
    ConFrameBuilder &set_energy(double energy);
    /// Sets the zero-based frame index metadata.
    ConFrameBuilder &set_frame_index(uint64_t idx);
    /// Sets the simulation time metadata.
    ConFrameBuilder &set_time(double time);
    /// Sets the timestep metadata.
    ConFrameBuilder &set_timestep(double dt);
    /// Sets the NEB bead index metadata.
    ConFrameBuilder &set_neb_bead(uint64_t bead);
    /// Sets the NEB band index metadata.
    ConFrameBuilder &set_neb_band(uint64_t band);

    /**
     * @brief Adds an atom and returns *this for chaining.
     *
     * Optional `velocity` and `force` parameters carry the per-atom
     * vector data. Pass `std::nullopt` (or rely on the default) for atoms
     * without that section.
     *
     * Example:
     * @code
     *   builder.add_atom("Cu", 0, 0, 0, {true, true, true}, 0, 63.546,
     *                    {{0.1, 0.2, 0.3}});
     * @endcode
     *
     * For chained per-atom attachment use the legacy `with_velocity` /
     * `with_force` helpers, which mutate the most recently added atom.
     */
    ConFrameBuilder &add_atom(
        const std::string &symbol, double x, double y, double z,
        const std::array<bool, 3> &fixed, uint64_t atom_id, double mass,
        std::optional<std::array<double, 3>> velocity = std::nullopt,
        std::optional<std::array<double, 3>> force = std::nullopt);

    /// Convenience overload for the all-axes-fixed boolean shorthand.
    ConFrameBuilder &add_atom(
        const std::string &symbol, double x, double y, double z, bool is_fixed,
        uint64_t atom_id, double mass,
        std::optional<std::array<double, 3>> velocity = std::nullopt,
        std::optional<std::array<double, 3>> force = std::nullopt);

    /// Attaches velocity to the most recently added atom (chainable).
    ConFrameBuilder &with_velocity(const std::array<double, 3> &v);
    /// Attaches force to the most recently added atom (chainable).
    ConFrameBuilder &with_force(const std::array<double, 3> &f);

    /**
     * @brief Consumes the builder and returns a finalized ConFrame.
     *
     * The builder is invalidated after this call: every subsequent
     * method (add_atom, set_*, with_*, build) is a no-op or throws.
     * Construct a new ConFrameBuilder if you need to author another
     * frame.
     *
     * @throws std::runtime_error if the build fails or if `build()`
     *         is called on an already-consumed builder.
     */
    ConFrame build();

  private:
    RKRConFrameBuilder *builder_handle_ = nullptr;
};

// --- Convenience free functions ---

inline std::string status_message(RKRStatus status) {
    const char *message = rkr_status_message(status);
    return message ? std::string(message) : std::string("unknown status");
}

/**
 * @brief Returns the atomic number for a chemical symbol, or 0 if the
 *        symbol is unknown. Coverage is H..U (Z = 1..=92);
 *        case-sensitive.
 */
inline uint64_t symbol_to_z(const std::string &symbol) {
    return rkr_symbol_to_z(symbol.c_str());
}

/**
 * @brief Returns the chemical symbol for an atomic number, or "X" for
 *        unknown values. The returned string is process-static; copying
 *        into a std::string is safe.
 */
inline std::string z_to_symbol(uint64_t z) {
    const char *symbol = rkr_z_to_symbol(z);
    return symbol ? std::string(symbol) : std::string("X");
}

inline void throw_on_error(RKRStatus status, const std::string &operation) {
    if (status != RKRStatus::RKR_STATUS_SUCCESS) {
        throw std::runtime_error(operation + ": " + status_message(status));
    }
}

/**
 * @brief Reads the first frame from a .con file using mmap.
 * @throws std::runtime_error on failure.
 */
inline ConFrame read_first_frame(const std::filesystem::path &path) {
    RKRConFrame *handle = rkr_read_first_frame(path.string().c_str());
    if (!handle) {
        throw std::runtime_error("Failed to read first frame from: " +
                                 path.string());
    }
    return ConFrame(handle);
}

/**
 * @brief Reads all frames from a .con file using mmap.
 * @throws std::runtime_error on failure.
 */
inline std::vector<ConFrame> read_all_frames(const std::filesystem::path &path) {
    size_t num_frames = 0;
    RKRConFrame **handles = rkr_read_all_frames(path.string().c_str(), &num_frames);
    if (!handles) {
        throw std::runtime_error("Failed to read frames from: " +
                                 path.string());
    }
    std::vector<ConFrame> frames;
    frames.reserve(num_frames);
    for (size_t i = 0; i < num_frames; ++i) {
        frames.emplace_back(ConFrame(handles[i]));
    }
    // Null out the handles since they're now owned by ConFrame objects,
    // then free the array via the Rust allocator.
    for (size_t i = 0; i < num_frames; ++i) {
        handles[i] = nullptr;
    }
    free_rkr_frame_array(handles, num_frames);
    return frames;
}

// --- Implementation of ConFrameIterator and its nested Iterator ---

inline ConFrameIterator::ConFrameIterator(const std::filesystem::path &path) {
    CConFrameIterator *iter_ptr = read_con_file_iterator(path.string().c_str());
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
ConFrameIterator::Iterator::operator==(const Iterator &other) const {
    return current_frame_ == other.current_frame_;
}
inline bool
ConFrameIterator::Iterator::operator!=(const Iterator &other) const {
    return !(*this == other);
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
    has_forces_cache_ = c_frame->has_forces;

    atoms_cache_.reserve(c_frame->num_atoms);
    // The legacy Atom fields (vx/vy/vz, fx/fy/fz, has_velocity,
    // has_forces, is_fixed) carry [[deprecated]] markers so external
    // callers get a compile-time nudge toward velocity()/force() and
    // the per-axis flags. The wrapper still populates them here as the
    // single source of truth that the new accessors read from, so the
    // deprecation warning is suppressed locally.
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
    for (size_t i = 0; i < c_frame->num_atoms; ++i) {
        const CAtom &c_atom = c_frame->atoms[i];
        atoms_cache_.emplace_back(
            Atom{c_atom.atomic_number, c_atom.x, c_atom.y, c_atom.z,
                 c_atom.atom_id, c_atom.mass, c_atom.is_fixed,
                 c_atom.fixed_x, c_atom.fixed_y, c_atom.fixed_z,
                 c_atom.vx, c_atom.vy, c_atom.vz, c_atom.has_velocity,
                 c_atom.fx, c_atom.fy, c_atom.fz, c_atom.has_forces});
    }
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif

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

inline bool ConFrame::has_forces() const {
    cache_data();
    return has_forces_cache_;
}

inline uint32_t ConFrame::spec_version() const {
    return rkr_frame_spec_version(frame_handle_.get());
}

inline std::string ConFrame::metadata_json() const {
    char *json = rkr_frame_metadata_json(frame_handle_.get());
    if (!json)
        return "";
    std::string result(json);
    rkr_free_string(json);
    return result;
}

inline double ConFrame::energy() const {
    return rkr_frame_energy(frame_handle_.get());
}

inline uint64_t ConFrame::frame_index() const {
    return rkr_frame_frame_index(frame_handle_.get());
}

inline double ConFrame::time() const {
    return rkr_frame_time(frame_handle_.get());
}

inline double ConFrame::timestep() const {
    return rkr_frame_timestep(frame_handle_.get());
}

inline uint64_t ConFrame::neb_bead() const {
    return rkr_frame_neb_bead(frame_handle_.get());
}

inline uint64_t ConFrame::neb_band() const {
    return rkr_frame_neb_band(frame_handle_.get());
}

inline std::optional<double> ConFrame::energy_opt() const {
    double v = rkr_frame_energy(frame_handle_.get());
    if (std::isnan(v))
        return std::nullopt;
    return v;
}

inline std::optional<uint64_t> ConFrame::frame_index_opt() const {
    uint64_t v = rkr_frame_frame_index(frame_handle_.get());
    if (v == UINT64_MAX)
        return std::nullopt;
    return v;
}

inline std::optional<double> ConFrame::time_opt() const {
    double v = rkr_frame_time(frame_handle_.get());
    if (std::isnan(v))
        return std::nullopt;
    return v;
}

inline std::optional<double> ConFrame::timestep_opt() const {
    double v = rkr_frame_timestep(frame_handle_.get());
    if (std::isnan(v))
        return std::nullopt;
    return v;
}

inline std::optional<uint64_t> ConFrame::neb_bead_opt() const {
    uint64_t v = rkr_frame_neb_bead(frame_handle_.get());
    if (v == UINT64_MAX)
        return std::nullopt;
    return v;
}

inline std::optional<uint64_t> ConFrame::neb_band_opt() const {
    uint64_t v = rkr_frame_neb_band(frame_handle_.get());
    if (v == UINT64_MAX)
        return std::nullopt;
    return v;
}

inline std::optional<std::string> ConFrame::potential_type() const {
    char *p = rkr_frame_potential_type(frame_handle_.get());
    if (!p)
        return std::nullopt;
    std::string s(p);
    rkr_free_string(p);
    return s;
}

// --- Implementation of ConFrameWriter methods ---

inline ConFrameWriter::ConFrameWriter(const std::filesystem::path &path,
                                      uint8_t precision) {
    if (precision == 6) {
        writer_handle_.reset(create_writer_from_path_c(path.string().c_str()));
    } else {
        writer_handle_.reset(
            create_writer_from_path_with_precision_c(path.string().c_str(), precision));
    }
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

    throw_on_error(
        rkr_writer_extend(writer_handle_.get(), handles.data(), handles.size()),
        "Failed to write multiple frames");
}

// --- Implementation of ConFrameBuilder methods ---

inline ConFrameBuilder::ConFrameBuilder(
    const std::array<double, 3> &cell, const std::array<double, 3> &angles,
    const std::array<std::string, 2> &prebox,
    const std::array<std::string, 2> &postbox) {
    builder_handle_ =
        rkr_frame_new(cell.data(), angles.data(), prebox[0].c_str(),
                      prebox[1].c_str(), postbox[0].c_str(), postbox[1].c_str());
    if (!builder_handle_) {
        throw std::runtime_error("Failed to create frame builder.");
    }
}

inline ConFrameBuilder::~ConFrameBuilder() {
    if (builder_handle_) {
        free_rkr_frame_builder(builder_handle_);
    }
}

inline ConFrameBuilder::ConFrameBuilder(ConFrameBuilder &&other) noexcept
    : builder_handle_(other.builder_handle_) {
    other.builder_handle_ = nullptr;
}

inline ConFrameBuilder &
ConFrameBuilder::operator=(ConFrameBuilder &&other) noexcept {
    if (this != &other) {
        if (builder_handle_) {
            free_rkr_frame_builder(builder_handle_);
        }
        builder_handle_ = other.builder_handle_;
        other.builder_handle_ = nullptr;
    }
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::add_atom(const std::string &symbol, double x, double y,
                          double z, const std::array<bool, 3> &fixed,
                          uint64_t atom_id, double mass,
                          std::optional<std::array<double, 3>> velocity,
                          std::optional<std::array<double, 3>> force) {
    const double *vptr = velocity ? velocity->data() : nullptr;
    const double *fptr = force ? force->data() : nullptr;
    throw_on_error(rkr_frame_add_atom_full(builder_handle_, symbol.c_str(), x,
                                           y, z, fixed[0], fixed[1], fixed[2],
                                           atom_id, mass, vptr, fptr),
                   "Failed to add atom to frame builder");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::add_atom(const std::string &symbol, double x, double y,
                          double z, bool is_fixed, uint64_t atom_id,
                          double mass,
                          std::optional<std::array<double, 3>> velocity,
                          std::optional<std::array<double, 3>> force) {
    return add_atom(symbol, x, y, z,
                    {is_fixed, is_fixed, is_fixed}, atom_id, mass,
                    std::move(velocity), std::move(force));
}

inline ConFrameBuilder &
ConFrameBuilder::with_velocity(const std::array<double, 3> &v) {
    throw_on_error(
        rkr_frame_builder_set_last_velocity(builder_handle_, v.data()),
        "Failed to attach velocity to last atom");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::with_force(const std::array<double, 3> &f) {
    throw_on_error(
        rkr_frame_builder_set_last_force(builder_handle_, f.data()),
        "Failed to attach force to last atom");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_metadata_json(const std::string &metadata_json) {
    throw_on_error(rkr_frame_builder_set_metadata_json(builder_handle_,
                                                       metadata_json.c_str()),
                   "Failed to set builder metadata JSON");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_scalar_metadata(const std::string &key, double value) {
    throw_on_error(rkr_frame_builder_set_scalar_metadata(
                       builder_handle_, key.c_str(), value),
                   "Failed to set builder scalar metadata");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_string_metadata(const std::string &key,
                                     const std::string &value) {
    throw_on_error(rkr_frame_builder_set_string_metadata(
                       builder_handle_, key.c_str(), value.c_str()),
                   "Failed to set builder string metadata");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_energy(double energy) {
    throw_on_error(rkr_frame_builder_set_energy(builder_handle_, energy),
                   "Failed to set builder energy metadata");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_frame_index(uint64_t idx) {
    throw_on_error(rkr_frame_builder_set_frame_index(builder_handle_, idx),
                   "Failed to set builder frame_index metadata");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_time(double time) {
    throw_on_error(rkr_frame_builder_set_time(builder_handle_, time),
                   "Failed to set builder time metadata");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_timestep(double dt) {
    throw_on_error(rkr_frame_builder_set_timestep(builder_handle_, dt),
                   "Failed to set builder timestep metadata");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_neb_bead(uint64_t bead) {
    throw_on_error(rkr_frame_builder_set_neb_bead(builder_handle_, bead),
                   "Failed to set builder neb_bead metadata");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_neb_band(uint64_t band) {
    throw_on_error(rkr_frame_builder_set_neb_band(builder_handle_, band),
                   "Failed to set builder neb_band metadata");
    return *this;
}

inline ConFrame ConFrameBuilder::build() {
    RKRConFrame *frame = rkr_frame_builder_build(builder_handle_);
    builder_handle_ = nullptr; // ownership transferred
    if (!frame) {
        throw std::runtime_error("Failed to build frame from builder.");
    }
    return ConFrame(frame);
}

} // namespace readcon

#endif // READCON_PLUS_PLUS_H
