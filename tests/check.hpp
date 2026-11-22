#pragma once

#include <iostream>
#include <string_view>

namespace rome::test {

inline int failures = 0;

inline void check(bool condition, std::string_view expression, std::string_view file, int line) {
    if (condition) {
        return;
    }
    ++failures;
    std::cerr << file << ":" << line << ": FAILED  " << expression << "\n";
}

/// Returns the process exit code and prints a one-line summary.
inline int summary() {
    if (failures == 0) {
        std::cout << "all checks passed\n";
        return 0;
    }
    std::cerr << failures << " check(s) failed\n";
    return 1;
}

}  // namespace rome::test

// Variadic so that braced initialisers containing commas -- Color{1, 0, 0, 1}
// and the like -- are not mistaken for separate macro arguments.
#define CHECK(...) ::rome::test::check((__VA_ARGS__), #__VA_ARGS__, __FILE__, __LINE__)
