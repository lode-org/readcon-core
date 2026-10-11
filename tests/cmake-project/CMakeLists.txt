cmake_minimum_required(VERSION 3.22)
project(readcon-core-cmake-test C)

# Two modes:
#   - READCON_CORE_SOURCE_DIR set: add_subdirectory / FetchContent-from-source
#   - otherwise: find_package of an installed prefix
option(READCON_CORE_USE_FETCHCONTENT "Exercise FetchContent_Declare(SOURCE_DIR=...)" ON)

if(DEFINED READCON_CORE_FETCH_URL)
    include(FetchContent)
    if(DEFINED READCON_CORE_FETCH_HASH)
        FetchContent_Declare(
            readcon-core
            URL "${READCON_CORE_FETCH_URL}"
            URL_HASH "${READCON_CORE_FETCH_HASH}"
        )
    else()
        FetchContent_Declare(readcon-core URL "${READCON_CORE_FETCH_URL}")
    endif()
    FetchContent_MakeAvailable(readcon-core)
elseif(DEFINED READCON_CORE_SOURCE_DIR)
    if(READCON_CORE_USE_FETCHCONTENT)
        include(FetchContent)
        FetchContent_Declare(readcon-core SOURCE_DIR "${READCON_CORE_SOURCE_DIR}")
        FetchContent_MakeAvailable(readcon-core)
    else()
        add_subdirectory("${READCON_CORE_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/readcon-core")
    endif()
else()
    find_package(readcon-core REQUIRED CONFIG)
endif()

add_executable(c-main main.c)
target_link_libraries(c-main PRIVATE readcon-core::shared)

add_executable(c-main-static main.c)
target_link_libraries(c-main-static PRIVATE readcon-core::static)

add_executable(c-conformance "${CMAKE_CURRENT_SOURCE_DIR}/../c/test_conformance_goldens.c")
target_link_libraries(c-conformance PRIVATE readcon-core::shared)
target_link_libraries(c-conformance PRIVATE m)

add_executable(c-pre-grouping "${CMAKE_CURRENT_SOURCE_DIR}/../c/test_pre_grouping.c")
target_link_libraries(c-pre-grouping PRIVATE readcon-core::shared)

enable_language(CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(cxx-pre-grouping "${CMAKE_CURRENT_SOURCE_DIR}/../cxx/test_pre_grouping.cpp")
target_link_libraries(cxx-pre-grouping PRIVATE readcon-core::shared)
