"""Exact duplicate-card focus never falls back to ambiguous offer selection."""
from test_ui_workflow import run_lua


FIXTURE = r'''
local Focus=dofile('src/native_grid_focus.lua')
local function clone(v)if type(v)~='table'then return v end local t={};for k,x in pairs(v)do t[k]=clone(x)end;return t end
local A,B='armor:00000001','armor:00000002'
local live,owned,captured,mutated=true,true,0,0
local model={status='read_only_logical_model',group_partition_verified=true,selected_offer_matches=true,
 selected_group_matches=true,item_count=6,row_count=2,group_count=2,
 selected_index=0,selected_row=0,selected_column=0,selected_group=0,selected_offer=10,
 marker_offer=20,scroll=0,content=480,
 rows={{index=0,first_item=0,item_count=3,height=240},{index=1,first_item=3,item_count=3,height=240}},
 groups={{index=0,key=99,first_row=0,end_row=1,first_item=0,end_item=3},
  {index=1,key=0,first_row=1,end_row=2,first_item=3,end_item=6}},offers={},
 focus_view={verified=true,logical_rows={0,1},selected_slot=0},
 verify=function()return live end,verify_owned=function(ids)return owned and #ids==1 and (ids[1]==A or ids[1]==B)end}
for i=0,5 do model.offers[i+1]={index=i,offer_id=i==4 and 20 or 10,kit_id=i==4 and B or A,
 owned=true,group_key=i<3 and 99 or 0,flag_a=0,flag_b=0}end
local after
local bridge={capabilities={exact_index_focus_verified=true,row_focus_verified=true,
 update_boundary_verified=true,input_capture_verified=true},
 verify=function(value)return value==model and live end,
 capture=function()captured=captured+1;return true end,
 focus_exact=function(plan)
  mutated=mutated+1;after=clone(model);local target=plan.to
  after.selected_index=target.index;after.selected_row=target.row;after.selected_column=target.column
  after.selected_group=target.group;after.selected_offer=target.offer_id;after.selected_offer_matches=true;after.focus_view.selected_slot=target.visible_slot
  return true
 end,
 readback=function()return after end}
local focus=Focus.new(bridge)
'''


def test_duplicate_offers_focus_the_requested_index_row_column_and_group():
    run_lua(FIXTURE + r'''
local plan=assert(Focus.prepare(model,2,A))
assert(plan.to.row==0 and plan.to.column==2 and plan.to.group==0 and plan.to.offer_id==10)
local result=assert(focus:select(model,5,A))
assert(result.logical_index==5 and result.row==1 and result.column==2 and result.offer_id==10)
assert(after.selected_index==5 and after.selected_group==1 and model.selected_index==0)
assert(captured==1 and mutated==1 and not result.equipped and not result.rendering_verified)
''')


def test_missing_proof_stale_unowned_wrong_identity_and_offscreen_requests_never_mutate():
    run_lua(FIXTURE + r'''
bridge.capabilities.row_focus_verified=false
assert(not focus:select(model,2,A));bridge.capabilities.row_focus_verified=true
live=false;assert(not focus:select(model,2,A));live=true
owned=false;assert(not focus:select(model,2,A));owned=true
assert(not focus:select(model,2,B));assert(not focus:select(model,-1,A));assert(not focus:select(model,6,A))
model.focus_view.logical_rows={0};assert(not focus:select(model,5,A))
assert(captured==0 and mutated==0)
''')


def test_changed_capture_evidence_prevents_mutation_without_offer_fallback():
    run_lua(FIXTURE + r'''
bridge.capture=function()captured=captured+1;live=false;return true end
assert(not focus:select(model,2,A)and captured==1 and mutated==0)
live=true;bridge.capture=function()return false end
assert(not focus:select(model,2,A)and mutated==0)
''')


def test_first_duplicate_readback_cannot_report_success_even_when_offer_matches():
    run_lua(FIXTURE + r'''
bridge.focus_exact=function()mutated=mutated+1;after=clone(model);return true end
local result,why=focus:select(model,2,A)
assert(not result and why:find('exact requested card',1,true)and mutated==1)
''')


def test_changed_scroll_list_marker_or_visible_mapping_invalidates_focus_result():
    run_lua(FIXTURE + r'''
local original=bridge.focus_exact
local mutations={
 function(a)a.scroll=1 end,
 function(a)a.marker_offer=10 end,
 function(a)a.offers[3].offer_id=99 end,
 function(a)a.focus_view.logical_rows={1,0}end,
}
for _,change in ipairs(mutations)do
 bridge.focus_exact=function(plan)original(plan);change(after);return true end
 assert(not focus:select(model,2,A))
end
assert(mutated==4)
''')


def test_row_partition_or_visible_row_aliasing_rejects_before_native_work():
    run_lua(FIXTURE + r'''
model.rows[2].first_item=2;assert(not focus:select(model,2,A));model.rows[2].first_item=3
model.focus_view.logical_rows={0,0};assert(not focus:select(model,2,A));model.focus_view.logical_rows={0,1}
model.focus_view.selected_slot=1;assert(not focus:select(model,2,A));model.focus_view.selected_slot=0
model.offers[3].owned=false;assert(not focus:select(model,2,A))
assert(captured==0 and mutated==0)
''')


def test_controller_cursor_can_reconcile_a_lagging_known_offer_mirror():
    run_lua(FIXTURE+r'''
model.selected_index=4;model.selected_row=1;model.selected_column=1;model.selected_group=1
model.focus_view.selected_slot=1;model.selected_offer_matches=false
local result=assert(focus:select(model,4,B))
assert(result.logical_index==4 and after.selected_offer==20 and captured==1 and mutated==1)
''')


def test_mismatched_offer_cannot_authorize_another_cursor_target_or_unknown_offer():
    run_lua(FIXTURE+r'''
model.selected_offer_matches=false
assert(not focus:select(model,4,B))
model.selected_offer=999;assert(not focus:select(model,0,A))
assert(captured==0 and mutated==0)
''')
