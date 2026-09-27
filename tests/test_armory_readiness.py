"""Main-controller regression checks for native view readiness and frame budgets."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def controller(assertions, resolver_steps=1):
    main = (ROOT / "src/main.lua").read_text()
    fixture = r"""
local State=dofile('src/state.lua')
local now,request,sample=0,nil,nil
local files,events,logs={}, {}, {}
local native_calls,catalog_steps,catalog_resolver_steps,probe_instances=0,0,0,0
local CatalogData,CatalogCompat={},{}
local CatalogProbe={new=function()
 probe_instances=probe_instances+1
 return {step=function()catalog_steps=catalog_steps+1;return 'resolving'end}
end}
local Adapter={new=function(_,_,_,_,kind)
 if kind=='catalog'then return {
  step=function()
   catalog_resolver_steps=catalog_resolver_steps+1
   return catalog_resolver_steps>=RESOLVER_STEPS and 'ready'or 'resolving'
  end,
  data_bridge=function()return {}end,
 }end
 return {phase='ready',sample=function()return sample,'hidden native grid'end,
  debug_bridge=function()return {}end}
end}
local DebugOpenArmory={new=function()return {
 step=function()return 'ready'end,
 open=function()native_calls=native_calls+1;return true,'native transition invoked'end,
}end}
local DebugBridge={new=function()return {session='fixture-session',poll=function(_,handlers)
 if request then local command=request;request=nil;assert(handlers[command]())end
end}end}
local Platform={new=function()return {
 now=function()return now end,
 read=function(name)return files[name],files[name]and nil or 'missing'end,
 sample_input=function()return {x=0,y=0,down=false}end,
 write_atomic=function(name,text)
  files[name]=text
  if name=='debug-armory-open.txt'then
   local status=assert(text:match('^HD2TM_ARMORY_OPEN 1\nfixture%-session\n([a-z]+)\n'))
   events[#events+1]=status
  end
  return true
 end,
}end}
local Panel={new=function()return {
 clear=function()end,draw=function()return true end,hit=function()return nil end,
}end}
stingray={}
CowboyBingusModLoader={api=1,open_log=function()return {
 write=function(_,text)logs[#logs+1]=text end,flush=function()end,close=function()end,
}end}
local function count(status)local n=0;for _,s in ipairs(events)do if s==status then n=n+1 end end;return n end
local function boot()
"""
    code = fixture.replace('RESOLVER_STEPS',str(resolver_steps)) + main + r"""
end
boot();now=16000;update()
assert(HD2Transmog.compat_ready)
local function tick(at,visible)
 now=at;sample=visible;update()
 assert(not table.concat(logs):find('runtime.error=',1,true),table.concat(logs))
end
local armory={kind='armory',token='armory-equipment'}
""" + assertions
    process = subprocess.run(["luajit", "-"], input=code, text=True,
                             cwd=ROOT, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stdout + process.stderr


def test_constructor_flash_and_interrupted_visibility_do_not_confirm_readiness():
    controller(r"""
request='open_armory';tick(16010,armory)
assert(native_calls==1 and count('ok')==0 and events[#events]=='pending',
 'a transient constructor grid was reported as a ready view')
tick(16090,armory);assert(count('ok')==0)
tick(16100,nil) -- The native Weapons page hides the Equipment grid.
tick(16700,armory);assert(count('ok')==0,'time hidden counted toward readiness')
tick(17000,{kind='deployment',token='other-screen'})
tick(17500,armory);assert(count('ok')==0,'a different screen did not reset readiness')
tick(17999,armory);assert(count('ok')==0,'confirmed before 500ms of visibility')
tick(18000,armory)
assert(count('ok')==1 and count('error')==0 and native_calls==1)
assert(files['debug-armory-open.txt']:find('stably observed',1,true))
tick(18500,armory);assert(count('ok')==1,'ready notification repeated')
""")


def test_unconfirmed_native_transition_times_out_once_after_45_seconds():
    controller(r"""
request='open_armory';tick(16010,nil)
assert(native_calls==1 and count('ok')==0)
tick(61009,nil);assert(count('error')==0,'deadline expired before 45 seconds')
tick(61011,nil)
assert(count('error')==1 and count('ok')==0)
assert(files['debug-armory-open.txt']:find('visibility was not confirmed',1,true))
assert(table.concat(logs):find('debug.open_armory.error=',1,true))
tick(62000,armory);tick(63000,armory)
assert(count('error')==1 and count('ok')==0,'an expired request later reported success')
assert(native_calls==1,'timeout automatically repeated the native call')
""")


def test_debug_refresh_and_visible_ui_share_one_catalog_step_per_tick():
    controller(r"""
tick(16010,armory)
assert(catalog_steps==1 and catalog_resolver_steps==1 and probe_instances==1)
for i=1,3 do
 local probes,resolver=catalog_steps,catalog_resolver_steps
 if i==1 then request='read_catalog'end
 tick(16010+i*10,armory)
 assert(catalog_steps-probes==1,'debug and UI advanced the catalog twice in one tick')
 assert(catalog_resolver_steps==resolver,'completed catalog resolver was restarted')
end
assert(probe_instances==2,'explicit refresh did not replace the old observation')
""")


def test_catalog_signatures_warm_outside_armory_without_observing_ownership():
    controller(r"""
assert(catalog_resolver_steps==1 and catalog_steps==0 and probe_instances==0)
tick(16010,nil);tick(16020,nil)
assert(catalog_resolver_steps==3 and catalog_steps==0 and probe_instances==0)
tick(16030,nil)
assert(catalog_resolver_steps==3,'completed signature discovery was repeated')
tick(16040,armory)
assert(catalog_resolver_steps==3 and catalog_steps==1 and probe_instances==1)
""",resolver_steps=3)


def test_visible_entry_and_debug_request_do_not_double_advance_warming_resolver():
    controller(r"""
assert(catalog_resolver_steps==1)
request='read_catalog';tick(16010,armory)
assert(catalog_resolver_steps==2 and probe_instances==0 and catalog_steps==0)
tick(16020,armory)
assert(catalog_resolver_steps==3 and probe_instances==1 and catalog_steps==1)
""",resolver_steps=3)
