#pragma once

#include <memory>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#include "rome/types.hpp"

// Kept out of the public interface so consumers do not need SDL headers.
struct SDL_Window;

namespace rome {

struct WindowConfig {
    int width = 1280;
    int height = 720;
    std::string title = "ROME";
    bool resizable = true;
};

/// An SDL3 window plus the slice of event state the render loop cares about.
///
/// SDL is initialised on first construction and shut down when the last Window
/// is destroyed, so callers never manage SDL's lifetime themselves.
class Window {
public:
    explicit Window(const WindowConfig& config);
    ~Window();

    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;
    Window(Window&&) noexcept;
    Window& operator=(Window&&) noexcept;

    /// Drains the event queue. Returns false once the window has been closed.
    bool pump_events();

    /// Size of the drawable area in pixels, which is not the same as the
    /// window size on a HiDPI display.
    [[nodiscard]] Extent2D framebuffer_size() const;

    [[nodiscard]] bool is_minimised() const;

    [[nodiscard]] bool should_close() const {
        return should_close_;
    }

    void request_close() {
        should_close_ = true;
    }

    /// Set the window's title bar text (e.g. to show an FPS readout).
    void set_title(const std::string& title);

    /// True for exactly one pump_events() call after the size changed.
    [[nodiscard]] bool consume_resize_flag();

    /// Keys currently held down (lowercase letters, plus "escape"/"space"/
    /// "enter"; arrow keys report as w/a/s/d to mirror the ASCII backend).
    [[nodiscard]] std::vector<std::string> keys_held() const;

    /// Keys pressed since the previous call, then cleared (press edges).
    std::vector<std::string> take_pressed();

    /// Relative mouse mode captures the cursor and reports motion as deltas —
    /// what mouse-look needs. Off by default.
    void set_relative_mouse(bool enabled);

    /// Accumulated mouse motion (dx, dy) since the previous call, then reset.
    std::pair<float, float> take_mouse_delta();

    [[nodiscard]] SDL_Window* handle() const {
        return window_;
    }

private:
    SDL_Window* window_ = nullptr;
    bool should_close_ = false;
    bool resized_ = false;
    std::unordered_set<std::string> held_keys_;
    std::vector<std::string> pressed_keys_;
    float mouse_dx_ = 0.0F;
    float mouse_dy_ = 0.0F;
};

}  // namespace rome
