# Third-party dependencies, all fetched at configure time so the repo stays
# free of vendored source and no package manager is required.
include(FetchContent)

set(FETCHCONTENT_QUIET OFF)

# --- Vulkan --------------------------------------------------------------
# Found on the system via the Vulkan SDK (VULKAN_SDK), not fetched.
find_package(Vulkan REQUIRED COMPONENTS glslc)

# --- SDL3: window, input, events ----------------------------------------
set(SDL_SHARED ON  CACHE BOOL "" FORCE)
set(SDL_STATIC OFF CACHE BOOL "" FORCE)
set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
set(SDL_TESTS OFF CACHE BOOL "" FORCE)
set(SDL_EXAMPLES OFF CACHE BOOL "" FORCE)
set(SDL_INSTALL OFF CACHE BOOL "" FORCE)
FetchContent_Declare(SDL3
    GIT_REPOSITORY https://github.com/libsdl-org/SDL.git
    GIT_TAG release-3.4.14
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
)

# --- vk-bootstrap: instance/device/swapchain selection boilerplate -------
FetchContent_Declare(vk_bootstrap
    GIT_REPOSITORY https://github.com/charles-lunarg/vk-bootstrap.git
    GIT_TAG v1.4.341  # matched to the installed Vulkan SDK
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
)

# --- VulkanMemoryAllocator: GPU allocation -------------------------------
FetchContent_Declare(vma
    GIT_REPOSITORY https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator.git
    GIT_TAG v3.4.0
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
)

# --- GLM: vector and matrix maths ----------------------------------------
set(GLM_ENABLE_CXX_20 ON CACHE BOOL "" FORCE)
FetchContent_Declare(glm
    GIT_REPOSITORY https://github.com/g-truc/glm.git
    GIT_TAG 1.0.3
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
)

FetchContent_MakeAvailable(SDL3 vk_bootstrap vma glm)

# GLM defaults to OpenGL's [-1,1] depth range and column-major clip space;
# Vulkan wants [0,1]. Set it globally so no translation unit can disagree.
target_compile_definitions(glm INTERFACE
    GLM_FORCE_DEPTH_ZERO_TO_ONE
    GLM_FORCE_RADIANS
)
