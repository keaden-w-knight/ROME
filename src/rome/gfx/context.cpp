#include "rome/gfx/context.hpp"

#include <SDL3/SDL_vulkan.h>

#include <string>

#include "rome/error.hpp"
#include "rome/window.hpp"
#include "vk_check.hpp"

namespace rome::gfx {
namespace {

void enable_surface_extensions(vkb::InstanceBuilder& builder) {
    std::uint32_t count = 0;
    const char* const* extensions = SDL_Vulkan_GetInstanceExtensions(&count);
    if (extensions == nullptr) {
        throw Error{std::string{"SDL_Vulkan_GetInstanceExtensions failed: "} + SDL_GetError()};
    }
    for (std::uint32_t i = 0; i < count; ++i) {
        builder.enable_extension(extensions[i]);
    }
}

}  // namespace

Context::Context(Window& window, bool enable_validation) {
    try {
        vkb::InstanceBuilder builder;
        builder.set_app_name("ROME").set_engine_name("ROME").require_api_version(1, 3, 0);

        if (enable_validation) {
            builder.request_validation_layers(true).use_default_debug_messenger();
        }
        enable_surface_extensions(builder);

        auto instance_result = builder.build();
        if (!instance_result) {
            throw Error{"Vulkan instance creation failed: " + instance_result.error().message()};
        }
        instance_ = instance_result.value();

        if (!SDL_Vulkan_CreateSurface(window.handle(), instance_.instance, nullptr, &surface_)) {
            throw Error{std::string{"SDL_Vulkan_CreateSurface failed: "} + SDL_GetError()};
        }

        // Vulkan 1.3 core features this renderer is built on. Dynamic rendering
        // removes VkRenderPass/VkFramebuffer; synchronization2 gives the
        // barrier and submit forms used throughout.
        VkPhysicalDeviceVulkan13Features features13{};
        features13.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES;
        features13.dynamicRendering = VK_TRUE;
        features13.synchronization2 = VK_TRUE;

        VkPhysicalDeviceVulkan12Features features12{};
        features12.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES;
        features12.bufferDeviceAddress = VK_TRUE;
        features12.descriptorIndexing = VK_TRUE;

        vkb::PhysicalDeviceSelector selector{instance_};
        auto physical_result = selector.set_surface(surface_)
                                   .set_minimum_version(1, 3)
                                   .set_required_features_13(features13)
                                   .set_required_features_12(features12)
                                   .prefer_gpu_device_type(vkb::PreferredDeviceType::discrete)
                                   .select();
        if (!physical_result) {
            throw Error{"No suitable Vulkan 1.3 GPU found: " + physical_result.error().message()};
        }

        vkb::DeviceBuilder device_builder{physical_result.value()};
        auto device_result = device_builder.build();
        if (!device_result) {
            throw Error{"Vulkan device creation failed: " + device_result.error().message()};
        }
        device_ = device_result.value();

        auto queue_result = device_.get_queue(vkb::QueueType::graphics);
        if (!queue_result) {
            throw Error{"No graphics queue: " + queue_result.error().message()};
        }
        graphics_queue_ = queue_result.value();
        graphics_queue_family_ = device_.get_queue_index(vkb::QueueType::graphics).value();

        vkGetPhysicalDeviceProperties(device_.physical_device, &device_properties_);

        VmaAllocatorCreateInfo allocator_info{};
        allocator_info.physicalDevice = device_.physical_device;
        allocator_info.device = device_.device;
        allocator_info.instance = instance_.instance;
        allocator_info.vulkanApiVersion = VK_API_VERSION_1_3;
        allocator_info.flags = VMA_ALLOCATOR_CREATE_BUFFER_DEVICE_ADDRESS_BIT;
        ROME_VK_CHECK(vmaCreateAllocator(&allocator_info, &allocator_));

        // A small pool + fence for one-off uploads (see immediate_submit).
        VkCommandPoolCreateInfo transfer_pool_info{};
        transfer_pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        transfer_pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        transfer_pool_info.queueFamilyIndex = graphics_queue_family_;
        ROME_VK_CHECK(
            vkCreateCommandPool(device_.device, &transfer_pool_info, nullptr, &transfer_pool_));

        VkFenceCreateInfo transfer_fence_info{};
        transfer_fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        ROME_VK_CHECK(vkCreateFence(device_.device, &transfer_fence_info, nullptr, &transfer_fence_));
    } catch (...) {
        // A throwing constructor means ~Context never runs, so unwind by hand.
        destroy();
        throw;
    }
}

Context::~Context() {
    destroy();
}

void Context::destroy() noexcept {
    if (transfer_fence_ != VK_NULL_HANDLE) {
        vkDestroyFence(device_.device, transfer_fence_, nullptr);
        transfer_fence_ = VK_NULL_HANDLE;
    }
    if (transfer_pool_ != VK_NULL_HANDLE) {
        vkDestroyCommandPool(device_.device, transfer_pool_, nullptr);
        transfer_pool_ = VK_NULL_HANDLE;
    }
    if (allocator_ != VK_NULL_HANDLE) {
        vmaDestroyAllocator(allocator_);
        allocator_ = VK_NULL_HANDLE;
    }
    if (device_.device != VK_NULL_HANDLE) {
        vkb::destroy_device(device_);
        device_ = {};
    }
    if (surface_ != VK_NULL_HANDLE) {
        vkb::destroy_surface(instance_, surface_);
        surface_ = VK_NULL_HANDLE;
    }
    if (instance_.instance != VK_NULL_HANDLE) {
        vkb::destroy_instance(instance_);
        instance_ = {};
    }
}

void Context::wait_idle() const {
    if (device_.device != VK_NULL_HANDLE) {
        vkDeviceWaitIdle(device_.device);
    }
}

void Context::immediate_submit(const std::function<void(VkCommandBuffer)>& record) const {
    VkCommandBufferAllocateInfo alloc_info{};
    alloc_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    alloc_info.commandPool = transfer_pool_;
    alloc_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    alloc_info.commandBufferCount = 1;

    VkCommandBuffer cmd = VK_NULL_HANDLE;
    ROME_VK_CHECK(vkAllocateCommandBuffers(device_.device, &alloc_info, &cmd));

    VkCommandBufferBeginInfo begin_info{};
    begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin_info.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    ROME_VK_CHECK(vkBeginCommandBuffer(cmd, &begin_info));
    record(cmd);
    ROME_VK_CHECK(vkEndCommandBuffer(cmd));

    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;

    ROME_VK_CHECK(vkResetFences(device_.device, 1, &transfer_fence_));
    ROME_VK_CHECK(vkQueueSubmit(graphics_queue_, 1, &submit, transfer_fence_));
    ROME_VK_CHECK(vkWaitForFences(device_.device, 1, &transfer_fence_, VK_TRUE, UINT64_MAX));

    vkFreeCommandBuffers(device_.device, transfer_pool_, 1, &cmd);
}

}  // namespace rome::gfx
