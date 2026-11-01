#include "amun/3ds/memory_reader.hpp"

#include <3ds.h>
#include <CTRPluginFramework.hpp>

#include <cstring>

namespace amun::threeds {

namespace {

bool isReadableProcessState(std::uint32_t state) noexcept {
    // Deliberately reject FREE, RESERVED, and IO. Reading MMIO is unnecessary for
    // achievements and can have semantics unlike ordinary process memory.
    switch (state) {
    case MEMSTATE_STATIC:
    case MEMSTATE_CODE:
    case MEMSTATE_PRIVATE:
    case MEMSTATE_SHARED:
    case MEMSTATE_CONTINUOUS:
    case MEMSTATE_ALIASED:
    case MEMSTATE_ALIAS:
    case MEMSTATE_ALIASCODE:
    case MEMSTATE_LOCKED:
        return true;
    default:
        return false;
    }
}

} // namespace

bool ThreeDSMemoryReader::queryRegion(Address address, MemoryRegion &region) const noexcept {
    MemInfo info{};
    PageInfo page{};
    const Result result = svcQueryMemory(&info, &page, address);
    if (R_FAILED(result)) return false;

    region.base = info.base_addr;
    region.size = info.size;
    region.readable = (info.perm & MEMPERM_READ) != 0U && isReadableProcessState(info.state);

    // Achievement packs may observe game state, not the plugin itself. Luma's stable
    // runtime header fields identify the 3GX executable and heap mappings.
    // svcQueryMemory can report a mapping containing both ordinary game bytes and
    // a plugin allocation. Split at the exclusion boundaries so game bytes remain
    // readable, while BoundedMemoryReader can never copy across into the plugin.
    const auto *header = CTRPluginFramework::FwkSettings::Header;
    if (header != nullptr) {
        if (!excludeMemoryRange(address, 0x07000000U, header->exeSize, region) ||
            !excludeMemoryRange(address, header->heapVA, header->heapSize, region))
            return false;
    }
    return true;
}

bool ThreeDSMemoryReader::copyOut(Address source, void *destination,
                                  std::size_t size) const noexcept {
    // Source and destination are in the current process. BoundedMemoryReader has
    // already proved that this single copy cannot cross the queried region.
    std::memcpy(destination, reinterpret_cast<const void *>(source), size);
    return true;
}

} // namespace amun::threeds
