#include "pack_loader.hpp"

#include <CTRPluginFramework.hpp>

#include <limits>
#include <vector>

namespace amun::threeds {

PackLoadResult loadPackFromSd(const char *absolutePath, RuntimeLimits limits) noexcept {
    PackLoadResult result;
    if (absolutePath == nullptr || absolutePath[0] != '/') {
        result.detail = "pack path is not absolute";
        return result;
    }

    CTRPluginFramework::File file;
    if (CTRPluginFramework::File::Open(file, absolutePath,
                                       CTRPluginFramework::File::READ) !=
        CTRPluginFramework::File::SUCCESS) {
        result.detail = "could not open exact-title pack";
        return result;
    }

    const std::uint64_t rawSize = file.GetSize();
    if (rawSize == 0U || rawSize > limits.maxPackBytes ||
        rawSize > std::numeric_limits<std::uint32_t>::max()) {
        result.detail = "pack size is empty or exceeds the configured bound";
        return result;
    }

    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(rawSize));
    if (file.Read(bytes.data(), static_cast<std::uint32_t>(bytes.size())) !=
            CTRPluginFramework::File::SUCCESS ||
        file.Tell() != rawSize) {
        result.detail = "short or failed pack read";
        return result;
    }
    result.bytes = bytes.size();

    PackParser parser(limits);
    const PackParseResult parsed = parser.parse(bytes.data(), bytes.size(), result.pack);
    if (!parsed) {
        result.detail = parsed.detail.empty() ? "pack parser rejected the file" : parsed.detail;
        return result;
    }
    result.ok = true;
    return result;
}

} // namespace amun::threeds
