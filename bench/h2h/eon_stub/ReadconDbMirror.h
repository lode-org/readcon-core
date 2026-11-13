#pragma once
// Benchmark stand-in for eOn's optional readcon-db mirror.
// The real mirror re-reads the file it just parsed or wrote and does not
// change the Matter fields or the bytes of a .con / .convel. Timing it
// would charge eOn for a second copy of the file that ASE and readcon do
// not make. The functions are empty on purpose.

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace eonc::io {

inline std::uint64_t corpus_path_id(std::string_view) { return 1; }

inline void mirror_con_corpus(const std::string &) {}

inline void note_corpus_append(const std::string &, const std::string &) {}

inline void flush_corpus_appends() {}

inline std::size_t corpus_buffered_frames(const std::string &) { return 0; }

}  // namespace eonc::io
