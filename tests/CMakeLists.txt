add_executable(rome_tests test_types.cpp)
target_link_libraries(rome_tests PRIVATE rome::core rome_warnings)
add_test(NAME rome_tests COMMAND rome_tests)

# Importing the extension loads its DLLs but creates no window, so this is
# safe to run headless and catches packaging and linkage mistakes early.
if(ROME_BUILD_PYTHON AND Python_EXECUTABLE)
    add_test(NAME python_import
             COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_import.py")
    set_tests_properties(python_import PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
endif()
