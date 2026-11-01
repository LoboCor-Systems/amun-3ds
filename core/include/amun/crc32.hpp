#pragma once

#include <cstddef>
#include <cstdint>

namespace amun {
std::uint32_t crc32(const void *data, std::size_t size, std::uint32_t seed = 0U) noexcept;
}

