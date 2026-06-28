#ifndef READCON_PLUS_PLUS_H
#define READCON_PLUS_PLUS_H

#pragma once

// readcon-core C++ wrapper. Header-only RAII layer over the C API in
// readcon-core.h. Requires C++17 (uses std::optional, std::filesystem,
// and structured bindings).
#if defined(__cplusplus) && __cplusplus < 201703L
#error "readcon-core.hpp requires C++17 or later"
#endif

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iterator>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
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
    /// Per-atom energy contribution; meaningful only when `has_energy`
    /// is true. Mirrors `Rust AtomDatum::energy`.
    double energy;
    bool has_energy;

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

    /// Per-atom energy contribution if the file declared an
    /// `"energies"` section, else std::nullopt.
    std::optional<double> energy_value() const {
        if (has_energy)
            return energy;
        return std::nullopt;
    }
};

// Forward declarations
class ConFrame;
class ConFrameWriter;
class ConFrameBuilder;
class SelectionResult;

/**
 * @brief Optional frame topology bond (`metadata["bonds"]` entry).
 *
 * Indices are 0-based into `atom_data` order (not `atom_id`). Optional `order`
 * mirrors chemfiles bond orders when known (1=single, 2=double, ...).
 */
struct Bond {
    uint32_t i = 0;
    uint32_t j = 0;
    std::optional<int32_t> order;
};

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
    /// True when at least one atom carries a per-atom energy
    /// contribution (file declared an `"energies"` section).
    bool has_energies() const;

    /// Returns the position of an atom in the frame whose `atom_id`
    /// equals the given id, or `std::nullopt` if no such atom exists.
    /// O(N) per call.
    std::optional<size_t> atom_index_by_id(uint64_t atom_id) const;

    uint32_t spec_version() const;
    std::string metadata_json() const;

    /// Per-frame total energy. Returns NaN if absent (legacy, prefer
    /// `energy_opt()`).
    double energy() const;
    /// Campaign finite energy (index_proj); NaN if missing or non-finite.
    double index_energy() const;
    /// Canonical multiset formula for campaign indexes (e.g. Cu:2|H:2).
    std::string composition_formula() const;
    double total_mass() const;
    double cell_volume() const;
    double fmax() const;
    /// bit0 forces, bit1 velocities, bit2 energies.
    uint8_t sections_mask() const;
    uint32_t index_natoms() const;
    /// Full campaign projection as JSON (same fields as readcon-db prepare).
    std::string index_projection_json() const;
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

    /**
     * Optional frame topology from `metadata["bonds"]` (0-based atom_data indices).
     * Empty when absent. Enables chemfiles `bonds:` / `angles:` / `is_bonded`
     * selection when the library is built with chemfiles.
     */
    std::vector<Bond> bonds() const;

    /// True when `metadata["bonds"]` is present and non-empty.
    bool has_bonds() const;

    /**
     * Evaluate a chemfiles selection-language string on this frame.
     *
     * Requires a library built with chemfiles (`rkr_has_chemfiles_support()`).
     * Throws `std::runtime_error` on failure (invalid grammar, missing support).
     *
     * @param selection Chemfiles selection string, e.g. `"name O"` or `"all"`.
     */
    SelectionResult select(std::string_view selection) const;

    /**
     * Atom-context convenience: returns sorted unique primary indices for
     * selections such as `"name H"`. Throws if the selection is not atom context.
     */
    std::vector<size_t> select_atom_indices(std::string_view selection) const;


    /**
     * Atom count without materializing CFrame / AoS atoms cache.
     */
    std::size_t atom_count() const {
        return frame_handle_ ? static_cast<std::size_t>(rkr_frame_atom_count(frame_handle_.get()))
                             : 0;
    }

    /** Row-major xyz length >= 3*N. Status from C ABI. */
    RKRStatus copy_positions(double *out, std::size_t out_len) const {
        if (!frame_handle_)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_copy_positions(frame_handle_.get(), out, out_len);
    }
    RKRStatus copy_velocities(double *out, std::size_t out_len) const {
        if (!frame_handle_)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_copy_velocities(frame_handle_.get(), out, out_len);
    }
    RKRStatus copy_forces(double *out, std::size_t out_len) const {
        if (!frame_handle_)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_copy_forces(frame_handle_.get(), out, out_len);
    }
    RKRStatus copy_atom_energies(double *out, std::size_t out_len) const {
        if (!frame_handle_)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_copy_atom_energies(frame_handle_.get(), out, out_len);
    }
    RKRStatus copy_masses(double *out, std::size_t out_len) const {
        if (!frame_handle_)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_copy_masses(frame_handle_.get(), out, out_len);
    }
    RKRStatus copy_atom_ids(uint64_t *out, std::size_t out_len) const {
        if (!frame_handle_)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_copy_atom_ids(frame_handle_.get(), out, out_len);
    }
    /** DLPack positions (caller: rkr_dlpack_delete). Default float64/CPU. */
    RKRStatus positions_dlpack(RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_positions_dlpack(frame_handle_.get(), out_tensor);
    }
    /** Positions with DLPack dtype/device (`DLDataType` + `DLDevice`; CPU + f32/f64 for now). */
    RKRStatus positions_dlpack(const RKRDlpackExportOptions &opts,
                               RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_positions_dlpack_ex(frame_handle_.get(), &opts, out_tensor);
    }
    /** DLPack velocities; SECTION_ABSENT (-8) if the frame has none. */
    RKRStatus velocities_dlpack(RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_velocities_dlpack(frame_handle_.get(), out_tensor);
    }
    RKRStatus velocities_dlpack(const RKRDlpackExportOptions &opts,
                                RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_velocities_dlpack_ex(frame_handle_.get(), &opts, out_tensor);
    }
    /** DLPack forces; SECTION_ABSENT if missing. */
    RKRStatus forces_dlpack(RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_forces_dlpack(frame_handle_.get(), out_tensor);
    }
    RKRStatus forces_dlpack(const RKRDlpackExportOptions &opts,
                            RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_forces_dlpack_ex(frame_handle_.get(), &opts, out_tensor);
    }
    /** DLPack per-atom energies; SECTION_ABSENT if missing. */
    RKRStatus atom_energies_dlpack(RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_atom_energies_dlpack(frame_handle_.get(), out_tensor);
    }
    RKRStatus atom_energies_dlpack(const RKRDlpackExportOptions &opts,
                                   RKRDLManagedTensorVersioned **out_tensor) const {
        if (!frame_handle_ || !out_tensor)
            return RKR_STATUS_NULL_POINTER;
        return rkr_frame_atom_energies_dlpack_ex(frame_handle_.get(), &opts, out_tensor);
    }

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
    mutable bool has_energies_cache_ = false;
};

