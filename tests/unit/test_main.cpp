#include "test.hpp"

#include <iostream>

int main() {
    std::size_t failures = 0;
    for (const amun::test::Case &test : amun::test::registry()) {
        try {
            test.function();
            std::cout << "[PASS] " << test.name << '\n';
        } catch (const std::exception &exception) {
            ++failures;
            std::cerr << "[FAIL] " << test.name << ": " << exception.what() << '\n';
        } catch (...) {
            ++failures;
            std::cerr << "[FAIL] " << test.name << ": unknown exception\n";
        }
    }
    std::cout << (amun::test::registry().size() - failures) << '/' << amun::test::registry().size()
              << " tests passed\n";
    return failures == 0 ? 0 : 1;
}

