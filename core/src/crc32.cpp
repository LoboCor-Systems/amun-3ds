#include "amun/crc32.hpp"

namespace amun {

std::uint32_t crc32(const void *data, std::size_t size, std::uint32_t seed) noexcept {
    const auto *bytes = static_cast<const std::uint8_t *>(data);
    std::uint32_t value = ~seed;
    for (std::size_t i = 0; i < size; ++i) {
        value ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            const std::uint32_t mask = 0U - (value & 1U);
            value = (value >> 1U) ^ (0xEDB88320U & mask);
        }
    }
    return ~value;
}

} // namespace amun

