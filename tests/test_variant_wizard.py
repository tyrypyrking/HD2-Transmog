"""Pure wizard flow: owned choices, base tuple deduplication, atomic save proposal."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run_lua(code):
    result = subprocess.run(
        ['luajit', '-'], input=code, text=True, cwd=ROOT, capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


FIXTURE = r'''
local S=dofile('src/state.lua')
local W=dofile('src/variant_wizard.lua')
local catalog={
  a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'},
  b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'},
  c={appearance_id='look-c',stats_id='stats-c',passive_variant_id='perk-b'},
  d={appearance_id='look-d',stats_id='stats-d',passive_variant_id='perk-d'},
  e={appearance_id='look-a',stats_id='stats-e',passive_variant_id='perk-a'},
  locked={appearance_id='look-locked',stats_id='stats-locked',passive_variant_id='perk-b-stronger'},
}
local state=S.reconcile_owned(S.new(),catalog,{'a','b','c','d','e'})
state.requested={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}
state.selected={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}
state.presets.Existing={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}
local context={labels={appearance_id={['look-a']='Alpha',['look-b']='Beta'},
 passive_variant_id={['perk-b']='Padding'}},stats_profiles={},
 passive_variants={['perk-b']={icon_hash='real-icon-hash',effects={'Exact owned clause.'}}},
 appearance_previews={['look-b']={resource='verified-preview',valid=function() error('No native/preview calls allowed') end}}}
local function profile(armor,speed,regen)
 return {base_only=true,base_values_verified=true,
   base_values={armor_rating=armor,speed=speed,stamina_regen=regen}}
end
context.stats_profiles['stats-a']=profile(150,450,50)
context.stats_profiles['stats-b']=profile(50,550,125)
context.stats_profiles['stats-c']=profile(50,550,125) -- Different donor, same unboosted tuple.
context.stats_profiles['stats-d']=profile(100,500,100)
context.stats_profiles['stats-e']={base_only=false,base_values_verified=true,
 base_values={armor_rating=200,speed=450,stamina_regen=50},displayed_values={armor_rating=200}}
context.stats_profiles['stats-locked']=profile(1,999,999)
local wizard=W.new(S)
local function act(kind,id,label) return wizard:action(state,context,{type=kind,id=id,label=label}) end
local function choose()
 assert(act('open'));assert(act('select_look','look-b'))
 assert(act('select_stats','base:50/550/125'));assert(act('select_passive','perk-a'))
end
'''


def test_section_is_before_light_armor_and_plus_is_always_last():
    run_lua(FIXTURE + r'''
state.presets.Unavailable=catalog.locked
local view=wizard:view(state,context)
assert(view.section.title=='Custom Variant' and view.section.before=='Light Armor')
assert(#view.section.tiles==3 and view.section.tiles[1].label=='Existing')
assert(view.section.tiles[2].label=='Unavailable' and not view.section.tiles[2].enabled)
assert(view.section.tiles[3].kind=='add' and view.section.tiles[3].label=='+')
assert(view.section.tiles[3].enabled and not view.open and not view.can_create)
local before=S.encode(state)
local ok,_,intent=act('select_variant',nil,'Existing')
assert(ok and intent.kind=='select_variant' and intent.request.appearance_id=='look-a')
assert(S.encode(state)==before and state.selected.appearance_id=='look-a')
assert(not act('select_variant',nil,'Unavailable'))
''')


def test_owned_look_step_passes_previews_without_evaluating_them():
    run_lua(FIXTURE + r'''
assert(act('open'))
local view=wizard:view(state,context)
assert(view.open and view.step==1 and #view.options==4)
assert(not view.can_back and view.can_cancel and not view.can_create)
assert(view.options[1].id=='look-a' and #view.options[1].donor_kit_ids==2)
assert(view.options[2].id=='look-b' and view.options[2].preview==context.appearance_previews['look-b'])
assert(not act('select_look','look-locked'))
assert(not act('select_stats','base:50/550/125'))
assert(act('select_look','look-b') and wizard:view(state,context).step==2)
''')


def test_base_stats_deduplicate_and_sort_without_copying_donor_bonus():
    run_lua(FIXTURE + r'''
context.stats_profiles['stats-b'].displayed_values={armor_rating=100,speed=550,stamina_regen=125}
assert(act('open'));assert(act('select_look','look-b'))
local view=wizard:view(state,context)
assert(#view.options==3 and view.unresolved_stats_count==1)
assert(view.options[1].base_values.armor_rating==50)
assert(view.options[2].base_values.armor_rating==100 and view.options[3].base_values.armor_rating==150)
assert(#view.options[1].donor_stats_ids==2 and view.options[1].stats_id=='stats-b')
assert(view.options[1].donor_stats_ids[2]=='stats-c')
assert(not act('select_stats','base:200/450/50'))
assert(not act('select_stats','base:1/999/999'))
assert(act('select_stats',view.options[1].id))
assert(wizard:view(state,context).selection.stats_id=='stats-b')
''')


def test_exact_owned_passives_keep_their_icon_and_clauses():
    run_lua(FIXTURE + r'''
assert(act('open'));assert(act('select_look','look-b'));assert(act('select_stats','base:50/550/125'))
local view=wizard:view(state,context)
assert(view.step==3 and #view.options==3 and not view.can_create)
local seen={}
for _,option in ipairs(view.options) do
 seen[option.id]=true
 if option.id=='perk-b' then
   assert(option.label=='Padding' and option.icon_hash=='real-icon-hash')
   assert(option.effects[1]=='Exact owned clause.' and #option.donor_kit_ids==2)
 end
end
assert(not seen['perk-b-stronger'])
assert(not act('select_passive','perk-b-stronger'))
assert(act('select_passive','perk-b') and wizard:view(state,context).can_create)
assert(wizard:view(state,context).step==3) -- Selection does not auto-create.
''')


def test_back_and_cancel_preserve_all_original_state_and_selection():
    run_lua(FIXTURE + r'''
local before=S.encode(state)
choose()
assert(act('back') and wizard:view(state,context).step==2)
assert(wizard:view(state,context).stats_tuple_id=='base:50/550/125')
assert(act('back') and wizard:view(state,context).step==1)
assert(not act('back'))
assert(act('select_look','look-d'))
assert(act('select_stats','base:100/500/100'))
assert(wizard:view(state,context).selection.passive_variant_id=='perk-a')
assert(act('cancel'))
local view=wizard:view(state,context)
assert(not view.open and view.selection.appearance_id==nil)
assert(#view.section.tiles==2 and S.encode(state)==before)
assert(state.selected.stats_id=='stats-a' and state.requested.stats_id=='stats-a')
''')


def test_create_is_atomic_preserves_existing_variants_and_does_not_equip():
    run_lua(FIXTURE + r'''
local before=S.encode(state)
choose();assert(act('rename',nil,'Мой вариант'))
local ok,why,tx=act('create')
assert(ok and not why and tx.kind=='save_variant' and tx.label=='Мой вариант')
assert(S.encode(state)==before and not state.presets['Мой вариант'])
assert(wizard:view(state,context).saving and not wizard:view(state,context).can_create)
assert(#wizard:view(state,context).section.tiles==2)
assert(tx.candidate.presets.Existing.stats_id=='stats-a')
assert(tx.candidate.presets['Мой вариант'].appearance_id=='look-b')
assert(tx.candidate.presets['Мой вариант'].stats_id=='stats-b')
assert(tx.candidate.presets['Мой вариант'].passive_variant_id=='perk-a')
assert(tx.candidate.requested.stats_id=='stats-a' and tx.candidate.selected.stats_id=='stats-a')
assert(tx.candidate.selected~=state.selected and tx.candidate.presets.Existing~=state.presets.Existing)
assert(tx.encoded==S.encode(tx.candidate) and wizard:validate_transaction(tx,state,context))
local restored=assert(S.decode(tx.encoded))
assert(restored.presets['Мой вариант'].stats_id=='stats-b')
assert(not restored.ownership_verified) -- Persistence cannot authorize ownership.
state=tx.candidate;assert(wizard:saved(tx,state))
local view=wizard:view(state,context)
assert(not view.open and #view.section.tiles==3 and view.section.tiles[3].kind=='add')
assert(view.section.tiles[2].label=='Мой вариант')
assert(not wizard:saved(tx,state))
''')


def test_failed_persistence_leaves_draft_and_does_not_insert_a_card():
    run_lua(FIXTURE + r'''
choose();local _,_,tx=act('create')
assert(not act('cancel')) -- A dispatched write must be completed or failed explicitly.
assert(not wizard:saved(tx,state))
assert(wizard:failed(tx,'Write failed'))
local view=wizard:view(state,context)
assert(view.open and view.step==3 and view.can_create and not view.saving)
assert(view.notice=='Write failed' and #view.section.tiles==2)
assert(not wizard:validate_transaction(tx,state,context))
local _,_,retry=act('create');assert(retry and retry~=tx)
assert(wizard:validate_transaction(retry,state,context))
''')


def test_cached_or_lost_ownership_cannot_authorize_any_new_variant():
    run_lua(FIXTURE + r'''
choose()
state.ownership_verified=false
assert(not wizard:view(state,context).can_create)
assert(not act('create'))
assert(act('cancel') and not act('open'))
local view=wizard:view(state,context)
assert(#view.section.tiles==2 and not view.section.tiles[1].enabled and not view.section.tiles[2].enabled)
S.reconcile_owned(state,catalog,{'a','b','c','d','e'});choose()
S.reconcile_owned(state,catalog,{'a','c','d','e'})
assert(not wizard:view(state,context).can_create and not act('create'))
assert(wizard:view(state,context).selection.appearance_id=='look-b') -- No silent substitution.
assert(state.presets.Existing and state.requested.appearance_id=='look-a')
''')


def test_pending_transaction_rejects_inventory_profile_and_state_races():
    run_lua(FIXTURE + r'''
choose();local _,_,tx=act('create')
state.ownership_verified=false
assert(not wizard:validate_transaction(tx,state,context))
state.ownership_verified=true
context.stats_profiles['stats-b'].base_values.armor_rating=51
assert(not wizard:validate_transaction(tx,state,context))
context.stats_profiles['stats-b'].base_values.armor_rating=50
state.presets.Concurrent=catalog.d
assert(not wizard:validate_transaction(tx,state,context))
state.presets.Concurrent=nil
assert(wizard:validate_transaction(tx,state,context))
tx.candidate.presets.Existing.stats_id='stats-d'
assert(not wizard:validate_transaction(tx,state,context))
''')


def test_unknown_nonfinite_and_unverified_base_values_never_become_options():
    run_lua(FIXTURE + r'''
context.stats_profiles['stats-a'].base_values_verified=false
context.stats_profiles['stats-b'].base_values.speed=0/0
context.stats_profiles['stats-c'].base_values.speed=math.huge
context.stats_profiles['stats-d'].base_values.stamina_regen=-1
assert(act('open'));assert(act('select_look','look-a'))
local view=wizard:view(state,context)
assert(#view.options==0 and view.unresolved_stats_count==5 and not view.can_create)
assert(view.stats_notice and act('back') and act('cancel'))
''')


def test_names_and_capacity_are_checked_without_overwriting_saved_variants():
    run_lua(FIXTURE + r'''
choose()
assert(not act('rename',nil,'Existing'))
assert(not act('rename',nil,''))
assert(not act('rename',nil,'  '))
assert(not act('rename',nil,'bad\nname'))
assert(not act('rename',nil,string.char(255)))
assert(not act('rename',nil,string.rep('x',257)))
for i=1,255 do state.presets['Saved '..i]=catalog.a end
assert(not wizard:view(state,context).can_create and not act('create'))
assert(act('cancel') and not act('open'))
assert(#wizard:view(state,context).section.tiles==257)
assert(state.presets.Existing.stats_id=='stats-a')
''')


def test_look_and_stats_changes_never_infer_a_different_passive():
    run_lua(FIXTURE + r'''
choose()
assert(act('back'));assert(act('select_stats','base:150/450/50'))
assert(wizard:view(state,context).selection.passive_variant_id=='perk-a')
assert(act('select_passive','perk-b'))
assert(act('back'));assert(act('back'));assert(act('select_look','look-d'))
assert(act('select_stats','base:100/500/100'))
assert(wizard:view(state,context).selection.passive_variant_id=='perk-b')
local _,_,tx=act('create')
assert(tx.candidate.presets[tx.label].passive_variant_id=='perk-b')
assert(tx.candidate.presets[tx.label].stats_id=='stats-d')
''')


def test_equipment_policy_lists_every_saved_variant_without_creation():
    run_lua(FIXTURE+r"""
