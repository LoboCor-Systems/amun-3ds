#include "fuzz_support.hpp"

#include "amun/ledger.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size) {
    const auto path = std::filesystem::temp_directory_path() / "amun-fuzz-ledger.bin";
    try {
        {
            std::ofstream stream(path, std::ios::binary | std::ios::trunc);
            stream.write(reinterpret_cast<const char *>(data), static_cast<std::streamsize>(size));
        }
        amun::JournalLedger ledger(path.string(), 4096);
        (void)ledger.load();
        std::error_code ignored;
        std::filesystem::remove(path, ignored);
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(path, ignored);
    }
    return 0;
}

#ifdef AMUN_FUZZ_STANDALONE
int main() { return runStandaloneFuzzer(LLVMFuzzerTestOneInput); }
#endif

