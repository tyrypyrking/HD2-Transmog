"""Run the real workflow + variant session + refresh for a pristine vanilla card."""
from test_variant_session import FIXTURE
from test_runtime import run_lua


def test_vanilla_mouse_apply_cannot_reach_first_matching_native_handler():
    run_lua(FIXTURE+'''
local State=dofile('src/state.lua')
local Wizard=dofile('src/variant_wizard.lua')
local Workflow=dofile('src/ui_workflow.lua')
local domain=State.new{catalog=catalog.catalog,owned=catalog.owned}
domain.presets.Saved=request
local consumed,native_handler,focus,restores=false,0,12,0
local now=0
local panel={draw=function()return true end,clear=function()end,handle=function()return false end,
 capture=function()return false end,input_policy=function()return {}end,
 hit=function(_,x,y)
  if x==1000 and y==100 and s:view().can_apply then return {type='apply_variant',id=C}end
 end}
host.restore_focus=function(id,index)assert(id==C and index==12);focus=index;restores=restores+1;return true end
local flow=Workflow.new(State,Wizard,panel,{
 current=function()return domain,catalog.context end,
 persist=function()error('vanilla apply must not save a preset')end,
 preview_native_look=function(id,index)return s:browse(id,now,index)end,
 variant_view=function()return s:view()end,
 apply_variant=function()return s:apply(now)end,
 should_capture=function()return s:view().native_override end,
 consume_select=function()consumed=true;return true end,
})
local function frame(time,down)
 now=time;consumed=false
 local input={x=1000,y=100,down=down}
 assert(flow:before(input))
 if down and not consumed then native_handler=native_handler+1;focus=0 end
 s:step(now);flow:draw({},input)
end
assert(flow:action{type='select_native_look',id=C,index=12})
frame(0,false);frame(1,false)
assert(flow:view().native_override and flow:view().can_apply and flow:view().selected_variant==nil)
frame(2,true);assert(native_handler==0 and #commits==0)
frame(3,false);assert(s:busy()and #commits==0)
frame(4,false);assert(#commits==1 and commits[1]==C)
focus=0 -- Even an engine-side focus change is corrected once after verification.
live.cache_armor_id=C;live.cache_passive=1
frame(5,false);frame(6,false)
assert(s.phase=='equipped'and native_handler==0 and focus==12 and restores==1)
assert(plans==0 and applies==0 and resets==0 and #commits==1)
assert(flow:view().selected_variant==nil and not s:has_committed())
''')
