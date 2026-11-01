#include "test.hpp"
#include "test_support.hpp"

#include "amun/vm.hpp"

using namespace amun;
using namespace amun::test;

namespace {
SymbolSnapshot snapshot(std::int64_t current, std::int64_t previous, bool hasPrevious = true) {
    SymbolSnapshot result;
    result.current = Scalar::fromInteger(current);
    result.previous = Scalar::fromInteger(previous);
    result.initial = Scalar::fromInteger(previous);
    result.valid = true;
    result.hasPrevious = hasPrevious;
    result.hasInitial = true;
    return result;
}
}

TEST("VM verifies and evaluates comparisons and nested Boolean groups") {
    std::vector<std::uint8_t> code;
    load(code, Op::LoadCurrent, 0); constant(code, 10); op(code, Op::Ge);
    load(code, Op::LoadCurrent, 1); constant(code, 7); op(code, Op::Eq);
    op(code, Op::All); code.push_back(2);
    op(code, Op::Not);
    op(code, Op::End);
    const VmVerifyResult verified = verifyBytecode(code.data(), code.size(), 2);
    EXPECT(verified.valid);
    VmState state;
    state.slots.resize(verified.stateSlots);
    const VmEvalResult result = evaluateBytecode(code.data(), code.size(),
        {snapshot(10, 9), snapshot(6, 6)}, 0, state, 100, verified.maximumStack);
    EXPECT(result.valid);
    EXPECT(result.condition);
}

TEST("VM history and delta operations do not fire on first sample") {
    std::vector<std::uint8_t> code;
    op(code, Op::IncreasedBy); emitU16(code, 0); emitI64(code, 3);
    op(code, Op::End);
    VmState state;
    VmEvalResult result = evaluateBytecode(code.data(), code.size(), {snapshot(8, 5, false)},
                                           0, state, 20, 2);
    EXPECT(result.valid);
    EXPECT(!result.condition);
    result = evaluateBytecode(code.data(), code.size(), {snapshot(8, 5, true)}, 1, state, 20, 2);
    EXPECT(result.condition);
}

TEST("rising edge and hit count are edge based") {
    std::vector<std::uint8_t> code;
    load(code, Op::LoadCurrent, 0);
    op(code, Op::Rising); emitU16(code, 0);
    op(code, Op::HitCount); emitU16(code, 1); emitU16(code, 2);
    op(code, Op::End);
    VmState state; state.slots.resize(2);
    auto run = [&](std::int64_t value) {
        return evaluateBytecode(code.data(), code.size(), {snapshot(value, value)}, 0, state, 20, 2).condition;
    };
    EXPECT(!run(0)); EXPECT(!run(1)); EXPECT(!run(1)); EXPECT(!run(0)); EXPECT(run(1));
}

TEST("duration uses monotonic time and resets when false") {
    std::vector<std::uint8_t> code;
    load(code, Op::LoadCurrent, 0);
    op(code, Op::Duration); emitU16(code, 0); emitU32(code, 1000);
    op(code, Op::End);
    VmState state; state.slots.resize(1);
    EXPECT(!evaluateBytecode(code.data(), code.size(), {snapshot(1, 1)}, 500, state, 20, 2).condition);
    EXPECT(!evaluateBytecode(code.data(), code.size(), {snapshot(1, 1)}, 1499, state, 20, 2).condition);
    EXPECT(evaluateBytecode(code.data(), code.size(), {snapshot(1, 1)}, 1500, state, 20, 2).condition);
    EXPECT(!evaluateBytecode(code.data(), code.size(), {snapshot(0, 1)}, 1501, state, 20, 2).condition);
}

TEST("sequence advances in order and measured progress is bounded") {
    std::vector<std::uint8_t> sequence;
    load(sequence, Op::LoadCurrent, 0);
    load(sequence, Op::LoadCurrent, 1);
    op(sequence, Op::Sequence); emitU16(sequence, 0); sequence.push_back(2);
    op(sequence, Op::End);
    VmState state; state.slots.resize(1);
    EXPECT(!evaluateBytecode(sequence.data(), sequence.size(), {snapshot(0, 0), snapshot(0, 0)}, 0, state, 20, 3).condition);
    EXPECT(!evaluateBytecode(sequence.data(), sequence.size(), {snapshot(1, 0), snapshot(0, 0)}, 1, state, 20, 3).condition);
    EXPECT(!evaluateBytecode(sequence.data(), sequence.size(), {snapshot(0, 1), snapshot(0, 0)}, 2, state, 20, 3).condition);
    EXPECT(evaluateBytecode(sequence.data(), sequence.size(), {snapshot(0, 0), snapshot(1, 0)}, 3, state, 20, 3).condition);

    std::vector<std::uint8_t> progress;
    load(progress, Op::LoadCurrent, 0);
    op(progress, Op::SetProgress); emitU32(progress, 50);
    op(progress, Op::End);
    VmState progressState;
    const VmEvalResult measured = evaluateBytecode(progress.data(), progress.size(), {snapshot(72, 70)},
                                                    0, progressState, 20, 2);
    EXPECT(measured.condition);
    EXPECT_EQ(measured.progress, 50U);
}

