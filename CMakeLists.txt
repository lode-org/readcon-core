# CMake integration for the readcon-core C/C++ ABI.
#
# Headers in include/ are shipped pre-generated. cbindgen is a maintainer
# tool (scripts/regen-capi-headers.sh) and is never required here.
# Rustc/cargo compile the library; CMake only orchestrates cargo rustc,
# installs headers/libs, and writes cmake-config + pkg-config files.
#
# Consumption:
#   add_subdirectory / FetchContent_MakeAvailable  ->  readcon-core::{shared,static}
#   find_package(readcon-core) after cmake --install
#   pkg-config --libs readcon-core
cmake_minimum_required(VERSION 3.22)

if (${CMAKE_CURRENT_SOURCE_DIR} STREQUAL ${CMAKE_SOURCE_DIR})
    set(READCON_CORE_MAIN_PROJECT ON)
else()
    set(READCON_CORE_MAIN_PROJECT OFF)
endif()

if(${READCON_CORE_MAIN_PROJECT} AND NOT "${CACHED_LAST_CMAKE_VERSION}" VERSION_EQUAL ${CMAKE_VERSION})
    set(CACHED_LAST_CMAKE_VERSION ${CMAKE_VERSION} CACHE INTERNAL "Last version of cmake used to configure")
    message(STATUS "Running CMake version ${CMAKE_VERSION}")
endif()

if (POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()
if (POLICY CMP0077)
    cmake_policy(SET CMP0077 NEW)
endif()

file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml" CARGO_TOML_CONTENT)
set(READCON_CORE_VERSION "")
foreach(line ${CARGO_TOML_CONTENT})
    if (line MATCHES "^version = \"([0-9]+\\.[0-9]+\\.[0-9]+.*)\"")
        set(READCON_CORE_VERSION "${CMAKE_MATCH_1}")
        break()
    endif()
endforeach()
if (READCON_CORE_VERSION STREQUAL "")
    message(FATAL_ERROR "could not parse version from ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml")
endif()

string(REGEX REPLACE "([0-9]*)\\.([0-9]*)\\.([0-9]*).*" "\\1.\\2.\\3" READCON_CORE_CMAKE_VERSION ${READCON_CORE_VERSION})
project(readcon-core
    VERSION ${READCON_CORE_CMAKE_VERSION}
    LANGUAGES C
)
set(PROJECT_VERSION ${READCON_CORE_VERSION})

if(${READCON_CORE_MAIN_PROJECT})
    message(STATUS "Building readcon-core v${READCON_CORE_VERSION}")
endif()

option(BUILD_SHARED_LIBS "Use a shared library by default instead of a static one" ON)
option(READCON_CORE_INSTALL_BOTH_STATIC_SHARED "Install both shared and static libraries" ON)
set(READCON_CORE_CARGO_FEATURES "" CACHE STRING "Comma-free cargo features to enable (space-separated)")

set(BIN_INSTALL_DIR "bin" CACHE PATH "Path relative to CMAKE_INSTALL_PREFIX where to install binaries/DLL")
set(LIB_INSTALL_DIR "lib" CACHE PATH "Path relative to CMAKE_INSTALL_PREFIX where to install libraries")
set(INCLUDE_INSTALL_DIR "include" CACHE PATH "Path relative to CMAKE_INSTALL_PREFIX where to install headers")

set(RUST_BUILD_TARGET "" CACHE STRING "Cross-compilation target for rust code. Leave empty to build for the host")
set(EXTRA_RUST_FLAGS "" CACHE STRING "Flags used to build rust code")
mark_as_advanced(RUST_BUILD_TARGET EXTRA_RUST_FLAGS)

set(CMAKE_MACOSX_RPATH ON)
set(CMAKE_INSTALL_RPATH "${CMAKE_INSTALL_PREFIX}/${LIB_INSTALL_DIR}")

if (${READCON_CORE_MAIN_PROJECT})
    if("${CMAKE_BUILD_TYPE}" STREQUAL "" AND "${CMAKE_CONFIGURATION_TYPES}" STREQUAL "")
        message(STATUS "Setting build type to 'release' as none was specified.")
        set(CMAKE_BUILD_TYPE "release"
            CACHE STRING
            "Choose the type of build, options are: debug or release"
            FORCE)
        set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS release debug)
    endif()
endif()

