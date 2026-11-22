#include "rome/gfx/renderer.hpp"

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <vector>

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
constexpr std::uint32_t kMeshVertSpv[] =
#include "mesh.vert.h"
    ;
constexpr std::uint32_t kMeshFragSpv[] =
#include "mesh.frag.h"
    ;

constexpr std::uint64_t kNoTimeout = std::numeric_limits<std::uint64_t>::max();

// Matches the push_constant block in mesh.vert. 144 bytes; within the 256-byte
// limit of the target GPUs (the Vulkan-guaranteed minimum is 128 — a GPU capped
// there would need this moved into a UBO, which the lighting phase will add).
struct MeshPush {
    glm::mat4 mvp;
    glm::mat4 model;
    glm::vec4 color;
};

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
/// this runs a few times per frame on an attachment, not in a hot loop.
void transition_image(VkCommandBuffer cmd, VkImage image, VkImageLayout from, VkImageLayout to,
                      VkImageAspectFlags aspect = VK_IMAGE_ASPECT_COLOR_BIT) {
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
    barrier.subresourceRange.aspectMask = aspect;
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
    create_depth_resources(swapchain_.extent());
    create_pipeline();
    create_mesh_pipeline();
}

Renderer::~Renderer() {
    context_.wait_idle();

    const VkDevice device = context_.device();

    destroy_meshes();
    destroy_depth_resources();

    if (mesh_pipeline_ != VK_NULL_HANDLE) {
        vkDestroyPipeline(device, mesh_pipeline_, nullptr);
    }
    if (mesh_layout_ != VK_NULL_HANDLE) {
        vkDestroyPipelineLayout(device, mesh_layout_, nullptr);
    }
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

void Renderer::create_depth_resources(Extent2D extent) {
    destroy_depth_resources();
    if (extent.is_empty()) {
        return;
    }

    VkImageCreateInfo image_info{};
    image_info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    image_info.imageType = VK_IMAGE_TYPE_2D;
    image_info.format = depth_format_;
    image_info.extent = VkExtent3D{extent.width, extent.height, 1};
    image_info.mipLevels = 1;
    image_info.arrayLayers = 1;
    image_info.samples = VK_SAMPLE_COUNT_1_BIT;
    image_info.tiling = VK_IMAGE_TILING_OPTIMAL;
    image_info.usage = VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT;
    image_info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    VmaAllocationCreateInfo alloc_info{};
    alloc_info.usage = VMA_MEMORY_USAGE_AUTO;
    alloc_info.flags = VMA_ALLOCATION_CREATE_DEDICATED_MEMORY_BIT;
    ROME_VK_CHECK(vmaCreateImage(context_.allocator(), &image_info, &alloc_info, &depth_image_,
                                 &depth_alloc_, nullptr));

    VkImageViewCreateInfo view_info{};
    view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    view_info.image = depth_image_;
    view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view_info.format = depth_format_;
    view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
    view_info.subresourceRange.levelCount = 1;
    view_info.subresourceRange.layerCount = 1;
    ROME_VK_CHECK(vkCreateImageView(context_.device(), &view_info, nullptr, &depth_view_));
}

void Renderer::destroy_depth_resources() {
    const VkDevice device = context_.device();
    if (depth_view_ != VK_NULL_HANDLE) {
        vkDestroyImageView(device, depth_view_, nullptr);
        depth_view_ = VK_NULL_HANDLE;
    }
    if (depth_image_ != VK_NULL_HANDLE) {
        vmaDestroyImage(context_.allocator(), depth_image_, depth_alloc_);
        depth_image_ = VK_NULL_HANDLE;
        depth_alloc_ = VK_NULL_HANDLE;
    }
}

void Renderer::destroy_meshes() {
    const VmaAllocator allocator = context_.allocator();
    for (auto& [id, mesh] : meshes_) {
        if (mesh.vertex_buffer != VK_NULL_HANDLE) {
            vmaDestroyBuffer(allocator, mesh.vertex_buffer, mesh.vertex_alloc);
        }
        if (mesh.index_buffer != VK_NULL_HANDLE) {
            vmaDestroyBuffer(allocator, mesh.index_buffer, mesh.index_alloc);
        }
    }
    meshes_.clear();
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

    vkDestroyShaderModule(device, vert, nullptr);
    vkDestroyShaderModule(device, frag, nullptr);

    if (result != VK_SUCCESS) {
        detail::throw_vk(result, "vkCreateGraphicsPipelines", __FILE__, __LINE__);
    }
}

void Renderer::create_mesh_pipeline() {
    const VkDevice device = context_.device();

    VkPushConstantRange push_range{};
    push_range.stageFlags = VK_SHADER_STAGE_VERTEX_BIT;
    push_range.offset = 0;
    push_range.size = sizeof(MeshPush);

    VkPipelineLayoutCreateInfo layout_info{};
    layout_info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    layout_info.pushConstantRangeCount = 1;
    layout_info.pPushConstantRanges = &push_range;
    ROME_VK_CHECK(vkCreatePipelineLayout(device, &layout_info, nullptr, &mesh_layout_));

    const VkShaderModule vert = create_shader_module(device, kMeshVertSpv, sizeof(kMeshVertSpv));
    const VkShaderModule frag = create_shader_module(device, kMeshFragSpv, sizeof(kMeshFragSpv));

    std::array<VkPipelineShaderStageCreateInfo, 2> stages{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vert;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = frag;
    stages[1].pName = "main";

    // Interleaved vertex: vec3 position, vec3 normal.
    VkVertexInputBindingDescription binding{};
    binding.binding = 0;
    binding.stride = 6 * sizeof(float);
    binding.inputRate = VK_VERTEX_INPUT_RATE_VERTEX;

    std::array<VkVertexInputAttributeDescription, 2> attributes{};
    attributes[0].location = 0;
    attributes[0].binding = 0;
    attributes[0].format = VK_FORMAT_R32G32B32_SFLOAT;
    attributes[0].offset = 0;
    attributes[1].location = 1;
    attributes[1].binding = 0;
    attributes[1].format = VK_FORMAT_R32G32B32_SFLOAT;
    attributes[1].offset = 3 * sizeof(float);

    VkPipelineVertexInputStateCreateInfo vertex_input{};
    vertex_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vertex_input.vertexBindingDescriptionCount = 1;
    vertex_input.pVertexBindingDescriptions = &binding;
    vertex_input.vertexAttributeDescriptionCount = static_cast<std::uint32_t>(attributes.size());
    vertex_input.pVertexAttributeDescriptions = attributes.data();

    VkPipelineInputAssemblyStateCreateInfo input_assembly{};
    input_assembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    input_assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    VkPipelineViewportStateCreateInfo viewport_state{};
    viewport_state.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewport_state.viewportCount = 1;
    viewport_state.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    // Cull nothing for Phase 1: correct regardless of winding, and the depth
    // test resolves what shows. Back-face culling is a later optimisation.
    rasterizer.cullMode = VK_CULL_MODE_NONE;
    rasterizer.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rasterizer.lineWidth = 1.0F;

    VkPipelineMultisampleStateCreateInfo multisample{};
    multisample.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    multisample.minSampleShading = 1.0F;

    VkPipelineDepthStencilStateCreateInfo depth_stencil{};
    depth_stencil.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    depth_stencil.depthTestEnable = VK_TRUE;
    depth_stencil.depthWriteEnable = VK_TRUE;
    depth_stencil.depthCompareOp = VK_COMPARE_OP_LESS;
    depth_stencil.minDepthBounds = 0.0F;
    depth_stencil.maxDepthBounds = 1.0F;

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

    const VkFormat color_format = swapchain_.format();
    VkPipelineRenderingCreateInfo rendering_info{};
    rendering_info.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO;
    rendering_info.colorAttachmentCount = 1;
    rendering_info.pColorAttachmentFormats = &color_format;
    rendering_info.depthAttachmentFormat = depth_format_;

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
    pipeline_info.pDepthStencilState = &depth_stencil;
    pipeline_info.pColorBlendState = &color_blend;
    pipeline_info.pDynamicState = &dynamic_state;
    pipeline_info.layout = mesh_layout_;
    pipeline_info.renderPass = VK_NULL_HANDLE;

    const VkResult result = vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1, &pipeline_info,
                                                      nullptr, &mesh_pipeline_);

    vkDestroyShaderModule(device, vert, nullptr);
    vkDestroyShaderModule(device, frag, nullptr);

    if (result != VK_SUCCESS) {
        detail::throw_vk(result, "vkCreateGraphicsPipelines(mesh)", __FILE__, __LINE__);
    }
}

std::uint64_t Renderer::upload_mesh(const std::vector<float>& positions,
                                    const std::vector<float>& normals,
                                    const std::vector<std::uint32_t>& indices) {
    const std::size_t vertex_count = positions.size() / 3;
    if (vertex_count == 0 || normals.size() != positions.size() || indices.empty()) {
        throw Error{"upload_mesh: need matching non-empty positions/normals and indices"};
    }

    // Interleave into [px py pz nx ny nz] per vertex.
    std::vector<float> interleaved(vertex_count * 6);
    for (std::size_t i = 0; i < vertex_count; ++i) {
        interleaved[i * 6 + 0] = positions[i * 3 + 0];
        interleaved[i * 6 + 1] = positions[i * 3 + 1];
        interleaved[i * 6 + 2] = positions[i * 3 + 2];
        interleaved[i * 6 + 3] = normals[i * 3 + 0];
        interleaved[i * 6 + 4] = normals[i * 3 + 1];
        interleaved[i * 6 + 5] = normals[i * 3 + 2];
    }

    const VmaAllocator allocator = context_.allocator();
    const VkDeviceSize vertex_bytes = interleaved.size() * sizeof(float);
    const VkDeviceSize index_bytes = indices.size() * sizeof(std::uint32_t);

    GpuMesh mesh{};
    mesh.index_count = static_cast<std::uint32_t>(indices.size());

    auto make_device_buffer = [&](VkDeviceSize size, VkBufferUsageFlags usage, VkBuffer& buffer,
                                  VmaAllocation& alloc) {
        VkBufferCreateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        info.size = size;
        info.usage = usage | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        VmaAllocationCreateInfo alloc_info{};
        alloc_info.usage = VMA_MEMORY_USAGE_AUTO;
        ROME_VK_CHECK(vmaCreateBuffer(allocator, &info, &alloc_info, &buffer, &alloc, nullptr));
    };

    make_device_buffer(vertex_bytes, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT, mesh.vertex_buffer,
                       mesh.vertex_alloc);
    make_device_buffer(index_bytes, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, mesh.index_buffer,
                       mesh.index_alloc);

    auto upload = [&](const void* data, VkDeviceSize size, VkBuffer dst) {
        VkBufferCreateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        info.size = size;
        info.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
        info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        VmaAllocationCreateInfo alloc_info{};
        alloc_info.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_info.flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT |
                           VMA_ALLOCATION_CREATE_MAPPED_BIT;
        VkBuffer staging = VK_NULL_HANDLE;
        VmaAllocation staging_alloc = VK_NULL_HANDLE;
        VmaAllocationInfo staging_info{};
        ROME_VK_CHECK(
            vmaCreateBuffer(allocator, &info, &alloc_info, &staging, &staging_alloc, &staging_info));
        std::memcpy(staging_info.pMappedData, data, static_cast<std::size_t>(size));
        context_.immediate_submit([&](VkCommandBuffer cmd) {
            VkBufferCopy copy{};
            copy.size = size;
            vkCmdCopyBuffer(cmd, staging, dst, 1, &copy);
        });
        vmaDestroyBuffer(allocator, staging, staging_alloc);
    };

    upload(interleaved.data(), vertex_bytes, mesh.vertex_buffer);
    upload(indices.data(), index_bytes, mesh.index_buffer);

    const std::uint64_t id = next_mesh_id_++;
    meshes_.emplace(id, mesh);
    return id;
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

void Renderer::record_scene(VkCommandBuffer cmd, std::uint32_t image_index, Color clear_color,
                            const CameraParams& camera,
                            const std::vector<MeshInstance>& instances) const {
    VkCommandBufferBeginInfo begin_info{};
    begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin_info.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    ROME_VK_CHECK(vkBeginCommandBuffer(cmd, &begin_info));

    const VkImage image = swapchain_.images()[image_index];
    const Extent2D extent = swapchain_.extent();

    transition_image(cmd, image, VK_IMAGE_LAYOUT_UNDEFINED,
                     VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
    transition_image(cmd, depth_image_, VK_IMAGE_LAYOUT_UNDEFINED,
                     VK_IMAGE_LAYOUT_DEPTH_ATTACHMENT_OPTIMAL, VK_IMAGE_ASPECT_DEPTH_BIT);

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

    VkRenderingAttachmentInfo depth_attachment{};
    depth_attachment.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;
    depth_attachment.imageView = depth_view_;
    depth_attachment.imageLayout = VK_IMAGE_LAYOUT_DEPTH_ATTACHMENT_OPTIMAL;
    depth_attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    depth_attachment.storeOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    depth_attachment.clearValue.depthStencil.depth = 1.0F;

    VkRenderingInfo rendering{};
    rendering.sType = VK_STRUCTURE_TYPE_RENDERING_INFO;
    rendering.renderArea.extent = VkExtent2D{extent.width, extent.height};
    rendering.layerCount = 1;
    rendering.colorAttachmentCount = 1;
    rendering.pColorAttachments = &color_attachment;
    rendering.pDepthAttachment = &depth_attachment;

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

    record_mesh_draws(cmd, extent.width, extent.height, camera, instances);

    vkCmdEndRendering(cmd);

    transition_image(cmd, image, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                     VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);

    ROME_VK_CHECK(vkEndCommandBuffer(cmd));
}

void Renderer::record_mesh_draws(VkCommandBuffer cmd, std::uint32_t width, std::uint32_t height,
                                 const CameraParams& camera,
                                 const std::vector<MeshInstance>& instances) const {
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, mesh_pipeline_);

    const glm::vec3 eye{camera.position[0], camera.position[1], camera.position[2]};
    const glm::vec3 center{camera.target[0], camera.target[1], camera.target[2]};
    const glm::vec3 up{camera.up[0], camera.up[1], camera.up[2]};
    const float aspect =
        height != 0 ? static_cast<float>(width) / static_cast<float>(height) : 1.0F;
    const glm::mat4 view = glm::lookAt(eye, center, up);
    glm::mat4 proj = glm::perspective(glm::radians(camera.fov_deg), aspect, 0.1F, 100.0F);
    proj[1][1] *= -1.0F;  // Vulkan clip space has +Y down relative to GLM's default
    const glm::mat4 view_proj = proj * view;

    for (const MeshInstance& inst : instances) {
        const auto it = meshes_.find(inst.mesh);
        if (it == meshes_.end()) {
            continue;
        }

        // translate * Rz * Rx * Ry * scale, matching the framework's transform.
        glm::mat4 model =
            glm::translate(glm::mat4(1.0F),
                           glm::vec3(inst.position[0], inst.position[1], inst.position[2]));
        model = model * glm::rotate(glm::mat4(1.0F), inst.rotation[2], glm::vec3(0, 0, 1));
        model = model * glm::rotate(glm::mat4(1.0F), inst.rotation[0], glm::vec3(1, 0, 0));
        model = model * glm::rotate(glm::mat4(1.0F), inst.rotation[1], glm::vec3(0, 1, 0));
        model = model * glm::scale(glm::mat4(1.0F), glm::vec3(inst.scale));

        MeshPush push{};
        push.mvp = view_proj * model;
        push.model = model;
        push.color = glm::vec4(inst.color[0], inst.color[1], inst.color[2], 1.0F);
        vkCmdPushConstants(cmd, mesh_layout_, VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(MeshPush),
                           &push);

        const VkBuffer vertex_buffer = it->second.vertex_buffer;
        const VkDeviceSize offset = 0;
        vkCmdBindVertexBuffers(cmd, 0, 1, &vertex_buffer, &offset);
        vkCmdBindIndexBuffer(cmd, it->second.index_buffer, 0, VK_INDEX_TYPE_UINT32);
        vkCmdDrawIndexed(cmd, it->second.index_count, 1, 0, 0, 0);
    }
}

std::vector<std::uint8_t> Renderer::render_offscreen(Color clear_color, std::uint32_t width,
                                                     std::uint32_t height,
                                                     const CameraParams& camera,
                                                     const std::vector<MeshInstance>& instances) {
    const VkDevice device = context_.device();
    const VmaAllocator allocator = context_.allocator();
    const VkFormat color_format = swapchain_.format();

    // Off-screen colour target (also a transfer source, for readback).
    VkImage color_image = VK_NULL_HANDLE;
    VmaAllocation color_alloc = VK_NULL_HANDLE;
    VkImageView color_view = VK_NULL_HANDLE;
    {
        VkImageCreateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        info.imageType = VK_IMAGE_TYPE_2D;
        info.format = color_format;
        info.extent = VkExtent3D{width, height, 1};
        info.mipLevels = 1;
        info.arrayLayers = 1;
        info.samples = VK_SAMPLE_COUNT_1_BIT;
        info.tiling = VK_IMAGE_TILING_OPTIMAL;
        info.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
        info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        VmaAllocationCreateInfo alloc{};
        alloc.usage = VMA_MEMORY_USAGE_AUTO;
        alloc.flags = VMA_ALLOCATION_CREATE_DEDICATED_MEMORY_BIT;
        ROME_VK_CHECK(vmaCreateImage(allocator, &info, &alloc, &color_image, &color_alloc, nullptr));

        VkImageViewCreateInfo view_info{};
        view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
        view_info.image = color_image;
        view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
        view_info.format = color_format;
        view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        view_info.subresourceRange.levelCount = 1;
        view_info.subresourceRange.layerCount = 1;
        ROME_VK_CHECK(vkCreateImageView(device, &view_info, nullptr, &color_view));
    }

    // Off-screen depth target.
    VkImage depth_image = VK_NULL_HANDLE;
    VmaAllocation depth_alloc = VK_NULL_HANDLE;
    VkImageView depth_view = VK_NULL_HANDLE;
    {
        VkImageCreateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        info.imageType = VK_IMAGE_TYPE_2D;
        info.format = depth_format_;
        info.extent = VkExtent3D{width, height, 1};
        info.mipLevels = 1;
        info.arrayLayers = 1;
        info.samples = VK_SAMPLE_COUNT_1_BIT;
        info.tiling = VK_IMAGE_TILING_OPTIMAL;
        info.usage = VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT;
        info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        VmaAllocationCreateInfo alloc{};
        alloc.usage = VMA_MEMORY_USAGE_AUTO;
        alloc.flags = VMA_ALLOCATION_CREATE_DEDICATED_MEMORY_BIT;
        ROME_VK_CHECK(vmaCreateImage(allocator, &info, &alloc, &depth_image, &depth_alloc, nullptr));

        VkImageViewCreateInfo view_info{};
        view_info.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
        view_info.image = depth_image;
        view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
        view_info.format = depth_format_;
        view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
        view_info.subresourceRange.levelCount = 1;
        view_info.subresourceRange.layerCount = 1;
        ROME_VK_CHECK(vkCreateImageView(device, &view_info, nullptr, &depth_view));
    }

    // Host-visible buffer to copy the rendered image into.
    const VkDeviceSize byte_count = static_cast<VkDeviceSize>(width) * height * 4;
    VkBuffer readback = VK_NULL_HANDLE;
    VmaAllocation readback_alloc = VK_NULL_HANDLE;
    VmaAllocationInfo readback_info{};
    {
        VkBufferCreateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        info.size = byte_count;
        info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        VmaAllocationCreateInfo alloc{};
        alloc.usage = VMA_MEMORY_USAGE_AUTO;
        alloc.flags =
            VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT;
        ROME_VK_CHECK(
            vmaCreateBuffer(allocator, &info, &alloc, &readback, &readback_alloc, &readback_info));
    }

    context_.immediate_submit([&](VkCommandBuffer cmd) {
        transition_image(cmd, color_image, VK_IMAGE_LAYOUT_UNDEFINED,
                         VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
        transition_image(cmd, depth_image, VK_IMAGE_LAYOUT_UNDEFINED,
                         VK_IMAGE_LAYOUT_DEPTH_ATTACHMENT_OPTIMAL, VK_IMAGE_ASPECT_DEPTH_BIT);

        VkRenderingAttachmentInfo color_attachment{};
        color_attachment.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;
        color_attachment.imageView = color_view;
        color_attachment.imageLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
        color_attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
        color_attachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
        color_attachment.clearValue.color.float32[0] = clear_color.r;
        color_attachment.clearValue.color.float32[1] = clear_color.g;
        color_attachment.clearValue.color.float32[2] = clear_color.b;
        color_attachment.clearValue.color.float32[3] = clear_color.a;

        VkRenderingAttachmentInfo depth_attachment{};
        depth_attachment.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;
        depth_attachment.imageView = depth_view;
        depth_attachment.imageLayout = VK_IMAGE_LAYOUT_DEPTH_ATTACHMENT_OPTIMAL;
        depth_attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
        depth_attachment.storeOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
        depth_attachment.clearValue.depthStencil.depth = 1.0F;

        VkRenderingInfo rendering{};
        rendering.sType = VK_STRUCTURE_TYPE_RENDERING_INFO;
        rendering.renderArea.extent = VkExtent2D{width, height};
        rendering.layerCount = 1;
        rendering.colorAttachmentCount = 1;
        rendering.pColorAttachments = &color_attachment;
        rendering.pDepthAttachment = &depth_attachment;

        vkCmdBeginRendering(cmd, &rendering);

        VkViewport viewport{};
        viewport.width = static_cast<float>(width);
        viewport.height = static_cast<float>(height);
        viewport.minDepth = 0.0F;
        viewport.maxDepth = 1.0F;
        vkCmdSetViewport(cmd, 0, 1, &viewport);

        VkRect2D scissor{};
        scissor.extent = VkExtent2D{width, height};
        vkCmdSetScissor(cmd, 0, 1, &scissor);

        record_mesh_draws(cmd, width, height, camera, instances);

        vkCmdEndRendering(cmd);

        transition_image(cmd, color_image, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                         VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);

        VkBufferImageCopy copy{};
        copy.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        copy.imageSubresource.layerCount = 1;
        copy.imageExtent = VkExtent3D{width, height, 1};
        vkCmdCopyImageToBuffer(cmd, color_image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, readback, 1,
                               &copy);
    });

    vmaInvalidateAllocation(allocator, readback_alloc, 0, byte_count);
    std::vector<std::uint8_t> pixels(static_cast<std::size_t>(byte_count));
    std::memcpy(pixels.data(), readback_info.pMappedData, pixels.size());

    // Swapchain formats are usually BGRA; hand Python straight RGBA.
    if (color_format == VK_FORMAT_B8G8R8A8_UNORM || color_format == VK_FORMAT_B8G8R8A8_SRGB) {
        for (std::size_t i = 0; i + 2 < pixels.size(); i += 4) {
            const std::uint8_t tmp = pixels[i];
            pixels[i] = pixels[i + 2];
            pixels[i + 2] = tmp;
        }
    }

    vmaDestroyBuffer(allocator, readback, readback_alloc);
    vkDestroyImageView(device, depth_view, nullptr);
    vmaDestroyImage(allocator, depth_image, depth_alloc);
    vkDestroyImageView(device, color_view, nullptr);
    vmaDestroyImage(allocator, color_image, color_alloc);

    return pixels;
}

void Renderer::on_resize(Extent2D window_extent) {
    if (window_extent.is_empty()) {
        return;  // minimised: nothing valid to size a swapchain against
    }
    swapchain_.recreate(window_extent);
    create_depth_resources(swapchain_.extent());

    // The image count can change across a rebuild, so the per-image
    // presentation semaphores are rebuilt alongside it.
    destroy_present_semaphores();
    create_present_semaphores();
}

bool Renderer::submit_and_present(
    Extent2D window_extent, const std::function<void(VkCommandBuffer, std::uint32_t)>& record_fn) {
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

    record_fn(frame.command_buffer, image_index);

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

bool Renderer::draw(Color clear_color, Extent2D window_extent) {
    return submit_and_present(window_extent, [&](VkCommandBuffer cmd, std::uint32_t image_index) {
        record(cmd, image_index, clear_color);
    });
}

bool Renderer::draw_scene(Color clear_color, Extent2D window_extent, const CameraParams& camera,
                          const std::vector<MeshInstance>& instances) {
    return submit_and_present(window_extent, [&](VkCommandBuffer cmd, std::uint32_t image_index) {
        record_scene(cmd, image_index, clear_color, camera, instances);
    });
}

}  // namespace rome::gfx
