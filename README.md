# HD2 Transmog

Version **0.1.3** — combine an owned armor appearance, an owned base-stat profile, and an owned passive in Helldivers 2. Requires **Bingus Shared Loader v15+ / API 1**.

This release adds complete controller creation using the native armor thumbnail grid, fixes selection and equipment recovery after deleting a worn variant, and supports optional DiverKit Alpha **8.8.1 / 8.10.1** compatibility. Neither DiverKit nor a helmet-passive mod is required.

Arsenal provides three independent settings: armor stats are independent by default, helmet transmog is off by default, and armor-thumbnail passive badges are on by default. Disabling stat selection makes creation a two-stage process: look and passive, with base stats inherited from the look. Hiding thumbnail badges keeps passive-selection and detail icons visible.

Controller controls: **D-pad or left stick** moves focus; **A** selects or activates the focused button; **B** goes back (cancels at the first step); **Y** cancels; **LB/RB** changes choice pages. Look selection shares the native thumbnail grid with the mouse. In the stats/passive lists, left/right moves between choices and action buttons. Selecting a passive focuses **Create**, which requires a separate A confirmation. Creation never equips armor.

User QA confirmed navigation and configuration behavior on the final candidate. Automated validation passes **1,050 tests**, with 9 optional checks skipped. The release includes the startup resource-size fix verified by autonomous startup, Armory entry and controller navigation tests. Diagnostics and game captures remain private and excluded from distribution.

## Use

1. Open the ship Armory, select Equipment, then Armor.
2. Find **Custom Variants** before Light Armor and select **+**.
3. Choose an owned appearance, base stats, and an owned passive, then **Create**.
4. Select the saved card to preview it, then press the game's **Apply** button.

Create saves a variant without equipping it. Saved cards use the native preview, stat bars, and passive descriptions. Their names identify the appearance and passive. Base-stat choices exclude the donor's passive bonus; the selected passive is applied separately.

The creator, card clipping, and mouse Apply regions follow the native Armory's centered UI canvas on ultrawide displays. Layout and mouse-interaction regressions cover eight resolutions through 5120×1440, including live window resizing; live layout checks used 2400×1000 and 2400×675 (32:9). Use mouse Apply or press and release A on a ready selected armor with an XInput/Steam Input controller. Controller focus is checked against the native card; held buttons, focus loss, device changes and changed selections cancel confirmation. Keyboard confirmation and non-XInput controller backends are not covered.

After a verified armor change, Equip uses the native green equipped state and the vanilla equipment-selection sound routine for the equipped item and menu context. Helmet and Cape tab clicks remain available while browsing or creating; an armor change already in progress must finish before switching tabs.

Pre-mission Equipment shows saved variants. Creation and removal are available in the ship Armory. **Remove variant** deletes a saved card without changing worn armor. Newly owned armor becomes available automatically; reopen Armor if the game's thumbnail list has not refreshed.

After you equip a variant on this build, its exact definition is remembered in the mod-private `equipped.state` file. On the next launch, restoration waits for an idle ship, the same ordinary armor carrier, verified ownership, and a valid saved definition. It does not open the Armory. Missing, changed, unowned, or incompatible definitions leave normal armor in place. The game retains ordinary owned armor IDs, so uninstalling the mod leaves normal armor; the mod-private restore file is ignored without the mod. An interrupted restoration is not automatically retried next launch. Selecting or creating a variant alone does not enable restoration.

Input capture is restricted to the visible Armor picker. The parent Armory menu, other equipment categories, and hidden picker states keep their native controls.

Reduced Armor-menu work by reusing unchanged display choices and decoded offer data while retaining fresh ownership, geometry, and equip checks. Disconnected controller discovery is bounded, and input polling stops outside the active Armor picker. User-driven benchmarks found a modest Armor-menu improvement and no meaningful mission FPS difference in the repeated test route; some menu overhead remains. These results are specific to the tested system and route.

Final user QA on 2026-09-28 passed with only Bingus Shared Loader and the normal 0.1.2 build installed: creation, mouse/controller equipping, equipped-state feedback and sound, menu navigation, ultrawide layout, pre-mission use, restart restoration, and variant removal. The remaining Armor-menu overhead was accepted. That release passed 934 offline tests, with 9 optional checks skipped. The specific double-passive glitch remains untested in an affected live environment.

Creator base-stat choices now read the verified body type independently of the worn passive cache. Unknown cached passive data no longer blocks that read. Unknown worn armor IDs/categories and cached passives are logged for investigation without blocking browsing. Helmet identity/category diagnostics run only with helmet transmog enabled; cape IDs are never classified. All observed IDs still participate in freshness and non-body preservation checks, and writes require verified owned target/donor records. Missing stat evidence shows a diagnostic message and transient read failures are retried. This addresses a failure path consistent with the reported double-passive issue; further glitch-specific validation is deferred.

## Optional helmet variants

Helmet transmog is **off by default**. In Arsenal Options, set **Helmet transmog → On**, deploy with the game closed, and restart. This On/Off setting is independent of the armor creation process and passive icons.