/**
 * @brief One chemfiles selection match (1-4 atom indices).
 */
struct SelectionMatch {
    uint32_t size = 0;
    std::array<uint64_t, 4> atoms{{UINT64_MAX, UINT64_MAX, UINT64_MAX, UINT64_MAX}};
};

/**
 * @brief RAII result of `ConFrame::select` / `rkr_frame_select`.
 *
 * Only meaningful when the linked `readcon_core` was built with chemfiles.
 */
class SelectionResult {
  public:
    SelectionResult() = default;
    SelectionResult(const SelectionResult &) = delete;
    SelectionResult &operator=(const SelectionResult &) = delete;
    SelectionResult(SelectionResult &&) = default;
    SelectionResult &operator=(SelectionResult &&) = default;

    explicit SelectionResult(RKRSelectionResult *handle) : handle_(handle) {}

    uint64_t match_count() const {
        return handle_ ? rkr_selection_result_match_count(handle_.get()) : 0;
    }

    uint32_t context_size() const {
        return handle_ ? rkr_selection_result_context_size(handle_.get()) : 0;
    }

    SelectionMatch match_at(uint64_t index) const {
        SelectionMatch m;
        if (!handle_) {
            throw std::runtime_error("SelectionResult: null handle");
        }
        uint32_t size = 0;
        RKRStatus st = rkr_selection_result_match_at(handle_.get(), index, m.atoms.data(), &size);
        if (st != RKR_STATUS_SUCCESS) {
            throw std::runtime_error(std::string("rkr_selection_result_match_at: ") +
                                     rkr_status_message(st));
        }
        m.size = size;
        return m;
    }

