from test_helmet_composition import run

FIXTURE='''
local Editor=dofile('src/helmet_editor.lua');local State=dofile('src/state.lua')
local current='b';local selected='b';local files={};local target;local shown;local applies,resets,consumed=0,0,0
local sample={kind='armory'}
local snapshot={native_category=1,native_view_mode=0,screen_kind='armory',helmet_selected_kit_id='b'}
local result={category=1,catalog={a={appearance_id='a',stats_id='stats-a',passive_variant_id='perk-a'},
 b={appearance_id='b',stats_id='stats-b',passive_variant_id='perk-b'}},owned={a=true,b=true},
 context={labels={appearance_id={a='Helmet A',b='Helmet B'}}},capabilities={helmet_transmog_enabled=true}}
local panel={clear=function()end,draw=function(_,_,v)shown=v;return true end,hit=function()return target end,capture=function()return true end}
local host={state=State,panel=panel,report=function()end,
 fs={read=function(name)return files[name],files[name]and nil or 'missing'end,write_atomic=function(name,bytes)files[name]=bytes;return true end},
 player=function()return {sample=function()return {settled=true,request={helmet_id=current},current={helmet_id=current},verify=function()return true end}end}end,
 snapshot=function()return snapshot end,consume=function()consumed=consumed+1;return true end,
 patch=function()return {plan=function(_,_,req)return {target_id=req.appearance_id}end,
 apply=function()applies=applies+1;return true end,reset=function()resets=resets+1;return true end}end}
local editor=Editor.new(host)
local function draw(down)editor:draw(sample,snapshot,result,{x=0,y=0,down=down})end
local function click(key)target=key;draw(true);draw(false)end
draw(false);click('toggle');click('new_variant')
-- Current native selection seeds B. Cycle once to A as appearance.
click('next_option')
'''

def test_prepare_keeps_native_equip_with_user_and_blocks_equipped_carrier():
    run(FIXTURE+'''
current='a';click('apply_variant');assert(applies==0 and not editor:is_active())
current='b';snapshot.helmet_selected_kit_id='a';click('apply_variant');assert(applies==0)
snapshot.helmet_selected_kit_id='b';click('apply_variant');assert(applies==1 and editor:is_active())
assert(current=='b'and shown.notice:find('Helmet A',1,true))
current='a';click('reset_variant');assert(resets==0 and editor:is_active())
current='b';click('reset_variant');assert(resets==1 and not editor:is_active())
''')

def test_separate_helmet_save_file_and_no_body_catalog_entries():
    run(FIXTURE+'''
click('save_variant');assert(files['helmets.state']and not files['transmog.state'])
local saved=assert(State.decode(files['helmets.state']));assert(saved.presets)
''')

def test_pre_input_capture_consumes_press_and_release_and_does_not_capture_other_tabs():
    run(FIXTURE+'''
editor:before({x=0,y=0,down=true});assert(consumed==1)
panel.capture=function()return false end
editor:before({x=200,y=200,down=true});assert(consumed==2)
editor:before({x=200,y=200,down=false});assert(consumed==3)
snapshot.native_category=0
editor:before({x=0,y=0,down=true});assert(consumed==3)
''')

def test_vanilla_capability_hides_panel_and_cancels_click():
    run(FIXTURE+'''
result.capabilities.helmet_transmog_enabled=false
assert(not editor:draw(sample,snapshot,result,{x=0,y=0,down=false}))
editor:before({x=0,y=0,down=true});assert(consumed==0)
''')
