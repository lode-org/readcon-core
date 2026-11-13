// Walk a chemfiles frame without the C API shared_allocator.
// chfl_atom_from_frame locks a process-wide map once per atom. The scan
// below reads the atoms already stored on the frame.

#include "chemfiles/Frame.hpp"

namespace {

constexpr uint64_t kNameCap = 16;

bool copy_fit(const std::string& src, char* dst) {
    if (src.size() >= kNameCap) {
        return false;
    }
    src.copy(dst, src.size());
    dst[src.size()] = '\0';
    return true;
}

}  // namespace

extern "C" int rc_chemfiles_scan(
    chemfiles::Frame* frame,
    uint32_t* sym_of,
    char names[][kNameCap],
    double* masses,
    uint32_t max_kinds,
    uint32_t* n_kinds,
    uint32_t* any_extra,
    uint32_t* any_props
) {
    if (frame == nullptr || sym_of == nullptr || names == nullptr || masses == nullptr
        || n_kinds == nullptr || any_extra == nullptr || any_props == nullptr) {
        return 1;
    }
    *n_kinds = 0;
    *any_extra = 0;
    *any_props = 0;
    uint32_t kinds = 0;
    uint32_t index = 0;
    for (const chemfiles::Atom& atom : *frame) {
        const std::string& name = atom.name();
        const std::string& type_name = atom.type();
        const std::string& symbol = !type_name.empty() ? type_name : (!name.empty() ? name : "X");
        if (name != symbol || (!type_name.empty() && type_name != symbol)) {
            *any_extra = 1;
        }
        if (atom.charge() != 0.0 || atom.properties().size() != 0) {
            *any_props = 1;
        }
        uint32_t kind = kinds;
        for (uint32_t seen = 0; seen < kinds; ++seen) {
            if (symbol == names[seen]) {
                kind = seen;
                break;
            }
        }
        if (kind == kinds) {
            if (kinds >= max_kinds || !copy_fit(symbol, names[kinds])) {
                return 3;
            }
            masses[kinds] = 1.0;
            kinds += 1;
        }
        const bool canonical = name == type_name;
        const double mass = atom.mass();
        if (mass > 0.0 && (masses[kind] == 1.0 || canonical)) {
            masses[kind] = mass;
        }
        sym_of[index] = kind;
        index += 1;
    }
    *n_kinds = kinds;
    return 0;
}

// True when every atom in [begin, end) is `symbol`, with that mass, and no
// charge or property. Readers call it on disjoint ranges.
extern "C" int rc_chemfiles_matches(
    chemfiles::Frame* frame,
    uint64_t begin,
    uint64_t end,
    const char* symbol,
    double mass,
    uint32_t* bad
) {
    if (frame == nullptr || symbol == nullptr || bad == nullptr || begin > end
        || end > frame->size()) {
        return 1;
    }
    static const std::string kMissing = "X";
    for (uint64_t index = begin; index < end; ++index) {
        const chemfiles::Atom& atom = (*frame)[static_cast<size_t>(index)];
        const std::string& name = atom.name();
        const std::string& type_name = atom.type();
        const std::string& sym =
            !type_name.empty() ? type_name : (!name.empty() ? name : kMissing);
        const double found = atom.mass();
        if (sym != symbol || name != sym || atom.charge() != 0.0
            || atom.properties().size() != 0 || (found > 0.0 && found != mass)) {
            *bad = 1;
            return 0;
        }
    }
    *bad = 0;
    return 0;
}

extern "C" int rc_chemfiles_atom_view(
    chemfiles::Frame* frame,
    uint64_t index,
    char* name,
    uint64_t name_cap,
    char* type_name,
    uint64_t type_cap,
    double* mass,
    double* charge,
    uint64_t* nprops
) {
    if (frame == nullptr || name == nullptr || type_name == nullptr || mass == nullptr
        || charge == nullptr || nprops == nullptr || name_cap == 0 || type_cap == 0
        || index >= frame->size()) {
        return 1;
    }
    const chemfiles::Atom& atom = (*frame)[static_cast<size_t>(index)];
    auto copy = [](const std::string& src, char* dst, uint64_t cap) {
        auto n = src.size();
        if (n >= cap) {
            n = static_cast<size_t>(cap - 1);
        }
        if (n > 0) {
            src.copy(dst, n);
        }
        dst[n] = '\0';
    };
    copy(atom.name(), name, name_cap);
    copy(atom.type(), type_name, type_cap);
    *mass = atom.mass();
    *charge = atom.charge();
    *nprops = atom.properties().size();
    return 0;
}
