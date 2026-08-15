cmake_minimum_required(VERSION 3.22)
project(readcon-core-cmake-test C)

# Two modes:
#   - READCON_CORE_SOURCE_DIR set: add_subdirectory / FetchContent-from-source
#   - otherwise: find_package of an installed prefix
option(READCON_CORE_USE_FETCHCONTENT "Exercise FetchContent_Declare(SOURCE_DIR=...)" ON)

if(DEFINED READCON_CORE_SOURCE_DIR)
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
