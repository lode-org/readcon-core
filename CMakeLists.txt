cmake_minimum_required(VERSION 3.22)
project(readcon-core VERSION 0.2.0 LANGUAGES C CXX)

# Corrosion builds the Rust crate from Cargo.toml
include(FetchContent)
FetchContent_Declare(
    Corrosion
    GIT_REPOSITORY https://github.com/corrosion-rs/corrosion.git
    GIT_TAG v0.5
)
FetchContent_MakeAvailable(Corrosion)

corrosion_import_crate(MANIFEST_PATH ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml
                       CRATES readcon-core)
corrosion_set_env_vars(readcon-core "CARGO_CFG_TARGET_OS=$<LOWER_CASE:${CMAKE_SYSTEM_NAME}>")

# Generate the C header via cbindgen
find_program(CBINDGEN cbindgen REQUIRED)
set(READCON_HEADER ${CMAKE_CURRENT_SOURCE_DIR}/include/readcon-core.h)
add_custom_command(
    OUTPUT ${READCON_HEADER}
    COMMAND ${CBINDGEN}
        -q
        --config ${CMAKE_CURRENT_SOURCE_DIR}/cbindgen.toml
        --crate readcon
        --output ${READCON_HEADER}
        -- ${CMAKE_CURRENT_SOURCE_DIR}/src/lib.rs
    DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/cbindgen.toml
            ${CMAKE_CURRENT_SOURCE_DIR}/src/lib.rs
    COMMENT "Generating readcon-core.h via cbindgen"
)
add_custom_target(readcon-core-header DEPENDS ${READCON_HEADER})
add_dependencies(readcon-core readcon-core-header)

# Exported target for consumers: readcon-core::readcon-core
add_library(readcon-core::readcon-core ALIAS readcon-core)

target_include_directories(readcon-core INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

# Install header alongside the library
install(FILES ${READCON_HEADER} DESTINATION include)
