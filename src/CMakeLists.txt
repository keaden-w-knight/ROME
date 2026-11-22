# The renderer lives in a library so both the C++ examples and the Python
# extension link the same code.
add_library(rome_core
    rome/app.cpp
    rome/window.cpp
    rome/gfx/context.cpp
    rome/gfx/renderer.cpp
    rome/gfx/swapchain.cpp
    rome/gfx/vk_check.cpp
    rome/gfx/vma_impl.cpp
)
add_library(rome::core ALIAS rome_core)

target_include_directories(rome_core
    PUBLIC  "${PROJECT_SOURCE_DIR}/include"
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/rome/gfx"   # vk_check.hpp
)

target_link_libraries(rome_core
    PUBLIC
        Vulkan::Vulkan
        vk-bootstrap::vk-bootstrap
        GPUOpen::VulkanMemoryAllocator
        glm::glm
    PRIVATE
        SDL3::SDL3
        rome_warnings
)

# SDL3 appears in the public headers only as a forward-declared pointer, so it
# stays a private link dependency; consumers never need its headers.

rome_add_shaders(rome_core
    SHADERS
        "${PROJECT_SOURCE_DIR}/shaders/triangle.vert"
        "${PROJECT_SOURCE_DIR}/shaders/triangle.frag"
        "${PROJECT_SOURCE_DIR}/shaders/mesh.vert"
        "${PROJECT_SOURCE_DIR}/shaders/mesh.frag"
)

# SDL3 is built as a DLL, so it has to sit next to anything that loads it.
add_custom_command(TARGET rome_core POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:SDL3::SDL3>"
            "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}/$<TARGET_FILE_NAME:SDL3::SDL3>"
    COMMENT "Staging SDL3 runtime next to the binaries"
    VERBATIM
)
