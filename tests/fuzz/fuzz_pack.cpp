#include "fuzz_support.hpp"

#include "amun/pack.hpp"

#include <cstddef>
#include <cstdint>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size) {
    try {
        amun::AchievementPack pack;
        amun::PackParser{}.parse(data, size, pack);
    } catch (...) {
        // The harness contains allocation-capable host containers. Any memory-safety fault still
        // reaches the sanitizer; ordinary allocation exceptions are not parser findings.
    }
    return 0;
}

#ifdef AMUN_FUZZ_STANDALONE
int main() { return runStandaloneFuzzer(LLVMFuzzerTestOneInput); }
#endif

