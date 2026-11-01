#pragma once

namespace amun::threeds {

// Networking is deliberately absent from the initial shared-memory 3GX build.
// Enabling SOC safely requires resolving the private-memory compatibility boundary
// documented in docs/adr/0001-3gx-platform.md.
inline constexpr bool kNetworkingCompiledIn = false;

} // namespace amun::threeds
