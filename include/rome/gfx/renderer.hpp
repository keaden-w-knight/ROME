#pragma once

#include <vk_mem_alloc.h>
#include <vulkan/vulkan.h>

#include <array>
#include <cstdint>
#include <functional>
#include <unordered_map>
#include <vector>

#include "rome/types.hpp"

namespace rome::gfx {

class Context;
class Swapchain;

/// Vertex + index buffers for one uploaded mesh, device-local.
struct GpuMesh {
    VkBuffer vertex_buffer = VK_NULL_HANDLE;
    VmaAllocation vertex_alloc = VK_NULL_HANDLE;
    VkBuffer index_buffer = VK_NULL_HANDLE;
    VmaAllocation index_alloc = VK_NULL_HANDLE;
    std::uint32_t index_count = 0;
};

/// Records and submits one frame at a time.
///
/// Uses Vulkan 1.3 dynamic rendering, so there are no VkRenderPass or
/// VkFramebuffer objects to keep in step with the swapchain.
class Renderer {
public:
    /// Frames the CPU may run ahead of the GPU. Two is the usual balance
    /// between keeping the GPU fed and bounding input latency.
    static constexpr std::uint32_t kFramesInFlight = 2;

    Renderer(Context& context, Swapchain& swapchain);
    ~Renderer();

    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;
    Renderer(Renderer&&) = delete;
    Renderer& operator=(Renderer&&) = delete;

    /// Draws and presents one frame (the clear-only / triangle path). Returns
    /// false if the swapchain went out of date and was rebuilt.
    bool draw(Color clear_color, Extent2D window_extent);

    /// Uploads a mesh to the GPU and returns a handle for drawing it. Positions
    /// and normals are flat xyz triples (same vertex count); indices are a
    /// triangle list.
    std::uint64_t upload_mesh(const std::vector<float>& positions,
                              const std::vector<float>& normals,
                              const std::vector<std::uint32_t>& indices);

    /// Draws and presents one frame of a scene: each instance's mesh, lit,
    /// z-buffered, seen through the camera. Returns false if the swapchain was
    /// rebuilt this frame.
    bool draw_scene(Color clear_color, Extent2D window_extent, const CameraParams& camera,
                    const std::vector<MeshInstance>& instances);

    /// Renders a scene to an off-screen image and returns its pixels as RGBA8
    /// (row-major, top row first), width*height*4 bytes. No window involved.
    std::vector<std::uint8_t> render_offscreen(Color clear_color, std::uint32_t width,
                                               std::uint32_t height, const CameraParams& camera,
                                               const std::vector<MeshInstance>& instances);

    /// Rebuilds the swapchain (and depth buffer) at the given size. Safe to call
    /// with an empty extent (minimised), in which case it does nothing.
    void on_resize(Extent2D window_extent);

private:
    struct FrameData {
        VkCommandPool command_pool = VK_NULL_HANDLE;
        VkCommandBuffer command_buffer = VK_NULL_HANDLE;
        VkSemaphore image_available = VK_NULL_HANDLE;
        VkFence in_flight = VK_NULL_HANDLE;
    };

    void create_frame_data();
    void create_present_semaphores();
    void destroy_present_semaphores();
    void create_pipeline();
    void create_mesh_pipeline();
    void create_depth_resources(Extent2D extent);
    void destroy_depth_resources();
    void destroy_meshes();

    void record(VkCommandBuffer cmd, std::uint32_t image_index, Color clear_color) const;
    void record_scene(VkCommandBuffer cmd, std::uint32_t image_index, Color clear_color,
                      const CameraParams& camera,
                      const std::vector<MeshInstance>& instances) const;

    // Binds the mesh pipeline and draws every instance; assumes rendering has
    // begun and viewport/scissor are set. Shared by the windowed and off-screen
    // paths.
    void record_mesh_draws(VkCommandBuffer cmd, std::uint32_t width, std::uint32_t height,
                           const CameraParams& camera,
                           const std::vector<MeshInstance>& instances) const;

    // The acquire / submit / present scaffolding, shared by both draw paths. The
    // record callback fills the command buffer for the acquired image.
    bool submit_and_present(Extent2D window_extent,
                            const std::function<void(VkCommandBuffer, std::uint32_t)>& record_fn);

    Context& context_;
    Swapchain& swapchain_;

    std::array<FrameData, kFramesInFlight> frames_{};
    std::uint32_t frame_index_ = 0;

    // One per swapchain image rather than per frame-in-flight: a semaphore
    // signalled for presentation stays in use until that specific image is
    // reacquired, which does not track the frame-in-flight cycle.
    std::vector<VkSemaphore> render_finished_;

    VkPipelineLayout pipeline_layout_ = VK_NULL_HANDLE;
    VkPipeline pipeline_ = VK_NULL_HANDLE;

    VkPipelineLayout mesh_layout_ = VK_NULL_HANDLE;
    VkPipeline mesh_pipeline_ = VK_NULL_HANDLE;

    VkFormat depth_format_ = VK_FORMAT_D32_SFLOAT;
    VkImage depth_image_ = VK_NULL_HANDLE;
    VmaAllocation depth_alloc_ = VK_NULL_HANDLE;
    VkImageView depth_view_ = VK_NULL_HANDLE;

    std::unordered_map<std::uint64_t, GpuMesh> meshes_;
    std::uint64_t next_mesh_id_ = 1;
};

}  // namespace rome::gfx
