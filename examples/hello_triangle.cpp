#include <exception>
#include <iostream>

#include "rome/app.hpp"

int main() {
    try {
        rome::AppConfig config;
        config.window.title = "ROME - hello triangle (C++)";
#ifndef NDEBUG
        // Validation is worth its cost while developing, not in a release run.
        config.validation = true;
#endif

        rome::App app{config};
        std::cout << "GPU: " << app.gpu_name() << "\n";
        std::cout << "Press Escape or close the window to exit.\n";

        app.run();

        std::cout << "Rendered " << app.frame_count() << " frames in " << app.elapsed() << " s\n";
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << "\n";
        return 1;
    }
    return 0;
}
