# Declarative condition language

AMUN conditions are JSON trees compiled into verified postfix bytecode. They are not
scripts: there are no functions, variables, file/network APIs, native calls, writes,
jumps, or loops. Every child is compiled and evaluated, so Boolean groups do not
short-circuit stateful children.

The JSON Schema accepts the structural shape; the compiler is authoritative for valid
operation names, operands, stack effects, state-slot allocation, and limits.

## Values

A value expression is one of:

```json
7
3.5
true
"player.hp"
{"symbol": "player.hp"}
{"symbol": "player.hp", "state": "previous"}
{"const": 100}
{"bytes": "52 45 41 44 59 00"}
{"string": "READY"}
{"op": "multiply", "left": "player.hp", "right": 100}
```

Symbol state is `current` (default), `previous`, or `initial`. Previous/initial are
available only after the runtime has sampled the symbol accordingly. Byte and UTF-8
string constants occupy 1–16 bytes; equality requires both byte sequences to have the
same length and bytes.

Arithmetic operations are `add`, `subtract`, `multiply`, `divide`, `bit_and`, and
`bit_or`; `+`, `-`, `*`, and `/` are aliases. Signed-integer add/subtract/multiply
saturate at 64-bit limits. Integer division truncates toward zero and the `INT64_MIN / -1`
case saturates to `INT64_MAX`. Division by zero and non-finite floating results fail
the evaluation. Arithmetic on byte sequences is invalid.

## Comparisons

Shorthand and explicit forms are equivalent:

```json
{"op": "eq", "symbol": "boss.hp", "value": 0}
{"op": "eq", "left": {"symbol": "boss.hp"}, "right": 0}
```

Supported operations and aliases:

| Operation | Meaning |
|---|---|
| `eq`, `==`, `equals` | equal |
| `ne`, `!=` | not equal |
| `lt`, `<` | less than |
| `le`, `<=` | less than or equal |
| `gt`, `>` | greater than |
| `ge`, `>=` | greater than or equal |
| `between` | inclusive lower/upper bound |
| `bit_set`, `bitset` | every bit in mask is set |
| `bit_clear`, `bitclear` | no bit in mask is set |
| `masked_equals`, `masked_eq` | `(value & mask) == expected` |

Examples:

```json
{"op": "between", "symbol": "player.hp", "lower": 1, "upper": 10}
{"op": "bit_set", "symbol": "world.flags", "mask": 8}
{"op": "masked_equals", "symbol": "state.flags", "mask": 240, "value": 160}
```

`between` also accepts `min`/`max`. Ordered comparisons and bit operations are for
numeric values. Use `eq`/`ne` for `bytes` and `fixed_string`.

## History predicates

History operations name one symbol directly:

```json
{"op": "changed", "symbol": "player.hp"}
{"op": "increased_by", "symbol": "score", "amount": 100}
```

| Operation | True when |
|---|---|
| `changed` | current differs from previous |
| `unchanged` | current equals previous |
| `increased` | current is greater than previous |
| `decreased` | current is less than previous |
| `increased_by` | `current - previous == amount` |
| `decreased_by` | `current - previous == -amount` |

All return false until a valid previous sample exists. Delta amounts are non-negative
signed 64-bit integers. A symbol sampled more slowly can retain the same previous/
current pair across several achievement ticks; choose polling classes with that fact
in mind.

## Boolean composition

Compact tree forms:

```json
{
  "all": [
    {"op": "eq", "symbol": "boss.hp", "value": 0},
    {"op": "gt", "symbol": "player.hp", "value": 0}
  ]
}
```

```json
{"any": [true, {"op": "eq", "symbol": "stage.id", "value": 7}]}
{"not": {"op": "bit_set", "symbol": "status.flags", "mask": 4}}
```

Explicit `{"op":"all","conditions":[...]}`, `any`, and
`{"op":"not","condition":...}` are also accepted. ALL/ANY groups contain 1–255
children. Even if an early child determines the Boolean result, later children still
evaluate so their counters/timers have deterministic state.

## Edges, counters, and latch

### Rising and falling

```json
{"op": "rising", "condition": {"op": "eq", "symbol": "boss.hp", "value": 0}}
```

`rising` emits on false-to-true; `falling` on true-to-false. Their first evaluation
only records the current value and returns false. This priming rule prevents loading a
save in an already-true state from fabricating a transition. `one_shot` and
`one-shot` are aliases for `rising`; durable achievement unlock suppression is also
enforced by the ledger.

### Hit count

