#include "amun/memory.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace amun {

namespace {

bool checkedEnd(Address address, std::size_t size, std::uint64_t &end) noexcept {
    end = static_cast<std::uint64_t>(address) + static_cast<std::uint64_t>(size);
    return end <= (static_cast<std::uint64_t>(std::numeric_limits<Address>::max()) + 1ULL);
}

std::uint16_t loadU16(const std::uint8_t *data) noexcept {
    return static_cast<std::uint16_t>(data[0]) |
           static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[1]) << 8U);
}

std::uint32_t loadU32(const std::uint8_t *data) noexcept {
    return static_cast<std::uint32_t>(data[0]) |
           (static_cast<std::uint32_t>(data[1]) << 8U) |
           (static_cast<std::uint32_t>(data[2]) << 16U) |
           (static_cast<std::uint32_t>(data[3]) << 24U);
}

} // namespace

bool AddressRange::contains(Address address, std::size_t size) const noexcept {
    if (begin > end || address < begin) {
        return false;
    }
    std::uint64_t requestedEnd = 0;
    return checkedEnd(address, size, requestedEnd) && requestedEnd <= end;
}

SyntheticMemoryReader::Region *SyntheticMemoryReader::findRegion(Address address,
                                                                 std::size_t size) noexcept {
    for (Region &region : regions_) {
        const AddressRange range{region.base,
                                 static_cast<Address>(static_cast<std::uint64_t>(region.base) +
                                                      region.bytes.size())};
        if (range.contains(address, size)) {
            return &region;
        }
    }
    return nullptr;
}

const SyntheticMemoryReader::Region *SyntheticMemoryReader::findRegion(Address address,
                                                                       std::size_t size) const noexcept {
    for (const Region &region : regions_) {
        const std::uint64_t rawEnd = static_cast<std::uint64_t>(region.base) + region.bytes.size();
        if (rawEnd > std::numeric_limits<Address>::max()) {
            continue;
        }
        const AddressRange range{region.base, static_cast<Address>(rawEnd)};
        if (range.contains(address, size)) {
            return &region;
        }
    }
    return nullptr;
}

bool SyntheticMemoryReader::map(Address base, std::size_t size, std::uint8_t fill) {
    if (size == 0) {
        return false;
    }
    std::uint64_t end = 0;
    if (!checkedEnd(base, size, end) || end > std::numeric_limits<Address>::max()) {
        return false;
    }
    for (const Region &region : regions_) {
        const std::uint64_t regionEnd = static_cast<std::uint64_t>(region.base) + region.bytes.size();
        if (static_cast<std::uint64_t>(base) < regionEnd && end > region.base) {
            return false;
        }
    }
    Region region;
    region.base = base;
    region.bytes.assign(size, fill);
    regions_.push_back(std::move(region));
    std::sort(regions_.begin(), regions_.end(), [](const Region &left, const Region &right) {
        return left.base < right.base;
    });
    return true;
}

bool SyntheticMemoryReader::mapBytes(Address base, const std::vector<std::uint8_t> &bytes) {
    if (!map(base, bytes.size())) {
        return false;
    }
    return write(base, bytes.data(), bytes.size());
}

bool SyntheticMemoryReader::unmap(Address base) {
    const auto it = std::find_if(regions_.begin(), regions_.end(),
                                 [base](const Region &region) { return region.base == base; });
    if (it == regions_.end()) {
        return false;
    }
    regions_.erase(it);
    return true;
}

bool SyntheticMemoryReader::setReadable(Address base, bool readable) {
    Region *region = findRegion(base, 1);
    if (region == nullptr || region->base != base) {
        return false;
    }
    region->readable = readable;
    return true;
}

bool SyntheticMemoryReader::write(Address address, const void *source, std::size_t size) {
    if ((source == nullptr && size != 0) || size == 0) {
        return size == 0;
    }
    Region *region = findRegion(address, size);
    if (region == nullptr) {
        return false;
    }
    const std::size_t offset = static_cast<std::size_t>(address - region->base);
    std::memcpy(region->bytes.data() + offset, source, size);
    return true;
}

ReadResult SyntheticMemoryReader::read(Address address, void *destination, std::size_t size) noexcept {
    if ((destination == nullptr && size != 0) || size == 0) {
        return {size == 0 ? ReadStatus::Ok : ReadStatus::InvalidRange, 0};
    }
    const Region *region = findRegion(address, size);
    if (region == nullptr) {
        return {ReadStatus::Unmapped, 0};
    }
    if (!region->readable) {
        return {ReadStatus::InvalidRange, 0};
    }
    const std::size_t offset = static_cast<std::size_t>(address - region->base);
    std::memcpy(destination, region->bytes.data() + offset, size);
    return {ReadStatus::Ok, size};
}

bool SyntheticMemoryReader::isRangeReadable(Address address, std::size_t size) const noexcept {
    const Region *region = findRegion(address, size);
    return region != nullptr && region->readable;
}

