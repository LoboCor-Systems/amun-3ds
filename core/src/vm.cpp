#include "amun/vm.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>

namespace amun {

namespace {

bool takeU8(const std::uint8_t *code, std::size_t size, std::size_t &pc, std::uint8_t &out) noexcept {
    if (pc >= size) {
        return false;
    }
    out = code[pc++];
    return true;
}

bool takeU16(const std::uint8_t *code, std::size_t size, std::size_t &pc, std::uint16_t &out) noexcept {
    if (size - std::min(size, pc) < 2U) {
        return false;
    }
    out = static_cast<std::uint16_t>(code[pc]) |
          static_cast<std::uint16_t>(static_cast<std::uint16_t>(code[pc + 1U]) << 8U);
    pc += 2U;
    return true;
}

bool takeU32(const std::uint8_t *code, std::size_t size, std::size_t &pc, std::uint32_t &out) noexcept {
    if (size - std::min(size, pc) < 4U) {
        return false;
    }
    out = static_cast<std::uint32_t>(code[pc]) |
          (static_cast<std::uint32_t>(code[pc + 1U]) << 8U) |
          (static_cast<std::uint32_t>(code[pc + 2U]) << 16U) |
          (static_cast<std::uint32_t>(code[pc + 3U]) << 24U);
    pc += 4U;
    return true;
}

bool takeI64(const std::uint8_t *code, std::size_t size, std::size_t &pc, std::int64_t &out) noexcept {
    if (size - std::min(size, pc) < 8U) {
        return false;
    }
    std::uint64_t raw = 0;
    for (unsigned i = 0; i < 8U; ++i) {
        raw |= static_cast<std::uint64_t>(code[pc + i]) << (i * 8U);
    }
    pc += 8U;
    std::memcpy(&out, &raw, sizeof(out));
    return true;
}

bool takeF32(const std::uint8_t *code, std::size_t size, std::size_t &pc, float &out) noexcept {
    std::uint32_t raw = 0;
    if (!takeU32(code, size, pc, raw)) {
        return false;
    }
    std::memcpy(&out, &raw, sizeof(out));
    return true;
}

bool truthy(const Scalar &value) noexcept {
    if (value.kind == Scalar::Kind::Floating) return value.floating != 0.0F;
    if (value.kind == Scalar::Kind::Integer) return value.integer != 0;
    for (std::size_t i = 0; i < value.byteCount; ++i) {
        if (value.bytes[i] != 0) return true;
    }
    return false;
}

Scalar boolean(bool value) noexcept { return Scalar::fromInteger(value ? 1 : 0); }

std::int64_t saturatingAdd(std::int64_t left, std::int64_t right) noexcept {
    if (right > 0 && left > std::numeric_limits<std::int64_t>::max() - right)
        return std::numeric_limits<std::int64_t>::max();
    if (right < 0 && left < std::numeric_limits<std::int64_t>::min() - right)
        return std::numeric_limits<std::int64_t>::min();
    return left + right;
}

std::int64_t saturatingSubtract(std::int64_t left, std::int64_t right) noexcept {
    if (right < 0 && left > std::numeric_limits<std::int64_t>::max() + right)
        return std::numeric_limits<std::int64_t>::max();
    if (right > 0 && left < std::numeric_limits<std::int64_t>::min() + right)
        return std::numeric_limits<std::int64_t>::min();
    return left - right;
}

std::int64_t saturatingMultiply(std::int64_t left, std::int64_t right) noexcept {
    if (left == 0 || right == 0) return 0;
    const auto maximum = std::numeric_limits<std::int64_t>::max();
    const auto minimum = std::numeric_limits<std::int64_t>::min();
    if ((left == minimum && right == -1) || (right == minimum && left == -1)) return maximum;
    if (left > 0) {
        if (right > 0 && left > maximum / right) return maximum;
        if (right < 0 && right < minimum / left) return minimum;
    } else {
        if (right > 0 && left < minimum / right) return minimum;
        if (right < 0 && right < maximum / left) return maximum;
    }
    return left * right;
}

bool equal(const Scalar &left, const Scalar &right) noexcept {
    if (left.kind == Scalar::Kind::Bytes || right.kind == Scalar::Kind::Bytes) {
        if (left.kind != right.kind || left.byteCount != right.byteCount) return false;
        return std::equal(left.bytes.begin(), left.bytes.begin() + left.byteCount, right.bytes.begin());
    }
    if (left.kind == Scalar::Kind::Integer && right.kind == Scalar::Kind::Integer) {
        return left.integer == right.integer;
    }
    return left.asDouble() == right.asDouble();
}

bool requireStack(std::int32_t stack, std::int32_t required, VmVerifyResult &result,
                  std::size_t pc) {
    if (stack >= required) {
        return true;
    }
    result.error = "stack underflow at byte " + std::to_string(pc);
    return false;
}

bool updateSlotMaximum(std::uint16_t slot, std::uint32_t &slotMaximum,
                       const RuntimeLimits &limits, VmVerifyResult &result) {
    slotMaximum = std::max(slotMaximum, static_cast<std::uint32_t>(slot) + 1U);
    if (slotMaximum > limits.maxVmStateSlots) {
        result.error = "state slot limit exceeded";
        return false;
    }
    return true;
}

} // namespace

void VmState::reset() noexcept {
    for (VmSlotState &slot : slots) {
        slot = {};
    }
    paused = false;
}

VmVerifyResult verifyBytecode(const std::uint8_t *code, std::size_t size,
                              std::size_t symbolCount, const RuntimeLimits &limits) {
    VmVerifyResult result;
    if (code == nullptr || size == 0 || size > limits.maxBytecodeBytes) {
        result.error = "empty or oversized bytecode";
        return result;
    }
    std::size_t pc = 0;
    std::int32_t stack = 0;
    std::int32_t maximumStack = 0;
    std::uint32_t slotMaximum = 0;
    bool ended = false;

    auto requireSymbol = [&](std::uint16_t symbol) {
        if (symbol >= symbolCount) {
            result.error = "symbol index out of range at byte " + std::to_string(pc);
            return false;
        }
        return true;
    };

    while (pc < size) {
        if (++result.instructions > limits.maxInstructionsPerAchievement) {
            result.error = "instruction limit exceeded";
            return result;
        }
        const std::size_t instructionAt = pc;
        std::uint8_t raw = 0;
        takeU8(code, size, pc, raw);
        const Op op = static_cast<Op>(raw);
        std::uint16_t index = 0;
        std::uint16_t slot = 0;
        std::uint16_t target16 = 0;
        std::uint32_t target32 = 0;
        std::uint8_t count = 0;
        std::int64_t amount = 0;
        float floatValue = 0.0F;

        switch (op) {
        case Op::LoadCurrent:
        case Op::LoadPrevious:
        case Op::LoadInitial:
            if (!takeU16(code, size, pc, index) || !requireSymbol(index)) {
                if (result.error.empty()) result.error = "truncated symbol operand";
                return result;
            }
            ++stack;
            break;
        case Op::ConstI64:
            if (!takeI64(code, size, pc, amount)) {
                result.error = "truncated integer constant";
                return result;
            }
            ++stack;
            break;
        case Op::ConstF32:
            if (!takeF32(code, size, pc, floatValue) || !std::isfinite(floatValue)) {
                result.error = "invalid float constant";
                return result;
            }
            ++stack;
            break;
        case Op::ConstBytes:
            if (!takeU8(code, size, pc, count) || count == 0 || count > 16 ||
                pc > size || size - pc < count) {
                result.error = "invalid byte-sequence constant";
                return result;
            }
            pc += count;
            ++stack;
            break;
        case Op::Eq:
        case Op::Ne:
        case Op::Lt:
        case Op::Le:
        case Op::Gt:
        case Op::Ge:
        case Op::BitSet:
        case Op::BitClear:
        case Op::Add:
        case Op::Subtract:
        case Op::Multiply:
        case Op::Divide:
        case Op::BitAnd:
        case Op::BitOr:
            if (!requireStack(stack, 2, result, instructionAt)) return result;
            --stack;
            break;
        case Op::Between:
        case Op::MaskedEquals:
            if (!requireStack(stack, 3, result, instructionAt)) return result;
            stack -= 2;
            break;
        case Op::Changed:
        case Op::Unchanged:
        case Op::Increased:
        case Op::Decreased:
            if (!takeU16(code, size, pc, index) || !requireSymbol(index)) {
                if (result.error.empty()) result.error = "truncated history operand";
                return result;
            }
            ++stack;
            break;
        case Op::IncreasedBy:
        case Op::DecreasedBy:
            if (!takeU16(code, size, pc, index) || !takeI64(code, size, pc, amount) ||
                !requireSymbol(index)) {
                if (result.error.empty()) result.error = "truncated delta operand";
                return result;
            }
            ++stack;
            break;
        case Op::All:
        case Op::Any:
            if (!takeU8(code, size, pc, count) || count == 0) {
                result.error = "invalid Boolean group";
                return result;
            }
            if (!requireStack(stack, count, result, instructionAt)) return result;
            stack -= static_cast<std::int32_t>(count) - 1;
            break;
        case Op::Not:
            if (!requireStack(stack, 1, result, instructionAt)) return result;
            break;
        case Op::Rising:
        case Op::Falling:
        case Op::Latch:
            if (!takeU16(code, size, pc, slot) || !requireStack(stack, 1, result, instructionAt) ||
                !updateSlotMaximum(slot, slotMaximum, limits, result)) return result;
            break;
        case Op::HitCount:
        case Op::Consecutive:
            if (!takeU16(code, size, pc, slot) || !takeU16(code, size, pc, target16) || target16 == 0 ||
                !requireStack(stack, 1, result, instructionAt) ||
                !updateSlotMaximum(slot, slotMaximum, limits, result)) {
                if (result.error.empty()) result.error = "invalid counter operand";
                return result;
            }
            break;
        case Op::Duration:
        case Op::Cooldown:
            if (!takeU16(code, size, pc, slot) || !takeU32(code, size, pc, target32) || target32 == 0 ||
                !requireStack(stack, 1, result, instructionAt) ||
                !updateSlotMaximum(slot, slotMaximum, limits, result)) {
                if (result.error.empty()) result.error = "invalid timer operand";
                return result;
            }
            break;
        case Op::Sequence:
            if (!takeU16(code, size, pc, slot) || !takeU8(code, size, pc, count) || count == 0 ||
                !requireStack(stack, count, result, instructionAt) ||
                !updateSlotMaximum(slot, slotMaximum, limits, result)) {
                if (result.error.empty()) result.error = "invalid sequence operand";
                return result;
            }
            stack -= static_cast<std::int32_t>(count) - 1;
            break;
        case Op::ResetIf:
        case Op::PauseIf:
            if (!requireStack(stack, 2, result, instructionAt)) return result;
            --stack;
            break;
        case Op::SetProgress:
            if (!takeU32(code, size, pc, target32) || target32 == 0 ||
                !requireStack(stack, 1, result, instructionAt)) {
                if (result.error.empty()) result.error = "invalid progress target";
                return result;
            }
            break;
        case Op::End:
            if (pc != size || stack != 1) {
                result.error = "END must terminate a program with exactly one result";
                return result;
            }
            ended = true;
            break;
        default:
            result.error = "unknown opcode " + std::to_string(raw) + " at byte " +
                           std::to_string(instructionAt);
            return result;
        }
        maximumStack = std::max(maximumStack, stack);
        if (maximumStack > limits.maxVmStack) {
            result.error = "VM stack limit exceeded";
            return result;
        }
        if (ended) break;
    }
    if (!ended) {
        result.error = "program has no END";
        return result;
    }
    result.valid = true;
    result.maximumStack = static_cast<std::uint16_t>(maximumStack);
    result.stateSlots = static_cast<std::uint16_t>(slotMaximum);
    return result;
}

VmEvalResult evaluateBytecode(const std::uint8_t *code, std::size_t size,
                              const std::vector<SymbolSnapshot> &symbols,
                              Milliseconds monotonicMs, VmState &state,
                              std::uint32_t instructionBudget,
                              std::uint16_t stackLimit) {
    VmEvalResult result;
    if (code == nullptr || size == 0 || stackLimit == 0 || stackLimit > 256) {
        result.error = "invalid VM arguments";
        return result;
    }
    std::array<Scalar, 256> stack{};
    std::size_t stackSize = 0;
    if (state.slots.size() > 256U) {
        result.error = "state slot limit exceeded";
        return result;
    }
    std::array<VmSlotState, 256> initialSlots{};
    std::copy(state.slots.begin(), state.slots.end(), initialSlots.begin());
    const bool initialPaused = state.paused;
    std::size_t pc = 0;

    auto fail = [&](const char *message) {
        result.error = message;
        return result;
    };
    auto push = [&](Scalar value) {
        if (stackSize >= stackLimit || stackSize >= stack.size()) return false;
        stack[stackSize++] = value;
        return true;
    };
    auto pop = [&](Scalar &value) {
        if (stackSize == 0) return false;
        value = stack[--stackSize];
        return true;
    };
    auto slotFor = [&](std::uint16_t index) -> VmSlotState * {
        if (index >= state.slots.size()) return nullptr;
        return &state.slots[index];
    };
    auto snapshotFor = [&](std::uint16_t index) -> const SymbolSnapshot * {
        if (index >= symbols.size() || !symbols[index].valid) return nullptr;
        return &symbols[index];
    };

    while (pc < size) {
        if (++result.instructions > instructionBudget) {
            return fail("runtime instruction budget exceeded");
        }
        std::uint8_t raw = 0;
        if (!takeU8(code, size, pc, raw)) return fail("truncated opcode");
        const Op op = static_cast<Op>(raw);
        std::uint16_t index = 0;
        std::uint16_t slotIndex = 0;
        std::uint16_t target16 = 0;
        std::uint32_t target32 = 0;
        std::uint8_t count = 0;
        std::int64_t integer = 0;
        float floating = 0.0F;
        Scalar left;
        Scalar right;
        Scalar third;

        switch (op) {
        case Op::LoadCurrent:
        case Op::LoadPrevious:
        case Op::LoadInitial: {
            if (!takeU16(code, size, pc, index)) return fail("truncated symbol index");
            const SymbolSnapshot *snapshot = snapshotFor(index);
            if (snapshot == nullptr) return fail("unavailable symbol");
            Scalar value = snapshot->current;
            if (op == Op::LoadPrevious && snapshot->hasPrevious) value = snapshot->previous;
            if (op == Op::LoadInitial && snapshot->hasInitial) value = snapshot->initial;
            if (!push(value)) return fail("VM stack overflow");
            break;
        }
        case Op::ConstI64:
            if (!takeI64(code, size, pc, integer) || !push(Scalar::fromInteger(integer)))
                return fail("invalid integer constant");
            break;
        case Op::ConstF32:
            if (!takeF32(code, size, pc, floating) || !std::isfinite(floating) ||
                !push(Scalar::fromFloat(floating))) return fail("invalid float constant");
            break;
        case Op::ConstBytes:
            if (!takeU8(code, size, pc, count) || count == 0 || count > 16 ||
                pc > size || size - pc < count || !push(Scalar::fromBytes(code + pc, count)))
                return fail("invalid byte-sequence constant");
            pc += count;
            break;
        case Op::Eq:
        case Op::Ne:
        case Op::Lt:
        case Op::Le:
        case Op::Gt:
        case Op::Ge:
        case Op::BitSet:
        case Op::BitClear:
        case Op::Add:
        case Op::Subtract:
        case Op::Multiply:
        case Op::Divide:
        case Op::BitAnd:
        case Op::BitOr:
            if (!pop(right) || !pop(left)) return fail("VM stack underflow");
            if ((left.kind == Scalar::Kind::Bytes || right.kind == Scalar::Kind::Bytes) &&
                op != Op::Eq && op != Op::Ne) return fail("invalid operation on byte sequence");
            if (op == Op::Eq) third = boolean(equal(left, right));
            else if (op == Op::Ne) third = boolean(!equal(left, right));
            else if (op == Op::Lt) third = boolean(left.asDouble() < right.asDouble());
            else if (op == Op::Le) third = boolean(left.asDouble() <= right.asDouble());
            else if (op == Op::Gt) third = boolean(left.asDouble() > right.asDouble());
            else if (op == Op::Ge) third = boolean(left.asDouble() >= right.asDouble());
            else if (op == Op::BitSet)
                third = boolean((left.asInteger() & right.asInteger()) == right.asInteger());
            else if (op == Op::BitClear) third = boolean((left.asInteger() & right.asInteger()) == 0);
            else if (op == Op::Add) {
                third = left.kind == Scalar::Kind::Floating || right.kind == Scalar::Kind::Floating
                    ? Scalar::fromFloat(static_cast<float>(left.asDouble() + right.asDouble()))
                    : Scalar::fromInteger(saturatingAdd(left.integer, right.integer));
            } else if (op == Op::Subtract) {
                third = left.kind == Scalar::Kind::Floating || right.kind == Scalar::Kind::Floating
                    ? Scalar::fromFloat(static_cast<float>(left.asDouble() - right.asDouble()))
                    : Scalar::fromInteger(saturatingSubtract(left.integer, right.integer));
            } else if (op == Op::Multiply) {
                third = left.kind == Scalar::Kind::Floating || right.kind == Scalar::Kind::Floating
                    ? Scalar::fromFloat(static_cast<float>(left.asDouble() * right.asDouble()))
                    : Scalar::fromInteger(saturatingMultiply(left.integer, right.integer));
            } else if (op == Op::Divide) {
                if (right.asDouble() == 0.0) return fail("division by zero");
                third = left.kind == Scalar::Kind::Floating || right.kind == Scalar::Kind::Floating
                    ? Scalar::fromFloat(static_cast<float>(left.asDouble() / right.asDouble()))
                    : Scalar::fromInteger(left.integer == std::numeric_limits<std::int64_t>::min() &&
                                                  right.integer == -1
                                              ? std::numeric_limits<std::int64_t>::max()
                                              : left.integer / right.integer);
            } else if (op == Op::BitAnd) third = Scalar::fromInteger(left.asInteger() & right.asInteger());
            else third = Scalar::fromInteger(left.asInteger() | right.asInteger());
            if (third.kind == Scalar::Kind::Floating && !std::isfinite(third.floating))
                return fail("non-finite arithmetic result");
            if (!push(third)) return fail("VM stack overflow");
            break;
        case Op::Between:
            if (!pop(third) || !pop(right) || !pop(left)) return fail("VM stack underflow");
            if (!push(boolean(left.asDouble() >= right.asDouble() &&
                              left.asDouble() <= third.asDouble()))) return fail("VM stack overflow");
            break;
        case Op::MaskedEquals:
            if (!pop(third) || !pop(right) || !pop(left)) return fail("VM stack underflow");
            if (!push(boolean((left.asInteger() & right.asInteger()) == third.asInteger())))
                return fail("VM stack overflow");
            break;
        case Op::Changed:
        case Op::Unchanged:
        case Op::Increased:
        case Op::Decreased: {
            if (!takeU16(code, size, pc, index)) return fail("truncated history index");
            const SymbolSnapshot *snapshot = snapshotFor(index);
            if (snapshot == nullptr) return fail("unavailable history symbol");
            bool value = false;
            if (snapshot->hasPrevious) {
                if (op == Op::Changed) value = !equal(snapshot->current, snapshot->previous);
                else if (op == Op::Unchanged) value = equal(snapshot->current, snapshot->previous);
                else if (op == Op::Increased)
                    value = snapshot->current.asDouble() > snapshot->previous.asDouble();
                else value = snapshot->current.asDouble() < snapshot->previous.asDouble();
            }
            if (!push(boolean(value))) return fail("VM stack overflow");
            break;
        }
        case Op::IncreasedBy:
        case Op::DecreasedBy: {
            if (!takeU16(code, size, pc, index) || !takeI64(code, size, pc, integer))
                return fail("truncated delta operand");
            const SymbolSnapshot *snapshot = snapshotFor(index);
            if (snapshot == nullptr) return fail("unavailable delta symbol");
            const double delta = snapshot->current.asDouble() - snapshot->previous.asDouble();
            const bool value = snapshot->hasPrevious &&
                (op == Op::IncreasedBy ? delta == static_cast<double>(integer)
                                       : delta == -static_cast<double>(integer));
            if (!push(boolean(value))) return fail("VM stack overflow");
            break;
        }
        case Op::All:
        case Op::Any: {
            if (!takeU8(code, size, pc, count) || count == 0 || stackSize < count)
                return fail("invalid Boolean group");
            bool value = op == Op::All;
            for (std::uint8_t i = 0; i < count; ++i) {
                pop(left);
                if (op == Op::All) value = value && truthy(left);
                else value = value || truthy(left);
            }
            if (!push(boolean(value))) return fail("VM stack overflow");
            break;
        }
        case Op::Not:
            if (!pop(left) || !push(boolean(!truthy(left)))) return fail("invalid NOT");
            break;
        case Op::Rising:
        case Op::Falling:
        case Op::Latch: {
            if (!takeU16(code, size, pc, slotIndex) || !pop(left)) return fail("invalid state operand");
            VmSlotState *slot = slotFor(slotIndex);
            if (slot == nullptr) return fail("state slot out of range");
            const bool current = truthy(left);
            bool value = false;
            if (op == Op::Rising || op == Op::Falling) {
                if (!slot->active) {
                    slot->active = true;
                } else if (op == Op::Rising) {
                    value = current && !slot->previous;
                } else {
                    value = !current && slot->previous;
                }
            } else {
                if (current) slot->latched = true;
                value = slot->latched;
            }
            slot->previous = current;
            if (!push(boolean(value))) return fail("VM stack overflow");
            break;
        }
        case Op::HitCount:
        case Op::Consecutive: {
            if (!takeU16(code, size, pc, slotIndex) || !takeU16(code, size, pc, target16) ||
                !pop(left)) return fail("invalid counter operand");
            VmSlotState *slot = slotFor(slotIndex);
            if (slot == nullptr || target16 == 0) return fail("invalid counter slot");
            const bool current = truthy(left);
            if (op == Op::HitCount) {
                if (!slot->active) slot->active = true;
                else if (current && !slot->previous && slot->count < target16) ++slot->count;
                slot->previous = current;
            } else {
                slot->count = current ? std::min<std::uint32_t>(slot->count + 1U, target16) : 0U;
            }
            if (!push(boolean(slot->count >= target16))) return fail("VM stack overflow");
            break;
        }
        case Op::Duration: {
            if (!takeU16(code, size, pc, slotIndex) || !takeU32(code, size, pc, target32) ||
                !pop(left)) return fail("invalid duration operand");
            VmSlotState *slot = slotFor(slotIndex);
            if (slot == nullptr || target32 == 0) return fail("invalid duration slot");
            const bool current = truthy(left);
            if (current && !slot->active) {
                slot->active = true;
                slot->startedAt = monotonicMs;
            } else if (!current) {
                slot->active = false;
                slot->startedAt = 0;
            }
            const bool value = current && slot->active && monotonicMs >= slot->startedAt &&
                               monotonicMs - slot->startedAt >= target32;
            if (!push(boolean(value))) return fail("VM stack overflow");
            break;
        }
        case Op::Cooldown: {
            if (!takeU16(code, size, pc, slotIndex) || !takeU32(code, size, pc, target32) ||
                !pop(left)) return fail("invalid cooldown operand");
            VmSlotState *slot = slotFor(slotIndex);
            if (slot == nullptr || target32 == 0) return fail("invalid cooldown slot");
            const bool current = truthy(left);
            const bool edge = current && !slot->previous;
            const bool elapsed = !slot->latched ||
                                 (monotonicMs >= slot->lastAt && monotonicMs - slot->lastAt >= target32);
            const bool value = edge && elapsed;
            if (value) {
                slot->latched = true;
                slot->lastAt = monotonicMs;
            }
            slot->previous = current;
            if (!push(boolean(value))) return fail("VM stack overflow");
            break;
        }
        case Op::Sequence: {
            if (!takeU16(code, size, pc, slotIndex) || !takeU8(code, size, pc, count) ||
                count == 0 || stackSize < count) return fail("invalid sequence operand");
            VmSlotState *slot = slotFor(slotIndex);
            if (slot == nullptr) return fail("invalid sequence slot");
            std::array<bool, 256> conditions{};
            for (std::size_t i = count; i > 0; --i) {
                pop(left);
                conditions[i - 1U] = truthy(left);
            }
            if (!slot->active && slot->stage < count) {
                slot->active = true;
                slot->previous = conditions[slot->stage];
            } else if (slot->stage < count) {
                const bool current = conditions[slot->stage];
                if (current && !slot->previous) {
                    ++slot->stage;
                    slot->previous = slot->stage < count ? conditions[slot->stage] : false;
                } else {
                    slot->previous = current;
                }
            }
            if (!push(boolean(slot->stage >= count))) return fail("VM stack overflow");
            break;
        }
        case Op::ResetIf:
            if (!pop(right) || !pop(left)) return fail("invalid reset operand");
            if (truthy(right)) {
                state.reset();
                left = boolean(false);
            }
            if (!push(left)) return fail("VM stack overflow");
            break;
        case Op::PauseIf:
            if (!pop(right) || !pop(left)) return fail("invalid pause operand");
            state.paused = truthy(right);
            if (state.paused) {
                std::copy(initialSlots.begin(), initialSlots.begin() + state.slots.size(), state.slots.begin());
            } else if (initialPaused) {
                state.paused = false;
            }
            if (!push(boolean(!state.paused && truthy(left)))) return fail("VM stack overflow");
            break;
        case Op::SetProgress: {
            if (!takeU32(code, size, pc, target32) || target32 == 0 || !pop(left))
                return fail("invalid progress operand");
            const double rawProgress = std::max(0.0, left.asDouble());
            const auto bounded = static_cast<std::uint32_t>(
                std::min(rawProgress, static_cast<double>(target32)));
            result.progressChanged = bounded != result.progress;
            result.progress = bounded;
            if (!push(boolean(bounded >= target32))) return fail("VM stack overflow");
            break;
        }
        case Op::End:
            if (pc != size || stackSize != 1U) return fail("invalid END state");
            result.valid = true;
            result.value = stack[0];
            result.condition = truthy(stack[0]);
            return result;
        default:
            return fail("unknown opcode");
        }
    }
    return fail("program ended without END");
}

} // namespace amun
