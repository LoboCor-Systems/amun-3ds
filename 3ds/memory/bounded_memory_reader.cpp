#include "amun/3ds/memory_reader.hpp"

#include <algorithm>
#include <cstdint>
#include <limits>

namespace amun::threeds {

namespace {

constexpr std::uint64_t kAddressSpaceEnd =
    static_cast<std::uint64_t>(std::numeric_limits<Address>::max()) + 1ULL;

bool checkedRangeEnd(Address address, std::size_t size, std::uint64_t &end) noexcept {
    if (size > kAddressSpaceEnd) return false;
    end = static_cast<std::uint64_t>(address) + static_cast<std::uint64_t>(size);
    return end <= kAddressSpaceEnd;
}

bool regionContains(const MemoryRegion &region, std::uint64_t address,
                    std::uint64_t &regionEnd) noexcept {
    regionEnd = static_cast<std::uint64_t>(region.base) + region.size;
    return region.size != 0U && regionEnd <= kAddressSpaceEnd &&
           address >= region.base && address < regionEnd;
}

} // namespace

bool excludeMemoryRange(Address address, Address excludedBase, std::uint32_t excludedSize,
                        MemoryRegion &region) noexcept {
    std::uint64_t regionEnd = 0;
    std::uint64_t excludedEnd = 0;
    if (!regionContains(region, address, regionEnd) ||
        !checkedRangeEnd(excludedBase, excludedSize, excludedEnd)) {
        region.readable = false;
        return false;
    }
    if (excludedSize == 0U || excludedEnd <= region.base || excludedBase >= regionEnd)
        return true;

    if (address >= excludedBase && address < excludedEnd) {
        region.readable = false;
    } else if (address < excludedBase) {
        region.size = excludedBase - region.base;
    } else {
        // address is beyond the exclusion but still inside the mapping, so this
        // cast cannot wrap even for a mapping ending at the top of address space.
        region.base = static_cast<Address>(excludedEnd);
        region.size = static_cast<std::uint32_t>(regionEnd - excludedEnd);
    }
    return true;
}

ReadResult BoundedMemoryReader::read(Address address, void *destination,
                                     std::size_t size) noexcept {
    if (size == 0U) return {ReadStatus::Ok, 0U};
    if (destination == nullptr) return {ReadStatus::InvalidRange, 0U};

    std::uint64_t end = 0;
    if (!checkedRangeEnd(address, size, end)) return {ReadStatus::InvalidRange, 0U};

    auto *output = static_cast<std::uint8_t *>(destination);
    std::uint64_t cursor = address;
    std::size_t copied = 0U;

    while (cursor < end) {
        MemoryRegion region;
        if (!queryRegion(static_cast<Address>(cursor), region)) {
            return {copied == 0U ? ReadStatus::BackendError : ReadStatus::Partial, copied};
        }

        std::uint64_t regionEnd = 0;
        if (!regionContains(region, cursor, regionEnd)) {
            return {copied == 0U ? ReadStatus::BackendError : ReadStatus::Partial, copied};
        }
        if (!region.readable) {
            return {copied == 0U ? ReadStatus::Unmapped : ReadStatus::Partial, copied};
        }

        const std::uint64_t remaining = end - cursor;
        const std::uint64_t available = regionEnd - cursor;
        const std::size_t chunk = static_cast<std::size_t>(std::min(remaining, available));
        if (chunk == 0U || !copyOut(static_cast<Address>(cursor), output + copied, chunk)) {
            return {copied == 0U ? ReadStatus::BackendError : ReadStatus::Partial, copied};
        }

        copied += chunk;
        cursor += chunk;
    }

    return {ReadStatus::Ok, copied};
}

bool BoundedMemoryReader::isRangeReadable(Address address, std::size_t size) const noexcept {
    if (size == 0U) return true;

    std::uint64_t end = 0;
    if (!checkedRangeEnd(address, size, end)) return false;

    std::uint64_t cursor = address;
    while (cursor < end) {
        MemoryRegion region;
        if (!queryRegion(static_cast<Address>(cursor), region) || !region.readable) return false;

        std::uint64_t regionEnd = 0;
        if (!regionContains(region, cursor, regionEnd)) return false;
        cursor = std::min(end, regionEnd);
    }
    return true;
}

} // namespace amun::threeds
