#pragma once

#include "amun/types.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace amun {

enum class Op : std::uint8_t {
    LoadCurrent = 0x01,
    LoadPrevious = 0x02,
    LoadInitial = 0x03,
    ConstI64 = 0x04,
    ConstF32 = 0x05,
    ConstBytes = 0x06,
    Eq = 0x10,
    Ne = 0x11,
    Lt = 0x12,
    Le = 0x13,
    Gt = 0x14,
    Ge = 0x15,
    Between = 0x16,
    BitSet = 0x17,
    BitClear = 0x18,
    MaskedEquals = 0x19,
    Add = 0x1A,
    Subtract = 0x1B,
    Multiply = 0x1C,
    Divide = 0x1D,
    BitAnd = 0x1E,
    BitOr = 0x1F,
    Changed = 0x20,
    Unchanged = 0x21,
    Increased = 0x22,
    Decreased = 0x23,
    IncreasedBy = 0x24,
    DecreasedBy = 0x25,
    All = 0x30,
    Any = 0x31,
    Not = 0x32,
    Rising = 0x40,
    Falling = 0x41,
    HitCount = 0x42,
    Consecutive = 0x43,
    Latch = 0x44,
    Duration = 0x45,
    Cooldown = 0x46,
    Sequence = 0x47,
    ResetIf = 0x48,
    PauseIf = 0x49,
    SetProgress = 0x4A,
    End = 0xFF,
};

struct VmSlotState {
    std::uint32_t count{0};
    std::uint32_t stage{0};
    Milliseconds startedAt{0};
    Milliseconds lastAt{0};
    bool previous{false};
    bool latched{false};
    bool active{false};
};

struct VmState {
    std::vector<VmSlotState> slots;
    bool paused{false};

    void reset() noexcept;
};

struct VmVerifyResult {
    bool valid{false};
    std::uint16_t maximumStack{0};
    std::uint16_t stateSlots{0};
    std::uint32_t instructions{0};
    std::string error;
};

struct VmEvalResult {
    bool valid{false};
    bool condition{false};
    Scalar value{};
    bool progressChanged{false};
    std::uint32_t progress{0};
    std::uint32_t instructions{0};
    std::string error;
};

VmVerifyResult verifyBytecode(const std::uint8_t *code, std::size_t size,
                              std::size_t symbolCount, const RuntimeLimits &limits = {});

VmEvalResult evaluateBytecode(const std::uint8_t *code, std::size_t size,
                              const std::vector<SymbolSnapshot> &symbols,
                              Milliseconds monotonicMs, VmState &state,
                              std::uint32_t instructionBudget,
                              std::uint16_t stackLimit);

} // namespace amun