TEST("verifier rejects unknown, truncated, underflow, and oversized programs") {
    const std::uint8_t unknown[] = {0xEE, 0xFF};
    EXPECT(!verifyBytecode(unknown, sizeof(unknown), 1).valid);
    const std::uint8_t underflow[] = {static_cast<std::uint8_t>(Op::Eq), static_cast<std::uint8_t>(Op::End)};
    EXPECT(!verifyBytecode(underflow, sizeof(underflow), 1).valid);
    std::vector<std::uint8_t> invalid = equalityProgram(9, 1);
    EXPECT(!verifyBytecode(invalid.data(), invalid.size(), 1).valid);
}

TEST("runtime instruction budget is enforced") {
    std::vector<std::uint8_t> code = equalityProgram(0, 1);
    VmState state;
    const VmEvalResult result = evaluateBytecode(code.data(), code.size(), {snapshot(1, 1)},
                                                 0, state, 2, 4);
    EXPECT(!result.valid);
    EXPECT(result.error.find("budget") != std::string::npos);
}

TEST("bit masks, ranges, and every history direction evaluate deterministically") {
    std::vector<std::uint8_t> code;
    load(code, Op::LoadCurrent, 0); constant(code, 0x08); op(code, Op::BitSet);
    load(code, Op::LoadCurrent, 0); constant(code, 10); constant(code, 20); op(code, Op::Between);
    op(code, Op::Increased); emitU16(code, 0);
    op(code, Op::Changed); emitU16(code, 0);
    op(code, Op::All); code.push_back(4);
    op(code, Op::End);
    VmState state;
    const VmEvalResult result = evaluateBytecode(code.data(), code.size(), {snapshot(15, 7)},
                                                 0, state, 50, 6);
    EXPECT(result.valid);
    EXPECT(result.condition);

    std::vector<std::uint8_t> masked;
    load(masked, Op::LoadCurrent, 0); constant(masked, 0xF0); constant(masked, 0xA0);
    op(masked, Op::MaskedEquals); op(masked, Op::End);
    EXPECT(evaluateBytecode(masked.data(), masked.size(), {snapshot(0xAB, 0)}, 0, state, 20, 4).condition);
}

