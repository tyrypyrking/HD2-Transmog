"""Controller-only creation: all stages, paging, back/cancel and safe gestures."""
from test_variant_wizard import FIXTURE, run_lua
from test_wizard_panel import RENDER_FIXTURE

FLOW = FIXTURE+RENDER_FIXTURE+r'''
local Workflow=dofile('src/ui_workflow.lua')
local now,saves,equips,previews,captures,leaks=0,0,0,0,0,0
local captured=false
sample.custom_section={x=172,y=650,w=644,h=196}
local source='XInput0'
local host={current=function()return state,context end,now=function()return now end,
 controller_action=function()return {type='open'}end,validate_confirm=function()return true end,
 should_capture=function()return true end,
 consume_select=function()captured=true;return true end,
 consume_creator=function()captured=true;captures=captures+1;return true end,
 preview_look=function()previews=previews+1;return true end,
 apply_variant=function()equips=equips+1;return true end,
 persist=function(tx)saves=saves+1;state=tx.candidate;return true,state end}
local flow=Workflow.new(S,W,panel,host)
local function frame(changes,dt)
 now=now+(dt or 100);captured=false
 local input={x=-1,y=-1,down=false,controller_source=source,confirm_down=false,back_down=false,cancel_down=false,
 nav_x=0,nav_y=0,page_prev_down=false,page_next_down=false}
 for k,v in pairs(changes or {})do input[k]=v end
 local ok,why=flow:before(input);assert(ok,why)
 if (input.confirm_down or input.back_down or input.cancel_down or input.nav_x~=0 or input.nav_y~=0)and not captured then leaks=leaks+1 end
 assert(flow:draw(sample,input))
 return flow:view()
end
local function button(name)frame({[name]=true});return frame()end
local function open()
 frame();button('confirm_down');frame()
 assert(flow:is_open()and flow:view().controller_mode and flow:view().step==1)
end
local function finish()
 button('confirm_down') -- look
 if flow:view().step==2 then button('confirm_down')end -- stats
 assert(flow:view().step==3)
 button('confirm_down') -- passive
 assert(flow:view().can_create and flow:view().controller_focus.type=='create')
 button('confirm_down') -- create
 assert(not flow:is_open()and saves==1 and equips==0 and leaks==0)
end
'''


def test_three_stage_creator_is_completed_without_a_mouse():
    run_lua(FLOW+r'''
local before=S.encode(state)
open();frame({nav_y=-1});frame()
assert(flow:view().controller_focus.id=='look-b')
finish()
assert(previews==1 and captures>5 and S.encode(state)~=before)
assert(state.presets.Existing and state.selected.stats_id=='stats-a')
''')


def test_two_stage_creator_is_completed_without_a_mouse():
    run_lua(FLOW+r'''
host.stats_follow_look=true;flow=Workflow.new(S,W,panel,host)
open();assert(flow:view().step_count==2)
finish()
''')


def test_every_owned_look_and_passive_can_be_reached_across_pages():
    run_lua(FLOW+r'''
for i=1,18 do
 local n=string.format('%02d',i)
 catalog['new'..n]={appearance_id='look-z'..n,stats_id='stats-a',passive_variant_id='perk-z'..n}
end
local owned={};for id in pairs(catalog)do if id~='locked'then owned[#owned+1]=id end end
S.reconcile_owned(state,catalog,owned)
open();local first=flow:view().controller_focus.id
button('page_next_down')
assert(flow:view().controller_page==2 and flow:view().controller_focus.id~=first)
local target=flow:view().controller_focus.id;local visible=false
for _,r in ipairs(panel.regions)do if r.action.type=='select_look'and r.action.id==target then visible=true end end
assert(visible,'focused look is off the visible page')
button('confirm_down');button('confirm_down')
button('page_next_down');assert(flow:view().controller_page==2)
button('confirm_down');assert(flow:view().can_create)
button('confirm_down');assert(saves==1 and equips==0)
''')


