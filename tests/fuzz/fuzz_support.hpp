#pragma once

#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>

#ifdef AMUN_FUZZ_STANDALONE
inline int runStandaloneFuzzer(int (*entry)(const std::uint8_t *, std::size_t)) {
    std::mt19937 generator(0x414D554EU);
    std::uniform_int_distribution<std::size_t> sizeDistribution(0, 4096);
    std::uniform_int_distribution<unsigned> byteDistribution(0, 255);
    for (unsigned iteration = 0; iteration < 1000; ++iteration) {
        std::vector<std::uint8_t> input(sizeDistribution(generator));
        for (std::uint8_t &value : input) value = static_cast<std::uint8_t>(byteDistribution(generator));
        entry(input.data(), input.size());
    }
    return 0;
}
#endif

