# Silver Memory native codec

`memory.sr` implements the fixed version-1 Silver Memory (`.sm`) header
format described in `DOCS/GC hybrid paging design.md`, and `sm_selftest.sr`
exercises the implementation. Both are written in memory-safe Silver.

## API

- `smFnv1_64(data)` computes the required 64-bit **FNV-1** name hash
  (multiply first, then XOR; it is intentionally not FNV-1a).
- `smCrc32c(data)` computes CRC32C using the Castagnoli polynomial.
- `smHeaderEncode(header)` writes exactly 96 little-endian bytes and
  calculates the header checksum.
- `smHeaderDecode(in, header)` checks magic, reserved bytes, the header
  checksum, and all supported semantic fields before returning a header.
- `smHeaderValidate(header, fileSize, checkFileSize, expectedHash,
  checkNameHash)` validates a decoded or newly constructed header. With
  `checkFileSize` enabled, the file must end exactly after the index and
  payload; with `checkNameHash` enabled, the opaque filename hash must match.
- `smResultString(result)` returns a human-readable description of an error
  code.

Error codes are positive integers (`SM_OK = 0`, `SM_ERR_NULL = 1`, ...,
`SM_ERR_CHECKSUM = 14`) so they round-trip correctly through the self-hosted
Silver ABI, which corrupts negative integer constants.

Version 1 currently supports only uncompressed pages (`codec=0`). Compressed
pages are rejected until a codec and its bounded decompression rules are added.
For the same reason, version 1 requires `payload_size == logical_size`.

The codec does not perform filesystem I/O, allocate memory, parse filenames, or
manage page lifecycle state. The future page manager owns those operations and
must call this codec before exposing a page to the evaluator. The codec is
memory-safe Silver with no dependency on the C runtime.

## Safety properties

- No packed native struct is read from disk; all fields use explicit
  little-endian loads/stores into a 96-byte buffer.
- Reserved fields and unknown flags are rejected.
- Chunk count and index size are derived with overflow-safe arithmetic.
- A file-size check requires an exact end offset, preventing trailing or
  truncated payloads from being accepted by the page manager.
- Header checksum calculation treats the checksum field as zero, so encoding
  and decoding are deterministic across platforms.
- The codec performs no I/O and cannot page or launch `silveri` by itself.
