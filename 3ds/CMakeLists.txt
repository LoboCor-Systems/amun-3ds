cmake_minimum_required(VERSION 3.20)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(amun_3ds_portable LANGUAGES CXX)
    enable_testing()
endif()

option(AMUN_3DS_BUILD_HOST_TESTS "Build portable 3DS-boundary host tests" ON)

add_library(amun_3ds_portable
    identity/title_gate.cpp
    memory/bounded_memory_reader.cpp
    runtime/lifecycle.cpp
    runtime/runtime_policy.cpp
    storage/ledger_snapshot.cpp
)
target_include_directories(amun_3ds_portable
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_SOURCE_DIR}/../core/include
)
target_compile_features(amun_3ds_portable PUBLIC cxx_std_17)

if(MSVC)
    target_compile_options(amun_3ds_portable PRIVATE /W4 /permissive-)
else()
    target_compile_options(amun_3ds_portable PRIVATE
        -Wall -Wextra -Wpedantic -Wconversion -Wshadow
    )
endif()

if(AMUN_3DS_BUILD_HOST_TESTS)
    add_executable(amun-3ds-platform-tests tests/platform_tests.cpp)
    target_link_libraries(amun-3ds-platform-tests PRIVATE amun_3ds_portable)
    add_test(NAME amun-3ds-platform COMMAND amun-3ds-platform-tests)
endif()
