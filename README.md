# HD2 Transmog

Version **0.1** — combine an owned armor appearance, an owned base-stat profile, and an owned passive in Helldivers 2. Requires **Bingus Shared Loader v15+ / API 1**.

## Use

1. Open the ship Armory, select Equipment, then Armor.
2. Find **Custom Variants** before Light Armor and select **+**.
3. Choose an owned appearance, base stats, and an owned passive, then **Create**.
4. Select the saved card to preview it, then press the game's **Apply** button.

Create saves a variant without equipping it. Saved cards use the native preview, stat bars, and passive descriptions. Their names identify the appearance and passive. Base-stat choices exclude the donor's passive bonus; the selected passive is applied separately.

Pre-mission Equipment shows saved variants. Creation and removal are available in the ship Armory. **Remove variant** deletes a saved card without changing worn armor. Newly owned armor becomes available automatically; reopen Armor if the game's thumbnail list has not refreshed.

## Independent combinations

Version 0.1 removes the requirement that mixed-stat armor have the same parts as its appearance. IE-57 Hell-Bent with the 64-rating profile and Democracy Protects is covered by a regression test, including apply and reset. Its base tuple is **64 armor / 536 speed / 118 stamina regeneration**.

Missing stat contributions use records without a visual resource. Surplus visible armor parts use an unoccupied non-armor classification in the same slot, preventing collisions with existing parts. Resource hashes, materials, appearance package identity, and localization stay with the chosen appearance. The implementation does not use the unsupported fourth weight coefficient.

Uniform displayed profiles use the corresponding Light, Medium, or Heavy weight on all armor parts. This deliberately normalizes incidental cape/hip weights rather than copying hidden differences between donors that have identical displayed base stats. Mixed profiles retain the donor's armor-weight distribution and torso class.

Automated checks cover all **18,225 appearance/stat pairs** in the current 135-armor catalog, for both body shapes. They check native rounded base values, visual resource/material preservation, unit-slot collisions, torso class, and the native collection limit. Separate tests cover passive selection, reversible writes, and equipment transitions. These checks do not establish visual or combat behavior for every combination.

Live validation used a freshly restarted 0.1 runtime and a deployed package matching the tested build hash. The Armory showed IE-57 with **64 armor / 536 speed / 118 stamina regeneration**, **Democracy Protects**, and the **Equipped** label; the runtime reported `variant.equipped=native_armor_and_passive_cache_verified`. Concurrent screen changes interrupted navigation, so this is an observed equipped result, not a completed autonomous navigation test. It does not establish live coverage of surplus-part reclassification, every combination, or mission behavior. Captures and runtime logs remain private and ignored.

## Build and install

Prerequisites: Python 3.10+, LuaJIT on PATH, and the Python packages below (use a virtual environment). The setup command downloads two packaging modules from Bingus Shared Loader at revision `836427cef78b8a67cf771c1f16291d93be921744`, verifies their SHA-256 hashes, and stores them in ignored local dependency storage. Network access is needed for setup only; normal builds and tests need no installed game.

The external [Bingus Shared Loader source](https://github.com/CowboyBingus/BingusSharedLoader) is not redistributed in this repository; consult upstream for its terms. The bundled LuaJIT decoder is MIT-licensed, with its copyright and provenance in `vendor/LuaJIT-disassembler`. Static game reference facts and their provenance are described in [reference/README.md](reference/README.md).

```sh
python3 -m pip install -r requirements-dev.txt
python3 tools/setup_dependencies.py
python3 -m pytest -q tests
python3 tools/build.py
```

Import `dist/HD2-Transmog-Foundation-0.1.zip` through Arsenal as the existing mod, enable it with the loader, and deploy while the game is closed. Let Arsenal assign patch numbers. Restart the game after installing an update.

The mod identity and saved-state format are unchanged by the version reset to 0.1. Existing saved variants are retained. State is stored under `%LOCALAPPDATA%/CowboyBingus/Helldivers2/Transmog`; diagnostics are in `STATUS.txt` and the sibling `Logs/HD2Transmog.log`. Corrupt or unreadable state is preserved rather than discarded.

## Compatibility and limits

Ownership is rechecked before saving or applying. The current catalog supports up to 120 saved variants. Unknown records become unavailable without deleting saved definitions.

Applying a variant retains the appearance's package identity and switches away from a worn carrier before changing its composition. Helmet, cape selection, and other equipment are retained. Reset checks original bytes and restores only changes attributable to this mod.

Native functions and data are discovered and validated against the current executable. Structural game changes may require an adapter update. Cache confirmation does not prove resource streaming has finished. Mission behavior and compatibility with other mods require live testing.

Development automation is opt-in through the local `debug.enabled` marker. Research captures, personal state, logs, deployment backups, and local game data are not part of the public repository.

## Public source hygiene

Git uses an allowlist of source, offline tests, build tools, documentation, three static reference fixtures, and the licensed decoder. Local research, notes, release drafts, screenshots, logs, saves, game dumps, caches, backups, archives and other vendor checkouts are excluded. New public files must be deliberately added to the allowlist; do not force-add local artifacts.
