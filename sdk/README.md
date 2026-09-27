# Transmog appearance providers — experimental authoring layer

**Status: registration and inspection work; independent appearance rendering is not implemented or enabled.** A registration-preview ZIP is not a usable armor mod. API 1 below is a draft contract for development, not yet a stable public ecosystem release.

The vanilla-card selection fix ships independently of this work. Existing saved variants keep their stable resource-preserving behavior.

## Intended author and player experience

An author supplies an independent visual identity, a display name, and geometry/materials for `lean`, `muscle`, or both. They do not choose a vanilla armor to replace, a stat donor, a passive, an ownership ID, memory addresses, executable versions or native call signatures. The exporter supplies namespaced resource paths and a visual asset ABI automatically. A single-body appearance is unavailable for the other body; the framework must not silently reuse a mismatched rig.

Players install Transmog once and install appearance packs through Arsenal. Future visual selection will be a separate look choice while the actual owned gameplay armor and passive remain unchanged. This provider API never grants items or sends custom armor IDs to multiplayer peers. Other players seeing these client-local visuals is not part of this design.

Transmog owns compatibility and lifecycle: resource registration/loading, local actor identification, rig adaptation, preview and worn actors, attachment, original visibility, actor replacement, safe detachment and release. Packs must never perform those operations themselves.

## Draft data contract

See [the example](examples/ceremonial.appearances.json). `schema`, `api` and `asset_abi` are explicit. A provider ID is `author/pack`; appearance IDs are local to that provider. Each body references its own package and one or more root visual units under:

```
mods/hd2transmog/appearances/<author>/<pack>/...
```

These are exporter-facing resource identities, not current game offsets. All root resources and their private dependency references must be namespaced. Merely renaming archive directory entries is insufficient: units reference materials, meshes, bones and textures inside their binary payloads.

The registry rejects unknown fields, gameplay stats/perks, carrier IDs, pointers, foreign resource namespaces, metatables, sparse arrays, duplicate identities, unsupported schema/ABI versions and conflicting re-registration. Accepted declarations and returned lists are defensively copied. Registering identical data twice is idempotent.

The runtime API is `HD2Transmog.appearances`:

```lua
local result, reason = HD2Transmog.appearances.register(manifest)
local capabilities = HD2Transmog.appearances.capabilities()
local lean_looks = HD2Transmog.appearances.list('lean')
```

Current capabilities explicitly report `independent_rendering=false`. Every registered look reports `available=false`, `status='registered_unavailable'` and a reason. Registration never touches the native catalog, resources, units, ownership or equipment. There is deliberately no callable external renderer or readiness switch in the public API.

## Tools available now

Run from the project root with Python 3 and LuaJIT available:

```sh
python3 tools/appearance_sdk.py inspect /path/to/legacy-mod.zip --output /path/to/inspection.json
python3 tools/appearance_sdk.py validate sdk/examples/ceremonial.appearances.json
python3 tools/appearance_sdk.py build-registration sdk/examples/ceremonial.appearances.json --output /path/to/provider-preview.zip
```

`inspect` reads archive directories and validates resource and sidecar bounds without executing or extracting the mod. It reports resources matching the pinned stock catalog, optional bundles and resource types. It **does not convert** a legacy replacer.

`build-registration` produces a deterministic Arsenal addon with the original declaration included, a stable provider UUID, and an unambiguous loader resource name. Its bootstrap checks Transmog availability before requiring it, so provider load order does not determine whether registration works. Missing Transmog or an incompatible provider API produces an explicit dependency error. The generated ZIP is clearly marked registration-only and contains no meshes or replacement assets. It is not installed automatically.

## The actual missing backend

The captured current game Lua API includes `ResourcePackage.load/has_loaded/flush/unload` and unit spawn/link/visibility operations, but not the normal `Application.resource_package/release_resource_package` factory/lifetime entry points. Their existence in generic Stingray documentation is not proof they are callable in Helldivers 2. Nor are generic unit APIs proof of correct local-avatar binding, skeletal animation merge, collision isolation, actor reconstruction or multiplayer isolation.

Before enabling a pack, the backend must prove all of the following together:

1. Load a namespaced package and its complete private dependency graph with an owned lifetime token; never block a frame waiting for streaming.
2. Identify the correct local preview or worn actor, body type and generation. Never attach to every unit sharing an armor resource.
3. Spawn visual-only units without gameplay actors or network registration; verify the rig/animation merge and default armor visibility.
4. Prepare a replacement fully before presenting it. On failure, keep the original appearance visible and retain any possibly referenced resources.
5. Detach and destroy owned visuals before releasing packages, accounting for previews, mission transitions, death, respawn and shutdown. A changed armor cache is not a resource-release fence.
6. Test repeated switching, cancellation, re-entry, body-type changes and joining another host. The earlier package-remapping crash is a required regression scenario, not an acceptable fallback.

Until then, exposing an enabled cosmetic card or silently falling back to overwriting vanilla kits would misrepresent support and reintroduce known risk.

## Compatibility promise

Centralized bindings can spare authors updates when native call locations, menu layouts or actor access change but their visual ABI remains supported. A Transmog update can restore all compatible packs together.

“Zero breakage across every Arrowhead patch” is not a defensible guarantee. Mesh formats, shaders, skeletons and animation conventions can change. A versioned portable visual representation plus framework-owned compilation/migration is the stronger long-term route; compiled legacy unit blobs alone cannot guarantee that. ABI migration, rig conversion and exporter integration are still work to do before declaring this API stable.

Third-party downloaded artwork is inspected locally only; the example contains no redistributed assets.
