# Compiles GLSL to SPIR-V and emits it as a C initialiser list, so shaders are
# baked into the binary. A Python extension module gets imported from wherever
# site-packages happens to be, and hunting for loose .spv files at runtime is a
# reliable source of bugs; embedding sidesteps the question entirely.
#
#   rome_add_shaders(<target> SHADERS <file>...)
#
# Each <file>.vert becomes "<file>.vert.h" in the target's binary dir,
# includable as:
#
#   static constexpr uint32_t kCode[] =
#   #include "triangle.vert.h"
#   ;

function(rome_add_shaders TARGET)
    cmake_parse_arguments(ARG "" "" "SHADERS" ${ARGN})

    if(NOT ARG_SHADERS)
        message(FATAL_ERROR "rome_add_shaders(${TARGET}): no SHADERS given")
    endif()

    set(out_dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shaders")
    file(MAKE_DIRECTORY "${out_dir}")

    set(generated "")
    foreach(shader IN LISTS ARG_SHADERS)
        get_filename_component(shader_abs "${shader}" ABSOLUTE)
        get_filename_component(shader_name "${shader}" NAME)
        set(out_file "${out_dir}/${shader_name}.h")

        add_custom_command(
            OUTPUT "${out_file}"
            COMMAND Vulkan::glslc
                    --target-env=vulkan1.3
                    -mfmt=c
                    -O
                    "${shader_abs}"
                    -o "${out_file}"
            DEPENDS "${shader_abs}"
            COMMENT "Compiling shader ${shader_name}"
            VERBATIM
        )
        list(APPEND generated "${out_file}")
    endforeach()

    add_custom_target(${TARGET}_shaders DEPENDS ${generated})
    add_dependencies(${TARGET} ${TARGET}_shaders)
    target_include_directories(${TARGET} PRIVATE "${out_dir}")
endfunction()
