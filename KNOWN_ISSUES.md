# Known Issues

## Remaining parse failures: unknown property types cause data misalignment

**Status:** Open
**Affects:** ~20 out of 134 tested .one files (files under 5MB)
**Error:** `struct.error: unpack requires a buffer of N bytes` (where N is a huge garbage value)

### Root cause

When `PropertySet.__init__` encounters an unknown property type (>0x11), it logs a warning and appends `None` to `rgData`, but does **not consume any bytes from the file stream**. For known types, the parser reads a specific number of bytes (e.g., 1 byte for type 0x3, 4 bytes for type 0x5, variable for type 0x7, etc.). Skipping an unknown type without advancing the file pointer leaves it misaligned, so all subsequent reads in that PropertySet — and potentially in sibling PropertySets — interpret wrong bytes, producing cascading garbage.

This manifests as `struct.unpack` trying to read billions of bytes (e.g., `2300837918`, `2756199521`) when it hits a garbage `cb` field that should have been a small number.

### Why we can't simply skip N bytes

The MS-ONESTORE spec defines property types 0x0 through 0x11. Types above 0x11 don't exist in the spec, so there's no way to know how many data bytes they carry. The type code encodes the data format:

| Type | Data size |
|------|-----------|
| 0x0, 0x1, 0x2 | 0 bytes (no data / bool) |
| 0x3 | 1 byte |
| 0x4 | 2 bytes |
| 0x5 | 4 bytes |
| 0x6 | 8 bytes |
| 0x7 | variable (4-byte length prefix + data) |
| 0x8-0xD | reads from OID/OSID/ContextID streams |
| 0x10, 0x11 | recursive PropertySet(s) |

For an unknown type like 0x14, we don't know if it's 4 bytes, 8 bytes, or variable-length. Guessing wrong would make the misalignment worse.

### Possible fixes

1. **Wrap PropertySet parsing in try/except at the call site** (`ObjectSpaceObjectPropSet.__init__` and `ObjectDeclaration2RefCountFND.__init__`). When a PropertySet fails, log a warning and continue parsing the rest of the file. This wouldn't fix the individual PropertySet but would prevent one bad section from killing the entire document.

2. **Reverse-engineer the unknown types.** The types showing up most often are 0x12, 0x13, 0x14, 0x15, and 0x1f. These might be undocumented Microsoft extensions. The [onenote.rs](https://github.com/nicoretti/onenote.rs) project may have hints. If their data sizes can be determined, the parser could skip them correctly.

3. **Use the PropertyID's type field as a heuristic.** The upper 5 bits of the PropertyID encode the type. If we can build a mapping of known PropertyID values to expected types, encountering an unexpected type could signal that the data is already corrupt and parsing should bail out early for that PropertySet.
