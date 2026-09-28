"""Optional Lua adapter: exact recipe persistence and serialized application."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(code):
    p = subprocess.run(['luajit', '-'], input=code, text=True, cwd=ROOT,
                       capture_output=True, timeout=20)
    assert p.returncode == 0, p.stdout + p.stderr


FIXTURE = r'''
local C=dofile('src/diverkit_compat.lua')
local function clone(s)local out={};for k,v in pairs(s)do out[k]=v end;return out end
local Model={}
function Model.validate_snapshot(s)assert(type(s)=='table'and type(s.armor)=='string');return s end
function Model.copy_snapshot(s)Model.validate_snapshot(s);return {armor=s.armor,primary=s.primary}end
function Model.mask(mask)return mask and clone(mask)or {armor=true,primary=true}end
function Model.compose(saved,current,mask)
 local out=Model.copy_snapshot(current)
 for k,v in pairs(Model.mask(mask))do if v then out[k]=saved[k]end end
 return out
end
local Apply={}
local native_starts,native_polls,native_cancels=0,0,0
local native_fail=false
function Apply.new()
 return {busy=false,start=function(self,snapshot,now,mask)
  native_starts=native_starts+1;self.mask=mask;self.busy=true;return true,'Applying'
 end,poll=function(self,now)
  native_polls=native_polls+1;self.busy=false
  return native_fail and 'Apply not confirmed' or 'Preset applied'
 end,cancel=function(self)native_cancels=native_cancels+1;self.busy=false;return 'cancelled'end}
end
local state={};local context={};local activation
local capture=function()return {armor='0x00000001',primary='0x00000002'}end
local function tick()return state,Model,Apply,capture,context,activation end
local function after()return tick()end
local function update()return after()end
local binding=assert(C.find(update,state))
local recipe={version=1,label='Variant A',appearance_id='armor:00000001',stats_id='stats-b',passive_variant_id='perk-c'}
local live=recipe;local active=true;local begins,polls,cancels,prepares=0,0,0,0
local phase='complete';local refuse=false;local logs={}
local host={report=function(k,v)logs[#logs+1]={k,v}end,
 capture=function()return live end,active=function()return active end,
 prepare=function(value,armor,driver)
  prepares=prepares+1
  if refuse then return nil,'ownership changed'end
  assert(driver.model==Model and driver.apply==Apply)
  return {begin=function(now)begins=begins+1;return true end,
   poll=function(now)polls=polls+1;return phase,'fixture failure'end,
   cancel=function(why)cancels=cancels+1 end}
 end}
local original_capture=capture
local adapter=C.attach(binding,host)
local instance=Apply.new(context,capture)
'''


def test_absent_or_unsupported_diverkit_never_changes_global_update_or_native_behavior():
    run(r'''
local C=dofile('src/diverkit_compat.lua')
local calls=0;local fn=function()calls=calls+1 end
local adapter=C.new{report=function()end}
for i=0,100 do adapter:step(i*1000,fn,nil)end
assert(adapter.status=='absent'and calls==0 and not adapter:busy())
local state={};adapter:step(101000,fn,state)
assert(adapter.status=='waiting'and calls==0)
assert(not C.supported({},{}))
local capture=function()end
local Model={};local Apply={}
local function tick()return state,Model,Apply,capture end
adapter:step(102000,tick,state)
assert(adapter.status=='unsupported'and tick()==state and calls==0)
adapter:shutdown()
''')


def test_capture_and_copies_preserve_exact_same_look_recipes_and_partial_masks():
    run(FIXTURE+r'''
local a=capture();assert(a.transmog.label=='Variant A')
local b=clone(recipe);b.label='Variant B';b.stats_id='stats-c';b.passive_variant_id='perk-b'
live=b;local second=capture()
assert(a.armor==second.armor and a.transmog.stats_id~=second.transmog.stats_id)
local saved=Model.copy_snapshot(a)
assert(saved.transmog~=a.transmog and saved.transmog.stats_id=='stats-b')
a.transmog.stats_id='changed';assert(saved.transmog.stats_id=='stats-b')
assert(Model.compose(saved,second,{armor=true}).transmog.label=='Variant A')
assert(Model.compose(saved,second,{primary=true}).transmog.label=='Variant B')
live=false;assert(capture().transmog==false)
assert(Model.compose(capture(),second,{armor=true}).transmog==false)
assert(Model.compose({armor=second.armor,primary=second.primary},second,{armor=true}).transmog==nil)
''')


def test_same_look_switch_runs_transmog_even_without_native_armor_change():
    run(FIXTURE+r'''
local saved=capture()
assert(instance:start(saved,0,{armor=true}))
assert(native_starts==0 and instance.busy and prepares==1 and begins==0)
assert(instance:poll(1)=='Preset applied')
assert(begins==1 and polls==1 and not instance.busy and not adapter:busy())
''')


def test_other_equipment_finishes_before_transmog_and_no_success_is_reported_early():
    run(FIXTURE+r'''
local saved=capture();phase='applying'
assert(instance:start(saved,0))
assert(native_starts==1 and instance.mask.armor==false and instance.mask.primary==true)
assert(instance:poll(1)==nil and begins==1 and instance.busy)
assert(not instance:start(saved,2))
phase='complete';assert(instance:poll(3)=='Preset applied'and not instance.busy)
assert(begins==1 and polls==2 and native_polls==1)
''')


def test_ordinary_and_armor_excluded_presets_preserve_vanilla_behavior():
    run(FIXTURE+r'''
local saved=capture()
assert(instance:start(saved,0,{primary=true}))
assert(prepares==0 and native_starts==1)
assert(instance:poll(1)=='Preset applied'and begins==0)
active=false;live=false;saved=capture()
assert(instance:start(saved,2))
assert(prepares==0 and native_starts==2 and instance.mask==nil)
instance:poll(3)
-- A vanilla preset must explicitly remove an active composition, even if IDs match.
active=true;assert(instance:start(saved,4,{armor=true}))
assert(prepares==1 and native_starts==2)
assert(instance:poll(5)=='Preset applied'and begins==1)
''')


def test_rejected_or_cancelled_operation_never_reports_success_or_retries():
    run(FIXTURE+r'''
local saved=capture();refuse=true
assert(not instance:start(saved,0))
assert(native_starts==0 and begins==0 and not instance.busy)
refuse=false;native_fail=true
assert(instance:start(saved,1))
assert(instance:poll(2)=='Apply not confirmed')
assert(begins==0 and cancels==1 and not instance.busy)
native_fail=false;phase='applying'
assert(instance:start(saved,3,{armor=true}))
assert(instance:poll(4)==nil)
assert(instance:cancel('screen changed'):find('interrupted'))
assert(cancels==2 and not instance.busy)
assert(instance:start(saved,5,{armor=true}))
adapter:watch(2006)
assert(not instance.busy and cancels==3)
''')


def test_invalid_metadata_and_unverified_capture_fail_without_native_mutation():
    run(FIXTURE+r'''
local saved=capture();saved.transmog.appearance_id='armor:ffffffff'
assert(not instance:start(saved,0)and prepares==0 and native_starts==0)
assert(not pcall(Model.copy_snapshot,saved))
saved=capture();saved.transmog.version=99
assert(not pcall(Model.copy_snapshot,saved))
saved=capture();saved.transmog.injection=function()end
assert(not pcall(Model.copy_snapshot,saved))
live=nil;assert(capture()==nil)
assert(native_starts==0)
''')


def test_shutdown_unwraps_only_owned_functions_and_cancels_pending_operations():
    run(FIXTURE+r'''
assert(instance:start(capture(),0,{armor=true}))
local foreign=function()return 'foreign'end
Model.compose=foreign
adapter:shutdown()
assert(capture==original_capture and cancels==1 and not instance.busy)
assert(Model.compose==foreign)
assert(Model.copy_snapshot({armor='0x00000001',transmog=recipe}).transmog==nil)
''')


SOURCE = ROOT/'vendor/DiverKit-reference/loadouts.lua'


def real_modules(source_path=SOURCE):
    if not source_path.exists():
        pytest.skip('Optional locally installed DiverKit source is unavailable')
    source = source_path.read_text()
    source = source[:source.index('local ok,why=pcall(start_presets)')]
    return source + r'''
Files.rotate_log=function()return true,'fixture'end
Pointer.new=function()return {}end
PadHotkeys.new=function()return {}end
Panel.new=function()return {clear=function()end}end
return {model=Model,apply=Apply,json=JSON,start=start_presets}
'''


@pytest.mark.parametrize('source_path', [SOURCE, SOURCE.with_name('loadouts-8.10.1.lua')])
def test_supported_installed_source_is_discovered_and_real_atomic_saves_keep_metadata(source_path):
    source = real_modules(source_path)
    run("local original_source=[==========["+source+"]==========]\n"+r'''
local real_require=require
local env=setmetatable({}, {__index=_G});env._G=env
local fakefile={write=function()end,flush=function()end,close=function()end}
env.CowboyBingusModLoader={open_log=function()return fakefile end}
env.stingray={}
env.require=function(name)
 if name=='ffi'then return {cdef=function()end,load=function()return {GetTickCount64=function()return 0 end}end}end
 return real_require(name)
end
local chunk=assert(loadstring(original_source,'@mods/codex/loadouts'));setfenv(chunk,env)
local real=chunk();real.start()
local C=dofile('src/diverkit_compat.lua')
assert(C.supported(real.model,real.apply),'supported-source fingerprint differs')
local binding=assert(C.find(env.update,env.CodexLoadouts))
local adapter=C.attach(binding,{capture=function()return false end,active=function()return false end})
local JSON,Model=real.json,real.model
local slots=JSON.array();for i=1,4 do slots[i]={slot=i,key=JSON.null,enum=0}end
local a={schema_version=4,source_version='fixture',armor='0x00000001',helmet='0x00000002',cape='0x00000003',
 primary='0x00000004',pistol='0x00000005',grenade='0x00000006',title='0x00000000',player_card='0x00000000',booster='0x00000000',stratagems=slots,
 transmog={version=1,label='A',appearance_id='armor:00000001',stats_id='native-stats:00000002',passive_variant_id='passive-a'}}
local bytes
local fs={read=function()return nil,'missing'end,write_atomic=function(_,value)bytes=value;return true end}
local store=Model.new(fs);assert(store:save(a,nil,1))
a.transmog.label='B';a.transmog.passive_variant_id='passive-b';assert(store:save(a,nil,2))
local decoded=JSON.decode(bytes)
assert(decoded.presets[1].loadout.transmog.label=='A')
assert(decoded.presets[2].loadout.transmog.label=='B')
assert(store:rename(1,'New name')and store:set_apply_fields(1,{armor=true}))
assert(JSON.decode(bytes).presets[1].loadout.transmog.label=='A')
a.transmog=false;assert(store:save(a,1))
assert(JSON.decode(bytes).presets[1].loadout.transmog==false)
local before=bytes;fs.write_atomic=function()return false,'disk full'end
a.transmog=nil;assert(not store:save(a,1));assert(bytes==before)
assert(store.db.presets[1].loadout.transmog==false)
adapter:shutdown();assert(C.supported(real.model,real.apply))
-- Recognize a late-installed addon behind either update-hook ordering.
local root=env.update
local function wrapper()return root()end
local detector=C.new{capture=function()return false end,active=function()return false end}
detector:step(0,wrapper,nil);assert(detector.status=='absent')
detector:step(1000,wrapper,env.CodexLoadouts);assert(detector.status=='attached')
assert(not detector:busy())
detector:step(1001,wrapper,nil);assert(detector.status=='absent')
assert(C.supported(real.model,real.apply),'detaching failed to restore originals')
local original=real.apply.preflight
real.apply.preflight=function()error('unsupported implementation')end
detector:step(2002,wrapper,env.CodexLoadouts);assert(detector.status=='unsupported')
real.apply.preflight=original

''')



def test_bad_capture_and_activity_probe_are_isolated_from_diverkit():
    run(FIXTURE+r"""
live={version=99};assert(capture()==nil)
live=false;active=false
local saved=capture()
host.active=function()error('player read unavailable')end
local ok,why=instance:start(saved,0)
assert(not ok and why:find('player read unavailable')and native_starts==0 and not instance.busy)
assert(instance:start(saved,1,{primary=true}))
assert(instance:poll(2)=='Preset applied')
""")
