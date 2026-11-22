#include "rome/app.hpp"

#include <SDL3/SDL.h>

#include "rome/gfx/context.hpp"
#include "rome/gfx/renderer.hpp"
#include "rome/gfx/swapchain.hpp"

namespace rome {
namespace {

/// Milliseconds to idle for while minimised, rather than spinning on a window
/// that cannot be drawn to.
constexpr std::uint32_t kMinimisedSleepMs = 10;

double seconds_since(std::uint64_t start) {
    const double frequency = static_cast<double>(SDL_GetPerformanceFrequency());
    return static_cast<double>(SDL_GetPerformanceCounter() - start) / frequency;
}

}  // namespace

App::App(const AppConfig& config) : window_(config.window), clear_color_(config.clear_color) {
    context_ = std::make_unique<gfx::Context>(window_, config.validation);
    gpu_name_ = context_->device_name();
    swapchain_ =
        std::make_unique<gfx::Swapchain>(*context_, window_.framebuffer_size(), config.vsync);
    renderer_ = std::make_unique<gfx::Renderer>(*context_, *swapchain_);

    start_ticks_ = SDL_GetPerformanceCounter();
    last_ticks_ = start_ticks_;
}

App::~App() {
    // Destruction order matters: the renderer holds command buffers that may
    // still reference swapchain images, and both outlive nothing else.
    if (context_) {
        context_->wait_idle();
    }
    renderer_.reset();
    swapchain_.reset();
    context_.reset();
}

bool App::tick() {
    if (!window_.pump_events()) {
        return false;
    }

    update_timing();

    if (window_.is_minimised()) {
        SDL_Delay(kMinimisedSleepMs);
        return true;
    }

    const Extent2D size = window_.framebuffer_size();
    if (size.is_empty()) {
        SDL_Delay(kMinimisedSleepMs);
        return true;
    }

    // Rebuild eagerly on a size change rather than waiting for the driver to
    // report the swapchain out of date, which some drivers never do.
    if (window_.consume_resize_flag()) {
        renderer_->on_resize(size);
    }

    renderer_->draw(clear_color_, size);
    ++frame_count_;
    return true;
}

void App::run() {
    while (tick()) {
        // tick() owns the loop body; nothing to add here.
    }
}

std::uint64_t App::upload_mesh(const std::vector<float>& positions,
                               const std::vector<float>& normals,
                               const std::vector<std::uint32_t>& indices) {
    return renderer_->upload_mesh(positions, normals, indices);
}

bool App::render_scene(const std::vector<MeshInstance>& instances, const CameraParams& camera) {
    if (!window_.pump_events()) {
        return false;
    }

    update_timing();

    if (window_.is_minimised()) {
        SDL_Delay(kMinimisedSleepMs);
        return true;
    }

    const Extent2D size = window_.framebuffer_size();
    if (size.is_empty()) {
        SDL_Delay(kMinimisedSleepMs);
        return true;
    }

    if (window_.consume_resize_flag()) {
        renderer_->on_resize(size);
    }

    renderer_->draw_scene(clear_color_, size, camera, instances);
    ++frame_count_;
    return true;
}

void App::update_timing() {
    const std::uint64_t now = SDL_GetPerformanceCounter();
    const double frequency = static_cast<double>(SDL_GetPerformanceFrequency());
    delta_time_ = static_cast<double>(now - last_ticks_) / frequency;
    last_ticks_ = now;
}

double App::elapsed() const {
    return seconds_since(start_ticks_);
}

double App::fps() const {
    return delta_time_ > 0.0 ? 1.0 / delta_time_ : 0.0;
}

}  // namespace rome
