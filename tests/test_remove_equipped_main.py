"""Delete a worn card, rebuild the real main workflow, then equip vanilla armor."""
from test_creator_failure_main import HARNESS, ROOT
from test_startup_restore_main import SEED
from test_diverkit_compat import run

SETUP = r'''
PlayerCustomizationProbe.format=function()return 'fixture player'end
local custom_count=0
local focus_id,focus_index=A,0
local detail_id=A
local active_patch=false
local reset_count=0
AppearancePatch.new=function()
 local object={}
 function object:plan(_,r)return {source_id=A,target_id=A,request=r}end
 function object:apply()
  assert(live.request_armor_id~=A and live.cache_armor_id~=A)
  active_patch=true;patches=patches+1;return true
 end
 function object:reset()
  assert(live.request_armor_id~=A and live.cache_armor_id~=A,'reset worn armor during deletion')
  active_patch=false;reset_count=reset_count+1;return true
 end
 function object:is_active()return active_patch end
 return object
end
ArmorRefreshBridge.new=function()return runtime_bridge end
function grid:inspect_model()
 return {item_count=3,offers={{kit_id=A,owned=true},{kit_id=B,owned=true},{kit_id=C,owned=true}}}
end
function grid:select_kit(id)focus_id=id;focus_index=0;return true end
function grid:focus_index(index,id)focus_index=index;focus_id=id;return true end
function grid:selection_index()return focus_index end
function grid:preview_variant_details(id,stats,passive,context,options)
 detail_id=id;focus_id=id
 if options.focus_index then focus_index=options.focus_index end
 return true
end
function grid:detail_state()return {kit_id=detail_id}end
function grid:equipment_feedback()return true end
function grid:snapshot()
 return {kind=4,native_view_mode=0,identity_mapping_verified=true,selected_kit_id=focus_id,
 logical_selected_index=focus_index,appearance_previews={},headers={},scroll=0,
 item_count=3+custom_count,widgets={{logical_index=focus_index,bound_owned_kit_id=focus_id,
 root_viewport_rect={x=200,y=400,w=100,h=100}},
 {logical_index=custom_count+1,bound_owned_kit_id=B,root_viewport_rect={x=300,y=400,w=100,h=100}}}}
end
NativeGridPresentation.new=function()
 local object={phase='idle'}
 function object:attempt(cards)
  custom_count=#cards;presentation_builds=presentation_builds+1
  presentation_active=true;self.phase='active';focus_id=A;focus_index=0
  return {phase='active'}
 end
 function object:restore()
  custom_count=0;presentation_restores=presentation_restores+1
  presentation_active=false;self.phase='restored';focus_index=0;focus_id=A
  return {phase='restored'}
 end
 return object
end
local function menu_tick()
 now=now+100;update()
 live.cache_armor_id=live.request_armor_id
 live.cache_passive=active_patch and live.request_armor_id==A and 1
  or result.context.passive_variants[catalog[live.request_armor_id].passive_variant_id].enum
end
'''


def exercise(extra=''):
    return HARNESS+SEED+SETUP+extra+'\nlocal function boot()\n'+(ROOT/'src/main.lua').read_text()+r'''
end
local runtime=boot();assert(runtime.status~='startup_failed',runtime.status)
now=16000
for i=1,30 do menu_tick()end
assert(active_patch and commits==2 and reset_count==0)
sample_mode='ready'
for i=1,15 do menu_tick()end
assert(presentation_active and flow:view().selected_variant.label=='Saved')
assert(flow:view().can_remove and not flow:view().apply_pending)
assert(flow:action{type='remove_variant',label='Saved'})
assert(active_patch and reset_count==0 and live.request_armor_id==A and commits==2)
for i=1,15 do menu_tick()end
assert(presentation_active and not flow:view().selected_variant)
local view=flow:view()
assert(view.native_override and view.native_override_id==B and view.can_apply,'no vanilla recovery selection after removal')
assert(flow:action{type='apply_variant',id=B})
for i=1,15 do menu_tick()end
assert(not active_patch and reset_count==1 and live.request_armor_id==B and live.cache_armor_id==B)
assert(live.cache_passive==7 and flow:view().variant_phase=='equipped')
assert(logged_count('runtime.error=')==0 and logged_count('variant.apply_failed=')==0)
'''


def test_last_worn_variant_can_be_removed_then_replaced_with_vanilla():
    run(exercise())


def test_removing_worn_variant_with_other_saved_cards_keeps_vanilla_recovery():
    # Sort after Saved so the initial automatic selection remains the worn card.
    run(exercise(r'''
saved.presets.ZOther={appearance_id=B,stats_id='stats-a',passive_variant_id='perk-a'}
files['transmog.state']='HD2TRANSMOG_UI\t1\nappearance\n'..assert(State.encode(saved))
'''))



def test_failed_deletion_preserves_saved_card_worn_patch_and_selection():
    code=exercise(r"""
local block_delete=false
local platform_new=Platform.new
Platform.new=function(...)
 local fs=platform_new(...);local write=fs.write_atomic
 fs.write_atomic=function(name,bytes)
  if block_delete and name=='transmog.state'then return nil,'disk full'end
  return write(name,bytes)
 end
 return fs
end
""")
    point="assert(flow:action{type='remove_variant',label='Saved'})"
    code=code.replace(point,r"""
local stored=files['transmog.state'];local builds=presentation_builds
block_delete=true
assert(not flow:action{type='remove_variant',label='Saved'})
assert(files['transmog.state']==stored and flow:view().selected_variant.label=='Saved')
assert(active_patch and reset_count==0 and commits==2 and presentation_builds==builds)
block_delete=false
"""+point,1)
    run(code)



def test_deletion_recovery_does_not_require_a_third_owned_armor():
    code=exercise().replace("assert(flow:action{type='apply_variant',id=B})",r"""
-- The selected vanilla B is unchanged, so it can also release the old carrier A.
result.owned[C]=false
assert(flow:action{type='apply_variant',id=B})
""",1)
    run(code)


def test_deletion_with_only_saved_cards_visible_waits_for_explicit_vanilla_selection():
    code=exercise(r'''
local snapshot=grid.snapshot
function grid:snapshot(...)
 local s=snapshot(self,...);s.widgets={s.widgets[1]};return s
end
''')
    code=code.replace("local view=flow:view()\nassert(view.native_override", "assert(not flow:view().native_override and not flow:view().apply_pending)\nassert(flow:action{type='select_native_look',id=B,index=custom_count+1})\nfor i=1,15 do menu_tick()end\nlocal view=flow:view()\nassert(view.native_override")
    run(code)
