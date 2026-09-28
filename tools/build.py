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
VERSION = re.search(r"local runtime = \{version='([0-9]+(?:\.[0-9]+)+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?)'", (ROOT/'src/main.lua').read_text()).group(1)
NAME = 'mods/hd2transmog/foundation'
GUID = '46b51e90-d243-457a-ae92-8d7e6875c0ea'
TITLE = 'HD2 Transmog Foundation'
DESCRIPTION = ('Owned armor variants with independent appearance, base stats and exact passives. '
               'Requires Bingus Shared Loader v15 or newer (API 1). '
               'Native stat/perk previews and one-button equipment in the Armor list. '
               'Create saves locally without equipping the armor.')

def bundle(stats_follow_look=False, passive_preview_icons=True, helmet_transmog=False):
    chunks = ['-- HD2-Addon: ' + NAME + '\n']
    for variable, filename in [('Diagnostics','diagnostics.lua'), ('State','state.lua'), ('EquippedState','equipped_state.lua'), ('ControllerInput','controller_input.lua'), ('CreatorController','creator_controller.lua'), ('Platform','platform.lua'),
                               ('AppearanceRegistry','appearance_registry.lua'),
                               ('CompatSpec','compat_spec.lua'),
                               ('CatalogCompat','catalog_compat.lua'),
                               ('CatalogData','catalog_data.lua'),
                               ('CatalogLabels','catalog_labels.lua'),
                               ('Localization','localization.lua'),
                               ('HelmetCatalog','helmet_catalog.lua'),
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
                               ('DiverKitCompat','diverkit_compat.lua'),
                               ('DiverKitBridge','diverkit_bridge.lua'),
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
                               ('HelmetLayout','helmet_layout.lua'),
                               ('AppearancePatch','armor_composition.lua'),
                               ('RuntimeWriter','runtime_writer.lua'),
                               ('Adapter','runtime_adapter.lua'), ('Panel','panel.lua'), ('HelmetEditor','helmet_editor.lua')]:
        chunks.append('local '+variable+' = (function()\n'+(ROOT/'src'/filename).read_text()+'\nend)()\n')
    chunks.append((ROOT/'src/main.lua').read_text())
    source=''.join(chunks)
    if stats_follow_look:
        source=source.replace('local STATS_FOLLOW_LOOK = false', 'local STATS_FOLLOW_LOOK = true', 1)
    if not passive_preview_icons:
        source=source.replace('local PASSIVE_PREVIEW_ICONS = true', 'local PASSIVE_PREVIEW_ICONS = false', 1)
    if helmet_transmog:
        source=source.replace('local HELMET_TRANSMOG = false', 'local HELMET_TRANSMOG = true', 1)
    build_id=hashlib.sha256(source.encode()).hexdigest()[:16]
    return source.replace("build='source'", "build='"+build_id+"'", 1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-tag', help='Require a release tag matching the runtime version (for example v0.1.3).')
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
    # The main addon is always included by its group. Each independent setting
    # has its own boolean resource; none replaces another setting or the addon.
    from archive import ARCHIVE, make_archive, resource_hash
    import struct
    for folder,setting,value in [('IndependentStats','stats_follow_look',False),('LookStats','stats_follow_look',True),
                                 ('HelmetOff','helmet_transmog',False),('HelmetOn','helmet_transmog',True),
                                 ('PassiveIconsOn','passive_preview_icons',True),('PassiveIconsOff','passive_preview_icons',False)]:
        # Very short Lua payloads crash the native resource loader before any
        # addon executes (reproduced with 12/13-byte option scripts). Keep each
        # independent setting above the live-tested 1 KiB source size.
        payload=(b'-- Transmog configuration resource.\n'+b'-- '+b' '*1024+b'\n'
                 +('return '+str(value).lower()+'\n').encode())
        resource=struct.pack('<II',len(payload),2)+payload
        files[folder+'/'+ARCHIVE]=make_archive({resource_hash('mods/hd2transmog/options/'+setting):resource})
        for suffix in ('.stream','.gpu_resources'):
            files[folder+'/'+ARCHIVE+suffix]=b''
    manifest=json.loads(files['manifest.json'])
    manifest['IconPath']='mod-icon.png'
    files['mod-icon.png']=(ROOT/'assets/mod-icon.png').read_bytes()
    manifest['Description']=DESCRIPTION
    def choice(name,folder,description):
        return {'Name':name,'Description':description,'Include':[folder],'Image':'mod-icon.png'}
    # Arsenal selects each enabled group's first choice on import. Defaults are
    # also correct when its global enable-all preference enables every group.
    manifest['Options']=[
        {'Name':TITLE,'Description':'Armor creation process. Helmet and icon settings are independent.',
         'Include':['Addon'],'Image':'mod-icon.png','SubOptions':[
             choice('Independent armor stats (default)','IndependentStats','Choose look, base stats, then passive.'),
             choice('Disable armor stat selection','LookStats','Choose look and passive; the look supplies base stats.')]},
        {'Name':'Helmet transmog','Description':'Optional experimental helmet variant editor. Off by default.',
         'Include':[],'Image':'mod-icon.png','SubOptions':[
             choice('Off (default)','HelmetOff','Disable helmet transmog and current helmet identity/category checks.'),
             choice('On','HelmetOn','Enable the editor for supported modified helmets.')]},
        {'Name':'Armor thumbnail passive icons','Description':'Show or hide passive badges on armor thumbnails. On by default.',
         'Include':[],'Image':'mod-icon.png','SubOptions':[
             choice('On (default)','PassiveIconsOn','Show passive badges on armor thumbnails.'),
             choice('Off','PassiveIconsOff','Hide thumbnail badges; passive-selection and detail-panel icons stay visible.')]},
    ]
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
        'Optional: in Arsenal Options select Disable armor stat selection, deploy with the game closed, then restart.\n'
        'This uses two stages (look and passive); the look supplies base stats. Existing variants are unchanged.\n'
        'Passive badges on armor thumbnails are ON by default. Set Armor thumbnail passive icons to Off to hide them.\n'
        'Passive-selection and detail-panel icons are unaffected; armor stats and effects are unchanged.\n'
        'Creator mode, Helmet transmog and Armor thumbnail passive icons are independent settings.\n'
        'After updating from combined options, reselect your creator mode and both On/Off settings once, then deploy and restart.\n'
        'Base-stat choices exclude donor passive bonuses and are sorted by armor rating.\n'
        'Create saves locally and does not equip or change the worn armor.\n'
        'Optional DiverKit Alpha 8.8.1 / 8.10.1 compatibility is detected automatically; DiverKit is not required.\n'
        'Equip each custom variant in Transmog, then save/overwrite its DiverKit preset to capture its exact stats and passive.\n'
        'Old DiverKit presets must be saved again. Excluding Armor leaves it unchanged; unknown interfaces disable compatibility.\n'
        'Select a saved card to preview its look in the original stat/perk panels.\n'
        'Click Apply or press and release controller A (XInput/Steam Input) on a ready selected armor.\n'
        '0.1.3: complete controller creation using the native look grid, independent Arsenal settings and selection recovery fixes.\n'
        'Creator controls: D-pad/left stick moves focus; A selects; B goes back; Y cancels; LB/RB pages choices.\n'
        'Left/right switches choices and buttons. Final Create needs a separate confirmation and never equips armor.\n'
        'After deleting a worn variant, select an ordinary owned armor and Apply to restore the old carrier and equip it.\n'
        'Includes the optional stat-selection mode, optional DiverKit adapter, and closer facemask icon.\n'
        'Helmet transmog is OFF by default. Set Helmet transmog to On in Arsenal Options to enable it, deploy and restart.\n'
        'When enabled, supported modified helmets are detected from gameplay data. Unknown worn gear is logged without blocking browsing.\n'
        'The optional helmet editor is an initial path; live combat stacking and numeric helmet previews remain unverified.\n'
        'Install as an update to Transmog; do not enable a second copy. Existing variants are retained.\n'
        'After reproducing an issue, send HD2Transmog.log, HD2Transmog.previous.log, BingusSharedLoader.log and Transmog/STATUS.txt.\n'
        'Logs are under %LOCALAPPDATA%/CowboyBingus/Helldivers2/Logs. No debug.enabled marker is needed.\n'
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