    /// Primary atom index per match (length == match_count()).
    std::vector<uint64_t> primary_indices() const {
        if (!handle_) {
            return {};
        }
        const uint64_t n = match_count();
        std::vector<uint64_t> out(static_cast<size_t>(n));
        if (n == 0) {
            return out;
        }
        uint64_t written = 0;
        RKRStatus st =
            rkr_selection_result_primary_indices(handle_.get(), out.data(), n, &written);
        if (st != RKR_STATUS_SUCCESS) {
            throw std::runtime_error(std::string("rkr_selection_result_primary_indices: ") +
                                     rkr_status_message(st));
        }
        out.resize(static_cast<size_t>(written));
        return out;
    }

    const RKRSelectionResult *get_handle() const { return handle_.get(); }

  private:
    struct Deleter {
        void operator()(RKRSelectionResult *p) const {
            if (p)
                rkr_selection_result_free(p);
        }
    };
    std::unique_ptr<RKRSelectionResult, Deleter> handle_;
};

inline bool has_chemfiles_support() { return rkr_has_chemfiles_support() != 0; }

inline SelectionResult ConFrame::select(std::string_view selection) const {
    if (!has_chemfiles_support()) {
        throw std::runtime_error(
            "readcon::ConFrame::select requires a chemfiles-enabled readcon_core build");
    }
    std::string sel(selection);
    RKRSelectionResult *raw = nullptr;
    RKRStatus st = rkr_frame_select(frame_handle_.get(), sel.c_str(), &raw);
    if (st != RKR_STATUS_SUCCESS) {
        throw std::runtime_error(std::string("rkr_frame_select: ") + rkr_status_message(st));
    }
    return SelectionResult(raw);
}