When enabled, the ship Armory shows a **Helmet Variants** editor only when verified helmet records contain a passive effect or differ from the reference passive/weight data. Vanilla helmets leave it hidden. Detection reads the native passive definition, including changed existing effects and additional enum entries within the verified table bounds; it does not identify or depend on any particular mod.

Choose **New**, then an owned helmet look, base-weight donor and passive. **Save variant** stores the definition separately in `helmets.state`; **Saved** reopens those definitions. To **Prepare**, wear and select another helmet first. Then select the chosen look in the native Helmet list and use the game's normal **Apply**. To **Reset**, wear and select a different helmet first. Preparation preserves the look's package, resources and material bytes and copies the selected passive and compatible helmet weights. Body-armor donors are never offered in this editor.

This is an initial development path, not parity with body-armor custom cards. Saved helmet definitions require preparation each launch; automatic equipped restoration, pre-mission editing, numeric helmet stat previews and combat stacking are not implemented. Unsupported helmet piece layouts remain unavailable. Offline tests cover detection, ownership, composition, rollback, storage and input handling; live appearance, UI placement and combat behavior still need testing. The editor does not add or aggregate passive effects itself.

## Independent combinations

Version 0.1 removes the requirement that mixed-stat armor have the same parts as its appearance. IE-57 Hell-Bent with the 64-rating profile and Democracy Protects is covered by a regression test, including apply and reset. Its base tuple is **64 armor / 536 speed / 118 stamina regeneration**.

Missing stat contributions use records without a visual resource. Surplus visible armor parts use an unoccupied non-armor classification in the same slot, preventing collisions with existing parts. Resource hashes, materials, appearance package identity, and localization stay with the chosen appearance. The implementation does not use the unsupported fourth weight coefficient.

Uniform displayed profiles use the corresponding Light, Medium, or Heavy weight on all armor parts. This deliberately normalizes incidental cape/hip weights rather than copying hidden differences between donors that have identical displayed base stats. Mixed profiles retain the donor's armor-weight distribution and torso class.

Automated checks cover all **18,225 appearance/stat pairs** in the current 135-armor catalog, for both body shapes. They check native rounded base values, visual resource/material preservation, unit-slot collisions, torso class, and the native collection limit. Separate tests cover passive selection, reversible writes, and equipment transitions. These checks do not establish visual or combat behavior for every combination.

Live validation used a freshly restarted 0.1 runtime and a deployed package matching the tested build hash. The Armory showed IE-57 with **64 armor / 536 speed / 118 stamina regeneration**, **Democracy Protects**, and the **Equipped** label; the runtime reported `variant.equipped=native_armor_and_passive_cache_verified`. Concurrent screen changes interrupted navigation, so this is an observed equipped result, not a completed autonomous navigation test. It does not establish live coverage of surplus-part reclassification, every combination, or mission behavior. Captures and runtime logs remain private and ignored.

## Build and install

Prerequisites: Python 3.10+, a current LuaJIT 2.1 on PATH, GNU binutils (for synthetic x86-64 test fixtures), and the Python packages below (use a virtual environment). The setup command downloads two packaging modules from Bingus Shared Loader at revision `836427cef78b8a67cf771c1f16291d93be921744`, verifies their SHA-256 hashes, and stores them in ignored local dependency storage. Network access is needed for setup only; normal builds and tests need no installed game.

