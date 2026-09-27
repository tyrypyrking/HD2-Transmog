"""Active variant naming stays outside native stats/perk/equip controls."""
from test_variant_editor import FIXTURE, run_lua


def test_title_only_exists_with_verified_controller_metadata_and_keeps_native_controls_clear():
    run_lua(FIXTURE + '''
local P=dofile('src/panel.lua')
local function vector(...)return {...}end
local created,texts=0,{}
local e={Vector2=vector,Vector3=vector,Color=vector,IdString64={from_hex=function(v)return v end},
 Application={worlds=function()return {'main','armory'}end,main_world=function()return 'main'end},
 World={create_screen_gui=function()created=created+1;return created end,destroy_gui=function()end},
 Gui={resolution=function()return 1920,1080 end,material=function()return {}end,rect=function()end,
 text=function(_,text)texts[#texts+1]=text end},
 Material={set_scalar=function()end,set_vector2=function()end,set_vector4=function()end,set_texture=function()end}}
local panel=P.new(e)
local sample={kind='armory',anchor={x=100,y=100,w=10,h=700},font='a',material='b',atlas='c'}
local view={open=false,tab='appearance',notice='ready',editor=S.editor_view(state,editor,'appearance',context)}
assert(panel:draw(sample,view));assert(not panel.active_title_bounds)
local before=created
view.active_variant={label='My independent mix',appearance_label='Lawmaker',stats_label='FS-37 base',passive_label='Extra Padding'}
assert(panel:draw(sample,view));assert(created==before+1 and panel.active_title_bounds)
assert(table.concat(texts,'|'):find('MY VARIANT',1,true))
assert(table.concat(texts,'|'):find('My independent mix',1,true))
assert(table.concat(texts,'|'):find('LOOK: Lawmaker   |   BASE: FS-37 base   |   PERK: Extra Padding',1,true))
assert(not panel:capture(1000,480)) -- Informational title does not intercept input.
assert(not panel:capture(1500,300)) -- Native stat/perk panel remains untouched.
assert(not panel:capture(1700,120)) -- Native Apply remains untouched.
before=created;assert(panel:draw(sample,view));assert(created==before)
view.active_variant=nil;assert(panel:draw(sample,view));assert(not panel.active_title_bounds and created==before+1)
view.active_variant={label='Incomplete metadata'}
assert(panel:draw(sample,view));assert(not panel.active_title_bounds)
''')
