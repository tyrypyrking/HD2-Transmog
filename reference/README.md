# Static reference fixtures

These three files are an explicit allowlist of nonpersonal game-format facts needed for offline regression tests and SDK archive inspection. They are not player captures or ownership lists.

- `current_catalog.json`: catalog identifiers, schema layouts, armor composition bytes and passive definitions. Source revision and input hashes are embedded. The same kit/passive/schema facts are shipped in `src/catalog_data.lua`.
- `armor_display.json`: English labels and effect templates with provenance hashes, corresponding to `src/catalog_labels.lua`.
- `passive_icon_geometry_manifest.json`: source hashes, dimensions and rectangle counts for `src/passive_icon_geometry.lua`; no original texture files.

The recorded source revision identifies the catalog input; executable addresses, local paths, account identifiers, personal inventory and runtime session state are not included. Reference facts never establish ownership, which is checked at runtime. Game names, strings and icon representations remain the property of their respective owners; no license to the original game assets is implied.

Normal builds and tests use these checked-in facts and require no installed game or research directory. Regeneration tools require separately supplied source files/localization or game-data inputs; their private inputs and caches remain ignored. Optional DDS comparisons run only when local samples exist.

`tests/native_header_code.json` is a small, nonpersonal instruction-byte fixture for the native header parser; it contains only named hex snippets, not a memory capture or executable.