```json
{
  "op": "hit_count",
  "count": 3,
  "condition": {"op": "eq", "symbol": "combo.state", "value": 1}
}
```

The first evaluation primes the edge detector. Each later false-to-true transition
adds one, up to the 1–65535 target. Remaining true for several ticks counts once.
Aliases are `hitcount`; `target` may replace `count`.

### Consecutive

```json
{"op": "consecutive", "count": 10, "condition": {"op": "gt", "symbol": "speed", "value": 5}}
```

Each true evaluation increments the count; false resets it to zero. This measures
polls, not frames or milliseconds. Use `duration` for time.

### Latch

```json
{"op": "latch", "condition": {"op": "eq", "symbol": "battle.id", "value": 7}}
```

Once true, a latch remains true until its containing VM state is reset or the session
ends.

## Time

```json
{
  "op": "duration",
  "milliseconds": 30000,
  "condition": {"op": "eq", "symbol": "challenge.active", "value": 1}
}
```

`duration` becomes true after the condition stays continuously true for the requested
1–4,294,967,295 ms. False clears the timer. Timing uses the injected monotonic clock;
changing the 3DS wall clock cannot complete it.

```json
{
  "op": "cooldown",
  "durationMs": 1000,
  "condition": {"op": "eq", "symbol": "event.flag", "value": 1}
}
```

`cooldown` emits on a rising edge when no prior emission exists or the interval since
the last emission has elapsed. Unlike `rising`, an initially true cooldown condition
is eligible to emit on its first evaluation. If initialization must never count, wrap
or structure the rule around an explicitly primed edge. `milliseconds`, `durationMs`,
and `target` are accepted duration keys.

## Sequence

```json
{
  "op": "sequence",
  "conditions": [
    {"op": "eq", "symbol": "battle.id", "value": 7},
    {"op": "eq", "symbol": "boss.hp", "value": 0}
  ]
}
```

A sequence contains 1–255 stages. It primes the current stage on its first evaluation,
then advances only on a later false-to-true edge for that stage. On advance it samples
the next stage's current value as the new baseline, so two stages already true on the
same tick do not collapse into two events. It remains true after the final stage until
reset/session end.

## Reset and pause gates

```json
{
  "op": "reset_if",
  "condition": {"op": "rising", "condition": {"op": "eq", "symbol": "boss.hp", "value": 0}},
  "reset": {"op": "increased", "symbol": "healing.used"}
}
```

The main condition and reset gate both evaluate. When the gate is true, every state
slot in that achievement program is reset and the operation returns false. Reset does
not itself create a permanent disqualification; if failure must remain remembered,
model that fact explicitly with a latch or stable symbol and test later frames.

```json
{
  "op": "pause_if",
  "condition": {"op": "duration", "milliseconds": 5000, "condition": true},
  "pause": {"op": "eq", "symbol": "game.paused", "value": 1}
}
```

When the pause gate is true, the operation returns false and rolls state slots back to
their values at the start of that program evaluation. Timers/counters therefore do
not advance on paused ticks. The gate is declarative achievement state; console HOME,
sleep, and swap lifecycle also suspend the entire runtime at the platform boundary.

## Measured progress

```json
{"op": "set_progress", "symbol": "collectibles.count", "target": 50}
```

Or use any numeric value expression:

```json
{"op": "set_progress", "value": {"symbol": "enemy.count"}, "target": 100}
```

The value is clamped to `0..target`; the condition is true at the target. Runtime
progress checkpoints are throttled to meaningful increases and written before any
optional network event. Targets are 1–4,294,967,295. One compiled achievement has one
progress target.

## State initialization and unlock semantics

At session start the runtime resolves all symbols, samples according to the read plan,
and initializes history. A program is evaluated only with valid required values.
Achievement prerequisites and existing ledger unlocks are checked outside the VM. A
true program appends an unlock event durably; duplicate IDs/events are ignored on
later ticks and sessions.

Test every stateful rule with at least:

- an initialization frame where the condition is already true;
- a genuine false-to-true (or true-to-false) transition;
- a negative path;
- reset/pause behavior where used;
- a restart scenario for durable unlock suppression.

## Hard limits

- source nesting: 32;
- Boolean/sequence children: 255;
- bytecode: 256 KiB section ceiling;
- stack: 64 values;
- state slots: 256 per program;
- instructions: 2048 per achievement, plus a global per-tick runtime budget;
- no arbitrary jumps or loops.

Use `python3 amun.py pack inspect game.amunpack --disassemble` and Studio's condition
debugger to see the exact compiled operations and state allocation.
