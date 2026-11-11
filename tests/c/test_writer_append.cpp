// Append, flush, and in-memory serialization through the C++ wrapper.
// Usage: test_writer_append <scratch dir>
#include "readcon-core.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

static readcon::ConFrame make_frame(uint64_t id, double x) {
    readcon::ConFrameBuilder builder({4.0, 4.0, 4.0}, {90.0, 90.0, 90.0});
    builder.add_atom("Cu", x, 0.1, 0.2, false, id, 63.546);
    return builder.build();
}

static std::string slurp(const std::filesystem::path &path) {
    std::ifstream in(path, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(in),
                       std::istreambuf_iterator<char>());
}

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "usage: test_writer_append <scratch>\n";
        return 2;
    }
    const std::filesystem::path dir(argv[1]);
    std::filesystem::create_directories(dir);

    std::vector<readcon::ConFrame> frames;
    frames.push_back(make_frame(0, 0.0));
    frames.push_back(make_frame(1, 1.0));
    const std::string bytes = readcon::write_frames_to_string(frames);

    const auto whole = dir / "whole.con";
    {
        readcon::ConFrameWriter writer(whole);
        writer.extend(frames);
        writer.flush();
        if (readcon::read_all_frames(whole).size() != frames.size()) {
            std::cerr << "flush did not leave a parseable file\n";
            return 1;
        }
    }
    if (slurp(whole) != bytes) {
        std::cerr << "string does not match the whole-file write\n";
        return 1;
    }

    const auto part = dir / "part.con";
    {
        readcon::ConFrameWriter writer(part);
        std::vector<readcon::ConFrame> head;
        head.push_back(make_frame(0, 0.0));
        writer.extend(head);
    }
    {
        readcon::ConFrameWriter writer(
            part, readcon::ConFrameWriter::OpenMode::Append);
        std::vector<readcon::ConFrame> rest;
        rest.push_back(make_frame(1, 1.0));
        writer.extend(rest);
        writer.flush();
    }
    if (slurp(part) != bytes) {
        std::cerr << "append does not match the whole-file write\n";
        return 1;
    }

    bool refused = false;
    try {
        readcon::ConFrameWriter compressed(
            dir / "x.con.gz", readcon::ConFrameWriter::OpenMode::Append);
        (void)compressed;
    } catch (const std::runtime_error &) {
        refused = true;
    }
    if (!refused) {
        std::cerr << "gzip append was accepted\n";
        return 1;
    }
    return 0;
}
