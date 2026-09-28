"""Real catalog shapes in synthetic memory: no installed game or other mods."""
import subprocess
from test_catalog import DATA, fixture_script, ROOT

ARMOR=next(k for k in DATA['kits'].values() if k['category']==0)
HELMET=next(k for k in DATA['kits'].values() if k['category']==1)

def run(script):
    p=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr
    return p.stdout

def fixture(mutation='',checks=''):
    return fixture_script(selected=[ARMOR,HELMET],live_passives=True,mutation=mutation,
        post_ready="assert(result.helmets,'missing helmet domain'); "+checks)

def test_vanilla_helmet_is_verified_but_does_not_enable_editor():
    text=run(fixture(checks=f"""
local h=result.helmets
assert(h.catalog['{HELMET['id']}'])
assert(not h.capabilities.helmet_transmog_enabled)
assert(not result.catalog['{HELMET['id']}'])
assert(not h.owned['{HELMET['id']}'])
"""))
    assert text.startswith('ready'),text

def test_live_passive_enables_owned_helmet_without_body_donor_leak():
    text=run(fixture("patch(0x23000+28,string.char(7,0,0,0));patch(0x40000+0x1ce4+184+0x14,string.char(2,0,0,0))",f"""
local h=result.helmets;local id='{HELMET['id']}'
assert(h.capabilities.helmet_transmog_enabled and h.detected.passives_present)
assert(h.catalog[id].passive_variant_id==data.passives[7].variant_id)
assert(h.owned[id] and h.verify_owned({{id}}))
assert(not result.owned[id] and not h.catalog['{ARMOR['id']}'])
patch(0x40000+0x1ce4+184+0x14,string.char(1,0,0,0))
assert(not h.verify_owned({{id}}))
local phase
repeat phase=result.refresh_ownership()until phase~='resolving'
assert(phase=='ready'and not h.owned[id])
"""))
    assert text.startswith('ready'),text

def test_changed_helmet_weight_enables_editor_without_passive():
    text=run(fixture("""
local body=read(0x23000+48,8);local ffi=require('ffi')
local function number(s)local n=0;for i=#s,1,-1 do n=n*256+s:byte(i)end;return n end
local pieces=number(read(number(body)+8,8))
local weight=read(pieces+16,1):byte()
patch(pieces+16,string.char((weight+1)%3,0,0,0))
""", "assert(result.helmets.capabilities.helmet_transmog_enabled);assert(not result.helmets.detected.passives_present)"))
    assert text.startswith('ready'),text

def test_unrelated_header_change_is_not_promoted_to_compatibility():
    text=run(fixture("patch(0x23000+4,string.char(33,0,0,0))",f"assert(not result.helmets.catalog['{HELMET['id']}'])"))
    assert text.startswith('ready'),text

def test_changed_native_passive_effect_is_observed_instead_of_using_stale_reference():
    # Enum zero is a native placeholder with modifier_id=0. A provider can give
    # that same enum a HUD behavior without naming itself to Transmog.
    index=list(DATA['passives']).index('0')
    text=run(fixture(f"patch({0xB10000+index*0x1000+48},string.char(99,0,0,0))",f"""
local h=result.helmets;assert(h.capabilities.helmet_transmog_enabled)
local id=h.catalog['{HELMET['id']}'].passive_variant_id
assert(id~=data.passives[0].variant_id and h.context.passive_variants[id].behavior_tag==99)
"""))
    assert text.startswith('ready'),text

def test_additional_passive_enum_is_read_without_provider_registration():
    text=run(fixture("""
patch(0x23000+28,string.char(200,0,0,0))
put(0x20030+200*4,string.char(0,0,0,0))
patch(0xB10000,string.char(200,0,0,0))
patch(0xB10000+48,string.char(42,0,0,0))
""",f"""
local h=result.helmets;assert(h.capabilities.helmet_transmog_enabled)
local id=h.catalog['{HELMET['id']}'].passive_variant_id
assert(h.context.passive_variants[id].enum==200 and h.context.passive_variants[id].behavior_tag==42)
"""))
    assert text.startswith('ready'),text
