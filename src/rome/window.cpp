#include "rome/window.hpp"

#include <SDL3/SDL.h>

#include <string>
#include <utility>

#include "rome/error.hpp"

namespace rome {
namespace {

// SDL is a process-global singleton, so its lifetime is refcounted against the
// number of live windows rather than tied to any one of them.
int g_live_windows = 0;

[[noreturn]] void throw_sdl(const char* what) {
    throw Error(std::string{what} + ": " + SDL_GetError());
}

}  // namespace

Window::Window(const WindowConfig& config) {
    if (g_live_windows == 0 && !SDL_Init(SDL_INIT_VIDEO)) {
        throw_sdl("SDL_Init failed");
    }

    SDL_WindowFlags flags = SDL_WINDOW_VULKAN | SDL_WINDOW_HIGH_PIXEL_DENSITY;
    if (config.resizable) {
        flags |= SDL_WINDOW_RESIZABLE;
    }

    window_ = SDL_CreateWindow(config.title.c_str(), config.width, config.height, flags);
    if (window_ == nullptr) {
        if (g_live_windows == 0) {
            SDL_Quit();
        }
        throw_sdl("SDL_CreateWindow failed");
    }

    ++g_live_windows;
}

Window::~Window() {
    if (window_ == nullptr) {
        return;  // moved-from
    }
    SDL_DestroyWindow(window_);
    if (--g_live_windows == 0) {
        SDL_Quit();
    }
}

Window::Window(Window&& other) noexcept
    : window_(std::exchange(other.window_, nullptr)),
      should_close_(other.should_close_),
      resized_(other.resized_) {}

Window& Window::operator=(Window&& other) noexcept {
    if (this != &other) {
        if (window_ != nullptr) {
            SDL_DestroyWindow(window_);
            --g_live_windows;
        }
        window_ = std::exchange(other.window_, nullptr);
        should_close_ = other.should_close_;
        resized_ = other.resized_;
    }
    return *this;
}

bool Window::pump_events() {
    SDL_Event event;
    while (SDL_PollEvent(&event)) {
        switch (event.type) {
            case SDL_EVENT_QUIT:
                should_close_ = true;
                break;

            case SDL_EVENT_WINDOW_CLOSE_REQUESTED:
                if (event.window.windowID == SDL_GetWindowID(window_)) {
                    should_close_ = true;
                }
                break;

            // The pixel size is what the swapchain is sized against; on a
            // HiDPI display it moves independently of the window size.
            case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
                if (event.window.windowID == SDL_GetWindowID(window_)) {
                    resized_ = true;
                }
                break;

            case SDL_EVENT_KEY_DOWN:
                if (event.key.key == SDLK_ESCAPE) {
                    should_close_ = true;
                }
                break;

            default:
                break;
        }
    }
    return !should_close_;
}

Extent2D Window::framebuffer_size() const {
    int width = 0;
    int height = 0;
    SDL_GetWindowSizeInPixels(window_, &width, &height);
    return Extent2D{static_cast<std::uint32_t>(width), static_cast<std::uint32_t>(height)};
}

bool Window::is_minimised() const {
    return (SDL_GetWindowFlags(window_) & SDL_WINDOW_MINIMIZED) != 0;
}

bool Window::consume_resize_flag() {
    return std::exchange(resized_, false);
}

}  // namespace rome