def test_back_cancel_and_directional_access_to_action_buttons():
    run_lua(FLOW+r'''
local before=S.encode(state)
open();button('confirm_down');assert(flow:view().step==2)
button('back_down');assert(flow:view().step==1)
frame({nav_x=1});frame();assert(flow:view().controller_focus.type=='cancel')
button('confirm_down');assert(not flow:is_open()and S.encode(state)==before)
open();button('confirm_down');button('cancel_down')
assert(not flow:is_open()and S.encode(state)==before and saves==0 and equips==0)
open();button('back_down');assert(not flow:is_open())
''')


def test_holds_focus_loss_and_device_changes_do_not_accidentally_advance_or_save():
    run_lua(FLOW+r'''
open();frame({confirm_down=true})
for i=1,15 do frame({confirm_down=true})end
assert(flow:view().step==1)
source='XInput1';frame();assert(flow:view().step==1)
button('confirm_down');assert(flow:view().step==2)
frame({confirm_down=true});flow:before(nil);frame()
assert(flow:view().step==2)
button('confirm_down');button('confirm_down');assert(flow:view().can_create)
frame({confirm_down=true});flow:clear();frame();assert(flow:is_open()and saves==0)
button('confirm_down');assert(not flow:is_open()and saves==1 and equips==0)
''')


def test_repeat_navigation_is_bounded_and_stale_ownership_disarms_confirmation():
    run_lua(FLOW+r'''
open();frame({nav_y=-1},1)
local id=flow:view().controller_focus.id
for i=1,10 do frame({nav_y=-1},10)end
assert(flow:view().controller_focus.id==id)
frame({nav_y=-1},400);assert(flow:view().controller_focus.id~=id)
frame();frame({confirm_down=true})
S.reconcile_owned(state,catalog,{'a'})
frame();assert(flow:view().step==1 and previews==0 and saves==0)
''')


def test_failed_save_keeps_creator_open_and_focus_on_explicit_retry():
    run_lua(FLOW+r'''
local persist=host.persist;host.persist=function()return nil,'disk full'end
open();button('confirm_down');button('confirm_down');button('confirm_down')
button('confirm_down');assert(flow:is_open()and flow:view().notice=='disk full'and saves==0)
host.persist=persist;button('confirm_down');assert(not flow:is_open()and saves==1)
''')



def test_unavailable_rendering_cannot_advance_or_create():
    run_lua(FLOW+r"""
open();frame({confirm_down=true})
local draw=panel.draw;panel.draw=function()return false end
local input={x=-1,y=-1,down=false,controller_source=source,confirm_down=false,nav_x=0,nav_y=0}
assert(flow:before(input));assert(not flow:draw(sample,input))
assert(flow:view().step==1 and saves==0 and previews==0)
panel.draw=draw;frame();button('confirm_down');assert(flow:view().step==2)
""")


def test_controller_focus_is_on_visible_controls_at_ultrawide_and_small_resolutions():
    for width,height in [(1280,720),(1920,1080),(3440,1440)]:
        run_lua(FLOW+f'resolution={{{width},{height}}}\n'+r"""
local scale=math.min(resolution[1]/1920,resolution[2]/1080)
local left=(resolution[1]-1920*scale)/2
sample.custom_section={x=left+172*scale,y=650*scale,w=644*scale,h=196*scale}
open();frame({nav_y=-1});frame()
local focus=flow:view().controller_focus
local found=false
for _,r in ipairs(panel.regions)do
 if r.action.type==focus.type and r.action.id==focus.id then
  assert(r.x>=0 and r.y>=0 and r.x+r.w<=resolution[1] and r.y+r.h<=resolution[2]);found=true
 end
end
assert(found)
finish()
""")



def test_mouse_click_does_not_replace_controller_look_list_mid_gesture():
    run_lua(FLOW+r"""
open();local wanted
for _,r in ipairs(panel.regions)do if r.action.type=='select_look'and r.action.id=='look-b'then wanted=r end end
assert(wanted)
local x,y=wanted.x+wanted.w/2,wanted.y+wanted.h/2
frame({down=true,x=x,y=y});assert(flow:view().controller_mode and flow:view().step==1)
frame({x=x,y=y});assert(flow:view().step==2 and flow:view().selection.appearance_id=='look-b')
assert(previews==1 and saves==0 and equips==0)
""")


