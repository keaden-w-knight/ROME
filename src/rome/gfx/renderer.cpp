#include "rome/gfx/renderer.hpp"

#include <array>
#include <cstdint>
#include <limits>

#include "rome/error.hpp"
#include "rome/gfx/context.hpp"
#include "rome/gfx/swapchain.hpp"
#include "vk_check.hpp"

namespace rome::gfx {
namespace {

// Emitted by glslc -mfmt=c at build time; see cmake/Shaders.cmake.
constexpr std::uint32_t kTriangleVertSpv[] =
#include "triangle.vert.h"
    ;
constexpr std::uint32_t kTriangleFragSpv[] =
#include "triangle.frag.h"
    ;

constexpr std::uint64_t kNoTimeout = std::numeric_limits<std::uint64_t>::max();

VkShaderModule create_shader_module(VkDevice device, const std::uint32_t* code,
                                    std::size_t size_bytes) {
    VkShaderModuleCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    info.codeSize = size_bytes;
    info.pCode = code;

    VkShaderModule module = VK_NULL_HANDLE;
    ROME_VK_CHECK(vkCreateShaderModule(device, &info, nullptr, &module));
    return module;
}

/// A synchronization2 image barrier. Broad stage masks are acceptable here:
/// this runs twice per frame on the swapchain image, not in a hot loop.
void transition_image(VkCommandBuffer cmd, VkImage image, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier2 barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2;
    barrier.srcStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    barrier.srcAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT;
    barrier.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    barrier.dstAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT | VK_ACCESS_2_MEMORY_READ_BIT;
    barrier.oldLayout = from;
    barrier.newLayout = to;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = image;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.levelCount = VK_REMAINING_MIP_LEVELS;
    barrier.subresourceRange.layerCount = VK_REMAINING_ARRAY_LAYERS;

    VkDependencyInfo dependency{};
    dependency.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO;
    dependency.imageMemoryBarrierCount = 1;
    dependency.pImageMemoryBarriers = &barrier;

    vkCmdPipelineBarrier2(cmd, &dependency);
}

}  // namespace

Renderer::Renderer(Context& context, Swapchain& swapchain)
    : context_(context), swapchain_(swapchain) {
    create_frame_data();
    create_present_semaphores();
    create_pipeline();
}

Renderer::~Renderer() {
    context_.wait_idle();

    const VkDevice device = context_.device();

    if (pipeline_ != VK_NULL_HANDLE) {
        vkDestroyPipeline(device, pipeline_, nullptr);
    }
    if (pipeline_layout_ != VK_NULL_HANDLE) {
        vkDestroyPipelineLayout(device, pipeline_layout_, nullptr);
    }

    destroy_present_semaphores();

    for (FrameData& frame : frames_) {
        if (frame.in_flight != VK_NULL_HANDLE) {
            vkDestroyFence(device, frame.in_flight, nullptr);
        }
        if (frame.image_available != VK_NULL_HANDLE) {
            vkDestroySemaphore(device, frame.image_available, nullptr);
        }
        if (frame.command_pool != VK_NULL_HANDLE) {
            // Destroying the pool frees the command buffers allocated from it.
            vkDestroyCommandPool(device, frame.command_pool, nullptr);
        }
    }
}

void Renderer::create_frame_data() {
    const VkDevice device = context_.device();

    VkCommandPoolCreateInfo pool_info{};
    pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool_info.flags = VK_COMMAND_POOL_CREATE_TRANSIENT_BIT;
    pool_info.queueFamilyIndex = context_.graphics_queue_family();

    VkSemaphoreCreateInfo semaphore_info{};
    semaphore_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;

    // Created signalled so the very first vkWaitForFences returns immediately.
    VkFenceCreateInfo fence_info{};
    fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    fence_info.flags = VK_FENCE_CREATE_SIGNALED_BIT;

    for (FrameData& frame : frames_) {
        ROME_VK_CHECK(vkCreateCommandPool(device, &pool_info, nullptr, &frame.command_pool));

        VkCommandBufferAllocateInfo alloc_info{};
        alloc_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        alloc_info.commandPool = frame.command_pool;
        alloc_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        alloc_info.commandBufferCount = 1;
        ROME_VK_CHECK(vkAllocateCommandBuffers(device, &alloc_info, &frame.command_buffer));

        ROME_VK_CHECK(vkCreateSemaphore(device, &semaphore_info, nullptr, &frame.image_available));
        ROME_VK_CHECK(vkCreateFence(device, &fence_info, nullptr, &frame.in_flight));
    }
}

void Renderer::create_present_semaphores() {
    VkSemaphoreCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;

    render_finished_.resize(swapchain_.image_count(), VK_NULL_HANDLE);
    for (VkSemaphore& semaphore : render_finished_) {
        ROME_VK_CHECK(vkCreateSemaphore(context_.device(), &info, nullptr, &semaphore));
    }
}

void Renderer::destroy_present_semaphores() {
    for (VkSemaphore semaphore : render_finished_) {
        if (semaphore != VK_NULL_HANDLE) {
            vkDestroySemaphore(context_.device(), semaphore, nullptr);
        }
    }
    render_finished_.clear();
}

void Renderer::create_pipeline() {
    const VkDevice device = context_.device();

    VkPipelineLayoutCreateInfo layout_info{};
    layout_info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    ROME_VK_CHECK(vkCreatePipelineLayout(device, &layout_info, nullptr, &pipeline_layout_));

    const VkShaderModule vert =
        create_shader_module(device, kTriangleVertSpv, sizeof(kTriangleVertSpv));
    const VkShaderModule frag =
        create_shader_module(device, kTriangleFragSpv, sizeof(kTriangleFragSpv));

    std::array<VkPipelineShaderStageCreateInfo, 2> stages{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vert;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = frag;
    stages[1].pName = "main";

    // No vertex buffers: the vertex shader synthesises its own positions.
    VkPipelineVertexInputStateCreateInfo vertex_input{};
    vertex_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkPipelineInputAssemblyStateCreateInfo input_assembly{};
    input_assembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    input_assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    // Viewport and scissor are dynamic so a resize needs no pipeline rebuild.
    VkPipelineViewportStateCreateInfo viewport_state{};
    viewport_state.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewport_state.viewportCount = 1;
    viewport_state.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.cullMode = VK_CULL_MODE_NONE;
    rasterizer.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rasterizer.lineWidth = 1.0F;

    VkPipelineMultisampleStateCreateInfo multisample{};
    multisample.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    multisample.minSampleShading = 1.0F;

    VkPipelineColorBlendAttachmentState blend_attachment{};
    blend_attachment.blendEnable = VK_FALSE;
    blend_attachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
                                      VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;

    VkPipelineColorBlendStateCreateInfo color_blend{};
    color_blend.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    color_blend.attachmentCount = 1;
    color_blend.pAttachments = &blend_attachment;

    constexpr std::array<VkDynamicState, 2> kDynamicStates{VK_DYNAMIC_STATE_VIEWPORT,
                                                           VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamic_state{};
    dynamic_state.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamic_state.dynamicStateCount = static_cast<std::uint32_t>(kDynamicStates.size());
    dynamic_state.pDynamicStates = kDynamicStates.data();

    // Dynamic rendering: attachment formats are declared here instead of in a
    // VkRenderPass, and there is no VkFramebuffer to build or resize.
    const VkFormat color_format = swapchain_.format();
    VkPipelineRenderingCreateInfo rendering_info{};
    rendering_info.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO;
    rendering_info.colorAttachmentCount = 1;
    rendering_info.pColorAttachmentFormats = &color_format;

    VkGraphicsPipelineCreateInfo pipeline_info{};
    pipeline_info.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipeline_info.pNext = &rendering_info;
    pipeline_info.stageCount = static_cast<std::uint32_t>(stages.size());
    pipeline_info.pStages = stages.data();
    pipeline_info.pVertexInputState = &vertex_input;
    pipeline_info.pInputAssemblyState = &input_assembly;
    pipeline_info.pViewportState = &viewport_state;
    pipeline_info.pRasterizationState = &rasterizer;
    pipeline_info.pMultisampleState = &multisample;
    pipeline_info.pColorBlendState = &color_blend;
    pipeline_info.pDynamicState = &dynamic_state;
    pipeline_info.layout = pipeline_layout_;
    pipeline_info.renderPass = VK_NULL_HANDLE;

    const VkResult result =
        vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1, &pipeline_info, nullptr, &pipeline_);

    // The modules are only needed while the pipeline is being created.
    vkDestroyShaderModule(device, vert, nullptr);
    vkDestroyShaderModule(device, frag, nullptr);

    if (result != VK_SUCCESS) {
        detail::throw_vk(result, "vkCreateGraphicsPipelines", __FILE__, __LINE__);
    }
}

void Renderer::record(VkCommandBuffer cmd, std::uint32_t image_index, Color clear_color) const {
    VkCommandBufferBeginInfo begin_info{};
    begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin_info.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    ROME_VK_CHECK(vkBeginCommandBuffer(cmd, &begin_info));

    const VkImage image = swapchain_.images()[image_index];
    const Extent2D extent = swapchain_.extent();

    transition_image(cmd, image, VK_IMAGE_LAYOUT_UNDEFINED,
                     VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);

    VkRenderingAttachmentInfo color_attachment{};
    color_attachment.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;
    color_attachment.imageView = swapchain_.image_views()[image_index];
    color_attachment.imageLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    color_attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    color_attachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    color_attachment.clearValue.color.float32[0] = clear_color.r;
    color_attachment.clearValue.color.float32[1] = clear_color.g;
    color_attachment.clearValue.color.float32[2] = clear_color.b;
    color_attachment.clearValue.color.float32[3] = clear_color.a;

    VkRenderingInfo rendering{};
    rendering.sType = VK_STRUCTURE_TYPE_RENDERING_INFO;
    rendering.renderArea.extent = VkExtent2D{extent.width, extent.height};
    rendering.layerCount = 1;
    rendering.colorAttachmentCount = 1;
    rendering.pColorAttachments = &color_attachment;

    vkCmdBeginRendering(cmd, &rendering);

    VkViewport viewport{};
    viewport.width = static_cast<float>(extent.width);
    viewport.height = static_cast<float>(extent.height);
    viewport.minDepth = 0.0F;
    viewport.maxDepth = 1.0F;
    vkCmdSetViewport(cmd, 0, 1, &viewport);

    VkRect2D scissor{};
    scissor.extent = VkExtent2D{extent.width, extent.height};
    vkCmdSetScissor(cmd, 0, 1, &scissor);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_);
    vkCmdDraw(cmd, 3, 1, 0, 0);

    vkCmdEndRendering(cmd);

    transition_image(cmd, image, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                     VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);

    ROME_VK_CHECK(vkEndCommandBuffer(cmd));
}

void Renderer::on_resize(Extent2D window_extent) {
    if (window_extent.is_empty()) {
        return;  // minimised: nothing valid to size a swapchain against
    }
    swapchain_.recreate(window_extent);

    // The image count can change across a rebuild, so the per-image
    // presentation semaphores are rebuilt alongside it.
    destroy_present_semaphores();
    create_present_semaphores();
}

bool Renderer::draw(Color clear_color, Extent2D window_extent) {
    const VkDevice device = context_.device();
    FrameData& frame = frames_[frame_index_];

    ROME_VK_CHECK(vkWaitForFences(device, 1, &frame.in_flight, VK_TRUE, kNoTimeout));

    std::uint32_t image_index = 0;
    const VkResult acquired =
        vkAcquireNextImageKHR(device, swapchain_.handle(), kNoTimeout, frame.image_available,
                              VK_NULL_HANDLE, &image_index);
    if (acquired == VK_ERROR_OUT_OF_DATE_KHR) {
        on_resize(window_extent);
        return false;
    }
    if (acquired != VK_SUCCESS && acquired != VK_SUBOPTIMAL_KHR) {
        detail::throw_vk(acquired, "vkAcquireNextImageKHR", __FILE__, __LINE__);
    }

    // Reset only once the frame is certain to be submitted: an early return
    // above would otherwise leave the fence unsignalled forever.
    ROME_VK_CHECK(vkResetFences(device, 1, &frame.in_flight));
    ROME_VK_CHECK(vkResetCommandPool(device, frame.command_pool, 0));

    record(frame.command_buffer, image_index, clear_color);

    VkCommandBufferSubmitInfo cmd_info{};
    cmd_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO;
    cmd_info.commandBuffer = frame.command_buffer;

    VkSemaphoreSubmitInfo wait_info{};
    wait_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO;
    wait_info.semaphore = frame.image_available;
    wait_info.stageMask = VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT;

    VkSemaphoreSubmitInfo signal_info{};
    signal_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO;
    signal_info.semaphore = render_finished_[image_index];
    signal_info.stageMask = VK_PIPELINE_STAGE_2_ALL_GRAPHICS_BIT;

    VkSubmitInfo2 submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO_2;
    submit.waitSemaphoreInfoCount = 1;
    submit.pWaitSemaphoreInfos = &wait_info;
    submit.commandBufferInfoCount = 1;
    submit.pCommandBufferInfos = &cmd_info;
    submit.signalSemaphoreInfoCount = 1;
    submit.pSignalSemaphoreInfos = &signal_info;

    ROME_VK_CHECK(vkQueueSubmit2(context_.graphics_queue(), 1, &submit, frame.in_flight));

    const VkSwapchainKHR swapchain_handle = swapchain_.handle();
    VkPresentInfoKHR present{};
    present.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    present.waitSemaphoreCount = 1;
    present.pWaitSemaphores = &render_finished_[image_index];
    present.swapchainCount = 1;
    present.pSwapchains = &swapchain_handle;
    present.pImageIndices = &image_index;

    const VkResult presented = vkQueuePresentKHR(context_.graphics_queue(), &present);

    frame_index_ = (frame_index_ + 1) % kFramesInFlight;

    if (presented == VK_ERROR_OUT_OF_DATE_KHR || presented == VK_SUBOPTIMAL_KHR) {
        on_resize(window_extent);
        return false;
    }
    if (presented != VK_SUCCESS) {
        detail::throw_vk(presented, "vkQueuePresentKHR", __FILE__, __LINE__);
    }
    return true;
}

}  // namespace rome::gfx