inline std::vector<size_t> ConFrame::select_atom_indices(std::string_view selection) const {
    SelectionResult res = select(selection);
    if (res.context_size() != 1) {
        throw std::runtime_error("select_atom_indices requires an atom-context selection");
    }
    auto prim = res.primary_indices();
    std::vector<size_t> out;
    out.reserve(prim.size());
    for (auto i : prim) {
        out.push_back(static_cast<size_t>(i));
    }
    std::sort(out.begin(), out.end());
    out.erase(std::unique(out.begin(), out.end()), out.end());
    return out;
}

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
     * @brief Compression codec applied to the output stream.
     *
     * The Rust core transparently reads gzip and (with the `zstd` Cargo
     * feature) zstd streams; these codecs expose the matching writers.
     * `Zstd` requires readcon-core to have been built with the `zstd`
     * feature: the backing C symbols are only declared when
     * `READCON_CORE_HAS_ZSTD` is defined, and requesting `Zstd` without
     * that support throws std::runtime_error.
     */
    enum class Compression { None, Gzip, Zstd };

    /**
     * @brief Constructs a writer and opens the specified file for writing.
     * @param path The path to the output .con file.
     * @param precision Number of decimal places for floating-point output (default 6).
     * @throws std::runtime_error if the file cannot be created.
     */
    explicit ConFrameWriter(const std::filesystem::path &path,
                            uint8_t precision = 6);

    /**
     * @brief Constructs a writer that compresses the output stream.
     * @param path The path to the output .con file.
     * @param compression Compression codec for the output stream.
     * @param precision Number of decimal places for floating-point output (default 6).
     * @throws std::runtime_error if the writer cannot be created, including
     *         when `Compression::Zstd` is requested but the library was built
     *         without the `zstd` feature (`READCON_CORE_HAS_ZSTD` undefined).
     */
    explicit ConFrameWriter(const std::filesystem::path &path,
                            Compression compression, uint8_t precision = 6);

    /**
     * @brief Picks a compression codec from a path's file extension.
     * @param path The output path to inspect.
     * @return `Compression::Gzip` for `.gz`, `Compression::Zstd` for `.zst`,
     *         `Compression::None` otherwise.
     *
     * Mirrors the Rust `detect_compression_from_extension` helper so a
     * single call site can route `.con`, `.con.gz`, and `.con.zst` paths
     * to the matching writer.
     */
    static Compression compression_from_extension(
        const std::filesystem::path &path);

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
     * @brief Cheap copy-on-write clone of this builder.
     *
     * Per-atom buffers (positions, velocities, forces, masses, atom_ids,
     * energies) share storage with the source via ArcArray; the resulting
     * builder is a distinct mutable handle but pays only an Arc bump
     * up-front. Subsequent mutations on either builder trigger a
     * per-buffer copy-on-write so writes do not leak across clones.
     *
     * Intended for NEB-style consumers that need N+2 builders carrying
     * the same template data without paying N (N, 3) f64 copies.
     */
    [[nodiscard]] ConFrameBuilder clone() const;

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
    /// Attaches a per-atom energy contribution to the most recently
    /// added atom (chainable). The frame auto-declares an `"energies"`
    /// section on `build()` if any atom carries an energy.
    ConFrameBuilder &with_energy(double energy);

    // --- v0.11.0 in-place mutation API --------------------------------------
    //
    // Allows long-lived consumers to bulk-load atoms once and then update
    // positions / velocities / forces / energies in place across many
    // simulation steps, calling build() only at I/O boundaries.
    // Out-of-range index errors raise std::runtime_error via throw_on_error.

    /// Number of atoms currently held in the builder.
    [[nodiscard]] size_t atom_count() const;

    /// Updates the Cartesian position of an existing atom. Throws on
    /// out-of-range index.
    ConFrameBuilder &set_atom_position(size_t i, double x, double y, double z);
    /// Sets the velocity of an existing atom (auto-declares "velocities"
    /// section on build() if any atom carries a velocity).
    ConFrameBuilder &set_atom_velocity(size_t i,
                                       const std::array<double, 3> &v);
    /// Sets the force on an existing atom.
    ConFrameBuilder &set_atom_force(size_t i, const std::array<double, 3> &f);
    /// Sets the per-atom energy contribution of an existing atom.
    ConFrameBuilder &set_atom_energy(size_t i, double energy);
    /// Updates per-direction fixed flags `[fixed_x, fixed_y, fixed_z]`.
    ConFrameBuilder &set_atom_fixed(size_t i, const std::array<bool, 3> &fixed);
    /// Updates the mass of an existing atom.
    ConFrameBuilder &set_atom_mass(size_t i, double mass);
    /// Updates the atom_id (.con column 5 pre-grouping index) of an
    /// existing atom. The atom_ids buffer's data pointer stays stable
    /// across this call.
    ConFrameBuilder &set_atom_id(size_t i, uint64_t atom_id);

    /// Removes velocity / force / energy data from an existing atom.
    ConFrameBuilder &clear_atom_velocity(size_t i);
    ConFrameBuilder &clear_atom_force(size_t i);
    ConFrameBuilder &clear_atom_energy(size_t i);

    /// Bulk-update positions for every atom from a flat row-major buffer
    /// `[x0,y0,z0,x1,y1,z1,...]` of length `3 * atom_count()`.
    ConFrameBuilder &set_positions_from_flat(const std::vector<double> &positions);
    /// Bulk-update forces from a flat row-major buffer of length `3 * atom_count()`.
    ConFrameBuilder &set_forces_from_flat(const std::vector<double> &forces);
    /// Bulk-update per-atom energies from a buffer of length `atom_count()`.
    ConFrameBuilder &set_atom_energies_from_flat(const std::vector<double> &energies);

    /// Read-only accessor: position of atom `i` as `(x, y, z)`.
    [[nodiscard]] std::array<double, 3> get_atom_position(size_t i) const;
    /// Read-only accessor: velocity of atom `i`, if any.
    [[nodiscard]] std::optional<std::array<double, 3>>
    get_atom_velocity(size_t i) const;
    /// Read-only accessor: force on atom `i`, if any.
    [[nodiscard]] std::optional<std::array<double, 3>>
    get_atom_force(size_t i) const;
    /// Read-only accessor: per-atom energy of atom `i`, if any.
    [[nodiscard]] std::optional<double> get_atom_energy(size_t i) const;
    /// Read-only accessor: mass of atom `i`.
    [[nodiscard]] double get_atom_mass(size_t i) const;

    /**
     * @name In-process zero-copy data accessors (v0.11.1)
     *
     * Raw pointer borrow into the builder's ndarray storage. The
     * intended use is `Eigen::Map<Eigen::Matrix<double, Eigen::Dynamic,
     * 3, Eigen::RowMajor>>(builder.positions_data(), N, 3)` and
     * equivalents in C, Fortran, and other in-process consumers. The
     * returned pointer is non-owning; the builder MUST outlive any
     * use, and the pointer becomes invalid if `add_atom` reallocates
     * the underlying buffer. Cross-language tensor consumers (NumPy,
     * PyTorch, Julia) should use the DLPack tier-3 accessors below
     * which carry shape / dtype / device metadata and respect the
     * DLPack ABI's deleter contract.
     *
     * @return raw pointer to the field's first element; nullptr if
     *         the section is absent or the builder is invalid.
     * @{
     */
    [[nodiscard]] double *positions_data() noexcept;
    [[nodiscard]] double *velocities_data() noexcept;
    [[nodiscard]] double *forces_data() noexcept;
    [[nodiscard]] double *atom_energies_data() noexcept;
    [[nodiscard]] double *masses_data() noexcept;
    [[nodiscard]] const uint64_t *atom_ids_data() const noexcept;
    /// @}

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
    has_energies_cache_ = c_frame->has_energies;

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
                 c_atom.fx, c_atom.fy, c_atom.fz, c_atom.has_forces,
                 c_atom.energy, c_atom.has_energy});
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

