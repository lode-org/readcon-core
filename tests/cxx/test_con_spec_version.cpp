// A CON 3.1 file reports con_spec_version, and two writes match.

#include "readcon-core.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>

namespace fs = std::filesystem;

static const char TEXT[] =
    "CON 3.1\n"
    "{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":"
    "\"eV\",\"mass\":\"amu\"}}\n"
    "10.000000 10.000000 10.000000\n"
    "90.000000 90.000000 90.000000\n"
    "\n"
    "\n"
    "1\n"
    "1\n"
    "1.007940\n"
    "H\n"
    "Coordinates of Component 1\n"
    "0.000000 0.000000 0.000000 0 0\n";

static std::string read_file(const fs::path &path) {
    std::ifstream in(path, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

static int fail(const std::string &message) {
    std::cerr << message << "\n";
    return 1;
}

int main() {
    const fs::path dir = fs::temp_directory_path();
    const fs::path src = dir / "readcon-cxx-spec-src.con";
    const fs::path first = dir / "readcon-cxx-spec-a.con";
    const fs::path second = dir / "readcon-cxx-spec-b.con";
    {
        std::ofstream out(src, std::ios::binary);
        out << TEXT;
    }

    auto frames = readcon::read_all_frames(src);
    if (frames.size() != 1) {
        return fail("expected one frame");
    }
    if (frames[0].spec_version() != 3) {
        return fail("spec_version is not 3");
    }
    const std::string json = frames[0].metadata_json();
    if (json.find("\"con_spec_version\":3") == std::string::npos) {
        return fail("metadata json missing con_spec_version 3: " + json);
    }

    {
        readcon::ConFrameWriter writer(first);
        writer.extend(frames);
    }
    auto again = readcon::read_all_frames(first);
    if (again.size() != 1 || again[0].spec_version() != 3) {
        return fail("re-read lost the frame");
    }
    if (again[0].metadata_json().find("\"con_spec_version\":3") == std::string::npos) {
        return fail("re-read metadata json missing con_spec_version 3");
    }
    {
        readcon::ConFrameWriter writer(second);
        writer.extend(again);
    }
    if (read_file(first) != read_file(second)) {
        return fail("write then read then write changed the bytes");
    }
    fs::remove(src);
    fs::remove(first);
    fs::remove(second);
    std::cout << "cxx con_spec_version: OK\n";
    return 0;
}
