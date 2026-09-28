"""Runtime host integration: optional discovery and exact equipped-state binding."""
from test_creator_failure_main import HARNESS, ROOT
from test_startup_restore_main import SEED
from test_diverkit_compat import run


def main_run(body, before=''):
    adapters = r'''
local compat_host
local DiverKitCompat={new=function(host)
 compat_host=host
 return {status='fixture',busy=function()return false end,step=function()end,shutdown=function()end}
end}
local DiverKitBridge={new=function()return runtime_bridge end}
'''
    run(HARNESS+SEED+adapters+before+'\nlocal function boot()\n'+(ROOT/'src/main.lua').read_text()+r'''
end
local runtime=boot();assert(runtime.status~='startup_failed',runtime.status)
now=16000
for i=1,30 do tick_ship()end
'''+body)


def test_capture_binds_only_verified_equipped_recipe_and_external_apply_completes():
    main_run(r'''
local record=assert(compat_host.capture('0x00000001'))
assert(record.label=='Saved'and record.stats_id=='stats-b'and record.passive_variant_id=='perk-a')
local bad={version=1,label='Missing',appearance_id=A,stats_id='stats-b',passive_variant_id='perk-a'}
assert(not compat_host.prepare(bad,'0x00000001',{}))
assert(commits==2)
local op=assert(compat_host.prepare(record,'0x00000001',{}))
assert(op.begin(now))
for i=1,15 do
 now=now+100
 live.cache_armor_id=live.request_armor_id;live.cache_passive=live.request_armor_id==A and 1 or 7
 op.poll(now)
end
local phase,why=op.poll(now+1);assert(phase=='complete',why)
assert(commits==4 and patches==1,'same recipe reused its verified patch')
assert(compat_host.capture('0x00000001').label=='Saved')
assert(logged_count('runtime.error=')==0)
''')


def test_preflight_rejects_unowned_or_changing_armor_before_any_operation():
    main_run(r'''
local record=assert(compat_host.capture('0x00000001'))
result.owned[B]=false
assert(not compat_host.prepare(record,'0x00000001',{}))
result.owned[B]=true
live.cache_armor_id=C
assert(not compat_host.capture('0x00000001'))
assert(not compat_host.prepare(record,'0x00000001',{}))
assert(commits==2 and patches==1)
''')


def test_main_is_inert_without_diverkit_and_reports_absence():
    from test_creator_failure_main import run as run_main
    run_main(r'''
assert(runtime.diverkit_compat.status=='absent')
assert(not runtime.diverkit_compat:busy())
assert(logged_count('diverkit.error=')==0)
assert(command('open_creator')and flow:view().step_count==3)
''')
