# Python itself is resolved in the top-level CMakeLists so the tests can see
# it as well. Development.Module (rather than Development) is the correct
# component for an extension module: it wants the headers but must not link
# libpython.
include(FetchContent)
FetchContent_Declare(nanobind
    GIT_REPOSITORY https://github.com/wjakob/nanobind.git
    GIT_TAG v2.15.0
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
)
FetchContent_MakeAvailable(nanobind)

# NB_STATIC links nanobind's runtime into this module. With a single extension
# module that is the smaller and simpler option.
nanobind_add_module(_rome NB_STATIC bindings.cpp)

target_link_libraries(_rome PRIVATE rome::core rome_warnings)
target_compile_definitions(_rome PRIVATE ROME_VERSION="${PROJECT_VERSION}")

# The .pyd and the Python sources have to sit together for `import rome` to
# work straight out of the build tree, without installing anything.
set(stage_dir "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}/rome")

set_target_properties(_rome PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${stage_dir}"
    RUNTIME_OUTPUT_DIRECTORY "${stage_dir}"
)

add_custom_command(TARGET _rome POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_CURRENT_SOURCE_DIR}/rome/__init__.py"
            "${stage_dir}/__init__.py"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_CURRENT_SOURCE_DIR}/rome/py.typed"
            "${stage_dir}/py.typed"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:SDL3::SDL3>"
            "${stage_dir}/$<TARGET_FILE_NAME:SDL3::SDL3>"
    COMMENT "Staging the rome Python package"
    VERBATIM
)

# Wheel layout, used when scikit-build-core drives the build.
install(TARGETS _rome LIBRARY DESTINATION rome RUNTIME DESTINATION rome)
install(FILES
        "${CMAKE_CURRENT_SOURCE_DIR}/rome/__init__.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/rome/py.typed"
        DESTINATION rome)
install(FILES "$<TARGET_FILE:SDL3::SDL3>" DESTINATION rome)
