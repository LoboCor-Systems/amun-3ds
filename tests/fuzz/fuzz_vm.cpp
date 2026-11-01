#include "fuzz_support.hpp"

#include "amun/vm.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size) {
    amun::RuntimeLimits limits;
    limits.maxBytecodeBytes = 4096;
    const amun::VmVerifyResult verified = amun::verifyBytecode(data, size, 16, limits);
    if (verified.valid) {
        std::vector<amun::SymbolSnapshot> symbols(16);
        for (amun::SymbolSnapshot &symbol : symbols) {
            symbol.valid = true;
            symbol.hasInitial = true;
            symbol.hasPrevious = true;
        }
        amun::VmState state;
        state.slots.resize(verified.stateSlots);
        (void)amun::evaluateBytecode(data, size, symbols, 1234, state,
                                     verified.instructions, verified.maximumStack);
    }
    return 0;
}

#ifdef AMUN_FUZZ_STANDALONE
int main() { return runStandaloneFuzzer(LLVMFuzzerTestOneInput); }
#endif

