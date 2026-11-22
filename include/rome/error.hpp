#pragma once

#include <stdexcept>

namespace rome {

/// Every failure ROME raises derives from this, so the binding layer can map
/// one C++ type onto one Python exception type.
class Error : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

}  // namespace rome
