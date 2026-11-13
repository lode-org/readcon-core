// The C and C++ calls from the how-to and the atom-correspondence page.
// Usage: test_doc_examples <scratch dir>
#include "readcon-core.hpp"

#include <cstdint>
using namespace readcon;
#include <filesystem>
#include <iostream>
#include <vector>

static readcon::ConFrame two_atoms(const char *first, uint64_t first_id, double first_x,
                                   const char *second, uint64_t second_id, double second_x) {
    readcon::ConFrameBuilder builder({10.0, 10.0, 10.0}, {90.0, 90.0, 90.0});
    builder.add_atom(first, first_x, 0.0, 0.0, {false, false, false}, first_id, 12.0);
    builder.add_atom(second, second_x, 0.0, 0.0, {false, false, false}, second_id, 12.0);
    return builder.build();
}

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "usage: test_doc_examples <scratch>\n";
        return 2;
    }
    const std::filesystem::path dir(argv[1]);
    std::filesystem::create_directories(dir);

    readcon::ConFrame reactant = two_atoms("C", 1, 0.0, "O", 2, 1.0);
    readcon::ConFrame product = two_atoms("O", 2, 1.2, "C", 1, 0.1);

    const RKRConFrame *frame_a = reactant.get_handle();
    const RKRConFrame *frame_b = product.get_handle();
    const uintptr_t n = reactant.atoms().size();
    std::vector<uint64_t> perm(n);
    if (rkr_frame_atom_id_permutation(frame_a, frame_b, 1, perm.data(), n) !=
        RKR_STATUS_SUCCESS) {
        std::cerr << "permutation failed: " << rkr_last_error_message() << "\n";
        return 1;
    }
    if (perm[0] != 1 || perm[1] != 0) {
        std::cerr << "permutation is not the reactant order\n";
        return 1;
    }

    RKRConFrame *ordered = rkr_frame_reorder_like(frame_a, frame_b, 1);
    if (ordered == nullptr) {
        std::cerr << "reorder_like failed: " << rkr_last_error_message() << "\n";
        return 1;
    }
    free_rkr_frame(ordered);

    const RKRConFrame *band[] = {frame_a, frame_b};
    uint64_t frame_index = 0;
    uint64_t atom_id = 0;
    if (rkr_frames_check_atom_ids(band, 2, 1, &frame_index, &atom_id) !=
        RKR_STATUS_SUCCESS) {
        std::cerr << "band check failed: " << rkr_last_error_message() << "\n";
        return 1;
    }
    if (frame_index != UINT64_MAX || atom_id != UINT64_MAX) {
        std::cerr << "a consistent band did not report UINT64_MAX\n";
        return 1;
    }

    std::vector<double> disp(3 * n);
    if (rkr_frame_minimum_image_displacements(frame_a, frame_b, 1, disp.data(),
                                              disp.size()) != RKR_STATUS_SUCCESS) {
        std::cerr << "displacements failed: " << rkr_last_error_message() << "\n";
        return 1;
    }
    if (disp[0] < 0.05 || disp[0] > 0.15) {
        std::cerr << "carbon minimum-image step is " << disp[0] << "\n";
        return 1;
    }

    const std::vector<size_t> cpp_perm = reactant.atom_id_permutation(product, true);
    if (cpp_perm.size() != 2 || cpp_perm[0] != 1 || cpp_perm[1] != 0) {
        std::cerr << "C++ permutation disagrees\n";
        return 1;
    }
    readcon::ConFrame cpp_ordered = reactant.reorder_like(product, true);
    if (cpp_ordered.atoms().at(0).atom_id != 1 || cpp_ordered.atoms().at(1).atom_id != 2) {
        std::cerr << "C++ reorder_like did not restore reactant order\n";
        return 1;
    }
    readcon::check_atom_id_consistency({&reactant, &product}, true);
    const auto cpp_disp = reactant.minimum_image_displacements(product, true);
    if (cpp_disp.size() != 2) {
        std::cerr << "C++ displacements have the wrong length\n";
        return 1;
    }

    const auto path = dir / "run.con";
    {
        std::vector<readcon::ConFrame> head;
        head.push_back(std::move(reactant));
        readcon::ConFrameWriter writer(path);
        writer.extend(head);
        writer.flush();
    }
    {
        std::vector<readcon::ConFrame> rest;
        rest.push_back(std::move(product));
        readcon::ConFrameWriter writer(path, readcon::ConFrameWriter::OpenMode::Append);
        writer.extend(rest);
        writer.flush();
    }
    const auto sequential = readcon::read_all_frames(path, 1);
    const auto pool = readcon::read_all_frames(path, 2);
    if (sequential.size() != 2 || pool.size() != 2) {
        std::cerr << "parallel and serial reads disagree on the frame count\n";
        return 1;
    }

    uintptr_t count = 0;
    RKRConFrame **handles =
        rkr_read_all_frames_n_threads(path.string().c_str(), &count, 2);
    if (handles == nullptr || count != 2) {
        std::cerr << "rkr_read_all_frames_n_threads did not return two frames\n";
        return 1;
    }
    free_rkr_frame_array(handles, count);
    return 0;
}
