cmake_minimum_required(VERSION 3.20)

include("${CMAKE_CURRENT_LIST_DIR}/Dependencies.cmake")
find_package(Git REQUIRED)

if(NOT DEFINED AMUN_DEPS_DIR OR AMUN_DEPS_DIR STREQUAL "")
    get_filename_component(AMUN_DEPS_DIR
        "${CMAKE_CURRENT_LIST_DIR}/../../build-3ds-deps" ABSOLUTE)
else()
    get_filename_component(AMUN_DEPS_DIR "${AMUN_DEPS_DIR}" ABSOLUTE)
endif()
file(MAKE_DIRECTORY "${AMUN_DEPS_DIR}")

function(amun_run_checked description working_directory)
    execute_process(
        COMMAND ${ARGN}
        WORKING_DIRECTORY "${working_directory}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE output
        ERROR_VARIABLE error
    )
    if(NOT result EQUAL 0)
        message(FATAL_ERROR "${description} failed (${result})\n${output}\n${error}")
    endif()
endfunction()

function(amun_checkout name repository revision recurse)
    set(destination "${AMUN_DEPS_DIR}/${name}")
    set(fresh_clone FALSE)
    if(NOT EXISTS "${destination}/.git")
        if(EXISTS "${destination}")
            message(FATAL_ERROR
                "${destination} exists but is not a Git checkout; choose a clean AMUN_DEPS_DIR")
        endif()
        amun_run_checked("clone ${name}" "${AMUN_DEPS_DIR}"
            "${GIT_EXECUTABLE}" clone --no-checkout "${repository}" "${destination}")
        set(fresh_clone TRUE)
    endif()

    amun_run_checked("fetch ${name} revision" "${destination}"
        "${GIT_EXECUTABLE}" fetch --depth 1 origin "${revision}")
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" rev-parse HEAD
        WORKING_DIRECTORY "${destination}"
        RESULT_VARIABLE head_result
        OUTPUT_VARIABLE head
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    # `clone --no-checkout` may already point HEAD at the requested default-branch
    # commit while leaving the working tree empty. A fresh clone must therefore be
    # checked out even when rev-parse happens to match.
    if(fresh_clone OR NOT head_result EQUAL 0 OR NOT "${head}" STREQUAL "${revision}")
        amun_run_checked("checkout ${name} revision" "${destination}"
            "${GIT_EXECUTABLE}" checkout --detach "${revision}")
    endif()

    if(recurse)
        amun_run_checked("initialize ${name} submodules" "${destination}"
            "${GIT_EXECUTABLE}" submodule update --init --recursive)
    endif()
endfunction()

function(amun_apply_patch name patch_path)
    set(destination "${AMUN_DEPS_DIR}/${name}")
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" apply --reverse --check "${patch_path}"
        WORKING_DIRECTORY "${destination}"
        RESULT_VARIABLE already_applied
        OUTPUT_QUIET ERROR_QUIET
    )
    if(already_applied EQUAL 0)
        message(STATUS "${name}: patch already applied")
        return()
    endif()

    amun_run_checked("validate ${name} patch" "${destination}"
        "${GIT_EXECUTABLE}" apply --check "${patch_path}")
    amun_run_checked("apply ${name} patch" "${destination}"
        "${GIT_EXECUTABLE}" apply "${patch_path}")
endfunction()

amun_checkout("ctrpluginframework" "${AMUN_CTRPF_REPOSITORY}"
    "${AMUN_CTRPF_REVISION}" TRUE)
amun_checkout("3gxtool" "${AMUN_3GXTOOL_REPOSITORY}"
    "${AMUN_3GXTOOL_REVISION}" TRUE)

amun_apply_patch("ctrpluginframework"
    "${CMAKE_CURRENT_LIST_DIR}/patches/ctrpf-luma-v13.4-header.patch")
amun_apply_patch("ctrpluginframework"
    "${CMAKE_CURRENT_LIST_DIR}/patches/ctrpf-devkitarm-r68-warnings.patch")
amun_apply_patch("ctrpluginframework"
    "${CMAKE_CURRENT_LIST_DIR}/patches/ctrpf-amun-menu-hotkey.patch")
amun_apply_patch("ctrpluginframework"
    "${CMAKE_CURRENT_LIST_DIR}/patches/ctrpf-menu-root-ownership.patch")
amun_apply_patch("ctrpluginframework"
    "${CMAKE_CURRENT_LIST_DIR}/patches/ctrpf-threadex-safe-destruction.patch")
amun_apply_patch("ctrpluginframework"
    "${CMAKE_CURRENT_LIST_DIR}/patches/ctrpf-plgldr-null-event-guard.patch")
amun_apply_patch("3gxtool"
    "${CMAKE_CURRENT_LIST_DIR}/patches/3gxtool-luma-v13.4-homebrew-flag.patch")
amun_apply_patch("3gxtool"
    "${CMAKE_CURRENT_LIST_DIR}/patches/3gxtool-msvc-layout.patch")

set(AMUN_CTRPF_SOURCE "${AMUN_DEPS_DIR}/ctrpluginframework")
include("${CMAKE_CURRENT_LIST_DIR}/verify_patched_ctrpf.cmake")

message(STATUS "Pinned 3DS sources are ready in ${AMUN_DEPS_DIR}")