TEST("falling latch consecutive cooldown reset and pause preserve their state contracts") {
    std::vector<std::uint8_t> falling;
    load(falling, Op::LoadCurrent, 0); op(falling, Op::Falling); emitU16(falling, 0); op(falling, Op::End);
    VmState fallingState; fallingState.slots.resize(1);
    EXPECT(!evaluateBytecode(falling.data(), falling.size(), {snapshot(1, 1)}, 0, fallingState, 20, 2).condition);
    EXPECT(evaluateBytecode(falling.data(), falling.size(), {snapshot(0, 1)}, 1, fallingState, 20, 2).condition);

    std::vector<std::uint8_t> latch;
    load(latch, Op::LoadCurrent, 0); op(latch, Op::Latch); emitU16(latch, 0); op(latch, Op::End);
    VmState latchState; latchState.slots.resize(1);
    EXPECT(evaluateBytecode(latch.data(), latch.size(), {snapshot(1, 0)}, 0, latchState, 20, 2).condition);
    EXPECT(evaluateBytecode(latch.data(), latch.size(), {snapshot(0, 1)}, 1, latchState, 20, 2).condition);

    std::vector<std::uint8_t> consecutive;
    load(consecutive, Op::LoadCurrent, 0); op(consecutive, Op::Consecutive);
    emitU16(consecutive, 0); emitU16(consecutive, 3); op(consecutive, Op::End);
    VmState consecutiveState; consecutiveState.slots.resize(1);
    EXPECT(!evaluateBytecode(consecutive.data(), consecutive.size(), {snapshot(1, 0)}, 0, consecutiveState, 20, 2).condition);
    EXPECT(!evaluateBytecode(consecutive.data(), consecutive.size(), {snapshot(1, 1)}, 1, consecutiveState, 20, 2).condition);
    EXPECT(evaluateBytecode(consecutive.data(), consecutive.size(), {snapshot(1, 1)}, 2, consecutiveState, 20, 2).condition);
    EXPECT(!evaluateBytecode(consecutive.data(), consecutive.size(), {snapshot(0, 1)}, 3, consecutiveState, 20, 2).condition);

    std::vector<std::uint8_t> cooldown;
    load(cooldown, Op::LoadCurrent, 0); op(cooldown, Op::Cooldown);
    emitU16(cooldown, 0); emitU32(cooldown, 100); op(cooldown, Op::End);
    VmState cooldownState; cooldownState.slots.resize(1);
    EXPECT(evaluateBytecode(cooldown.data(), cooldown.size(), {snapshot(1, 0)}, 0, cooldownState, 20, 2).condition);
    EXPECT(!evaluateBytecode(cooldown.data(), cooldown.size(), {snapshot(0, 1)}, 1, cooldownState, 20, 2).condition);
    EXPECT(!evaluateBytecode(cooldown.data(), cooldown.size(), {snapshot(1, 0)}, 50, cooldownState, 20, 2).condition);
    EXPECT(!evaluateBytecode(cooldown.data(), cooldown.size(), {snapshot(0, 1)}, 60, cooldownState, 20, 2).condition);
    EXPECT(evaluateBytecode(cooldown.data(), cooldown.size(), {snapshot(1, 0)}, 100, cooldownState, 20, 2).condition);

    std::vector<std::uint8_t> paused;
    load(paused, Op::LoadCurrent, 0); op(paused, Op::HitCount); emitU16(paused, 0); emitU16(paused, 1);
    load(paused, Op::LoadCurrent, 1); op(paused, Op::PauseIf); op(paused, Op::End);
    VmState pauseState; pauseState.slots.resize(1);
    EXPECT(!evaluateBytecode(paused.data(), paused.size(), {snapshot(0, 0), snapshot(0, 0)}, 0, pauseState, 30, 3).condition);
    EXPECT(!evaluateBytecode(paused.data(), paused.size(), {snapshot(1, 0), snapshot(1, 0)}, 1, pauseState, 30, 3).condition);
    EXPECT_EQ(pauseState.slots[0].count, 0U);
    EXPECT(!evaluateBytecode(paused.data(), paused.size(), {snapshot(0, 1), snapshot(0, 1)}, 2, pauseState, 30, 3).condition);
    EXPECT(evaluateBytecode(paused.data(), paused.size(), {snapshot(1, 0), snapshot(0, 0)}, 3, pauseState, 30, 3).condition);

    std::vector<std::uint8_t> reset;
    load(reset, Op::LoadCurrent, 0); op(reset, Op::Latch); emitU16(reset, 0);
    load(reset, Op::LoadCurrent, 1); op(reset, Op::ResetIf); op(reset, Op::End);
    VmState resetState; resetState.slots.resize(1);
    EXPECT(evaluateBytecode(reset.data(), reset.size(), {snapshot(1, 0), snapshot(0, 0)}, 0, resetState, 30, 3).condition);
    EXPECT(!evaluateBytecode(reset.data(), reset.size(), {snapshot(0, 1), snapshot(1, 0)}, 1, resetState, 30, 3).condition);
    EXPECT(!resetState.slots[0].latched);
}

TEST("bounded arithmetic and fixed byte constants support derived values") {
    std::vector<std::uint8_t> arithmetic;
    load(arithmetic, Op::LoadCurrent, 0); constant(arithmetic, 100); op(arithmetic, Op::Multiply);
    load(arithmetic, Op::LoadCurrent, 1); op(arithmetic, Op::Divide);
    op(arithmetic, Op::End);
    VmState state;
    VmEvalResult result = evaluateBytecode(arithmetic.data(), arithmetic.size(),
        {snapshot(3, 3), snapshot(4, 4)}, 0, state, 30, 4);
    EXPECT(result.valid);
    EXPECT_EQ(result.value.integer, 75);
    result = evaluateBytecode(arithmetic.data(), arithmetic.size(),
        {snapshot(3, 3), snapshot(0, 0)}, 0, state, 30, 4);
    EXPECT(!result.valid);

    std::vector<std::uint8_t> bytes;
    op(bytes, Op::ConstBytes); bytes.push_back(4); bytes.insert(bytes.end(), {'A', 'M', 'U', 'N'});
    op(bytes, Op::ConstBytes); bytes.push_back(4); bytes.insert(bytes.end(), {'A', 'M', 'U', 'N'});
    op(bytes, Op::Eq); op(bytes, Op::End);
    EXPECT(evaluateBytecode(bytes.data(), bytes.size(), {}, 0, state, 20, 3).condition);
}
