#pragma once

#include <vulkan/vulkan.h>

#include <string>
#include <string_view>

#include "rome/error.hpp"

namespace rome::gfx::detail {

/// Human-readable name for the VkResult values this project can actually hit.
[[nodiscard]] std::string_view result_name(VkResult result);

[[noreturn]] void throw_vk(VkResult result, std::string_view expression, std::string_view file,
                           int line);

}  // namespace rome::gfx::detail

/// Throws rome::Error unless the wrapped call returns VK_SUCCESS.
/// Note this rejects VK_SUBOPTIMAL_KHR too, so it must not wrap the acquire
/// and present calls, which handle non-success codes themselves.
#define ROME_VK_CHECK(expr)                                                            \
    do {                                                                               \
        const VkResult rome_vk_result_ = (expr);                                       \
        if (rome_vk_result_ != VK_SUCCESS) {                                           \
            ::rome::gfx::detail::throw_vk(rome_vk_result_, #expr, __FILE__, __LINE__); \
        }                                                                              \
    } while (false)
