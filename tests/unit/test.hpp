#pragma once

#include <exception>
#include <functional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace amun::test {

struct Case { const char *name; void (*function)(); };
inline std::vector<Case> &registry() { static std::vector<Case> cases; return cases; }
struct Registrar {
    Registrar(const char *name, void (*function)()) { registry().push_back({name, function}); }
};

inline void fail(const char *expression, const char *file, int line, const std::string &detail = {}) {
    std::ostringstream message;
    message << file << ':' << line << ": expectation failed: " << expression;
    if (!detail.empty()) message << " (" << detail << ')';
    throw std::runtime_error(message.str());
}

} // namespace amun::test

#define AMUN_JOIN_INNER(a, b) a##b
#define AMUN_JOIN(a, b) AMUN_JOIN_INNER(a, b)
#define TEST(name) \
    static void AMUN_JOIN(test_, __LINE__)(); \
    static ::amun::test::Registrar AMUN_JOIN(registrar_, __LINE__)(name, &AMUN_JOIN(test_, __LINE__)); \
    static void AMUN_JOIN(test_, __LINE__)()
#define EXPECT(condition) do { if (!(condition)) ::amun::test::fail(#condition, __FILE__, __LINE__); } while (false)
#define EXPECT_EQ(left, right) do { const auto &_l = (left); const auto &_r = (right); \
    if (!(_l == _r)) ::amun::test::fail(#left " == " #right, __FILE__, __LINE__); } while (false)
#define EXPECT_NE(left, right) do { const auto &_l = (left); const auto &_r = (right); \
    if (_l == _r) ::amun::test::fail(#left " != " #right, __FILE__, __LINE__); } while (false)

