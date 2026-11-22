cmake_minimum_required(VERSION 3.28)

project(rome
    VERSION 0.1.0
    DESCRIPTION "A Vulkan 3D viewport library with Python bindings"
    LANGUAGES C CXX
)

list(APPEND CMAKE_MODULE_PATH "${PROJECT_SOURCE_DIR}/cmake")

# Settings that belong to the build as a whole, not to ROME as a dependency.
if(PROJECT_IS_TOP_LEVEL)
    set(CMAKE_CXX_STANDARD 23)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
    set(CMAKE_CXX_EXTENSIONS OFF)

    # Drives IntelliSense and any clang-based tooling.
    set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

    # Everything runnable lands in one place so launch configs and the DLL
    # search path have a single, stable location.
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

    if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
        set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build type" FORCE)
    endif()

    # Position-independent code throughout: the Python extension is a shared
    # library and everything it links must be relocatable.
    set(CMAKE_POSITION_INDEPENDENT_CODE ON)
endif()

option(ROME_BUILD_PYTHON   "Build the Python extension module" ON)
option(ROME_BUILD_EXAMPLES "Build the C++ examples"            ON)
option(ROME_BUILD_TESTS    "Build the test suite"              ${PROJECT_IS_TOP_LEVEL})
option(ROME_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)

include(Dependencies)
include(Shaders)

# Resolved at the top level rather than inside python/ so that the test suite
# can see Python_EXECUTABLE too: FindPython sets it per-directory, not cached.
if(ROME_BUILD_PYTHON)
    find_package(Python 3.10 REQUIRED COMPONENTS Interpreter Development.Module)
    message(STATUS "Python: ${Python_EXECUTABLE} (${Python_VERSION})")
endif()

# Carrier for the project-wide warning set; link it PRIVATE into targets we own
# so third-party headers never trip our own strictness.
add_library(rome_warnings INTERFACE)

if(MSVC)
    target_compile_options(rome_warnings INTERFACE
        /W4
        /permissive-
        /utf-8
        /Zc:preprocessor
        /wd4251  # DLL-interface warnings on STL members of exported types
    )
    if(ROME_WARNINGS_AS_ERRORS)
        target_compile_options(rome_warnings INTERFACE /WX)
    endif()
else()
    target_compile_options(rome_warnings INTERFACE
        -Wall
        -Wextra
        -Wpedantic
        -Wshadow
        -Wconversion
        -Wsign-conversion
        -Wnon-virtual-dtor
        -Wold-style-cast
        -Wcast-align
        -Wunused
        -Woverloaded-virtual
        -Wnull-dereference
        -Wdouble-promotion
        -Wformat=2
    )
    if(ROME_WARNINGS_AS_ERRORS)
        target_compile_options(rome_warnings INTERFACE -Werror)
    endif()
endif()

add_subdirectory(src)

if(ROME_BUILD_PYTHON)
    add_subdirectory(python)
endif()

if(ROME_BUILD_EXAMPLES)
    add_subdirectory(examples)
endif()

if(ROME_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

message(STATUS "")
message(STATUS "ROME ${PROJECT_VERSION}")
message(STATUS "  compiler      : ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
message(STATUS "  build type    : ${CMAKE_BUILD_TYPE}")
message(STATUS "  Vulkan        : ${Vulkan_VERSION}")
message(STATUS "  python module : ${ROME_BUILD_PYTHON}")
message(STATUS "")