def test_optional_controller_capture_failure_keeps_mouse_creator_available():
    run_lua(FLOW+r'''
host.consume_creator=function()return nil,'unverified direction reader'end
frame();button('confirm_down');frame()
assert(flow:is_open()and flow:view().step==1 and not flow:view().controller_mode)
assert(saves==0 and equips==0)
local cancel
for _,r in ipairs(panel.regions)do if r.action.type=='cancel'then cancel=r end end
assert(cancel)
frame({down=true,x=cancel.x+cancel.w/2,y=cancel.y+cancel.h/2})
frame({x=cancel.x+cancel.w/2,y=cancel.y+cancel.h/2})
assert(not flow:is_open()and saves==0)
host.consume_creator=function()captured=true;return true end
open();assert(flow:view().controller_mode)
''')


def test_mouse_paging_in_controller_layout_persists_and_keeps_a_reachable_focus():
    run_lua(FLOW+r'''
for i=1,18 do
 local n=string.format('%02d',i)
 catalog['new'..n]={appearance_id='look-z'..n,stats_id='stats-a',passive_variant_id='perk-z'..n}
end
local owned={};for id in pairs(catalog)do if id~='locked'then owned[#owned+1]=id end end
S.reconcile_owned(state,catalog,owned)
open()
local next_page
for _,r in ipairs(panel.regions)do
 if r.action.type=='panel_page'and r.action.target=='options'and r.action.delta==1 then next_page=r end
end
assert(next_page)
local x,y=next_page.x+next_page.w/2,next_page.y+next_page.h/2
frame({down=true,x=x,y=y});frame({x=x,y=y});frame({x=x,y=y})
assert(flow:view().controller_page==2)
local focus=flow:view().controller_focus.id
button('confirm_down')
assert(flow:view().step==2 and flow:view().selection.appearance_id==focus)
assert(saves==0 and equips==0)
''')


def test_native_look_grid_stays_visible_for_controller_and_mouse_selection():
    run_lua(FLOW+r'''
host.controller_native_looks=true
host.controller_look_order=function()return {'look-b','look-a'}end
local highlighted={}
host.focus_look=function(id)highlighted[#highlighted+1]=id;return true end
host.look_at=function()return 'look-a'end
open()
assert(flow:view().controller_native_looks and highlighted[1]=='look-b')
assert(panel:input_policy().native_look_pick and not panel:input_policy().block_native_grid)
for _,r in ipairs(panel.regions)do assert(r.action.type~='select_look','custom list covered native thumbnails')end
frame({nav_x=1});frame()
assert(highlighted[#highlighted]=='look-a'and flow:view().controller_focus.id=='look-a')
button('confirm_down');assert(flow:view().step==2 and previews==1)
button('back_down');frame()
local r=panel:input_policy().native_picker_rect
local x,y=r.x+r.w/2,r.y+r.h/2
frame({x=x,y=y,down=true});frame({x=x,y=y})
assert(flow:view().step==2 and flow:view().selection.appearance_id=='look-a')
assert(saves==0 and equips==0)
''')


def test_native_grid_paging_and_cancel_do_not_create_or_equip():
    run_lua(FLOW+r'''
host.controller_native_looks=true;host.focus_look=function()return true end
for i=1,18 do
 local n=string.format('%02d',i)
 catalog['new'..n]={appearance_id='look-z'..n,stats_id='stats-a',passive_variant_id='perk-z'..n}
end
local owned={};for id in pairs(catalog)do if id~='locked'then owned[#owned+1]=id end end
S.reconcile_owned(state,catalog,owned)
open();local first=flow:view().controller_focus.id
button('page_next_down');assert(flow:view().controller_page==2 and flow:view().controller_focus.id~=first)
button('page_prev_down');assert(flow:view().controller_focus.id==first)
button('cancel_down');assert(not flow:is_open()and saves==0 and equips==0)
''')
