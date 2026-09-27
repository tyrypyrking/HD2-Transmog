"""Owned donor composition, transactional saves, and renderer capability gates."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run_lua(code):
    result = subprocess.run(
        ['luajit', '-'], input=code, text=True, cwd=ROOT, capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


FIXTURE = '''
local S=dofile('src/state.lua')
local catalog={
  a={appearance_id='appearance-a',stats_id='stats-a',passive_variant_id='passive-a'},
  b={appearance_id='appearance-b',stats_id='stats-b',passive_variant_id='passive-b'},
  locked={appearance_id='appearance-c',stats_id='stats-c',passive_variant_id='passive-b-stronger'},
}
local state=S.reconcile_owned(S.new(),catalog,{'a','b'})
local editor=S.editor_new()
local context={current_kit_id='a',kit_labels={a='Fixture armor'},labels={
  stats_id={['stats-b']='Fixture heavy profile'},
},details={passive_variant_id={['passive-b']={'Fixture complete effect clause.'}}}}
local function act(action,tab) return S.editor_action(state,editor,action,tab or 'appearance',context) end
'''


def test_draft_uses_independent_owned_donors_and_save_is_transactional():
    run_lua(FIXTURE + '''
assert(S.editor_view(state,editor,'appearance',context).can_new)
assert(act('new_variant'))
assert(editor.label=='Fixture armor 1' and editor.dirty)
assert(editor.draft.appearance_id=='appearance-a')
assert(act('next_option','stats'))
assert(editor.draft.stats_id=='stats-b')
assert(act('next_option','passive'))
assert(editor.draft.passive_variant_id=='passive-b')
local model=S.editor_view(state,editor,'stats',context)
assert(model.choice=='Fixture heavy profile' and model.count==2 and model.can_save)
local before=assert(S.encode(state))
local handled,notice,candidate=act('save_variant')
assert(handled and candidate and notice==nil)
assert(S.encode(state)==before and state.requested==nil and next(state.presets)==nil)
assert(editor.dirty) -- Simulate failed disk persistence: caller does not adopt.
assert(candidate.presets[editor.label].stats_id=='stats-b')
assert(candidate.requested.passive_variant_id=='passive-b')
assert(candidate.selected==nil) -- A saved request is never an applied claim.
state=candidate;S.editor_saved(editor)
assert(not editor.dirty and S.editor_view(state,editor,'appearance',context).can_duplicate)
act('duplicate_variant')
assert(editor.label=='Fixture armor 1 copy 1' and editor.dirty)
editor.draft.stats_id='stats-a'
assert(state.presets['Fixture armor 1'].stats_id=='stats-b')
''')


def test_cached_inventory_cannot_authorize_and_unavailable_saved_parts_survive():
    run_lua(FIXTURE + '''
act('new_variant');act('next_option','passive')
local _,_,saved=act('save_variant')
state=assert(S.decode(assert(S.encode(saved))))
editor=S.editor_new()
assert(state.ownership_verified==false)
assert(not S.select(state,'appearance-a','stats-a','passive-b'))
local model=S.editor_view(state,editor,'appearance',context)
assert(not model.can_new and model.count==0)
act('next_option','presets')
assert(editor.draft.passive_variant_id=='passive-b')
assert(not S.editor_view(state,editor,'passive',context).can_save)
-- A partial refresh may remove a donor, but never substitutes a different perk.
S.reconcile_owned(state,catalog,{'a'})
assert(editor.draft.passive_variant_id=='passive-b')
assert(state.presets[editor.label].passive_variant_id=='passive-b')
local _,why,proposal=act('save_variant')
assert(not proposal and why:find('ownership'))
act('next_option','passive')
assert(editor.draft.passive_variant_id=='passive-a')
local _,_,proposal=act('save_variant');assert(proposal)
''')


def test_unsaved_edits_are_preserved_until_explicit_discard_and_names_validated():
    run_lua(FIXTURE + '''
act('new_variant')
assert(not S.editor_rename(state,editor,''))
assert(not S.editor_rename(state,editor,'broken\\nname'))
assert(S.editor_rename(state,editor,'Мой вариант'))
local _,_,proposal=act('save_variant');state=proposal;S.editor_saved(editor)
act('next_option','stats')
local requested=editor.draft.stats_id
act('new_variant');assert(editor.draft.stats_id==requested)
act('next_option','presets');assert(editor.draft.stats_id==requested)
act('discard_variant')
assert(not editor.dirty and editor.draft.stats_id=='stats-a')
assert(editor.label=='Мой вариант')
-- A known native selection which is unowned must not silently fall back.
context.current_kit_id='locked'
assert(not S.editor_view(state,editor,'appearance',context).can_new)
act('new_variant');assert(editor.label=='Мой вариант')
''')


def test_new_prefers_saved_stat_donor_when_native_selection_is_unknown():
    run_lua(FIXTURE + '''
context.current_kit_id=nil
context.labels.appearance_id={['appearance-b']='Owned donor B'}
assert(S.select(state,'appearance-a','stats-b','passive-a'))
local model=S.editor_view(state,editor,'appearance',context)
assert(model.seed_kit_id=='b' and model.seed_source=='saved_stats_donor')
local _,notice=act('new_variant')
assert(editor.label=='Owned donor B 1')
assert(editor.draft.appearance_id=='appearance-b' and editor.draft.stats_id=='stats-b')
assert(notice=='Draft copied from the saved stat donor')
act('discard_variant');context.current_kit_id='a'
model=S.editor_view(state,editor,'appearance',context)
assert(model.seed_kit_id=='a' and model.seed_source=='native_selection')
context.current_kit_id='locked'
assert(not S.editor_view(state,editor,'appearance',context).can_new)
''')


def test_panel_disables_unsupported_actions_and_retains_all_effect_text():
    run_lua(FIXTURE + '''
local P=dofile('src/panel.lua')
local worlds={'main','armory'}
local created, rendered=0,{}
local function vector(...) return {...} end
local engine={Vector2=vector,Vector3=vector,Color=vector,IdString64={from_hex=function(v) return v end},
 Application={worlds=function() return worlds end,main_world=function() return 'main' end},
 World={create_screen_gui=function() created=created+1;return created end,destroy_gui=function() end},
 Gui={resolution=function() return 1920,1080 end,material=function() return {} end,
 rect=function() end,text=function(_,text) rendered[#rendered+1]=text end},
 Material={set_scalar=function() end,set_vector2=function() end,set_vector4=function() end,set_texture=function() end}}
local panel=P.new(engine)
local sample={kind='armory',anchor={x=100,y=100,w=420,h=40},font='a',material='b',atlas='c'}
local view={open=true,tab='passive',notice='ready',saved=false}
local function draw()
 view.editor=S.editor_view(state,editor,view.tab,context)
 assert(panel:draw(sample,view))
end
local function region(key)
 for _,r in ipairs(panel.regions) do if r.key==key then return r end end
end
draw();assert(not region('save_variant') and not region('apply_variant'))
assert(region('new_variant') and not region('next_option'))
assert(created==1);draw();assert(created==1)
act('new_variant')
context.details.passive_variant_id['passive-a']={
 'First exact clause with a sufficiently long localized explanation that needs more than one line.',
 'Second clause retains its entire magnitude and conditions even on small displays.',
 'Third clause is still accessible and must never be silently omitted: END_OF_EFFECT.'}
draw();assert(created==2 and region('save_variant') and not region('apply_variant'))
assert(region('next_details'))
act('next_details','passive');draw()
assert(table.concat(rendered,' '):find('END_OF_EFFECT',1,true))
assert(region('previous_details') and not region('next_details'))
-- Mutating a display label must invalidate the retained GUI cache.
local count=created
context.labels.passive_variant_id={['passive-a']='New localized name'}
draw();assert(created==count+1)
state.ownership_verified=false;draw()
assert(not region('new_variant') and not region('save_variant') and not region('next_option'))
-- Only an explicit verified controller capability enables the apply path.
view.editor=S.editor_view(state,editor,view.tab,context)
view.editor.can_apply=true
view.editor.apply_note='Ready for controlled native look test.'
count=created;assert(panel:draw(sample,view));assert(created==count+1)
assert(region('apply_variant') and not region('reset_variant'))
view.editor.patch_active=true
view.editor.apply_note='Memory verified; native preview still needs checking.'
count=created;assert(panel:draw(sample,view));assert(created==count+1)
assert(region('reset_variant') and not region('apply_variant'))
-- Changing only the live result note also rebuilds retained text.
view.editor.apply_note='Recovery required; original bytes are retained.'
count=created;assert(panel:draw(sample,view));assert(created==count+1)
''')