inline bool ConFrame::has_energies() const {
    cache_data();
    return has_energies_cache_;
}

inline std::optional<size_t>
ConFrame::atom_index_by_id(uint64_t atom_id) const {
    uint64_t idx = rkr_frame_atom_index_by_id(frame_handle_.get(), atom_id);
    if (idx == UINT64_MAX) {
        return std::nullopt;
    }
    return static_cast<size_t>(idx);
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

inline double ConFrame::index_energy() const {
    return rkr_frame_index_energy(frame_handle_.get());
}

inline std::string ConFrame::composition_formula() const {
    char *s = rkr_frame_composition_formula(frame_handle_.get());
    if (!s)
        return "";
    std::string result(s);
    rkr_free_string(s);
    return result;
}

inline double ConFrame::total_mass() const {
    return rkr_frame_total_mass(frame_handle_.get());
}

inline double ConFrame::cell_volume() const {
    return rkr_frame_cell_volume(frame_handle_.get());
}

inline double ConFrame::fmax() const {
    return rkr_frame_fmax(frame_handle_.get());
}

inline uint8_t ConFrame::sections_mask() const {
    return rkr_frame_sections_mask(frame_handle_.get());
}

inline uint32_t ConFrame::index_natoms() const {
    return rkr_frame_index_natoms(frame_handle_.get());
}

inline std::string ConFrame::index_projection_json() const {
    char *s = rkr_frame_index_projection_json(frame_handle_.get());
    if (!s)
        return "{}";
    std::string result(s);
    rkr_free_string(s);
    return result;
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

inline std::vector<Bond> ConFrame::bonds() const {
    uint64_t n = rkr_frame_bond_count(frame_handle_.get());
    std::vector<Bond> out;
    out.reserve(static_cast<size_t>(n));
    for (uint64_t idx = 0; idx < n; ++idx) {
        uint32_t i = 0, j = 0;
        uint8_t has_order = 0;
        int32_t order = 0;
        RKRStatus st = rkr_frame_bond_at(frame_handle_.get(), idx, &i, &j, &has_order, &order);
        if (st != RKR_STATUS_SUCCESS)
            throw std::runtime_error(std::string("rkr_frame_bond_at: ") + rkr_status_message(st));
        Bond b;
        b.i = i;
        b.j = j;
        if (has_order)
            b.order = order;
        out.push_back(b);
    }
    return out;
}

inline bool ConFrame::has_bonds() const {
    return rkr_frame_bond_count(frame_handle_.get()) > 0;
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

inline ConFrameWriter::ConFrameWriter(const std::filesystem::path &path,
                                      Compression compression,
                                      uint8_t precision) {
    const std::string p = path.string();
    RKRConFrameWriter *raw = nullptr;
    switch (compression) {
    case Compression::None:
        raw = (precision == 6)
                  ? create_writer_from_path_c(p.c_str())
                  : create_writer_from_path_with_precision_c(p.c_str(),
                                                             precision);
        break;
    case Compression::Gzip:
        raw = (precision == 6)
                  ? create_writer_gzip_c(p.c_str())
                  : create_writer_gzip_with_precision_c(p.c_str(), precision);
        break;
    case Compression::Zstd:
#if defined(READCON_CORE_HAS_ZSTD)
        raw = (precision == 6)
                  ? create_writer_zstd_c(p.c_str())
                  : create_writer_zstd_with_precision_c(p.c_str(), precision);
        break;
#else
        throw std::runtime_error(
            "Zstd compression requires readcon-core built with the zstd "
            "feature (READCON_CORE_HAS_ZSTD undefined): " +
            p);
#endif
    }
    writer_handle_.reset(raw);
    if (!writer_handle_) {
        throw std::runtime_error("Failed to create writer for file: " + p);
    }
}

inline ConFrameWriter::Compression
ConFrameWriter::compression_from_extension(
    const std::filesystem::path &path) {
    const std::filesystem::path ext = path.extension();
    if (ext == ".gz") {
        return Compression::Gzip;
    }
    if (ext == ".zst") {
        return Compression::Zstd;
    }
    return Compression::None;
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

inline ConFrameBuilder ConFrameBuilder::clone() const {
    RKRConFrameBuilder *cloned_handle = rkr_frame_builder_clone(builder_handle_);
    if (!cloned_handle) {
        throw std::runtime_error("Failed to clone frame builder.");
    }
    // Construct a placeholder builder (with throwaway cell metadata; the
    // shared ArcArray storage from the source overrides anything the
    // placeholder ctor would have set up) and swap in the cloned handle.
    ConFrameBuilder result({0.0, 0.0, 0.0}, {90.0, 90.0, 90.0});
    free_rkr_frame_builder(result.builder_handle_);
    result.builder_handle_ = cloned_handle;
    return result;
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

inline ConFrameBuilder &ConFrameBuilder::with_energy(double energy) {
    throw_on_error(
        rkr_frame_builder_set_last_energy(builder_handle_, energy),
        "Failed to attach per-atom energy to last atom");
    return *this;
}

// --- v0.11.0 in-place mutation API impls ------------------------------------

inline size_t ConFrameBuilder::atom_count() const {
    return rkr_frame_builder_atom_count(builder_handle_);
}

inline ConFrameBuilder &
ConFrameBuilder::set_atom_position(size_t i, double x, double y, double z) {
    throw_on_error(
        rkr_frame_builder_set_atom_position(builder_handle_, i, x, y, z),
        "Failed to set atom position");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_atom_velocity(size_t i, const std::array<double, 3> &v) {
    throw_on_error(
        rkr_frame_builder_set_atom_velocity(builder_handle_, i, v.data()),
        "Failed to set atom velocity");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_atom_force(size_t i, const std::array<double, 3> &f) {
    throw_on_error(
        rkr_frame_builder_set_atom_force(builder_handle_, i, f.data()),
        "Failed to set atom force");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_atom_energy(size_t i,
                                                         double energy) {
    throw_on_error(
        rkr_frame_builder_set_atom_energy(builder_handle_, i, energy),
        "Failed to set atom energy");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_atom_fixed(size_t i, const std::array<bool, 3> &fixed) {
    throw_on_error(rkr_frame_builder_set_atom_fixed(
                       builder_handle_, i, fixed[0], fixed[1], fixed[2]),
                   "Failed to set atom fixed flags");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::set_atom_mass(size_t i, double mass) {
    throw_on_error(rkr_frame_builder_set_atom_mass(builder_handle_, i, mass),
                   "Failed to set atom mass");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_atom_id(size_t i, uint64_t atom_id) {
    throw_on_error(
        rkr_frame_builder_set_atom_id(builder_handle_, i, atom_id),
        "Failed to set atom id");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::clear_atom_velocity(size_t i) {
    throw_on_error(
        rkr_frame_builder_clear_atom_velocity(builder_handle_, i),
        "Failed to clear atom velocity");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::clear_atom_force(size_t i) {
    throw_on_error(rkr_frame_builder_clear_atom_force(builder_handle_, i),
                   "Failed to clear atom force");
    return *this;
}

inline ConFrameBuilder &ConFrameBuilder::clear_atom_energy(size_t i) {
    throw_on_error(rkr_frame_builder_clear_atom_energy(builder_handle_, i),
                   "Failed to clear atom energy");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_positions_from_flat(const std::vector<double> &positions) {
    throw_on_error(rkr_frame_builder_set_positions_from_flat(
                       builder_handle_, positions.data(), positions.size()),
                   "Failed to bulk-set positions");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_forces_from_flat(const std::vector<double> &forces) {
    throw_on_error(rkr_frame_builder_set_forces_from_flat(
                       builder_handle_, forces.data(), forces.size()),
                   "Failed to bulk-set forces");
    return *this;
}

inline ConFrameBuilder &
ConFrameBuilder::set_atom_energies_from_flat(const std::vector<double> &energies) {
    throw_on_error(rkr_frame_builder_set_atom_energies_from_flat(
                       builder_handle_, energies.data(), energies.size()),
                   "Failed to bulk-set per-atom energies");
    return *this;
}

inline std::array<double, 3>
ConFrameBuilder::get_atom_position(size_t i) const {
    std::array<double, 3> xyz{0.0, 0.0, 0.0};
    throw_on_error(rkr_frame_builder_get_atom_position(builder_handle_, i,
                                                       xyz.data()),
                   "Failed to read atom position");
    return xyz;
}

inline std::optional<std::array<double, 3>>
ConFrameBuilder::get_atom_velocity(size_t i) const {
    std::array<double, 3> xyz{0.0, 0.0, 0.0};
    bool has_value = false;
    throw_on_error(rkr_frame_builder_get_atom_velocity(builder_handle_, i,
                                                       xyz.data(), &has_value),
                   "Failed to read atom velocity");
    if (has_value) {
        return xyz;
    }
    return std::nullopt;
}

inline std::optional<std::array<double, 3>>
ConFrameBuilder::get_atom_force(size_t i) const {
    std::array<double, 3> xyz{0.0, 0.0, 0.0};
    bool has_value = false;
    throw_on_error(
        rkr_frame_builder_get_atom_force(builder_handle_, i, xyz.data(),
                                         &has_value),
        "Failed to read atom force");
    if (has_value) {
        return xyz;
    }
    return std::nullopt;
}

inline std::optional<double>
ConFrameBuilder::get_atom_energy(size_t i) const {
    double value = 0.0;
    bool has_value = false;
    throw_on_error(
        rkr_frame_builder_get_atom_energy(builder_handle_, i, &value, &has_value),
        "Failed to read atom energy");
    if (has_value) {
        return value;
    }
    return std::nullopt;
}

inline double ConFrameBuilder::get_atom_mass(size_t i) const {
    double m = 0.0;
    throw_on_error(rkr_frame_builder_get_atom_mass(builder_handle_, i, &m),
                   "Failed to read atom mass");
    return m;
}

inline double *ConFrameBuilder::positions_data() noexcept {
    return rkr_frame_builder_positions_data(builder_handle_);
}
inline double *ConFrameBuilder::velocities_data() noexcept {
    return rkr_frame_builder_velocities_data(builder_handle_);
}
inline double *ConFrameBuilder::forces_data() noexcept {
    return rkr_frame_builder_forces_data(builder_handle_);
}
inline double *ConFrameBuilder::atom_energies_data() noexcept {
    return rkr_frame_builder_atom_energies_data(builder_handle_);
}
inline double *ConFrameBuilder::masses_data() noexcept {
    return rkr_frame_builder_masses_data(builder_handle_);
}
inline const uint64_t *ConFrameBuilder::atom_ids_data() const noexcept {
    return rkr_frame_builder_atom_ids_data(builder_handle_);
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
