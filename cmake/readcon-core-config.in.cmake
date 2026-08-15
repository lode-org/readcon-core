@PACKAGE_INIT@

cmake_minimum_required(VERSION 3.22)

if(readcon-core_FOUND)
    return()
endif()

get_filename_component(READCON_CORE_PREFIX_DIR "${CMAKE_CURRENT_LIST_DIR}/@PACKAGE_RELATIVE_PATH@" ABSOLUTE)

if (WIN32)
    set(READCON_CORE_SHARED_LOCATION ${READCON_CORE_PREFIX_DIR}/@BIN_INSTALL_DIR@/@READCON_CORE_SHARED_LIB_NAME@)
    set(READCON_CORE_IMPLIB_LOCATION ${READCON_CORE_PREFIX_DIR}/@LIB_INSTALL_DIR@/@READCON_CORE_IMPLIB_NAME@)
else()
    set(READCON_CORE_SHARED_LOCATION ${READCON_CORE_PREFIX_DIR}/@LIB_INSTALL_DIR@/@READCON_CORE_SHARED_LIB_NAME@)
endif()

set(READCON_CORE_STATIC_LOCATION ${READCON_CORE_PREFIX_DIR}/@LIB_INSTALL_DIR@/@READCON_CORE_STATIC_LIB_NAME@)
set(READCON_CORE_INCLUDE ${READCON_CORE_PREFIX_DIR}/@INCLUDE_INSTALL_DIR@/)

if (NOT EXISTS ${READCON_CORE_INCLUDE}/readcon-core.h)
    message(FATAL_ERROR
        "could not find readcon-core.h in '${READCON_CORE_INCLUDE}'. "
        "Re-install readcon-core (headers are shipped in the source tree; cbindgen is not required).")
endif()

# Shared library target
if (@READCON_CORE_INSTALL_BOTH_STATIC_SHARED@ OR @BUILD_SHARED_LIBS@)
    if (NOT EXISTS ${READCON_CORE_SHARED_LOCATION})
        message(FATAL_ERROR "could not find readcon-core shared library at '${READCON_CORE_SHARED_LOCATION}'")
    endif()

    add_library(readcon-core::shared SHARED IMPORTED GLOBAL)
    set_target_properties(readcon-core::shared PROPERTIES
        IMPORTED_LOCATION ${READCON_CORE_SHARED_LOCATION}
        INTERFACE_INCLUDE_DIRECTORIES ${READCON_CORE_INCLUDE}
        BUILD_VERSION "@PROJECT_VERSION@"
    )

    if (WIN32)
        if (NOT EXISTS ${READCON_CORE_IMPLIB_LOCATION})
            message(FATAL_ERROR "could not find readcon-core import library at '${READCON_CORE_IMPLIB_LOCATION}'")
        endif()
        set_target_properties(readcon-core::shared PROPERTIES
            IMPORTED_IMPLIB ${READCON_CORE_IMPLIB_LOCATION}
        )
    endif()
endif()

# Static library target
if (@READCON_CORE_INSTALL_BOTH_STATIC_SHARED@ OR NOT @BUILD_SHARED_LIBS@)
    if (NOT EXISTS ${READCON_CORE_STATIC_LOCATION})
        message(FATAL_ERROR "could not find readcon-core static library at '${READCON_CORE_STATIC_LOCATION}'")
    endif()

    add_library(readcon-core::static STATIC IMPORTED GLOBAL)
    set_target_properties(readcon-core::static PROPERTIES
        IMPORTED_LOCATION ${READCON_CORE_STATIC_LOCATION}
        INTERFACE_INCLUDE_DIRECTORIES ${READCON_CORE_INCLUDE}
        INTERFACE_LINK_LIBRARIES "@CARGO_DEFAULT_LIBRARIES@"
        BUILD_VERSION "@PROJECT_VERSION@"
    )
endif()

if (@BUILD_SHARED_LIBS@)
    if (NOT TARGET readcon-core::shared)
        message(FATAL_ERROR "readcon-core was installed without a shared library")
    endif()
    add_library(readcon-core ALIAS readcon-core::shared)
    add_library(readcon-core::readcon-core ALIAS readcon-core::shared)
else()
    if (NOT TARGET readcon-core::static)
        message(FATAL_ERROR "readcon-core was installed without a static library")
    endif()
    add_library(readcon-core ALIAS readcon-core::static)
    add_library(readcon-core::readcon-core ALIAS readcon-core::static)
endif()
