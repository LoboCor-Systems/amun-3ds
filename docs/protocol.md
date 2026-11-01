# Optional AMUN Hub protocol (AMNP v1)

AMNP is a small framed TCP protocol implemented by `hub/protocol.py` and
`hub/server.py`. It is optional: unlocks are committed to the console ledger before
any network work, and the stable 3DS build currently compiles networking out. Hub is
host tested, but no console AMNP client or original-2DS networking result is claimed.

Default listen address is `0.0.0.0:43831`:

```sh
python3 -m hub --host 127.0.0.1 --port 43831 --data ./hub-data
```

Binding to loopback is safest for local testing. Binding to all interfaces should be
used only on a trusted LAN with firewall rules appropriate to the machine.

## Frame

Every frame is a 32-byte little-endian `<4sBBHII16s>` header followed by one canonical
UTF-8 JSON object:

| Offset | Type | Field |
|---:|---|---|
| 0 | `char[4]` | magic `AMNP` |
| 4 | `u8` | protocol version `1` |
| 5 | `u8` | message type |
| 6 | `u16` | flags; currently no assigned meaning |
| 8 | `u32` | payload byte length, at most 65,536 |
| 12 | `u32` | payload CRC-32 |
| 16 | `u8[16]` | UUID message ID in network UUID byte order |

JSON objects are serialized with sorted keys, no insignificant whitespace, finite
numbers only, and UTF-8. Arrays/scalars at the payload root, invalid UTF-8, NaN/
Infinity, unknown message types, bad CRC, excessive lengths, and a decoder buffer over
128 KiB are rejected. TCP fragmentation and concatenated frames are supported by the
incremental decoder.

CRC detects corruption; it provides no authentication, confidentiality, or tamper
resistance.

## Message types

| Value | Name | Direction / role |
|---:|---|---|
| 1 | `HELLO` | client starts authentication |
| 2 | `HELLO_ACK` | Hub accepts a stored token |
| 3 | `PAIR_REQUIRED` | Hub requests code confirmation |
| 4 | `PAIR_CONFIRM` | client returns code |
| 5 | `PAIR_ACCEPTED` | Hub returns persistent token |
| 6 | `UNLOCK` | authenticated event |
| 7 | `PROGRESS` | authenticated progress event |
| 8 | `LEDGER_BACKUP` | authenticated bounded hex ledger |
| 9 | `PING` | authenticated keepalive |
| 10 | `PONG` | reply using the same message ID |
| 11 | `ACK` | accepted/duplicate reply using event ID |
| 12 | `ERROR` | bounded error text |

Unknown post-authentication messages close the connection after an error response.

## Pairing and reconnect

The first message must be:

```json
{
  "device_id": "stable-local-device-id",
  "name": "AMUN-2DS",
  "token": "optional-previous-token"
}
```

`device_id` is 1–128 characters. A known device with a constant-time matching token
receives `HELLO_ACK {"paired":true}`. Otherwise Hub creates a six-digit code, prints
it to its console, and sends:

```json
{"code": "581204", "expires_seconds": 60}
```

The client must answer before timeout:

```json
{"code": "581204"}
```

Hub then returns a 32-byte random token encoded as 64 hex characters and stores it in
`state.json` using atomic replacement.

Important current limitation: the pairing code is present in the `PAIR_REQUIRED`
payload on the same unauthenticated TCP channel. The desktop also prints it, but the
prototype does not yet implement an independent user-entry channel on the console.
It therefore proves protocol continuity, not physical possession or protection from a
LAN attacker. Do not describe it as strong authentication.

Tokens are stored unencrypted. Protect the Hub data directory with normal OS account
permissions. Remove the device entry from `state.json` to revoke a token while Hub is
stopped.

## Events and duplicate handling

After authentication, clients may send `UNLOCK`, `PROGRESS`, `LEDGER_BACKUP`, or
`PING`. Unlock/progress payload schemas are intentionally application-level JSON in
v1; send the ledger event fields needed by provenance (achievement/build/profile/
session IDs, timestamp, integrity, progress) rather than game memory or copyrighted
data.

For an event, Hub remembers up to 4096 recent message UUIDs in memory. It writes a fresh
unlock/progress event once to `events.jsonl`, flushes the stream, and replies:

```json
{"accepted": true, "duplicate": false}
```

A repeated recent UUID is not written again and receives:

```json
{"accepted": false, "duplicate": true}
```

The recent-ID cache is not persisted across a Hub restart. Clients must treat AMNP
delivery as at-least-once and reconcile by the durable ledger event UUID rather than
assuming the JSONL file is globally duplicate-free.

`LEDGER_BACKUP` uses `{"ledger_hex":"..."}` and stores
`backups/<sanitized-device-id>/<message-id>.amunledger`. Hex text is checked and the
protocol's 64 KiB payload ceiling dominates the server's larger defensive backup
bound. Large ledgers therefore require a future chunked protocol; v1 must not split a
file implicitly or allocate unbounded buffers.

## Failure policy

- Console ledger append is always first.
- A full queue, timeout, disconnect, disabled Wi-Fi, Hub shutdown, or malformed reply
  must never stall achievement evaluation or toast delivery.
- Retry uses the same event UUID so Hub can identify a duplicate.
- Lifecycle suspend/exit never performs network I/O.
- No memory snapshot or pack is transferred unless developer mode explicitly requests
  it; v1 has no such frame type.

## Threat model

AMNP v1 is intended for a trusted home LAN. It does not use TLS, encrypt payloads,
authenticate the Hub to the client, hide tokens from an on-path observer, or resist an
attacker who sees the pairing exchange. Device tokens deter casual reconnects after a
clean pairing but are bearer secrets. Do not expose port 43831 to the Internet.

The conservative production artifact keeps console networking disabled because the
current private-memory/SOC strategy has unresolved title-specific stability reports.
Networking may be enabled only after bounded nonblocking behavior, lifecycle shutdown,
and original-2DS title-matrix testing are demonstrated.
