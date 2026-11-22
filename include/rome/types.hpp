#pragma once

#include <cstdint>

namespace rome {

struct Extent2D {
    std::uint32_t width = 0;
    std::uint32_t height = 0;

    [[nodiscard]] bool is_empty() const {
        return width == 0 || height == 0;
    }

    friend bool operator==(const Extent2D&, const Extent2D&) = default;
};

/// Linear, non-premultiplied RGBA in the 0..1 range.
struct Color {
    float r = 0.0F;
    float g = 0.0F;
    float b = 0.0F;
    float a = 1.0F;

    friend bool operator==(const Color&, const Color&) = default;
};

}  // namespace rome