if("${CMAKE_BUILD_TYPE}" STREQUAL "")
    set(CMAKE_BUILD_TYPE "release")
endif()

if(${READCON_CORE_MAIN_PROJECT} AND NOT "${CACHED_LAST_CMAKE_BUILD_TYPE}" STREQUAL ${CMAKE_BUILD_TYPE})
    set(CACHED_LAST_CMAKE_BUILD_TYPE ${CMAKE_BUILD_TYPE} CACHE INTERNAL "Last build type used in configuration")
    message(STATUS "Building readcon-core in ${CMAKE_BUILD_TYPE} mode")
endif()

set(READCON_CORE_C_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/include/readcon-core.h")
set(READCON_CORE_CXX_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/include/readcon-core.hpp")
set(READCON_CORE_MTS_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/include/readcon-metatensor.h")
if (NOT EXISTS ${READCON_CORE_C_HEADER})
    message(FATAL_ERROR
        "missing shipped C header ${READCON_CORE_C_HEADER}. "
        "Maintainers regenerate it with scripts/regen-capi-headers.sh; "
        "consumers must not run cbindgen.")
endif()

find_program(CARGO_EXE "cargo" DOC "path to cargo (Rust build system)")
if (NOT CARGO_EXE)
    message(FATAL_ERROR
        "could not find cargo, please make sure the Rust compiler is installed \
        (see https://www.rust-lang.org/tools/install) or set CARGO_EXE")
endif()

execute_process(
    COMMAND ${CARGO_EXE} "--version" "--verbose"
    RESULT_VARIABLE CARGO_STATUS
    OUTPUT_VARIABLE CARGO_VERSION_RAW
)
if(CARGO_STATUS AND NOT CARGO_STATUS EQUAL 0)
    message(FATAL_ERROR "could not run cargo; install the Rust toolchain")
endif()

if (CARGO_VERSION_RAW MATCHES "cargo ([0-9]+\\.[0-9]+\\.[0-9]+).*")
    set(CARGO_VERSION "${CMAKE_MATCH_1}")
else()
    message(FATAL_ERROR "failed to determine cargo version, output was: ${CARGO_VERSION_RAW}")
endif()
if(NOT "${CACHED_LAST_CARGO_VERSION}" STREQUAL ${CARGO_VERSION})
    set(CACHED_LAST_CARGO_VERSION ${CARGO_VERSION} CACHE INTERNAL "Last version of cargo used in configuration")
    if(${READCON_CORE_MAIN_PROJECT})
        message(STATUS "Using cargo version ${CARGO_VERSION} at ${CARGO_EXE}")
    endif()
    set(CARGO_VERSION_CHANGED TRUE)
endif()

set(CARGO_BUILD_ARG "")
if (EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.lock)
    set(CARGO_BUILD_ARG "${CARGO_BUILD_ARG};--locked")
endif()
if (EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/vendor)
    set(CARGO_BUILD_ARG "${CARGO_BUILD_ARG};--offline")
endif()

string(TOLOWER ${CMAKE_BUILD_TYPE} BUILD_TYPE)
if ("${BUILD_TYPE}" STREQUAL "debug")
    set(CARGO_BUILD_TYPE "debug")
elseif("${BUILD_TYPE}" STREQUAL "release" OR "${BUILD_TYPE}" STREQUAL "relwithdebinfo" OR "${BUILD_TYPE}" STREQUAL "minsizerel")
    set(CARGO_BUILD_ARG "${CARGO_BUILD_ARG};--release")
    set(CARGO_BUILD_TYPE "release")
else()
    message(FATAL_ERROR "unsupported build type: ${CMAKE_BUILD_TYPE}")
endif()

set(CARGO_TARGET_DIR ${CMAKE_CURRENT_BINARY_DIR}/cargo-target)
set(CARGO_BUILD_ARG "${CARGO_BUILD_ARG};--target-dir=${CARGO_TARGET_DIR}")
if (NOT "${READCON_CORE_CARGO_FEATURES}" STREQUAL "")
    string(REPLACE " " "," _feats "${READCON_CORE_CARGO_FEATURES}")
    set(CARGO_BUILD_ARG "${CARGO_BUILD_ARG};--features=${_feats}")
endif()

if ("${RUST_BUILD_TARGET}" STREQUAL "")
    if (CARGO_VERSION_RAW MATCHES "host: ([a-zA-Z0-9_\\-]*)\n")
        set(RUST_HOST_TARGET "${CMAKE_MATCH_1}")
    else()
        message(FATAL_ERROR "failed to determine host target, output was: ${CARGO_VERSION_RAW}")
    endif()
    set(CARGO_OUTPUT_DIR "${CARGO_TARGET_DIR}/${CARGO_BUILD_TYPE}")
    set(RUST_BUILD_TARGET ${RUST_HOST_TARGET})
else()
    if (${READCON_CORE_MAIN_PROJECT})
        message(STATUS "Cross-compiling to ${RUST_BUILD_TARGET}")
    endif()
    set(CARGO_BUILD_ARG "${CARGO_BUILD_ARG};--target=${RUST_BUILD_TARGET}")
    set(CARGO_OUTPUT_DIR "${CARGO_TARGET_DIR}/${RUST_BUILD_TARGET}/${CARGO_BUILD_TYPE}")
endif()

# rustc native-static-libs for consumers of the static archive
if (CARGO_VERSION_CHANGED OR NOT DEFINED CARGO_DEFAULT_LIBRARIES)
    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/tempdir.cmake)
    get_tempdir(TMPDIR)

    execute_process(
        COMMAND "${CARGO_EXE}" new --lib _cargo_required_libs
        WORKING_DIRECTORY "${TMPDIR}"
        RESULT_VARIABLE cargo_new_result
        OUTPUT_VARIABLE cargo_new_stdout
        ERROR_VARIABLE cargo_new_stderr
    )
    if (cargo_new_result)
        message(FATAL_ERROR
            "could not create empty project to find cargo's default static libs (error ${cargo_new_result})\n"
            "stdout:\n${cargo_new_stdout}\nstderr:\n${cargo_new_stderr}")
    endif()
    file(APPEND "${TMPDIR}/_cargo_required_libs/Cargo.toml" "[lib]\ncrate-type=[\"staticlib\"]\n")

    execute_process(
        COMMAND ${CARGO_EXE} rustc --color never --target=${RUST_BUILD_TARGET} -- --print=native-static-libs
        WORKING_DIRECTORY "${TMPDIR}/_cargo_required_libs"
        RESULT_VARIABLE cargo_rustc_result
        OUTPUT_VARIABLE cargo_rustc_stdout
        ERROR_VARIABLE  cargo_rustc_stderr
    )
    file(REMOVE_RECURSE "${TMPDIR}")
    if(cargo_rustc_result)
        message(FATAL_ERROR
            "could not extract cargo's default static libs (error ${cargo_rustc_result})\n"
            "stdout:\n${cargo_rustc_stdout}\nstderr:\n${cargo_rustc_stderr}")
    endif()

    if(cargo_rustc_stderr MATCHES "native-static-libs: ([^\r\n]+)\r?\n")
        string(REPLACE " " ";" "libs_list" "${CMAKE_MATCH_1}")
        set(stripped_lib_list "")
        foreach(lib ${libs_list})
            string(REGEX REPLACE "^-l" "" "stripped_lib" "${lib}")
            string(REGEX REPLACE "\\.lib$" "" "stripped_lib" "${stripped_lib}")
            list(APPEND stripped_lib_list "${stripped_lib}")
        endforeach()
        list(TRANSFORM stripped_lib_list REPLACE "^msvcrt$" "\$<\$<CONFIG:Debug>:msvcrtd>")
        list(REMOVE_DUPLICATES stripped_lib_list)
        set(CARGO_DEFAULT_LIBRARIES "${stripped_lib_list}" CACHE INTERNAL "list of implicitly linked libraries")
        if (${READCON_CORE_MAIN_PROJECT})
            message(STATUS "Cargo default link libraries are: ${CARGO_DEFAULT_LIBRARIES}")
        endif()
    else()
        message(FATAL_ERROR "could not find cargo's default static libs in: `${cargo_rustc_stderr}`")
    endif()
endif()

file(GLOB_RECURSE ALL_RUST_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml
    ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.lock
    ${CMAKE_CURRENT_SOURCE_DIR}/build.rs
    ${CMAKE_CURRENT_SOURCE_DIR}/src/*.rs
)

add_library(readcon-core::shared SHARED IMPORTED GLOBAL)
set(READCON_CORE_SHARED_LOCATION "${CARGO_OUTPUT_DIR}/${CMAKE_SHARED_LIBRARY_PREFIX}readcon_core${CMAKE_SHARED_LIBRARY_SUFFIX}")
set(READCON_CORE_IMPLIB_LOCATION "${READCON_CORE_SHARED_LOCATION}.lib")

add_library(readcon-core::static STATIC IMPORTED GLOBAL)
set(READCON_CORE_STATIC_LOCATION "${CARGO_OUTPUT_DIR}/${CMAKE_STATIC_LIBRARY_PREFIX}readcon_core${CMAKE_STATIC_LIBRARY_SUFFIX}")

get_filename_component(READCON_CORE_SHARED_LIB_NAME ${READCON_CORE_SHARED_LOCATION} NAME)
get_filename_component(READCON_CORE_IMPLIB_NAME     ${READCON_CORE_IMPLIB_LOCATION} NAME)
get_filename_component(READCON_CORE_STATIC_LIB_NAME ${READCON_CORE_STATIC_LOCATION} NAME)

if (UNIX)
    if (APPLE)
        set(CARGO_RUSTC_ARGS "-Clink-arg=-Wl,-install_name,@rpath/${READCON_CORE_SHARED_LIB_NAME}")
    else()
        set(CARGO_RUSTC_ARGS "-Clink-arg=-Wl,-soname,${READCON_CORE_SHARED_LIB_NAME}")
    endif()
else()
    set(CARGO_RUSTC_ARGS "")
endif()
if (NOT "${EXTRA_RUST_FLAGS}" STREQUAL "")
    set(CARGO_RUSTC_ARGS "${CARGO_RUSTC_ARGS};${EXTRA_RUST_FLAGS}")
endif()

set(CARGO_ENV "")
if (NOT "${CMAKE_OSX_DEPLOYMENT_TARGET}" STREQUAL "")
    list(APPEND CARGO_ENV "MACOSX_DEPLOYMENT_TARGET=${CMAKE_OSX_DEPLOYMENT_TARGET}")
endif()
if (NOT "$ENV{RUSTC_WRAPPER}" STREQUAL "")
    list(APPEND CARGO_ENV "RUSTC_WRAPPER=$ENV{RUSTC_WRAPPER}")
endif()

if (READCON_CORE_INSTALL_BOTH_STATIC_SHARED)
    set(CARGO_RUSTC_CRATE_TYPES "--crate-type=cdylib;--crate-type=staticlib")
    set(CARGO_OUTPUTS ${READCON_CORE_SHARED_LOCATION} ${READCON_CORE_STATIC_LOCATION})
    if (WIN32)
        list(APPEND CARGO_OUTPUTS ${READCON_CORE_IMPLIB_LOCATION})
    endif()
else()
    if (BUILD_SHARED_LIBS)
        set(CARGO_RUSTC_CRATE_TYPES "--crate-type=cdylib")
        set(CARGO_OUTPUTS ${READCON_CORE_SHARED_LOCATION})
        if (WIN32)
            list(APPEND CARGO_OUTPUTS ${READCON_CORE_IMPLIB_LOCATION})
        endif()
    else()
        set(CARGO_RUSTC_CRATE_TYPES "--crate-type=staticlib")
        set(CARGO_OUTPUTS ${READCON_CORE_STATIC_LOCATION})
    endif()
endif()

add_custom_command(
    OUTPUT ${CARGO_OUTPUTS}
    COMMAND ${CMAKE_COMMAND} -E env ${CARGO_ENV}
            ${CARGO_EXE} rustc --lib ${CARGO_BUILD_ARG} --manifest-path ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml -- ${CARGO_RUSTC_CRATE_TYPES} ${CARGO_RUSTC_ARGS}
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    DEPENDS ${ALL_RUST_SOURCES}
    COMMENT "Building readcon-core C ABI with cargo"
    VERBATIM
)
add_custom_target(cargo-build-readcon-core ALL DEPENDS ${CARGO_OUTPUTS})
add_dependencies(readcon-core::shared cargo-build-readcon-core)
add_dependencies(readcon-core::static cargo-build-readcon-core)

set(READCON_CORE_HEADERS
    ${READCON_CORE_C_HEADER}
    ${READCON_CORE_CXX_HEADER}
    ${READCON_CORE_MTS_HEADER}
)
set(READCON_CORE_INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include/)

set_target_properties(readcon-core::shared PROPERTIES
    IMPORTED_LOCATION ${READCON_CORE_SHARED_LOCATION}
    INTERFACE_INCLUDE_DIRECTORIES ${READCON_CORE_INCLUDE_DIR}
    BUILD_VERSION "${READCON_CORE_VERSION}"
)
if (WIN32)
    set_target_properties(readcon-core::shared PROPERTIES
        IMPORTED_IMPLIB ${READCON_CORE_IMPLIB_LOCATION}
    )
endif()
set_target_properties(readcon-core::static PROPERTIES
    IMPORTED_LOCATION ${READCON_CORE_STATIC_LOCATION}
    INTERFACE_INCLUDE_DIRECTORIES ${READCON_CORE_INCLUDE_DIR}
    INTERFACE_LINK_LIBRARIES "${CARGO_DEFAULT_LIBRARIES}"
    BUILD_VERSION "${READCON_CORE_VERSION}"
)

if (BUILD_SHARED_LIBS)
    add_library(readcon-core ALIAS readcon-core::shared)
    add_library(readcon-core::readcon-core ALIAS readcon-core::shared)
else()
    add_library(readcon-core ALIAS readcon-core::static)
    add_library(readcon-core::readcon-core ALIAS readcon-core::static)
endif()

string(REPLACE "," ";" _readcon_feat_list "${READCON_CORE_CARGO_FEATURES}")
string(REPLACE " " ";" _readcon_feat_list "${_readcon_feat_list}")
foreach(_feat ${_readcon_feat_list})
    if (_feat STREQUAL "zstd")
        target_compile_definitions(readcon-core::shared INTERFACE READCON_CORE_HAS_ZSTD)
        target_compile_definitions(readcon-core::static INTERFACE READCON_CORE_HAS_ZSTD)
    elseif (_feat STREQUAL "metatensor")
        target_compile_definitions(readcon-core::shared INTERFACE READCON_CORE_HAS_METATENSOR)
        target_compile_definitions(readcon-core::static INTERFACE READCON_CORE_HAS_METATENSOR)
    endif()
endforeach()

#------------------------------------------------------------------------------#
# Installation: headers, libs, cmake package, pkg-config
#------------------------------------------------------------------------------#

include(CMakePackageConfigHelpers)
# Config file lives in lib/cmake/readcon-core; prefix is two dirs up.
set(PACKAGE_RELATIVE_PATH "../..")
configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/readcon-core-config.in.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/readcon-core-config.cmake"
    INSTALL_DESTINATION ${LIB_INSTALL_DIR}/cmake/readcon-core
)
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/readcon-core-config-version.in.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/readcon-core-config-version.cmake"
    @ONLY
)

set(PC_LIBS_PRIVATE "")
foreach(_lib ${CARGO_DEFAULT_LIBRARIES})
    if (NOT _lib MATCHES "^\\$")
        string(APPEND PC_LIBS_PRIVATE "-l${_lib} ")
    endif()
endforeach()
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/readcon-core.pc.in"
    "${CMAKE_CURRENT_BINARY_DIR}/readcon-core.pc"
    @ONLY
)

install(FILES ${READCON_CORE_HEADERS} DESTINATION ${INCLUDE_INSTALL_DIR})

if (READCON_CORE_INSTALL_BOTH_STATIC_SHARED OR BUILD_SHARED_LIBS)
    if (WIN32)
        install(FILES ${READCON_CORE_SHARED_LOCATION} DESTINATION ${BIN_INSTALL_DIR})
        install(FILES ${READCON_CORE_IMPLIB_LOCATION} DESTINATION ${LIB_INSTALL_DIR})
    else()
        install(FILES ${READCON_CORE_SHARED_LOCATION} DESTINATION ${LIB_INSTALL_DIR})
    endif()
endif()
if (READCON_CORE_INSTALL_BOTH_STATIC_SHARED OR NOT BUILD_SHARED_LIBS)
    install(FILES ${READCON_CORE_STATIC_LOCATION} DESTINATION ${LIB_INSTALL_DIR})
endif()

install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/readcon-core-config-version.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/readcon-core-config.cmake
    DESTINATION ${LIB_INSTALL_DIR}/cmake/readcon-core
)
install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/readcon-core.pc
    DESTINATION ${LIB_INSTALL_DIR}/pkgconfig
)
