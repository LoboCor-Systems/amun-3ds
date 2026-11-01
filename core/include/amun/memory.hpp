#pragma once

#include "amun/types.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace amun {

enum class ReadStatus : std::uint8_t { Ok = 0, InvalidRange, Unmapped, Partial, BackendError };

struct ReadResult {
    ReadStatus status{ReadStatus::BackendError};
    std::size_t bytesRead{0};

    explicit operator bool() const noexcept { return status == ReadStatus::Ok; }
};

struct AddressRange {
    Address begin{0};
    Address end{0}; // exclusive

    bool contains(Address address, std::size_t size) const noexcept;
};

class MemoryReader {
public:
    virtual ~MemoryReader() = default;
    virtual ReadResult read(Address address, void *destination, std::size_t size) noexcept = 0;
    virtual bool isRangeReadable(Address address, std::size_t size) const noexcept = 0;
};

class SyntheticMemoryReader final : public MemoryReader {
public:
    struct Region {
        Address base{0};
        std::vector<std::uint8_t> bytes;
        bool readable{true};
    };

    bool map(Address base, std::size_t size, std::uint8_t fill = 0);
    bool mapBytes(Address base, const std::vector<std::uint8_t> &bytes);
    bool unmap(Address base);
    bool setReadable(Address base, bool readable);
    bool write(Address address, const void *source, std::size_t size);

    template <typename T>
    bool writeLittleEndian(Address address, T value) {
        std::uint8_t data[sizeof(T)]{};
        for (std::size_t i = 0; i < sizeof(T); ++i) {
            data[i] = static_cast<std::uint8_t>((static_cast<std::uint64_t>(value) >> (i * 8U)) & 0xFFU);
        }
        return write(address, data, sizeof(data));
    }

    ReadResult read(Address address, void *destination, std::size_t size) noexcept override;
    bool isRangeReadable(Address address, std::size_t size) const noexcept override;

private:
    Region *findRegion(Address address, std::size_t size) noexcept;
    const Region *findRegion(Address address, std::size_t size) const noexcept;
    std::vector<Region> regions_;
};

struct PatternSpec {
    Address scanStart{0};
    std::uint32_t scanSize{0};
    std::vector<std::uint8_t> bytes;
    std::vector<std::uint8_t> mask; // non-zero means significant
    std::int32_t resultOffset{0};
};

enum class PatternStatus : std::uint8_t { Found = 0, NotFound, Ambiguous, Invalid, ReadFailure };

struct PatternResult {
    PatternStatus status{PatternStatus::Invalid};
    Address address{0};
    std::uint32_t matches{0};
};

PatternResult scanPattern(MemoryReader &reader, const PatternSpec &pattern,
                          std::size_t chunkBytes = 4096U) noexcept;

bool decodeScalarLittleEndian(ValueType type, const std::uint8_t *data, std::size_t size,
                              Scalar &out) noexcept;
std::size_t scalarWidth(ValueType type) noexcept;

} // namespace amun