state.presets.Second=state.presets.Existing
state.presets.Unavailable={appearance_id='look-locked',stats_id='stats-locked',passive_variant_id='perk-b-stronger'}
wizard=W.new(S,{allow_create=false})
local before=S.encode(state)
local view=wizard:view(state,context)
assert(#view.section.tiles==3 and not view.open and not view.can_create)
for _,tile in ipairs(view.section.tiles)do assert(tile.kind=='variant')end
assert(view.section.tiles[3].enabled==false,'unavailable saved variant was hidden or enabled')
for _,kind in ipairs({'open','select_look','select_stats','select_passive','set_label','create','back','cancel'})do
 local ok,why=act(kind,'look-a','New');assert(not ok and why:find('ship Armory',1,true))
end
local ok,why,tx=act('select_variant',nil,'Second')
assert(ok and tx.kind=='select_variant' and tx.label=='Second',why)
assert(S.encode(state)==before and not wizard:view(state,context).open)
state.presets={};assert(#wizard:view(state,context).section.tiles==0)
""")


def test_generated_names_and_legacy_display_names_preserve_saved_identity():
    run_lua(FIXTURE + r'''
local old=S.encode(state)
state.presets['Custom Variant 7']=catalog.b
state.presets['старое имя']=catalog.b
local view=wizard:view(state,context)
for _,tile in ipairs(view.section.tiles)do
 if tile.label=='Custom Variant 7'or tile.label=='старое имя'then
  assert(tile.display_name=='Beta - Padding' and tile.action.label==tile.label)
 end
end
choose();assert(act('select_passive','perk-b'))
assert(wizard:view(state,context).label=='Beta - Padding')
local ok,why,tx=act('create');assert(ok,why)
assert(tx.candidate.presets['Beta - Padding'])
assert(tx.candidate.presets['старое имя'] and tx.candidate.presets['Custom Variant 7'])
assert(wizard:saved(tx,tx.candidate));state=tx.candidate
choose();assert(act('select_passive','perk-b'))
assert(wizard:view(state,context).label=='Beta - Padding (2)')
assert(act('rename',nil,'My exact name'));assert(act('select_passive','perk-b'))
assert(wizard:view(state,context).label=='My exact name')
''')


def test_display_cache_refreshes_revision_ownership_and_live_previews():
    run_lua(FIXTURE+r'''
context.options_revision=0
assert(act('open'))
local old=wizard:view(state,context)
assert(old.options[2].label=='Beta')
local preview={resource='new-preview'}
context.appearance_previews['look-b']=preview
local current=wizard:view(state,context)
assert(current.options[2].preview==preview and old.options[2].preview~=preview)
context.labels.appearance_id['look-b']='Beta updated'
context.options_revision=1
assert(wizard:view(state,context).options[2].label=='Beta updated')
S.reconcile_owned(state,catalog,{'a'})
current=wizard:view(state,context)
assert(#current.options==1 and current.options[1].id=='look-a')
assert(not act('select_look','look-b'))
S.reconcile_owned(state,catalog,nil)
assert(#wizard:view(state,context).options==0)
''')


def test_display_cache_cannot_authorize_stale_action_or_keep_old_stats():
    run_lua(FIXTURE+r'''
context.options_revision=0
assert(act('open'));assert(act('select_look','look-b'))
local before=wizard:view(state,context)
context.stats_profiles['stats-b']=profile(51,550,125)
context.stats_profiles['stats-c']=profile(51,550,125)
-- Actions remain fresh even before the host publishes its display revision.
assert(not act('select_stats','base:50/550/125'))
context.options_revision=1
local after=wizard:view(state,context)
assert(after.options[1].id=='base:51/550/125')
assert(before.options[1].id=='base:50/550/125')
assert(act('select_stats','base:51/550/125'))
''')


def test_stats_follow_look_two_stage_save_back_cancel_and_retry():
    run_lua(FIXTURE+r'''
wizard=W.new(S,{stats_follow_look=true})
local before=S.encode(state)
assert(act('open'));assert(wizard:view(state,context).step_count==2)
assert(act('select_look','look-b'))
local view=wizard:view(state,context)
assert(view.step==3 and view.step_number==2 and view.title=='Choose a passive')
assert(view.selection.stats_id=='stats-b' and not view.can_create)
assert(not act('select_stats','base:150/450/50'))
assert(act('select_passive','perk-a') and act('back'))
assert(wizard:view(state,context).step==1)
assert(act('select_look','look-d'))
view=wizard:view(state,context)
assert(view.selection.stats_id=='stats-d' and view.selection.passive_variant_id=='perk-a')
assert(view.can_create and not view.stats_notice)
assert(act('rename',nil,'Two stages'))
local ok,why,tx=act('create');assert(ok,why)
assert(wizard:validate_transaction(tx,state,context))
assert(tx.candidate.presets['Two stages'].stats_id=='stats-d')
assert(S.encode(state)==before)
assert(wizard:failed(tx,'Disk full'))
assert(wizard:view(state,context).can_create)
local _,_,retry=act('create');assert(wizard:validate_transaction(retry,state,context))
assert(wizard:saved(retry,retry.candidate));state=retry.candidate
assert(state.presets.Existing.stats_id=='stats-a' and state.selected.stats_id=='stats-a')
assert(act('open') and act('select_look','look-b') and act('cancel'))
assert(not wizard:view(state,context).open)
-- Existing mixed-stat variants stay selectable in either configuration.
state.presets.Mixed={appearance_id='look-b',stats_id='stats-a',passive_variant_id='perk-a'}
local selected,_,intent=act('select_variant',nil,'Mixed')
assert(selected and intent.request.stats_id=='stats-a')
''')


def test_stats_follow_look_uses_exact_owned_donor_without_tuple_dedup_or_bonus():
    run_lua(FIXTURE+r'''
wizard=W.new(S,{stats_follow_look=true})
-- stats-b and stats-c have equal tuples; choosing look-c must retain stats-c.
assert(act('open') and act('select_look','look-c'))
assert(wizard:view(state,context).selection.stats_id=='stats-c')
assert(act('back') and act('select_look','look-a'))
assert(wizard:view(state,context).selection.stats_id=='stats-a') -- Stable first owned kit, not stats-e.
assert(act('back'))
context.stats_profiles={} -- No manual tuple verification is needed to inherit a native donor.
assert(act('select_look','look-b') and act('select_passive','perk-a'))
local ok,why,tx=act('create');assert(ok,why)
assert(tx.candidate.presets[tx.label].stats_id=='stats-b')
assert(tx.candidate.presets[tx.label].passive_variant_id=='perk-a')
assert(wizard:validate_transaction(tx,state,context))
''')


def test_stats_follow_look_rechecks_catalog_relationship_and_ownership_on_save():
    run_lua(FIXTURE+r'''
wizard=W.new(S,{stats_follow_look=true})
assert(act('open') and not act('select_look','look-locked'))
assert(act('select_look','look-b') and act('select_passive','perk-a'))
local _,_,tx=act('create')
-- The old stats are still owned, but are no longer this look's native stats.
state.catalog.b.stats_id='stats-d'
assert(not wizard:validate_transaction(tx,state,context))
state.catalog.b.stats_id='stats-b'
assert(wizard:validate_transaction(tx,state,context))
S.reconcile_owned(state,catalog,{'a','c','d','e'})
assert(not wizard:validate_transaction(tx,state,context))
assert(wizard:failed(tx,'Ownership changed'))
assert(not wizard:view(state,context).can_create and not act('create'))
assert(act('cancel') and act('open'))
assert(not act('select_look','look-b'))
''')
