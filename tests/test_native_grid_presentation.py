"""Presentation transaction policy; injected fake constructors, never native calls."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=r'''
local P=dofile('src/native_grid_presentation.lua')
local function copy(v)if type(v)~='table'then return v end;local t={};for k,x in pairs(v)do t[k]=copy(x)end;return t end
local source={menu_token='menu-one',kind=4,compact=false,layout_verified=true,columns=3,
 base_row_height=200,header_height=46,root_geometry={x=172,y=-238,width=644,height=738},
 entries={},rows={},groups={{key=0,first_row=0,first_item=0},{key=1,first_row=9,first_item=27},{key=2,first_row=24,first_item=70}},
 item_count=93,row_count=32,group_count=3,content=6538,selected_offer_id=1002,marker_offer_id=1003,scroll_value=0}
for i=1,93 do source.entries[i]={offer_id=1000+i,kit_id=string.format('armor:%08x',i),owned=true,
 group_key=i<=27 and 0 or(i<=70 and 1 or 2),flag_a=1,flag_b=i%2}end
local first=0
for row=0,31 do
 local count=row==23 and 1 or(row==31 and 2 or 3)
 source.rows[row+1]={count=count,first_item=first,height=(row==0 or row==9 or row==24)and 246 or 200};first=first+count
end
local cards={{key='saved-one',kind='variant',kit_id='armor:00000001'},
 {key='create',kind='create',kit_id='armor:00000003'}}
local events={};local current=copy(source);local owner=true;local generation=true;local ownership=true;local captured=false
local counts={clear=0,append=0,finish=0,view=0,begin=0,['end']=0}
local bridge={capabilities={constructor_verified=true,input_capture_verified=true,view_restore_verified=true,update_boundary_verified=true}}
function bridge.snapshot()return copy(source)end
function bridge.verify(snapshot)return snapshot.menu_token==source.menu_token and owner and generation end
function bridge.verify_owned(ids)assert(#ids<=16);return ownership end
function bridge.same_menu(ticket)return owner and ticket.menu==source.menu_token end
function bridge.owns(ticket)return generation end
function bridge.begin(snapshot)counts.begin=counts.begin+1;events[#events+1]='begin';return {menu=snapshot.menu_token}end
function bridge.capture(value,ticket)captured=value;events[#events+1]=value and 'capture' or 'release';return true end
function bridge.clear(ticket)
 assert(captured);counts.clear=counts.clear+1;events[#events+1]='clear'
 current=copy(source);current.entries={};current.rows={};current.groups={};current.content=0
 current.selected_offer_id=0;current.marker_offer_id=0;return true
end
function bridge.append(ticket,entry)
 assert(captured);counts.append=counts.append+1;events[#events+1]='append'
 current.entries[#current.entries+1]=copy(entry);return true
end
function bridge.finish(ticket)
 assert(captured);counts.finish=counts.finish+1;events[#events+1]='finish'
 local last,columns=nil,0
 for i,e in ipairs(current.entries)do
  if last~=e.group_key then
   if columns>0 then columns=0 end
   current.groups[#current.groups+1]={key=e.group_key,first_row=#current.rows,first_item=i-1};last=e.group_key
  end
  if columns==0 then
   current.rows[#current.rows+1]={count=0,first_item=i-1,height=200}
   if current.groups[#current.groups].first_row==#current.rows-1 then current.rows[#current.rows].height=246 end
  end
  local row=current.rows[#current.rows];row.count=row.count+1;columns=(columns+1)%3
 end
 current.item_count=#current.entries;current.row_count=#current.rows;current.group_count=#current.groups
 for _,row in ipairs(current.rows)do current.content=current.content+row.height end
 return true
end
function bridge.restore_view(ticket,view,custom)
 counts.view=counts.view+1;events[#events+1]='view'
 current.selected_offer_id=custom and 0 or view.selected_offer_id
 current.marker_offer_id=custom and 0 or view.marker_offer_id;current.scroll_value=view.scroll_value;return true
end
function bridge.view_matches(ticket,view,custom)
 return current.selected_offer_id==(custom and 0 or view.selected_offer_id)
  and current.marker_offer_id==(custom and 0 or view.marker_offer_id)and current.scroll_value==view.scroll_value
end
function bridge.readback()return copy(current)end
function bridge.end_update()counts['end']=counts['end']+1;events[#events+1]='end';return true end
function bridge.resume_update()events[#events+1]='resume';return true end
local controller=P.new(bridge)
'''


def run(code):
    result=subprocess.run(['luajit','-'],input=FIXTURE+code,text=True,capture_output=True,cwd=ROOT,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr


def test_real_native_model_prefix_preserves_originals_exact_flags_and_geometry():
    run('''
source.entries[1].flag_b=127
local plan=P.prepare(source,cards)
assert(plan.proposed.item_count==95 and plan.proposed.row_count==33 and plan.proposed.group_count==4)
assert(plan.proposed.content==6784 and plan.proposed.root_geometry.y==-238)
assert(plan.proposed.groups[2].first_row==1 and plan.proposed.groups[2].first_item==2)
assert(plan.proposed.entries[1].flag_b==127 and plan.proposed.entries[1].offer_id==source.entries[1].offer_id)
for i,e in ipairs(source.entries)do local a=plan.proposed.entries[i+2]
 assert(a.offer_id==e.offer_id and a.group_key==e.group_key and a.flag_a==e.flag_a and a.flag_b==e.flag_b)end
assert(plan.cards[2].opaque and plan.cards[2].input_capture_required and not plan.rendering_verified)
plan.proposed.entries[3].flag_b=17;assert(source.entries[1].flag_b==127)
''')


def test_success_order_capture_and_single_finish_without_visual_claim_or_repeat():
    run('''
local r=controller:attempt(cards);assert(r.phase=='active' and not r.rendering_verified,r.error)
assert(events[1]=='begin' and events[2]=='capture' and events[3]=='clear')
assert(counts.clear==1 and counts.append==95 and counts.finish==1 and counts['end']==1 and captured)
assert(events[#events-2]=='finish' and events[#events-1]=='view' and events[#events]=='end')
local before=#events;r=controller:attempt(cards)
assert(r.phase=='active' and #events==before and captured)
''')


def test_explicit_restoration_reconstructs_originals_and_burns_menu_token():
    run('''
assert(controller:attempt(cards).phase=='active')
local r=controller:restore();assert(r.phase=='restored' and r.error==nil)
assert(P.matches(current,source) and current.selected_offer_id==1002 and current.marker_offer_id==1003)
assert(counts.clear==2 and counts.append==188 and counts.finish==2 and not captured)
local before=#events;controller:attempt(cards);controller:restore();assert(#events==before)
source.menu_token='menu-two';assert(controller:attempt(cards).phase=='active')
assert(counts.clear==3)
''')


def test_invalid_owned_recipe_or_capability_never_begins_a_native_update():
    run('''
source.entries[1].owned=false
assert(controller:attempt(cards).phase=='blocked' and counts.begin==0 and counts.clear==0)
source.entries[1].owned=true;assert(controller:attempt(cards).phase=='blocked' and counts.begin==0)
source.menu_token='menu-two';bridge.capabilities.input_capture_verified=false
assert(controller:attempt(cards).phase=='blocked' and counts.begin==0)
''')


def test_limits_zero_offer_missing_flags_and_create_order_are_preflight_errors():
    run('''
for _,key in ipairs({'offer_id','flag_a','flag_b'})do
 local old=source.entries[1][key];source.entries[1][key]=nil
 assert(not pcall(P.prepare,source,cards));source.entries[1][key]=old
end
source.entries[1].offer_id=0;assert(not pcall(P.prepare,source,cards));source.entries[1].offer_id=1001
source.entries[1].flag_a=256;assert(not pcall(P.prepare,source,cards));source.entries[1].flag_a=1
cards[1].kind='create';assert(not pcall(P.prepare,source,cards));cards[1].kind='variant'
cards[2].kit_id='armor:ffffffff';assert(not pcall(P.prepare,source,cards))
assert(counts.clear==0)
''')


def test_failed_append_restores_once_and_never_retries_custom_insertion():
    run('''
local append=bridge.append;local calls=0
bridge.append=function(...)
 calls=calls+1;if calls==3 then error('simulated append failure')end;return append(...)
end
local r=controller:attempt(cards)
assert(r.phase=='restored' and r.error:find('append failure'))
assert(P.matches(current,source) and counts.clear==2 and counts.finish==1 and not captured)
local before=#events;controller:attempt(cards);controller:restore();assert(#events==before)
''')


def test_uncertain_finish_is_never_repeated_without_clear():
    run('''
local finish=bridge.finish;local calls=0
bridge.finish=function(...)
 calls=calls+1;local result=finish(...);if calls==1 then return nil end;return result
end
local r=controller:attempt(cards);assert(r.phase=='restored',r.error)
assert(counts.clear==2 and counts.finish==2 and P.matches(current,source))
local first_finish
for i,event in ipairs(events)do if event=='finish'then first_finish=i;break end end
assert(events[first_finish+1]=='clear','uncertain finish was retried without reconstruction')
''')


def test_equal_totals_but_wrong_flags_or_order_fail_readback_and_restore():
    run('''
local read=bridge.readback;local reads=0
bridge.readback=function(...)
 reads=reads+1;local value=read(...)
 if reads==1 then value.entries[1].flag_b=99 end;return value
end
local r=controller:attempt(cards);assert(r.phase=='restored' and r.error:find('readback differs'))
assert(counts.clear==2 and P.matches(current,source))
local wrong=copy(source);wrong.entries[1],wrong.entries[2]=wrong.entries[2],wrong.entries[1]
assert(not P.matches(wrong,source))
''')


def test_external_generation_or_retired_menu_prevents_restoration_writes():
    run('''
local append=bridge.append
bridge.append=function(...)local r=append(...);generation=false;return r end
local r=controller:attempt(cards);assert(r.phase=='retired')
assert(counts.clear==1 and counts.append==1 and counts.finish==0 and not captured)
''')
    run('''
local clear=bridge.clear
bridge.clear=function(...)local r=clear(...);owner=false;return r end
local r=controller:attempt(cards);assert(r.phase=='retired' and counts.clear==1 and counts.append==0)
''')


def test_restore_failure_retains_capture_and_cannot_loop_or_hide_by_new_attempt():
    run('''
bridge.finish=function()counts.finish=counts.finish+1;return false end
local r=controller:attempt(cards);assert(r.phase=='restore_failed' and captured)
assert(counts.clear==2 and counts.finish==2)
local before=#events;controller:restore();controller:attempt(cards)
assert(#events==before and captured)
assert(not controller:retire(),'live menu was forgotten')
owner=false;assert(controller:retire() and not captured)
''')


def test_reentrant_attempt_cannot_release_capture_or_reset_transaction():
    run('''
local append=bridge.append;local once=false
bridge.append=function(...)
 if not once then once=true;local r=controller:attempt(cards);assert(r.phase=='building' and captured)end
 return append(...)
end
assert(controller:attempt(cards).phase=='active')
assert(counts.clear==1 and counts.finish==1 and captured)
''')


def test_ownership_loss_before_first_clear_is_blocked_and_batched():
    run('''
local calls=0;bridge.verify_owned=function(ids)assert(#ids<=16);calls=calls+1;return calls<3 end
assert(controller:attempt(cards).phase=='blocked')
assert(counts.clear==0 and counts.begin==0 and not captured)
''')


def test_failed_explicit_restore_boundary_keeps_capture_and_stops():
    run('''
assert(controller:attempt(cards).phase=='active')
bridge.resume_update=function()return false end
assert(controller:restore().phase=='restore_failed' and captured)
assert(counts.clear==1 and counts.finish==1)
''')


def test_group_capacity_and_combined_item_capacity_fail_before_clear():
    run('''
source.entries={};source.rows={};source.groups={}
for i=1,33 do
 source.entries[i]={offer_id=1000+i,kit_id=string.format('armor:%08x',i),owned=true,group_key=i,flag_a=1,flag_b=0}
 source.rows[i]={count=1,first_item=i-1,height=246}
 source.groups[i]={key=i,first_row=i-1,first_item=i-1}
end
source.item_count=33;source.row_count=33;source.group_count=33;source.content=33*246
local r=controller:attempt(cards);assert(r.phase=='blocked' and r.error:find('group capacity'))
assert(counts.begin==0 and counts.clear==0)
source.menu_token='menu-two'
for i=34,255 do source.entries[i]=copy(source.entries[1])end
r=controller:attempt(cards);assert(r.phase=='blocked' and r.error:find('item capacity'))
assert(counts.begin==0)
''')


def test_capture_failure_closes_update_without_touching_native_list():
    run('''
bridge.capture=function(value)if value then return false end;captured=false;return true end
local r=controller:attempt(cards);assert(r.phase=='blocked' and counts.clear==0)
assert(counts.begin==1 and counts['end']==1)
''')


def test_uncertain_clear_recovers_through_a_complete_original_rebuild():
    run('''
local clear=bridge.clear;local calls=0
bridge.clear=function(...)
 calls=calls+1;local r=clear(...);if calls==1 then error('uncertain clear')end;return r
end
local r=controller:attempt(cards);assert(r.phase=='restored' and r.error:find('uncertain clear'))
assert(counts.clear==2 and counts.append==93 and counts.finish==1 and P.matches(current,source))
''')


def test_layout_change_or_unowned_readback_is_not_accepted_as_verified():
    run('''
local wrong=copy(source);wrong.root_geometry.height=wrong.root_geometry.height-1
assert(not P.matches(wrong,source))
wrong=copy(source);wrong.rows[1].height=200;assert(not P.matches(wrong,source))
wrong=copy(source);wrong.entries[1].owned=false;assert(not P.matches(wrong,source))
wrong=copy(source);wrong.groups[1].first_item=1;assert(not P.matches(wrong,source))
''')


def test_temporary_snapshot_readiness_failure_retries_without_native_construction():
    run('''
local snapshot=bridge.snapshot;local calls=0
bridge.snapshot=function(...)
 calls=calls+1;if calls<4 then error('first native row not ready')end;return snapshot(...)
end
for i=1,3 do
 local r=controller:attempt(cards)
 assert(r.phase=='waiting'and r.retryable and counts.begin==0 and counts.clear==0)
end
assert(controller:attempt(cards).phase=='active'and counts.clear==1)
''')


def test_source_generation_change_and_busy_update_boundary_retry_before_mutation():
    run('''
local verify=bridge.verify;local changed=true
bridge.verify=function(...)return not changed and verify(...)end
local r=controller:attempt(cards);assert(r.phase=='waiting'and r.retryable)
assert(counts.begin==0 and counts.clear==0)
changed=false;assert(controller:attempt(cards).phase=='active'and counts.clear==1)
''')
    run('''
local begin=bridge.begin;local busy=true
bridge.begin=function(...)if busy then return nil end;return begin(...)end
local r=controller:attempt(cards);assert(r.phase=='waiting'and r.retryable)
assert(counts.clear==0 and not captured)
busy=false;assert(controller:attempt(cards).phase=='active'and counts.clear==1)
''')


def test_status_detects_same_menu_generation_replacement_without_restoration_writes():
    run('''
assert(controller:attempt(cards).phase=='active')
assert(controller:status().phase=='active')
local clears,appends=counts.clear,counts.append
generation=false
local r=controller:status()
assert(r.phase=='retired'and r.error:find('generation changed')and not captured)
assert(counts.clear==clears and counts.append==appends)
''')


def test_unreadable_status_does_not_retire_a_live_presentation():
    run('''
assert(controller:attempt(cards).phase=='active')
local owns=bridge.owns;bridge.owns=function()error('snapshot unreadable')end
local r=controller:status();assert(r.phase=='active'and r.readable==false and captured)
bridge.owns=owns;assert(controller:status().phase=='active'and captured)
''')


def test_long_session_can_construct_more_than_256_verified_menu_entries():
    run('''
for i=1,300 do
 source.menu_token='menu:'..i
 assert(controller:attempt(cards).phase=='active')
 assert(controller:restore().phase=='restored')
end
assert(counts.clear==600 and counts.finish==600)
''')


def test_equipment_prefix_uses_saved_cards_only_and_restores_original_list():
    run(r"""
local policy={allow_create=false}
local saved={cards[1],{key='second',kind='variant',kit_id=cards[1].kit_id}}
local plan=P.prepare(source,saved,policy)
assert(plan.custom_count==2 and plan.proposed.group_count==4)
assert(plan.cards[1].logical_index==0 and plan.cards[2].logical_index==1)
assert(not pcall(P.prepare,source,cards,policy),'Equipment admitted a Create card')
assert(not pcall(P.prepare,source,saved),'Armory lost its required Create card')
local equipment=P.new(bridge,policy)
assert(equipment:attempt(saved).phase=='active')
assert(equipment:restore().phase=='restored')
assert(current.item_count==source.item_count and current.group_count==source.group_count)
""")
