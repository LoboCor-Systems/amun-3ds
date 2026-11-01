cmake_minimum_required(VERSION 3.20)

include("${CMAKE_CURRENT_LIST_DIR}/Dependencies.cmake")

if(NOT DEFINED AMUN_DEPS_DIR OR AMUN_DEPS_DIR STREQUAL "")
    get_filename_component(AMUN_DEPS_DIR
        "${CMAKE_CURRENT_LIST_DIR}/../../build-3ds-deps" ABSOLUTE)
else()
    get_filename_component(AMUN_DEPS_DIR "${AMUN_DEPS_DIR}" ABSOLUTE)
endif()

set(tool_source "${AMUN_DEPS_DIR}/3gxtool")
set(tool_build "${AMUN_DEPS_DIR}/3gxtool-build")
set(ctrpf_library "${AMUN_DEPS_DIR}/ctrpluginframework/Library")

if(NOT EXISTS "${tool_source}/CMakeLists.txt" OR
   NOT EXISTS "${ctrpf_library}/Makefile")
    message(FATAL_ERROR
        "Pinned sources are absent. Run fetch_pinned_dependencies.cmake first.")
endif()
if(NOT DEFINED ENV{DEVKITARM} OR "$ENV{DEVKITARM}" STREQUAL "")
    message(FATAL_ERROR "DEVKITARM is not set; enter a devkitPro environment first")
endif()

execute_process(
    COMMAND "${CMAKE_COMMAND}" -S "${tool_source}" -B "${tool_build}"
            -DGIT_SUBMODULE=OFF -DCMAKE_BUILD_TYPE=Release
    RESULT_VARIABLE configure_result
)
if(NOT configure_result EQUAL 0)
    message(FATAL_ERROR "3gxtool configure failed (${configure_result})")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${tool_build}" --config Release
    RESULT_VARIABLE tool_result
)
if(NOT tool_result EQUAL 0)
    message(FATAL_ERROR "3gxtool build failed (${tool_result})")
endif()

find_program(AMUN_MAKE_PROGRAM NAMES make gmake REQUIRED)
if(DEFINED AMUN_BUILD_JOBS AND NOT AMUN_BUILD_JOBS STREQUAL "")
    set(job_arguments -j "${AMUN_BUILD_JOBS}")
else()
    set(job_arguments)
endif()
execute_process(
    COMMAND "${AMUN_MAKE_PROGRAM}" ${job_arguments} lib/libctrpf.a
    WORKING_DIRECTORY "${ctrpf_library}"
    RESULT_VARIABLE ctrpf_result
)
if(NOT ctrpf_result EQUAL 0)
    message(FATAL_ERROR "CTRPluginFramework build failed (${ctrpf_result})")
endif()

message(STATUS "Pinned 3gxtool and release libctrpf.a were built in ${AMUN_DEPS_DIR}")
