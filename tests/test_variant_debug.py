"""The opt-in test controls exercise editor transactions and current ownership."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_debug_variants_use_owned_editor_and_durable_save_paths():
    main = (ROOT / 'src/main.lua').read_text()
    script = r'''
local now, visible, fail_save = 0,true,false
local files,handlers,last_view={},nil,nil
local State=dofile('src/state.lua')
local CatalogData,CatalogCompat={},{}
local result={source_commit='test',counts={kits=3,owned_armors=2},
 catalog={a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'},
 b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'},
 c={appearance_id='look-c',stats_id='stats-c',passive_variant_id='perk-c'}},
 owned={a=true,b=true},context={labels={}}}
local CatalogProbe={new=function()return {step=function()return 'ready',result end}end}
local Adapter={new=function(_,_,_,_,kind)
 if kind=='catalog' then return {step=function()return 'ready'end,data_bridge=function()return {}end}end
 return {phase='ready',sample=function()if visible then return {token='menu'}end end}
end}
local DebugBridge={new=function()return {poll=function(_,h)handlers=h end}end}
local Platform={new=function()return {
 now=function()return now end,read=function(name)return files[name],files[name] and nil or 'missing'end,
 sample_input=function()return {x=0,y=0,down=false}end,
 write_atomic=function(name,data)
  if name=='transmog.state' and fail_save then return nil,'disk full'end
  files[name]=data;return true
 end}end}
local Panel={new=function()return {clear=function()end,hit=function()end,
 draw=function(_,_,view)last_view=view;return true end}end}
local active,applications,resets=false,0,0
local RuntimeWriter={new=function()return {}end}
local AppearancePatch={new=function()return {
 plan=function(_,r,q)return {request=q}end,
 apply=function()active=true;applications=applications+1;return true,{status='verified'}end,
 reset=function()active=false;resets=resets+1;return true,{status='restored'}end,
 is_active=function()return active end}end}
stingray={};CowboyBingusModLoader={api=1}
local function boot()
''' + main + r'''
end
boot();now=16000;update();update()
local function command(name,args)
 local ok,value=pcall(handlers[name],args or '')
 update();return ok,value
end
local ok,why=command('draft_variant','look-a stats-b perk-c\nUnowned')
assert(not ok and applications==0)
ok,why=command('draft_variant','look-a stats-b perk-a\nIndependent test')
assert(ok,why);assert(last_view.editor.dirty)
fail_save=true;ok=command('save_variant');assert(not ok and not files['transmog.state'])
assert(last_view.editor.dirty)
fail_save=false;ok,why=command('save_variant');assert(ok,why)
assert(not last_view.editor.dirty and last_view.editor.saved_count==1)
local persisted=files['transmog.state']
local restored=assert(State.decode(assert(persisted:match('^HD2TRANSMOG_UI\t1\n[a-z]+\n(.*)$'))))
assert(restored.presets['Independent test'].stats_id=='stats-b')
visible=false;ok=command('apply_variant');assert(not ok and applications==0)
visible=true;update();update()
ok,why=command('select_variant','Independent test');assert(ok,why)
ok,why=command('apply_variant');assert(ok,why);assert(applications==1 and active)
ok=command('draft_variant','look-b stats-a perk-b\nRejected while active');assert(not ok)
ok,why=command('reset_variant');assert(ok,why);assert(resets==1 and not active)
assert(files['transmog.state']==persisted)
assert(files['debug-variant-status.txt']:find('active false',1,true))
'''
    result = subprocess.run(['luajit', '-'], input=script, text=True,
                            capture_output=True, cwd=ROOT, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
