#include "rome/gfx/swapchain.hpp"

#include <VkBootstrap.h>

#include "rome/error.hpp"
#include "rome/gfx/context.hpp"
#include "vk_check.hpp"

namespace rome::gfx {

Swapchain::Swapchain(Context& context, Extent2D extent, bool vsync)
    : context_(context), vsync_(vsync) {
    build(extent, VK_NULL_HANDLE);
}

Swapchain::~Swapchain() {
    destroy_image_views();
    if (swapchain_ != VK_NULL_HANDLE) {
        vkDestroySwapchainKHR(context_.device(), swapchain_, nullptr);
    }
}

void Swapchain::build(Extent2D extent, VkSwapchainKHR old_swapchain) {
    vkb::SwapchainBuilder builder{context_.vkb_device()};

    // FIFO is the only mode guaranteed present, and is the right default:
    // it is v-synced and never tears. Mailbox trades power for latency.
    const VkPresentModeKHR present_mode =
        vsync_ ? VK_PRESENT_MODE_FIFO_KHR : VK_PRESENT_MODE_MAILBOX_KHR;

    auto result = builder
                      .set_desired_format(VkSurfaceFormatKHR{VK_FORMAT_B8G8R8A8_UNORM,
                                                             VK_COLOR_SPACE_SRGB_NONLINEAR_KHR})
                      .set_desired_present_mode(present_mode)
                      .set_desired_extent(extent.width, extent.height)
                      .add_image_usage_flags(VK_IMAGE_USAGE_TRANSFER_DST_BIT)
                      .set_old_swapchain(old_swapchain)
                      .build();

    if (!result) {
        throw Error{"Swapchain creation failed: " + result.error().message()};
    }

    vkb::Swapchain built = result.value();
    swapchain_ = built.swapchain;
    format_ = built.image_format;
    extent_ = Extent2D{built.extent.width, built.extent.height};

    auto images = built.get_images();
    if (!images) {
        throw Error{"Could not retrieve swapchain images: " + images.error().message()};
    }
    images_ = images.value();

    auto views = built.get_image_views();
    if (!views) {
        throw Error{"Could not create swapchain image views: " + views.error().message()};
    }
    image_views_ = views.value();
}

void Swapchain::recreate(Extent2D extent) {
    // In-flight work may still reference the current images.
    context_.wait_idle();

    destroy_image_views();

    // Handing the old chain to the builder lets the driver reuse its images
    // instead of allocating a fresh set; it is destroyed once the new one
    // has been built from it.
    VkSwapchainKHR old = swapchain_;
    swapchain_ = VK_NULL_HANDLE;

    build(extent, old);

    if (old != VK_NULL_HANDLE) {
        vkDestroySwapchainKHR(context_.device(), old, nullptr);
    }
}

void Swapchain::destroy_image_views() {
    for (VkImageView view : image_views_) {
        vkDestroyImageView(context_.device(), view, nullptr);
    }
    image_views_.clear();
    // The images themselves are owned by the swapchain, not by us.
    images_.clear();
}

}  // namespace rome::gfx
