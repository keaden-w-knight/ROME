#pragma once

#include <vulkan/vulkan.h>

#include <array>
#include <cstdint>
#include <vector>

#include "rome/types.hpp"

namespace rome::gfx {

class Context;
class Swapchain;

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

    /// Draws and presents one frame. Returns false if the swapchain went out
    /// of date and was rebuilt, meaning this frame produced no image.
    bool draw(Color clear_color, Extent2D window_extent);

    /// Rebuilds the swapchain at the given size. Safe to call with an empty
    /// extent (minimised), in which case it does nothing.
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
    void record(VkCommandBuffer cmd, std::uint32_t image_index, Color clear_color) const;

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
};

}  // namespace rome::gfx
