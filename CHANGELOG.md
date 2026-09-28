# HD2 Transmog 0.1.3

- Full controller creation: native armor thumbnails for look selection, stats/passive navigation, paging, Back/Cancel and a separate final Create confirmation. A also equips ready selected armor.
- Fixed mouse/controller focus conflicts, stale selection during quick navigation, and recovery after deleting an equipped variant. Removing a card does not change worn armor.
- Three independent Arsenal settings: **Disable armor stat selection** (off by default), **Helmet transmog** (off by default), and **Armor thumbnail passive icons** (on by default). Two-stage creation inherits the look's base stats; hiding thumbnail badges keeps other passive icons visible.
- Optional DiverKit Alpha **8.8.1 / 8.10.1** compatibility preserves the exact Transmog variant, including variants sharing the same look. DiverKit is not required.
- Optional helmet-passive support, improved facemask artwork, and fixes for native-list resource lifetime and startup loading of option resources.

## Installation and updating

Import the ZIP into Arsenal as an update to the existing Transmog entry, keep Bingus Shared Loader v15+ / API 1 enabled, and deploy with the game closed. Restart the game. Existing armor variants and mod identity are preserved.

If upgrading from a release candidate with combined options, reselect the three independent settings once before deploying.

For DiverKit, equip the intended variant in Transmog and save or overwrite its DiverKit preset. Older presets store only an ordinary armor ID and need recapture. Keep the corresponding Transmog definition; excluding Armor from a partial preset leaves it unchanged.

## Validation and limits

**1,050 automated tests passed; 9 optional checks skipped.** Package tests cover all eight independent option combinations, LuaJIT parsing and reproducible builds. Final candidate navigation and configuration behavior passed user QA; autonomous testing verified startup, Armory entry, native thumbnails and controller creation navigation.

Helmet variants require preparation each launch; automatic helmet restoration, pre-mission helmet editing, numeric helmet stat previews and combat stacking are outside the verified scope. Keyboard confirmation and non-XInput controller backends are not covered.
