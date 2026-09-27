"""Controller-level native preview queue tests; no game process or native calls."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

HARNESS=r'''
local now,active_view,observed=0,true,'a'
local request_name,request_args,request_ok,request_result
local patch_active_test,fail_reset=false,false
local calls,logs,files={}, {}, {}
local last_view
local State=dofile('src/state.lua')
local CatalogData,CatalogCompat={},{}
local result={source_commit='fixture',counts={kits=2,owned_armors=2},
 catalog={a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'},
          b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}},
 owned={a=true,b=true},context={labels={appearance_id={},stats_id={},passive_variant_id={}}}}
local CatalogProbe={new=function()return {step=function()return 'ready',result end}end}
local Adapter={new=function(_,_,_,_,kind)
 if kind=='catalog'then return {phase='ready',step=function()return 'ready'end,data_bridge=function()return {}end,pe_timestamp=1}end
 return {phase='ready',sample=function()if active_view then return {token='armory',kind='armory'}end end,debug_bridge=function()return {}end}
end}
local grid={phase='ready',reserved=false}
function grid:snapshot()
 return {identity_mapping_verified=true,selected_kit_id=observed,native_category=1,native_view_mode=0,appearance_previews={}}
end
function grid:select_kit(id)
 calls[#calls+1]={id=id,patch_active=patch_active_test};return {status='native_highlight_readback_verified'}
end
function grid:layout_active()return self.reserved end
function grid:reserve_top()self.reserved=true;return {status='fixture_layout_readback'}end
function grid:release_view()self.reserved=false;return true end
function grid:consume_select()return true end
local NativeGrid={new=function()return grid end}
local DebugBridge={new=function()return {poll=function(_,handlers)
 if request_name then
  local name,payload=request_name,request_args;request_name=nil
  request_ok,request_result=pcall(handlers[name],payload or '')
 end
end}end}
local RuntimeWriter={new=function()return {}end}
local AppearancePatch={new=function()return {
 plan=function(_,_,draft)return {target_id=draft.stats_id=='stats-b'and 'b'or 'a'}end,
 apply=function(_,plan)patch_active_test=true;return true,{status='memory_readback_verified',source_id='a',target_id=plan.target_id}end,
 is_active=function()return patch_active_test end,
 reset=function()
  if fail_reset then return nil,'fixture reset conflict'end
  patch_active_test=false;return true,{status='original_memory_restored',target_id='b'}
 end,
}end}
local Platform={new=function()return {
 now=function()return now end,
 read=function(name)return files[name],files[name]and nil or 'missing'end,
 write_atomic=function(name,value)files[name]=value;return true end,
 sample_input=function()return {x=0,y=0,down=false}end,
}end}
local Panel={new=function()return {clear=function()end,hit=function()return nil end,
 draw=function(_,_,view)last_view=view;return true end}end}
stingray={Gui={resolution=function()return 1920,1080 end}}
CowboyBingusModLoader={api=1,open_log=function()return {
 write=function(_,text)logs[#logs+1]=text end,flush=function()end,close=function()end}end}
local function logged(part)
 for _,line in ipairs(logs)do if line:find(part,1,true)then return true end end
 return false
end
local function advance(ms)now=now+(ms or 100);update()end
local function command(name,payload)
 request_name,request_args=name,payload;advance();return request_ok,request_result
end
'''


def run_lua(test):
    main=(ROOT/'src/main.lua').read_text()
    script=HARNESS+'\nlocal function boot()\n'+main+'\nend\nboot();now=16000;update()\n'+test
    proc=subprocess.run(['luajit','-'],input=script,text=True,capture_output=True,cwd=ROOT,timeout=10)
    assert proc.returncode==0,proc.stdout+proc.stderr


def test_preview_queue_requires_observed_requested_kit_and_times_out_wrong_kit():
    run_lua(r'''
assert(command('draft_variant','look-a stats-b perk-b\nDemo'))
assert(command('apply_variant'))
assert(#calls==1 and calls[1].id=='b')
observed='a';advance(500)
assert(not logged('variant.native_preview=b'))
advance(16000)
assert(logged('variant.native_preview_error=native selection was not observed before deadline'))
assert(not logged('variant.native_preview=b') and #calls==1)
assert(last_view.notice=='Select the Stats armor to inspect this variant.')
''')


def test_same_kit_refresh_waits_for_alternate_then_waits_for_target():
    run_lua(r'''
observed='b';advance()
assert(command('draft_variant','look-a stats-b perk-b\nDemo'))
assert(command('apply_variant'));assert(#calls==1 and calls[1].id=='a')
advance();assert(#calls==1 and not logged('variant.native_preview=b'))
observed='a';advance();assert(#calls==1)
advance();assert(#calls==2 and calls[2].id=='b')
advance();assert(not logged('variant.native_preview=b'))
observed='b';advance();assert(logged('variant.native_preview=b'))
assert(last_view.notice=='Use the native Apply button to equip this variant.')
''')


def test_successful_reset_supersedes_pending_variant_preview():
    run_lua(r'''
assert(command('draft_variant','look-a stats-b perk-b\nDemo'))
assert(command('apply_variant'));assert(#calls==1 and calls[1].patch_active)
assert(command('reset_variant'));assert(not patch_active_test)
assert(#calls==2 and calls[2].id=='b'and calls[2].patch_active==false)
observed='b';advance()
assert(last_view.notice=='Original armor selected in the native preview.')
''')


def test_leaving_native_view_cancels_pending_preview_without_new_native_selection():
    run_lua(r'''
assert(command('draft_variant','look-a stats-b perk-b\nDemo'))
assert(command('apply_variant'));assert(#calls==1)
active_view=false;advance();observed='b';advance(1000)
active_view=true;advance()
assert(#calls==1 and not logged('variant.native_preview=b'))
''')


def test_failed_reset_cancels_pending_success_notice_before_attempting_reset():
    run_lua(r'''
assert(command('draft_variant','look-a stats-b perk-b\nDemo'))
assert(command('apply_variant'));assert(#calls==1)
fail_reset=true;observed='b'
assert(not command('reset_variant'))
advance()
assert(not logged('variant.native_preview=b') and #calls==1)
''')
