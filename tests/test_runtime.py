"""Exercise the bundled controller in LuaJIT, without a game or Win32 writes."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def run_lua(code):
    p = subprocess.run(['luajit','-'],input=code,text=True,cwd=ROOT,capture_output=True)
    assert p.returncode == 0, p.stdout + p.stderr

def test_controller_callbacks_clicks_persistence_and_failures():
    main = (ROOT/'src/main.lua').read_text()
    state = (ROOT/'src/state.lua').read_text()
    prefix = '''
local files, saved, actions, now = {}, 0, {}, 0
local input = {x=0,y=0,down=false}
local active = true
local target = nil
local drawn = 0
local writes_fail = false
local Platform = {new=function() return {
  now=function() return now end,
  sample_input=function() return input end,
  read=function(n) return files[n], files[n] and nil or 'missing' end,
  write_atomic=function(n,s)
    if writes_fail then return nil,'disk failure' end
    files[n]=s;if n=='transmog.state' then saved=saved+1 end;return true
  end
} end}
local Adapter = {new=function() return {sample=function()
  if active then return {token='screen1',anchor={x=0,y=0,w=420,h=40}} end
end} end}
local Panel = {new=function() return {
  clear=function() end,
  hit=function() return target end,
  draw=function(self,s,v) drawn=drawn+1;actions[#actions+1]=v.tab;return true end
} end}
stingray={}
CowboyBingusModLoader={api=1,open_log=function() return {write=function() end,flush=function() end,close=function() end} end}
local old_count,shut_count=0,0
update=function() old_count=old_count+1;return 'before',nil,42 end
shutdown=function() shut_count=shut_count+1;return 'closed' end
'''
    code = prefix + '\nlocal State=(function()\n'+state+'\nend)()\n'
    code += 'local function boot()\n'+main+'\nend\n'
    code += '''
boot()
local a,b,c=update();assert(a=='before' and b==nil and c==42)
assert(drawn==0)
now=16000;update();assert(drawn==1)
local function click(key)
 target=key;input.down=true;update();input.down=false;update();update()
end
click('passive');assert(actions[#actions]=='passive')
click('save');assert(saved==1 and files['transmog.state']:find('passive'))
local before=files['transmog.state']
writes_fail=true;click('save');assert(saved==1 and files['transmog.state']==before)
writes_fail=false
-- Losing focus cancels an armed press, including a release on the same control.
target='save';input.down=true;update();input=nil;update()
input={x=0,y=0,down=false};update();assert(saved==1)
-- A held click on entry must not activate anything.
active=false;update();input.down=true;active=true;update();input.down=false;update();assert(saved==1)
assert(shutdown()=='closed' and shut_count==1)
-- Saved tab is loaded at boot; no account ownership is supplied by the controller.
HD2Transmog=nil;boot();now=32000;update();assert(actions[#actions]=='passive')
-- Corrupt files are preserved, including on explicit save.
shutdown();HD2Transmog=nil;files['transmog.state']='FUTURE_FORMAT';boot()
now=48000;update();click('save');assert(files['transmog.state']=='FUTURE_FORMAT')
-- Missing loader fails without replacing the host's callback.
shutdown();HD2Transmog=nil;CowboyBingusModLoader=nil
local previous=update;local r=boot();assert(r.status=='startup_failed' and update==previous)
'''
    run_lua(code)

def test_owned_ids_are_scoped_to_their_category():
    run_lua('''
local S=dofile('src/state.lua')
local catalog={a={appearance_id='look',stats_id='stats',passive_variant_id='passive'}}
local s=S.new{catalog=catalog,owned={a=true}}
assert(not S.select(s,'passive','stats','passive'))
assert(not S.select(s,'look','passive','passive'))
assert(not S.select(s,'look','stats','look'))
assert(S.select(s,'look','stats','passive'))
S.reconcile_owned(s,catalog,{a=true});assert(s.selected)
s.catalog.a=3;assert(not S.validate(s));assert(not S.encode(s))
''')


def test_panel_retention_layout_and_teardown():
    panel=(ROOT/'src/panel.lua').read_text()
    code='''
local created,destroyed,texts=0,0,0
local worlds={'main','menu'}
local width,height=1920,1080
local function vector(...) return {...} end
local e={Vector2=vector,Vector3=vector,Color=vector,IdString64={from_hex=function(h) return h end},
 Application={worlds=function() return worlds end,main_world=function() return 'main' end},
 World={create_screen_gui=function() created=created+1;return created end,destroy_gui=function() destroyed=destroyed+1 end},
 Gui={resolution=function() return width,height end,material=function() return {} end,rect=function() end,text=function() texts=texts+1 end},
 Material={set_scalar=function() end,set_vector2=function() end,set_vector4=function() end,set_texture=function() end}}
'''
    code+='local Panel=(function()\n'+panel+'\nend)()\n'
    code+='''
local p=Panel.new(e)
local sample={anchor={x=100,y=100,w=420,h=40},font='a',material='b',atlas='c'}
local view={open=false,tab='appearance',notice='ready',saved=false}
assert(p:draw(sample,view));assert(created==1 and texts>0)
assert(p:draw(sample,view));assert(created==1)
assert(p:hit(120,165)=='toggle');assert(not p:hit(0,0))
view.open=true;assert(p:draw(sample,view));assert(created==2 and destroyed==1)
width=500;assert(not p:draw(sample,view));assert(destroyed==2)
width=1920;sample.anchor.y=1050;assert(not p:draw(sample,view))
sample.anchor.y=100;assert(p:draw(sample,view));worlds={'main'};p:clear();assert(destroyed==2)
'''
    run_lua(code)
