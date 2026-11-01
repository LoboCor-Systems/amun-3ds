cmake_minimum_required(VERSION 3.20)
project(AMUN VERSION 0.1.0 LANGUAGES C CXX)

option(AMUN_BUILD_TESTS "Build host tests" ON)
option(AMUN_BUILD_TOOLS "Build host simulator and utilities" ON)
option(AMUN_BUILD_3DS_PLATFORM_TESTS "Build host tests for the 3DS safety boundary" ON)
option(AMUN_ENABLE_SANITIZERS "Enable host address/undefined sanitizers" OFF)
option(AMUN_BUILD_FUZZERS "Build standalone/libFuzzer parser harnesses" OFF)
option(AMUN_USE_LIBFUZZER "Link fuzz harnesses with Clang libFuzzer" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(amun_core
    core/src/crc32.cpp
    core/src/ledger.cpp
    core/src/log.cpp
    core/src/memory.cpp
    core/src/pack.cpp
    core/src/runtime.cpp
    core/src/trace.cpp
    core/src/vm.cpp
)
target_include_directories(amun_core PUBLIC core/include)
target_compile_definitions(amun_core PUBLIC AMUN_VERSION="${PROJECT_VERSION}")

if(MSVC)
    target_compile_options(amun_core PRIVATE /W4 /permissive- /EHsc)
else()
    target_compile_options(amun_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
    if(AMUN_ENABLE_SANITIZERS AND NOT CMAKE_CROSSCOMPILING)
        target_compile_options(amun_core PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(amun_core PUBLIC -fsanitize=address,undefined)
    endif()
endif()

if(AMUN_BUILD_TOOLS)
    add_executable(amun-sim simulator/main.cpp)
    target_link_libraries(amun-sim PRIVATE amun_core)

    add_executable(amun-bench tests/bench/runtime_bench.cpp)
    target_link_libraries(amun-bench PRIVATE amun_core)
endif()

if(AMUN_BUILD_TESTS)
    enable_testing()
    add_executable(amun-core-tests
        tests/unit/test_main.cpp
        tests/unit/test_ledger.cpp
        tests/unit/test_log.cpp
        tests/unit/test_memory.cpp
        tests/unit/test_metal_tier.cpp
        tests/unit/test_pack.cpp
        tests/unit/test_runtime.cpp
        tests/unit/test_vm.cpp
    )
    target_link_libraries(amun-core-tests PRIVATE amun_core)
    target_include_directories(amun-core-tests PRIVATE tests/unit)
    add_test(NAME amun-core COMMAND amun-core-tests)

    if(AMUN_BUILD_TOOLS)
        find_package(Python3 COMPONENTS Interpreter QUIET)
        if(Python3_Interpreter_FOUND)
            add_test(
                NAME amun-compiler-runtime-integration
                COMMAND ${Python3_EXECUTABLE}
                        ${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/e2e_compiler_runtime.py
                        --simulator $<TARGET_FILE:amun-sim>
            )
            set_tests_properties(amun-compiler-runtime-integration PROPERTIES
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            )
            add_test(
                NAME amun-mk7-coin-pack-integration
                COMMAND ${Python3_EXECUTABLE}
                        ${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/e2e_mk7_coins.py
                        --simulator $<TARGET_FILE:amun-sim>
            )
            set_tests_properties(amun-mk7-coin-pack-integration PROPERTIES
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            )
            add_test(
                NAME amun-pointer-pack-integration
                COMMAND ${Python3_EXECUTABLE}
                        ${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/e2e_pointer_resolvers.py
                        --simulator $<TARGET_FILE:amun-sim>
            )
            set_tests_properties(amun-pointer-pack-integration PROPERTIES
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            )
            add_test(
                NAME amun-mk7-progression-integration
                COMMAND ${Python3_EXECUTABLE}
                        ${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/e2e_mk7_progression.py
                        --simulator $<TARGET_FILE:amun-sim>
            )
            set_tests_properties(amun-mk7-progression-integration PROPERTIES
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            )
        endif()
    endif()
endif()

if(AMUN_BUILD_3DS_PLATFORM_TESTS AND NOT CMAKE_CROSSCOMPILING)
    add_subdirectory(3ds)
endif()

if(AMUN_BUILD_FUZZERS AND NOT CMAKE_CROSSCOMPILING)
    foreach(target pack vm trace ledger)
        add_executable(amun-fuzz-${target} tests/fuzz/fuzz_${target}.cpp)
        target_link_libraries(amun-fuzz-${target} PRIVATE amun_core)
        if(AMUN_USE_LIBFUZZER)
            if(NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
                message(FATAL_ERROR "AMUN_USE_LIBFUZZER requires Clang")
            endif()
            target_compile_options(amun-fuzz-${target} PRIVATE -fsanitize=fuzzer,address,undefined)
            target_link_options(amun-fuzz-${target} PRIVATE -fsanitize=fuzzer,address,undefined)
        else()
            target_compile_definitions(amun-fuzz-${target} PRIVATE AMUN_FUZZ_STANDALONE=1)
            if(AMUN_BUILD_TESTS)
                add_test(NAME amun-fuzz-${target}-smoke COMMAND amun-fuzz-${target})
            endif()
        endif()
    endforeach()
endif()
