#pragma once

#include <VkBootstrap.h>
#include <vk_mem_alloc.h>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <functional>

namespace rome {
class Window;
}

namespace rome::gfx {

/// Instance, surface, device, queue and allocator: everything whose lifetime
/// spans the whole session. Created once per Window and never recreated, so
/// swapchain churn on resize cannot invalidate anything held here.
class Context {
public:
    Context(Window& window, bool enable_validation);
    ~Context();

    Context(const Context&) = delete;
    Context& operator=(const Context&) = delete;
    Context(Context&&) = delete;
    Context& operator=(Context&&) = delete;

    [[nodiscard]] VkInstance instance() const {
        return instance_.instance;
    }

    [[nodiscard]] VkSurfaceKHR surface() const {
        return surface_;
    }

    [[nodiscard]] VkPhysicalDevice physical_device() const {
        return device_.physical_device;
    }

    [[nodiscard]] VkDevice device() const {
        return device_.device;
    }

    [[nodiscard]] VkQueue graphics_queue() const {
        return graphics_queue_;
    }

    [[nodiscard]] std::uint32_t graphics_queue_family() const {
        return graphics_queue_family_;
    }

    [[nodiscard]] VmaAllocator allocator() const {
        return allocator_;
    }

    [[nodiscard]] const vkb::Device& vkb_device() const {
        return device_;
    }

    /// Name of the selected GPU, for logging and for Python to report.
    [[nodiscard]] const char* device_name() const {
        return device_properties_.deviceName;
    }

    /// Blocks until the device is idle. Required before destroying anything
    /// that in-flight command buffers might still reference.
    void wait_idle() const;

    /// Records and runs a one-off command buffer on the graphics queue, blocking
    /// until it completes. Used for GPU uploads (staging -> device-local copies).
    void immediate_submit(const std::function<void(VkCommandBuffer)>& record) const;

private:
    void destroy() noexcept;

    vkb::Instance instance_{};
    VkSurfaceKHR surface_ = VK_NULL_HANDLE;
    vkb::Device device_{};
    VkQueue graphics_queue_ = VK_NULL_HANDLE;
    std::uint32_t graphics_queue_family_ = 0;
    VmaAllocator allocator_ = VK_NULL_HANDLE;
    VkPhysicalDeviceProperties device_properties_{};

    // Dedicated pool + fence for immediate_submit (one-off uploads).
    VkCommandPool transfer_pool_ = VK_NULL_HANDLE;
    VkFence transfer_fence_ = VK_NULL_HANDLE;
};

}  // namespace rome::gfx
