#!/usr/bin/env python3
"""Bundle the LuaJIT addon and produce a deterministic Arsenal import ZIP."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r"local runtime = \{version='([0-9]+(?:\.[0-9]+)+)'", (ROOT/'src/main.lua').read_text()).group(1)
NAME = 'mods/hd2transmog/foundation'
GUID = '46b51e90-d243-457a-ae92-8d7e6875c0ea'
TITLE = 'HD2 Transmog Foundation'
DESCRIPTION = ('Owned armor variants with independent appearance, base stats and exact passives. '
               'Requires Bingus Shared Loader v15 or newer (API 1). '
               'Native stat/perk previews and one-button equipment in the Armor list. '
               'Create saves locally without equipping the armor.')

def bundle():
    chunks = ['-- HD2-Addon: ' + NAME + '\n']
    for variable, filename in [('State','state.lua'), ('EquippedState','equipped_state.lua'), ('ControllerInput','controller_input.lua'), ('Platform','platform.lua'),
                               ('AppearanceRegistry','appearance_registry.lua'),
                               ('CompatSpec','compat_spec.lua'),
                               ('CatalogCompat','catalog_compat.lua'),
                               ('CatalogData','catalog_data.lua'),
                               ('CatalogLabels','catalog_labels.lua'),
                               ('Localization','localization.lua'),
                               ('CatalogProbe','catalog_probe.lua'),
                               ('DebugBridge','debug_bridge.lua'),
                               ('NativeDisassembler','../vendor/LuaJIT-disassembler/dis_x86.lua'),
                               ('DebugArmory','debug_armory.lua'),
                               ('ArmorStatSemantics','armor_stat_semantics.lua'),
                               ('ArmorStatResolver','armor_stat_resolver.lua'),
                               ('DebugController','debug_controller.lua'),
                               ('DebugOpenArmory','debug_open_armory.lua'),
                               ('NativeArmorProbe','native_armor_probe.lua'),
                               ('NativeGridModel','native_grid_model.lua'),
                               ('NativeGridFocus','native_grid_focus.lua'),
                               ('NativeGridProducers','native_grid_producers.lua'),
                               ('NativeGrid','native_grid.lua'),
                               ('NativeGridPresentation','native_grid_presentation.lua'),
                               ('ArmorySection','armory_section.lua'),
                               ('RenderProbe','render_probe.lua'),
                               ('PlayerCustomizationProbe','player_customization_probe.lua'),
                               ('ArmorRefresh','armor_refresh.lua'),
                               ('ArmorRefreshBridge','armor_refresh_bridge.lua'),
                               ('VariantSession','variant_session.lua'),
                               ('VariantLayout','variant_layout.lua'),
                               ('VariantWizard','variant_wizard.lua'),
                               ('VariantCards','variant_cards.lua'),
                               ('ArmorBaseStats','armor_base_stats.lua'),
                               ('PassiveIconGeometry','passive_icon_geometry.lua'),
                               ('PassiveIconDraw','passive_icon_draw.lua'),
                               ('UiLayout','ui_layout.lua'),
                               ('WizardPanel','wizard_panel.lua'),
                               ('IconProbe','icon_probe.lua'),
                               ('UiWorkflow','ui_workflow.lua'),
                               ('ArmorLayout','armor_layout.lua'),
                               ('AppearancePatch','armor_composition.lua'),
                               ('RuntimeWriter','runtime_writer.lua'),
                               ('Adapter','runtime_adapter.lua'), ('Panel','panel.lua')]:
        chunks.append('local '+variable+' = (function()\n'+(ROOT/'src'/filename).read_text()+'\nend)()\n')
    chunks.append((ROOT/'src/main.lua').read_text())
    return ''.join(chunks)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-tag', help='Require a release tag matching the runtime version (for example v0.1.2).')
    args = parser.parse_args()
    if args.release_tag is not None and args.release_tag not in (VERSION, 'v'+VERSION):
        parser.error(f'release tag must be {VERSION} or v{VERSION}; got {args.release_tag!r}')
    out = ROOT/'dist'
    out.mkdir(exist_ok=True)
    source = bundle()
    lua = out/'hd2_transmog.lua'
    lua.write_text(source)
    subprocess.run(['luajit','-e','assert(loadstring(io.read("*a")))'],
                   input=source,text=True,check=True)
    sys.path.insert(0,str(ROOT/'vendor/BingusSharedLoader/scripts'))
    from build_addon import build_addon
    package = out/f'HD2-Transmog-Foundation-{VERSION}.zip'
    build_addon(NAME,source.encode(),GUID,package,TITLE)
    with zipfile.ZipFile(package) as z:
        files={n:z.read(n) for n in z.namelist()}
    manifest=json.loads(files['manifest.json'])
    manifest['Description']=DESCRIPTION
    manifest['Options'][0]['Description']=DESCRIPTION
    files['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    files['THIRD-PARTY-LICENSES.txt']=(ROOT/'vendor/LuaJIT-disassembler/COPYRIGHT').read_bytes()
    files['README.txt']=(
        f'HD2 Transmog Foundation {VERSION} - Independent armor appearance, base stats and passives\n'
        'Import this ZIP in Arsenal, enable it with Bingus Shared Loader and deploy.\n'
        'Open the ship Armory: press 2, click the left Armor card, then press 1.\n'
        'Custom Variant appears before Light Armor. Saved variants precede the + tile.\n'
        'Newly owned armor refreshes without restarting; reopen Armor if the native list has not refreshed yet.\n'
        'Saved variant capacity reserves room for all verified Armor unlocks.\n'
        'Variant captions use appearance - passive names, including older saves.\n'
        'Remove variant in the ship Armory deletes the saved card without changing worn armor.\n'
        'Pre-mission Equipment uses the same saved-variant section without a + tile or creator.\n'
        'Select +, choose an owned look, base stats, then an owned passive, and Create.\n'
        'Base-stat choices exclude donor passive bonuses and are sorted by armor rating.\n'
        'Create saves locally and does not equip or change the worn armor.\n'
        'Select a saved card to preview its look in the original stat/perk panels.\n'
        'Click Apply or press and release controller A (XInput/Steam Input) on a ready selected armor.\n'
        '0.1.2: controller A confirmation, parent-menu input fix, and creator base stats independent of the worn passive cache.\n'
        'Reduced Armor-menu processing and disconnected-controller polling; fresh ownership and equip checks remain enabled.\n'
        'Equip a variant once on this build to remember it for future launches. Restoration waits for verified idle-ship context.\n'
        'Unknown, removed or unowned variants are skipped; the game save retains ordinary armor IDs when the mod is removed.\n'
        '0.1.1: centered ultrawide layout, aligned click regions, green Equipped feedback, and native Helmet/Cape tab clicks.\n'
        'Equipment audio uses the vanilla item/category and menu-context sound routine.\n'
        'Known limits: keyboard confirmation and non-XInput controllers are not covered.\n'
        'Apply keeps the old carrier intact until the native request/cache have switched away, then composes and equips.\n'
        'Catalog discovery warms before entry; bounded batch reads reduce section-loading work.\n'
        'Native cache confirmation is not proof of streaming completion or combat behavior. See README.md for validation limits.\n'
        'Updating retains the existing mod identity and saved variants. Keep other mods enabled as configured.\n'
        'Do not copy patch_0 manually over another mod; let Arsenal assign patch numbers.\n'
        'Saved state: %LOCALAPPDATA%/CowboyBingus/Helldivers2/Transmog/transmog.state\n'
        'Diagnostics: Transmog/STATUS.txt and sibling Logs/HD2Transmog.log.\n'
        'Development automation is opt-in through the local debug.enabled marker.\n'
    ).encode()
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            z.writestr(info,data)
    print(package)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_suffix('.zip.sha256').write_text(f'{digest}  {package.name}\n')
    print('SHA256', digest)

if __name__=='__main__':
    main()
