// Value-semantics tests for the types that cross the Python boundary. These
// deliberately touch no Vulkan and open no window, so they run anywhere.

#include "rome/types.hpp"

#include "check.hpp"

int main() {
    // Extent2D
    CHECK(rome::Extent2D{}.is_empty());
    CHECK(rome::Extent2D{1920, 0}.is_empty());
    CHECK(rome::Extent2D{0, 1080}.is_empty());
    CHECK(!rome::Extent2D{1920, 1080}.is_empty());
    CHECK(rome::Extent2D{800, 600} == rome::Extent2D{800, 600});
    CHECK(rome::Extent2D{800, 600} != rome::Extent2D{600, 800});

    // Color defaults to opaque black.
    constexpr rome::Color kDefault{};
    CHECK(kDefault.r == 0.0F);
    CHECK(kDefault.g == 0.0F);
    CHECK(kDefault.b == 0.0F);
    CHECK(kDefault.a == 1.0F);

    CHECK(rome::Color{1, 0, 0, 1} == rome::Color{1, 0, 0, 1});
    CHECK(rome::Color{1, 0, 0, 1} != rome::Color{0, 1, 0, 1});

    return rome::test::summary();
}
