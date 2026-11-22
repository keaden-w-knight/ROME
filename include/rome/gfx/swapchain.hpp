#pragma once

#include <vulkan/vulkan.h>

#include <vector>

#include "rome/types.hpp"

namespace rome::gfx {

class Context;

/// The swapchain and its image views. Rebuilt whenever the window resizes or
/// the presentation engine reports the current chain is out of date.
class Swapchain {
public:
    Swapchain(Context& context, Extent2D extent, bool vsync);
    ~Swapchain();

    Swapchain(const Swapchain&) = delete;
    Swapchain& operator=(const Swapchain&) = delete;
    Swapchain(Swapchain&&) = delete;
    Swapchain& operator=(Swapchain&&) = delete;

    /// Tears down and rebuilds at the new size, reusing the old chain so the
    /// driver can hand images over rather than reallocating from scratch.
    void recreate(Extent2D extent);

    [[nodiscard]] VkSwapchainKHR handle() const {
        return swapchain_;
    }

    [[nodiscard]] VkFormat format() const {
        return format_;
    }

    [[nodiscard]] Extent2D extent() const {
        return extent_;
    }

    [[nodiscard]] const std::vector<VkImage>& images() const {
        return images_;
    }

    [[nodiscard]] const std::vector<VkImageView>& image_views() const {
        return image_views_;
    }

    [[nodiscard]] std::size_t image_count() const {
        return images_.size();
    }

private:
    void build(Extent2D extent, VkSwapchainKHR old_swapchain);
    void destroy_image_views();

    Context& context_;
    VkSwapchainKHR swapchain_ = VK_NULL_HANDLE;
    VkFormat format_ = VK_FORMAT_UNDEFINED;
    Extent2D extent_{};
    bool vsync_ = true;
    std::vector<VkImage> images_;
    std::vector<VkImageView> image_views_;
};

}  // namespace rome::gfx
