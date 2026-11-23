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

/// One light for a frame: directional, point, or spot. Linear RGB in 0..1.
struct Light {
    int type = 0;  // 0 = directional, 1 = point, 2 = spot
    float position[3]{0.0F, 5.0F, 0.0F};     // point / spot
    float direction[3]{0.0F, -1.0F, 0.0F};   // directional / spot axis
    float color[3]{1.0F, 1.0F, 1.0F};
    float intensity = 1.0F;
    float range = 20.0F;      // point / spot distance falloff
    float inner_cos = 0.94F;  // spot: cos(inner cone angle)
    float outer_cos = 0.87F;  // spot: cos(outer cone angle)
};

/// Scene-wide shading params (ambient fill + the material highlight), not
/// per-light.
struct ShadingParams {
    float ambient = 0.12F;    // constant fill so unlit faces aren't black
    float specular = 0.4F;    // Blinn-Phong highlight strength
    float shininess = 32.0F;  // highlight tightness
};

/// A free look-at camera for a frame. Plain data, so the public headers stay
/// free of GLM; the matrices are built in the renderer.
struct CameraParams {
    float position[3]{0.0F, 0.0F, -5.0F};
    float target[3]{0.0F, 0.0F, 0.0F};
    float up[3]{0.0F, 1.0F, 0.0F};
    float fov_deg = 50.0F;
};

/// One placed mesh for a frame: a mesh handle (from App::upload_mesh) plus its
/// transform and base colour. Rotation is Euler radians, applied Y -> X -> Z;
/// scale is uniform; colour is linear RGB in 0..1.
struct MeshInstance {
    std::uint64_t mesh = 0;
    float position[3]{0.0F, 0.0F, 0.0F};
    float rotation[3]{0.0F, 0.0F, 0.0F};
    float scale = 1.0F;
    float color[3]{0.62F, 0.68F, 0.82F};
};

}  // namespace rome
