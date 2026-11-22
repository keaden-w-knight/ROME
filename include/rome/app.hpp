#pragma once

#include <memory>
#include <string>

#include "rome/types.hpp"
#include "rome/window.hpp"

namespace rome {

namespace gfx {
class Context;
class Swapchain;
class Renderer;
}  // namespace gfx

struct AppConfig {
    WindowConfig window{};
    bool vsync = true;
    /// Vulkan validation layers. Costly, so default to off and let debug
    /// builds or the caller turn them on deliberately.
    bool validation = false;
    Color clear_color{0.05F, 0.05F, 0.08F, 1.0F};
};

/// Window, Vulkan device and render loop behind one handle.
///
/// The loop is exposed two ways: run() drives it to completion, and tick()
/// steps it once so a caller (notably Python) can own the loop instead.
class App {
public:
    explicit App(const AppConfig& config = {});
    ~App();

    App(const App&) = delete;
    App& operator=(const App&) = delete;
    App(App&&) = delete;
    App& operator=(App&&) = delete;

    /// Processes events and draws one frame. Returns false once the window
    /// has been closed, which makes it directly usable as a while condition.
    bool tick();

    /// Runs tick() until the window closes.
    void run();

    void close() {
        window_.request_close();
    }

    [[nodiscard]] bool is_running() const {
        return !window_.should_close();
    }

    [[nodiscard]] Extent2D size() const {
        return window_.framebuffer_size();
    }

    [[nodiscard]] const std::string& gpu_name() const {
        return gpu_name_;
    }

    void set_clear_color(Color color) {
        clear_color_ = color;
    }

    [[nodiscard]] Color clear_color() const {
        return clear_color_;
    }

    /// Seconds since the App was constructed.
    [[nodiscard]] double elapsed() const;

    /// Seconds between the two most recent ticks.
    [[nodiscard]] double delta_time() const {
        return delta_time_;
    }

    [[nodiscard]] double fps() const;

    [[nodiscard]] std::uint64_t frame_count() const {
        return frame_count_;
    }

private:
    void update_timing();

    Window window_;
    // Held by pointer so the Vulkan headers stay out of this one.
    std::unique_ptr<gfx::Context> context_;
    std::unique_ptr<gfx::Swapchain> swapchain_;
    std::unique_ptr<gfx::Renderer> renderer_;

    std::string gpu_name_;
    Color clear_color_{};
    std::uint64_t start_ticks_ = 0;
    std::uint64_t last_ticks_ = 0;
    double delta_time_ = 0.0;
    std::uint64_t frame_count_ = 0;
};

}  // namespace rome
