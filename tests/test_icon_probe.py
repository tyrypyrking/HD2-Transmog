"""One-shot icon comparison uses owned GUI handles without casts or shared slots."""
from test_variant_wizard import run_lua


FIXTURE=r'''
local P=dofile('src/icon_probe.lua')
local created,destroyed,materials,bitmaps,sets,texts=0,0,{},{},{},{}
local worlds={'main','ui'}
local icon='7c818b04a594d8e5'
local generic='57fcf14ad069020b'
local sample={kind='armory',font='1111111111111111',material='2222222222222222',atlas='3333333333333333'}
local function vec(...)return {...}end
local engine={Vector2=vec,Vector3=vec,Color=vec,IdString64={from_hex=function(v)return v end},
 Application={worlds=function()return worlds end,main_world=function()return 'main'end,can_get=function()return true end},
 World={create_screen_gui=function(world)assert(world=='ui');created=created+1;return created end,
  destroy_gui=function(world,gui)assert(world=='ui');destroyed=destroyed+1 end},
 Gui={resolution=function()return 1920,1080 end,
  material=function(gui,id)local handle=newproxy(true);materials[handle]={gui=gui,id=id};return handle end,
  rect=function()end,text=function(_,value)texts[#texts+1]=value end,
  bitmap=function(gui,binding)bitmaps[#bitmaps+1]={gui=gui,binding=binding}end},
 Material={set_scalar=function(handle,slot,value)sets[#sets+1]={kind='scalar',handle=handle,slot=slot,value=value}end,
  set_vector2=function(handle,slot,value)sets[#sets+1]={kind='vector2',handle=handle,slot=slot,value=value}end,
  set_vector4=function(handle,slot,value)sets[#sets+1]={kind='vector4',handle=handle,slot=slot,value=value}end,
  set_texture=function(handle,slot,value)sets[#sets+1]={kind='texture',handle=handle,slot=slot,value=value}end}}
local probe=P.new(engine)
'''


def test_four_comparisons_use_separate_owned_guis_and_original_material_userdata():
    run_lua(FIXTURE+r'''
assert(probe:draw(sample,icon))
assert(created==5 and #bitmaps==4 and probe:metrics().bitmap_accepted==4)
assert(bitmaps[1].binding==icon) -- Explicit baseline reproduces old resource-ID route.
local seen={}
for index,entry in ipairs(bitmaps)do
 assert(not seen[entry.gui]);seen[entry.gui]=true
 if index>1 then
  assert(type(entry.binding)=='userdata' and materials[entry.binding].gui==entry.gui)
  assert(materials[entry.binding].id==(index==3 and generic or icon))
 end
end
local generic_bindings,configured_scalars=0,0
for _,entry in ipairs(sets)do
 if entry.kind=='texture'and entry.slot=='diffuse_map'then
  assert(entry.handle==bitmaps[3].binding and entry.value==icon);generic_bindings=generic_bindings+1
 end
 if entry.kind=='scalar'and entry.handle==bitmaps[4].binding then assert(entry.value==0);configured_scalars=configured_scalars+1 end
end
assert(generic_bindings==1 and configured_scalars==4)
assert(probe:report():find('visual_verified=false',1,true))
assert(probe:report():find('configured_uniforms_verified_for=font_material_only',1,true))
''')


def test_probe_is_one_shot_and_clear_destroys_only_owned_live_guis():
    run_lua(FIXTURE+r'''
assert(probe:draw(sample,icon))
assert(not probe:draw(sample,icon)and created==5)
probe:clear();assert(destroyed==5 and not probe:metrics().visible and probe:metrics().active_guis==0)
probe:clear();assert(destroyed==5)
assert(not probe:draw(sample,icon)and created==5)
local metrics=probe:metrics();metrics.attempts=999
assert(probe:metrics().attempts==1 and probe:metrics().draw_requests==3)
local another=P.new(engine);assert(another:draw(sample,icon))
worlds={'main'};another:clear();assert(destroyed==5 and another:metrics().active_guis==0)
''')


def test_nonuserdata_icon_materials_are_rejected_without_cast_or_bitmap_call():
    run_lua(FIXTURE+r'''
local original=engine.Gui.material
engine.Gui.material=function(gui,id)
 if id==sample.material then return original(gui,id)end
 return require('ffi').cast('void *',123456)
end
assert(probe:draw(sample,icon))
assert(#bitmaps==1 and bitmaps[1].binding==icon)
local report=probe:report()
assert(report:find('branch=icon_userdata accepted=false',1,true))
assert(report:find('branch=generic_texture accepted=false',1,true))
assert(report:find('branch=configured_icon accepted=false',1,true))
assert(not report:find('123456',1,true))
''')


def test_branch_failure_is_reported_without_retry_or_affecting_other_materials():
    run_lua(FIXTURE+r'''
local original=engine.Material.set_texture
engine.Material.set_texture=function(handle,slot,value)
 if slot=='diffuse_map'then error('rejected resource at 0xabcdef\nnext line')end
 return original(handle,slot,value)
end
assert(probe:draw(sample,icon)and #bitmaps==3)
local report=probe:report()
assert(report:find('branch=generic_texture accepted=false',1,true))
assert(report:find('branch=configured_icon accepted=true',1,true))
assert(not report:find('0xabcdef',1,true))
assert(probe:metrics().guis_created==5)
probe:clear();assert(destroyed==5)
''')


def test_invalid_context_and_missing_resources_fail_without_automatic_loading():
    run_lua(FIXTURE+r'''
assert(not probe:draw({kind='ship'},icon)and created==0)
assert(probe:metrics().attempts==1 and probe:report():find('status=failed',1,true))
probe=P.new(engine)
engine.Application.can_get=function()return false end
assert(probe:draw(sample,icon)and #bitmaps==0 and created==5)
assert(probe:report():find('material_available=false',1,true))
probe:clear();assert(destroyed==5)
''')
