#pragma once

#include "amun/memory.hpp"

#include <cstddef>
#include <cstdint>

namespace amun::threeds {

struct MemoryRegion {
    Address base{0};
    std::uint32_t size{0};
    bool readable{false};
};

// Retain only the part of a queried mapping containing address that lies outside
// an excluded range. A query inside the exclusion becomes unreadable. Invalid
// region/range metadata fails closed; an existing unreadable region stays so.
bool excludeMemoryRange(Address address, Address excludedBase, std::uint32_t excludedSize,
                        MemoryRegion &region) noexcept;

// Implements all range arithmetic and region-boundary handling in portable code.
// Platform subclasses only query one address and copy bytes out of that same process.
class BoundedMemoryReader : public MemoryReader {
public:
    ReadResult read(Address address, void *destination, std::size_t size) noexcept final;
    bool isRangeReadable(Address address, std::size_t size) const noexcept final;

protected:
    virtual bool queryRegion(Address address, MemoryRegion &region) const noexcept = 0;
    virtual bool copyOut(Address source, void *destination, std::size_t size) const noexcept = 0;
};

// Real-console adapter. The implementation uses libctru's svcQueryMemory and only
// copies from a region after the portable reader has bounded the copy to that region.
class ThreeDSMemoryReader final : public BoundedMemoryReader {
protected:
    bool queryRegion(Address address, MemoryRegion &region) const noexcept override;
    bool copyOut(Address source, void *destination, std::size_t size) const noexcept override;
};

} // namespace amun::threeds