PatternResult scanPattern(MemoryReader &reader, const PatternSpec &pattern,
                          std::size_t chunkBytes) noexcept {
    PatternResult result;
    if (pattern.bytes.empty() || pattern.bytes.size() != pattern.mask.size() ||
        pattern.scanSize < pattern.bytes.size() || chunkBytes < pattern.bytes.size()) {
        return result;
    }
    const std::uint64_t scanEnd64 = static_cast<std::uint64_t>(pattern.scanStart) + pattern.scanSize;
    if (scanEnd64 > std::numeric_limits<Address>::max()) {
        return result;
    }

    const std::size_t overlap = pattern.bytes.size() - 1U;
    std::vector<std::uint8_t> buffer(chunkBytes + overlap);
    std::size_t carried = 0;
    Address cursor = pattern.scanStart;
    const Address scanEnd = static_cast<Address>(scanEnd64);

    while (cursor < scanEnd) {
        const std::size_t remaining = static_cast<std::size_t>(scanEnd - cursor);
        const std::size_t toRead = std::min(chunkBytes, remaining);
        const ReadResult read = reader.read(cursor, buffer.data() + carried, toRead);
        if (!read || read.bytesRead != toRead) {
            result.status = PatternStatus::ReadFailure;
            return result;
        }
        const std::size_t available = carried + toRead;
        const Address bufferBase = static_cast<Address>(cursor - static_cast<Address>(carried));
        for (std::size_t i = 0; i + pattern.bytes.size() <= available; ++i) {
            bool matches = true;
            for (std::size_t j = 0; j < pattern.bytes.size(); ++j) {
                if (pattern.mask[j] != 0 && buffer[i + j] != pattern.bytes[j]) {
                    matches = false;
                    break;
                }
            }
            if (matches) {
                ++result.matches;
                const std::int64_t resolved = static_cast<std::int64_t>(bufferBase) +
                                              static_cast<std::int64_t>(i) + pattern.resultOffset;
                if (resolved < 0 || resolved > std::numeric_limits<Address>::max()) {
                    result.status = PatternStatus::Invalid;
                    return result;
                }
                result.address = static_cast<Address>(resolved);
            }
        }
        if (result.matches > 1) {
            result.status = PatternStatus::Ambiguous;
            return result;
        }
        carried = std::min(overlap, available);
        if (carried != 0) {
            std::memmove(buffer.data(), buffer.data() + available - carried, carried);
        }
        cursor = static_cast<Address>(cursor + toRead);
    }
    result.status = result.matches == 1 ? PatternStatus::Found : PatternStatus::NotFound;
    return result;
}

std::size_t scalarWidth(ValueType type) noexcept {
    switch (type) {
    case ValueType::Bit:
    case ValueType::Bool:
    case ValueType::U8:
    case ValueType::S8:
        return 1;
    case ValueType::U16:
    case ValueType::S16:
        return 2;
    case ValueType::U32:
    case ValueType::S32:
    case ValueType::F32:
        return 4;
    case ValueType::Bytes:
    case ValueType::FixedString:
        return 0;
    }
    return 0;
}

bool decodeScalarLittleEndian(ValueType type, const std::uint8_t *data, std::size_t size,
                              Scalar &out) noexcept {
    if (type == ValueType::Bytes || type == ValueType::FixedString) {
        if (data == nullptr || size == 0 || size > 16U) return false;
        out = Scalar::fromBytes(data, size);
        return true;
    }
    const std::size_t width = scalarWidth(type);
    if (data == nullptr || width == 0 || size < width) {
        return false;
    }
    switch (type) {
    case ValueType::Bit:
        out = Scalar::fromInteger((data[0] & 1U) != 0U ? 1 : 0);
        return true;
    case ValueType::Bool:
        out = Scalar::fromInteger(data[0] != 0U ? 1 : 0);
        return true;
    case ValueType::U8:
        out = Scalar::fromInteger(data[0]);
        return true;
    case ValueType::S8:
        out = Scalar::fromInteger(static_cast<std::int8_t>(data[0]));
        return true;
    case ValueType::U16:
        out = Scalar::fromInteger(loadU16(data));
        return true;
    case ValueType::S16:
        out = Scalar::fromInteger(static_cast<std::int16_t>(loadU16(data)));
        return true;
    case ValueType::U32:
        out = Scalar::fromInteger(loadU32(data));
        return true;
    case ValueType::S32:
        out = Scalar::fromInteger(static_cast<std::int32_t>(loadU32(data)));
        return true;
    case ValueType::F32: {
        const std::uint32_t raw = loadU32(data);
        float value = 0.0F;
        std::memcpy(&value, &raw, sizeof(value));
        if (!std::isfinite(value)) return false;
        out = Scalar::fromFloat(value);
        return true;
    }
    case ValueType::Bytes:
    case ValueType::FixedString:
        return false; // handled before the scalar-width switch
    }
    return false;
}

} // namespace amun
