# pyOneNote
pyOneNote is a lightweight python library to read OneNote files. The main goal of this parser is to allow cybersecurity analyst to extract useful information from OneNote files.

# Installing the parser

Installing the latest development

```
pip install -U https://github.com/DissectMalware/pyOneNote/archive/master.zip --force
```
# Running the parser

To dump all embedded file in current directory
```
pyonenote -f example.one 
```

To dump all embedded file in example.one into output_dir
```
pyonenote -f example.one -o output_dir 
```
To dump all embedded file in example.one into output_dir and add .bin to the end of each filename
```
pyonenote -f example.one -o output_dir -e bin
```

# Command Line
```
usage: pyonenote [-h] -f FILE [-o OUTPUT_DIR] [-e EXTENSION] [-j [JSON_PATH]]
                [--json-include SECTIONS] [--json-files-no-content]
```

## JSON output

- **Print JSON to stdout**
```
pyonenote -f example.one -j
```

- **Write JSON to a file**
```
pyonenote -f example.one -j output.json
```

- **Include only selected JSON sections**
```
pyonenote -f example.one -j --json-include headers,links
```

- **Omit embedded file content and include SHA-256 hash**
```
pyonenote -f example.one -j --json-include files --json-files-no-content
```

Note: pyOneNote is under active development

# Recent Improvements

## Parser Fixes

- **Stream head pointer bug** — `ObjectSpaceObjectStreamOfIDs.read()` was not advancing `self.head`, causing every call to return the first element. This produced incorrect CompactID resolution for OIDs, OSIDs, and ContextIDs across all property types that read from these streams (0x08–0x0D).
- **Unknown FileNode types** — Unrecognized FileNode types (the `else` branch) caused `AttributeError` crashes because `self.data` was never assigned. Now defaults to `None`.
- **Null stream guard** — `PropertySet.get_compact_ids()` crashed when `stream_of_context_ids` was `None`. Added a null check.
- **baseType==2 guard** — `FileNode.__init__` crashed when accessing `self.data.ref` for nodes where `data` was `None`.
- **`get_json()` hex encoding** — `OneDocument.get_json()` crashed on `content.hex()` when content was an empty string instead of bytes.

## Resilient Error Recovery

- **FileNode-level try/except** — If a `FileNode` fails to parse (e.g. in encrypted sections), the parser logs a warning and skips the rest of the fragment instead of crashing.
- **PropertySet-level try/except** — If an `ObjectSpaceObjectPropSet` fails to parse (e.g. due to data misalignment), the parser logs a warning and continues with the next node.
- **Sanity limits** — Added `MAX_READ_SIZE` (256 MB) and `MAX_ARRAY_COUNT` (100,000) to prevent multi-GB allocations and billion-iteration loops from corrupt data. Affects `FileDataStoreObject`, `PrtFourBytesOfLengthFollowedByData`, and array-type properties (0x09, 0x0B, 0x0D, 0x10).

## Ink Support

Added JCID and PropertyID mappings for OneNote ink objects:

- JCIDs: `jcidInkContainer`, `jcidInkLineNode`, `jcidInkParagraphNode`, `jcidInkWordNode`
- PropertyIDs: `InkData`, `InkPath`, `InkStrokes`, `InkBrushColor`, `InkBrushWidth`, `InkBrushHeight`, `InkBrushTransparency`

## Known Limitations

**Password-protected sections** — Encrypted revisions contain `ObjectDataEncryptionKeyV2FNDX` (node type 0x07C) after the revision manifest start. All subsequent data is ciphertext. The parser now survives these gracefully (via error recovery) but does not decrypt them.

**Property type misalignment** — When the parser encounters property types > 0x11, it cannot advance the file pointer correctly because the MS-ONESTORE spec defines no data format for these types. Confirmed via [onenote.rs](https://github.com/msiemens/onenote.rs) (`src/onestore/types/property.rs`) that types above 0x11 are not real — they are artifacts of upstream parsing corruption. The error recovery wrapping prevents these from crashing the parser; affected PropertySets are skipped with a warning.

## Test Results

Tested against 185 real OneNote backup files (ranging from 5 KB to 200+ MB). All 185 files parse successfully.

# How to Contribute
If you found a bug or would like to suggest an improvement, please create a new issue on the [issues page](https://github.com/DissectMalware/pyOneNote/issues).

Feel free to contribute to the project forking the project and submitting a pull request.

You can reach [me (@DissectMlaware) on Twitter](https://twitter.com/DissectMalware) via a direct message.
