#pragma once

namespace amun::threeds {

// CTRPF uses "selectable" to mean that the cursor may land on a row. An
// information-only MenuEntry has no callback, so pressing A remains inert.
inline constexpr bool kInformationRowsSelectable = true;

// At the root folder CTRPF only turns B into "close the overlay" when this
// framework setting is enabled explicitly.
inline constexpr bool kCloseMenuWithB = true;

} // namespace amun::threeds
