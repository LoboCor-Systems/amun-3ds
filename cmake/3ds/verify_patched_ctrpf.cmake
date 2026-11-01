cmake_minimum_required(VERSION 3.20)

if(NOT DEFINED AMUN_CTRPF_SOURCE OR AMUN_CTRPF_SOURCE STREQUAL "")
    message(FATAL_ERROR "Pass -DAMUN_CTRPF_SOURCE=<path-to-ctrpluginframework>")
endif()

get_filename_component(AMUN_CTRPF_SOURCE "${AMUN_CTRPF_SOURCE}" ABSOLUTE)
set(menu_header
    "${AMUN_CTRPF_SOURCE}/Library/include/CTRPluginFrameworkImpl/Menu/Menu.hpp")
set(menu_source
    "${AMUN_CTRPF_SOURCE}/Library/source/CTRPluginFrameworkImpl/Menu/Menu.cpp")
set(tools_source
    "${AMUN_CTRPF_SOURCE}/Library/source/CTRPluginFrameworkImpl/Menu/PluginMenuTools.cpp")
set(thread_source
    "${AMUN_CTRPF_SOURCE}/Library/source/CTRPluginFramework/System/ThreadEx.cpp")
set(plgldr_source
    "${AMUN_CTRPF_SOURCE}/Library/source/plgldr.c")

foreach(path IN ITEMS "${menu_header}" "${menu_source}" "${tools_source}" "${thread_source}"
                      "${plgldr_source}")
    if(NOT EXISTS "${path}")
        message(FATAL_ERROR "Patched CTRPF verification input is missing: ${path}")
    endif()
endforeach()

file(READ "${menu_header}" menu_header_text)
file(READ "${menu_source}" menu_source_text)
file(READ "${tools_source}" tools_source_text)
file(READ "${thread_source}" thread_source_text)
file(READ "${plgldr_source}" plgldr_source_text)

function(amun_require_text haystack needle description)
    string(FIND "${haystack}" "${needle}" found_at)
    if(found_at EQUAL -1)
        message(FATAL_ERROR "Patched CTRPF invariant is missing: ${description}")
    endif()
endfunction()

amun_require_text("${menu_header_text}" "bool takeOwnership = true"
    "Menu pointer constructor must declare ownership explicitly")
amun_require_text("${menu_header_text}" "_ownsRoot;"
    "Menu must retain root ownership state")
amun_require_text("${menu_source_text}" "_ownsRoot = true;"
    "title-created roots must remain owned")
amun_require_text("${menu_source_text}" "_ownsRoot = folder == nullptr || takeOwnership;"
    "null roots and explicitly owned roots must remain owned")
set(guarded_root_cleanup "if (_ownsRoot)\n            delete _root;")
amun_require_text("${menu_source_text}" "${guarded_root_cleanup}"
    "cleanup must destroy the root only when Menu owns it")
amun_require_text("${tools_source_text}" "_menu(&_mainMenu, nullptr, false)"
    "PluginMenuTools must borrow its embedded root")

string(FIND "${menu_source_text}" "delete _folder;" unsafe_delete)
if(NOT unsafe_delete EQUAL -1)
    message(FATAL_ERROR
        "Patched CTRPF still deletes Menu::_folder; this reintroduces invalid/double destruction")
endif()

amun_require_text("${thread_source_text}" "if (_thread->finished)"
    "ThreadEx destruction must not free a running thread")
amun_require_text("${thread_source_text}" "threadFree(_thread);"
    "finished ThreadEx resources must use libctru's thread cleanup")
string(FIND "${thread_source_text}" "std::free(_thread);" unsafe_thread_free)
if(NOT unsafe_thread_free EQUAL -1)
    message(FATAL_ERROR
        "Patched CTRPF still frees a possibly running thread during global destruction")
endif()

set(null_safe_event_fetch
    "if (plgEvent == NULL)\n        return PLG_OK;\n\n    s32  event = __ldrex__(plgEvent);")
amun_require_text("${plgldr_source_text}" "${null_safe_event_fetch}"
    "PLGLDR event polling must treat an unavailable event channel as idle")
set(null_safe_event_reply
    "if (plgEvent == NULL || plgReply == NULL)\n        return;\n\n    __strex__(plgReply, PLG_OK);")
amun_require_text("${plgldr_source_text}" "${null_safe_event_reply}"
    "PLGLDR event replies must not dereference an unavailable event channel")

message(STATUS
    "Patched CTRPF ownership, thread-destruction, and PLGLDR event invariants verified")
