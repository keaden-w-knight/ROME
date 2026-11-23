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

/// Maps an SDL scancode to the framework's key name, or "" to ignore it.
std::string key_name(SDL_Scancode sc) {
    switch (sc) {
        case SDL_SCANCODE_ESCAPE:
            return "escape";
        case SDL_SCANCODE_SPACE:
            return "space";
        case SDL_SCANCODE_RETURN:
            return "enter";
        case SDL_SCANCODE_UP:
            return "w";
        case SDL_SCANCODE_DOWN:
            return "s";
        case SDL_SCANCODE_LEFT:
            return "a";
        case SDL_SCANCODE_RIGHT:
            return "d";
        default:
            break;
    }
    if (sc >= SDL_SCANCODE_A && sc <= SDL_SCANCODE_Z) {
        return std::string(1, static_cast<char>('a' + (sc - SDL_SCANCODE_A)));
    }
    return "";
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
      resized_(other.resized_),
      held_keys_(std::move(other.held_keys_)),
      pressed_keys_(std::move(other.pressed_keys_)) {}

Window& Window::operator=(Window&& other) noexcept {
    if (this != &other) {
        if (window_ != nullptr) {
            SDL_DestroyWindow(window_);
            --g_live_windows;
        }
        window_ = std::exchange(other.window_, nullptr);
        should_close_ = other.should_close_;
        resized_ = other.resized_;
        held_keys_ = std::move(other.held_keys_);
        pressed_keys_ = std::move(other.pressed_keys_);
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

            case SDL_EVENT_KEY_DOWN: {
                if (event.key.key == SDLK_ESCAPE) {
                    should_close_ = true;
                }
                const std::string name = key_name(event.key.scancode);
                if (!name.empty()) {
                    held_keys_.insert(name);
                    if (!event.key.repeat) {
                        pressed_keys_.push_back(name);
                    }
                }
                break;
            }

            case SDL_EVENT_KEY_UP: {
                const std::string name = key_name(event.key.scancode);
                if (!name.empty()) {
                    held_keys_.erase(name);
                }
                break;
            }

            default:
                break;
        }
    }
    return !should_close_;
}

std::vector<std::string> Window::keys_held() const {
    return std::vector<std::string>(held_keys_.begin(), held_keys_.end());
}

std::vector<std::string> Window::take_pressed() {
    std::vector<std::string> out = std::move(pressed_keys_);
    pressed_keys_.clear();
    return out;
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

void Window::set_title(const std::string& title) {
    if (window_ != nullptr) {
        SDL_SetWindowTitle(window_, title.c_str());
    }
}

}  // namespace rome