The external [Bingus Shared Loader source](https://github.com/CowboyBingus/BingusSharedLoader) is not redistributed in this repository; consult upstream for its terms. The bundled LuaJIT decoder is MIT-licensed, with its copyright and provenance in `vendor/LuaJIT-disassembler`. Static game reference facts and their provenance are described in [reference/README.md](reference/README.md).

```sh
python3 -m pip install -r requirements-dev.txt
python3 tools/setup_dependencies.py
python3 -m pytest -q tests
python3 tools/build.py
```

Import `dist/HD2-Transmog-Foundation-0.1.3.zip` through Arsenal as the existing mod, enable it with the loader, and deploy while the game is closed. Let Arsenal assign patch numbers. Restart the game after installing an update.

Arsenal **Options → HD2 Transmog Foundation → Disable armor stat selection** is an optional two-stage creator: choose a look, then a passive. The look supplies its own base stats; the selected passive is applied independently. **Independent armor stats (default)** keeps the existing three-stage creator. Select one mode, deploy with the game closed, and restart. Existing saved variants keep their original stats in either mode.

Armor thumbnail passive badges are **on by default**. In Arsenal Options, set **Armor thumbnail passive icons → Off** to hide badges on original and custom armor thumbnails. This On/Off setting is independent of creator mode and helmet transmog. Passive-selection and detail-panel icons remain visible. Deploy with the game closed and restart to change the setting. When updating from the earlier combined choices, reselect the creator mode and both On/Off settings once; Arsenal cannot translate the old combined choices into separate settings.

The mod identity and body-armor saved-state format are unchanged in 0.1.3. Existing saved variants are retained. State is stored under `%LOCALAPPDATA%/CowboyBingus/Helldivers2/Transmog`; diagnostics are in `STATUS.txt` and the sibling `Logs/HD2Transmog.log`. Corrupt or unreadable state is preserved rather than discarded.

## Optional DiverKit compatibility

Transmog automatically attaches its compatibility adapter when supported DiverKit Alpha 8.8.1 or 8.10.1 Lua interfaces are present. DiverKit is not required: without it, Transmog uses its normal creator and equipment flow. Unrecognized DiverKit interfaces disable the adapter and are reported in `HD2Transmog.log`.

After updating, equip each custom variant through Transmog and save or overwrite its DiverKit preset. Older DiverKit presets contain only an ordinary armor ID and cannot recover their original custom stats/passive automatically. Newly saved presets retain the exact variant definition, including different variants using the same look. Keep the corresponding Transmog variant; removed or changed definitions require saving the DiverKit preset again.

When a preset includes Armor, DiverKit first finishes its other equipment changes, then Transmog performs and verifies its guarded armor change. Excluding Armor leaves it untouched. Ordinary armor presets restore the original armor composition. Cancellation, lost ownership, changed menus, or failed verification report an incomplete application rather than success.

For QA, test both mods together with two different looks, two variants sharing a look, an ordinary armor preset, and a preset with Armor excluded. Then disable DiverKit and verify normal Transmog creation, equipping, and restart restoration. The 8.8.1 adapter passed user QA; the updated 8.10.1 path still needs live-game QA; offline coverage includes the installed DiverKit source's save path and synthetic native equipment transitions.

## Reporting problems

Use the [issue forms](https://github.com/tyrypyrking/HD2-Transmog/issues/new/choose) for crashes, equipment problems, or other bugs. They list the useful details and log files; missing logs do not prevent a report.

## Compatibility and limits

Existing handling of unusual loadouts is retained. Unfamiliar current equipment produces bounded, deduplicated diagnostics instead of an equipment-category error in the UI. Helmet transmog is opt-in and uses observed helmet data; it does not require a named provider, loader order declaration, or companion-mod API.

Ownership is rechecked before saving or applying. The current catalog supports up to 120 saved variants. Unknown records become unavailable without deleting saved definitions.

Applying a variant retains the appearance's package identity and switches away from a worn carrier before changing its composition. Helmet, cape selection, and other equipment are retained. Reset checks original bytes and restores only changes attributable to this mod.

Native functions and data are discovered and validated against the current executable. Structural game changes may require an adapter update. Cache confirmation does not prove resource streaming has finished. Mission behavior and compatibility with other mods require live testing.

Diagnostics record startup health and action/native-call checkpoints, flushing each entry immediately. The current log and three previous sessions are retained in the Logs directory. Logging adds no periodic health scan or per-frame polling; entries and session size are bounded. For a crash report, include `HD2Transmog.log`, `HD2Transmog.previous.log`, `BingusSharedLoader.log`, and `Transmog/STATUS.txt` from the affected run. A final `begin` without its matching completion narrows the failure location but does not prove its cause.

Development automation is opt-in through the local `debug.enabled` marker. Research captures, personal state, logs, deployment backups, and local game data are not part of the public repository.

## Public source hygiene

Git uses an allowlist of source, offline tests, build tools, documentation, the mod-manager icon, three static reference fixtures, and the licensed decoder. Local research, notes, release drafts, screenshots, logs, saves, game dumps, caches, backups, archives and other vendor checkouts are excluded. New public files must be deliberately added to the allowlist; do not force-add local artifacts.

## GitLab CI and release builds

The pipeline runs the offline test suite on branch pushes, merge requests, and tags. When a merge request is open, its pipeline replaces the duplicate branch-push pipeline. Test results are uploaded as a [GitLab JUnit report](https://docs.gitlab.com/ci/testing/unit_test_reports/), including on test failure.

After tests pass, `build-package` provides the installable ZIP and its SHA-256 file as downloadable job artifacts, retained for 30 days. A tag such as `v0.1.3` runs `release-build` instead and keeps those artifacts without an expiration. Release tags must match the runtime version in `src/main.lua`; both `0.1.3` and `v0.1.3` are accepted. The ZIP filename and bundled readme derive their version from that same runtime declaration. Update the package regression expectations and documentation when changing the version.

The jobs need a Linux x86-64 Docker/Kubernetes runner with internet access to fetch the Python image, Debian/Python dependencies and checksum-verified packaging tools. They require no game installation, private captures, deployment credentials, or publishing token. Only the ZIP, checksum and test report are uploaded; CI does not publish the mod or create a GitLab release entry. Download the ZIP from the successful build job to publish it yourself.

To reproduce a tagged build locally:

```sh
python3 tools/setup_dependencies.py
python3 -m pytest -q tests
python3 tools/build.py --release-tag v0.1.3
(cd dist && sha256sum -c HD2-Transmog-Foundation-0.1.3.zip.sha256)
```

Pipeline triggering follows GitLab's documented [workflow rules](https://docs.gitlab.com/ci/yaml/workflow/).
