#pragma once

#include "amun/pack.hpp"
#include "amun/vm.hpp"

#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <string>
#include <vector>

namespace amun::test {

inline void emitU16(std::vector<std::uint8_t> &code, std::uint16_t value) {
    code.push_back(static_cast<std::uint8_t>(value));
    code.push_back(static_cast<std::uint8_t>(value >> 8U));
}
inline void emitU32(std::vector<std::uint8_t> &code, std::uint32_t value) {
    for (unsigned i = 0; i < 4U; ++i) code.push_back(static_cast<std::uint8_t>(value >> (i * 8U)));
}
inline void emitI64(std::vector<std::uint8_t> &code, std::int64_t value) {
    std::uint64_t raw = 0;
    std::memcpy(&raw, &value, sizeof(raw));
    for (unsigned i = 0; i < 8U; ++i) code.push_back(static_cast<std::uint8_t>(raw >> (i * 8U)));
}
inline void op(std::vector<std::uint8_t> &code, Op value) {
    code.push_back(static_cast<std::uint8_t>(value));
}
inline void load(std::vector<std::uint8_t> &code, Op value, std::uint16_t symbol) {
    op(code, value); emitU16(code, symbol);
}
inline void constant(std::vector<std::uint8_t> &code, std::int64_t value) {
    op(code, Op::ConstI64); emitI64(code, value);
}

inline std::vector<std::uint8_t> equalityProgram(std::uint16_t symbol, std::int64_t value) {
    std::vector<std::uint8_t> code;
    load(code, Op::LoadCurrent, symbol);
    constant(code, value);
    op(code, Op::Eq);
    op(code, Op::End);
    return code;
}

inline AchievementPack basicPack(std::vector<std::uint8_t> program = equalityProgram(0, 0)) {
    AchievementPack pack;
    pack.titleId = 0x000400000ABCDEF0ULL;
    pack.gameName = "AMUN Synthetic Game";
    pack.profileVersion = "1.0.0";
    pack.builds.push_back({"synthetic-eur-1.0", "EUR", "1.0", "0", "0123456789abcdef", false});
    SymbolDefinition symbol;
    symbol.name = "boss.hp";
    symbol.type = ValueType::U16;
    symbol.pollClass = PollClass::Normal;
    symbol.resolver.kind = ResolverKind::Absolute;
    symbol.resolver.address = 0x08001000U;
    pack.symbols.push_back(symbol);
    AchievementDefinition achievement;
    achievement.id = "first_boss";
    achievement.title = "An Old Score";
    achievement.description = "Defeat the synthetic boss.";
    achievement.points = 10;
    achievement.maxStack = 8;
    achievement.stateSlots = 8;
    achievement.instructionBudget = 128;
    achievement.bytecode = std::move(program);
    pack.achievements.push_back(std::move(achievement));
    return pack;
}

inline GameIdentity basicIdentity() {
    return {0x000400000ABCDEF0ULL, "EUR", "1.0", "0", "0123456789abcdef", 0x00100000U};
}

} // namespace amun::test

