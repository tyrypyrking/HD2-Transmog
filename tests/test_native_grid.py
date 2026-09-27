"""Current-image grid resolution, input capture and read-only mapping guards."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

FIXTURE=r'''
local ffi=require('ffi')
local memory={}
local function b(n,size)local out={};for i=1,size do out[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(out)end
local function f(n)local v=ffi.new('float[1]',n);return ffi.string(v,4)end
local function region(at,n)memory[#memory+1]={at=at,raw=string.rep('\0',n)}end
local function put(at,s)
 for _,r in ipairs(memory)do if at>=r.at and at+#s<=r.at+#r.raw then
  local i=at-r.at;r.raw=r.raw:sub(1,i)..s..r.raw:sub(i+#s+1);return end end
 error('bad fixture write')
end
local reads,large=0,0
local function read(at,n)
 reads=reads+1;if n>200000 then large=large+1 end
 for _,r in ipairs(memory)do if at>=r.at and at+n<=r.at+#r.raw then return r.raw:sub(at-r.at+1,at-r.at+n)end end
end
local base,manager,menu,owner,input=0x100000,0x200000,0x300000,0x400000,0x600000
local grid=owner+523752
region(base,0x60000);region(manager,0x1800);region(menu,0x4400);region(owner,1200000)
put(base,'MZ');put(base+60,b(0x80,4));put(base+0x80,'PE\0\0')
put(base+0x84,b(0x8664,2));put(base+0x86,b(2,2));put(base+0x94,b(240,2));put(base+0x98,b(0x20b,2));put(base+0xd0,b(0x60000,4))
local section=base+0x80+24+240
put(section+8,b(0x40000,4)..b(0x1000,4));put(section+36,b(0x60000020,4))
put(section+48,b(0x1000,4)..b(0x50000,4));put(section+76,b(0x40000040,4))
local patterns={
 position={0x1000,'48895c241848896c24204889542410565741574883ec20f30f104104488bda0f'},
 animation_stop={0x3000,'40534883ec40488b05000000004833c448894424300fb601'},
 consume={0x5000,'40534883ec204c8bd14c8bca488bcae800000000'},
}
for _,v in pairs(patterns)do put(base+v[1],(v[2]:gsub('%x%x',function(h)return string.char(tonumber(h,16))end)))end
local function decode(raw,rva)
 local ops
 if rva==patterns.position[1]then ops={'movss xmm0, [rcx+0x4]','movss xmm0, [rcx+0x8]','mov rbx, rdx'}
 elseif rva==patterns.animation_stop[1]then ops={'movzx eax, byte [rcx]','cmp eax, +0x07'}
 else ops={'mov r10, rcx','mov r9, rdx','mov byte [r11+r10+0x328], 0x0','mov [r11+r10+0x32c], rbx','mov [r11+r10+0x334], ebx','mov r8d, 0x2','mov rdx, r9'}end
 local rows={};for i,op in ipairs(ops)do rows[#rows+1]={rva=rva+i,op=op}end
 if rva==patterns.consume[1]then
  rows[#rows+1]={rva=rva+126,op=string.format('mov rcx, [rip+0x%x]',0x50020-(rva+133))}
  rows[#rows+1]={rva=rva+133,op='movaps xmm3, xmm2'}
 end
 return rows
end
DebugArmory={decode=decode}
local G=dofile('src/native_grid.lua')
put(base+0x50000,b(manager,8));put(base+0x50008,b(menu,8));put(base+0x50020,b(input,8))
put(manager+0x166c,b(1,4));put(manager+0x1670,b(owner,8)..b(224,4)..b(0,4))
put(menu+0x4294,b(5,4));put(menu+0x429c,b(5,4));put(menu+0x42b0,b(1,4))
put(grid+4,f(100)..f(200)..f(900)..f(700));put(grid+272+84,f(1))
put(grid+600452,b(2,4));put(grid+600308,b(1,4));put(grid+597772,b(1,4))
put(grid+622656,b(0,4)..b(2,4));put(grid+602052,b(2,4));put(grid+602096,b(1,4))
put(grid+600416,f(50));put(grid+600424,f(1200))
local rec=grid+602104+3*80;put(rec,b(0x1234,4)..b(0,4)..b(3,4));put(rec+60,b(1,4)..b(2,4));put(rec+72,b(7,4))
local row=grid+2816;put(row+44724,b(1,4));local widget=row+9192
put(widget+4,f(50)..f(60)..f(100)..f(200));put(widget+340,f(1))
put(widget+548,f(.1)..f(.2)..f(.3)..f(.4));put(widget+608,string.char(0x46,0xe4,0x06,0x55,0x43,0x06,0xef,0x27))
put(widget+1984,b(rec,8));put(widget+1984+21,string.char(1))
local bridge={base=base,manager_global=base+0x50000,menu_global=base+0x50008,read=read,verify=function()return true end}
local consumed,moves,stops=0,0,0
local backend={executable=function(at)return at==base+0x1000 or at==base+0x3000 or at==base+0x5000 end,
 consume=function(at,object)assert(at==base+0x5000 and object==input);consumed=consumed+1;return true end,
 position=function(at,object,x,y)assert(at==base+0x1000 and object==grid);moves=moves+1;put(grid+4,f(x)..f(y));return true end,
 stop=function(at,object)assert(at==base+0x3000 and object==grid+600320);stops=stops+1;return true end}
local function ready(instance)
 for i=1,1000 do
  local before=large;local phase=instance:step();assert(large-before<=1,'more than one scan chunk per step')
  if phase~='resolving'then return phase end
 end
 error('resolver did not finish')
end
'''


def run_lua(code):
    proc=subprocess.run(['luajit','-'],input=FIXTURE+code,text=True,capture_output=True,cwd=ROOT,timeout=20)
    assert proc.returncode==0,proc.stdout+proc.stderr


def test_dynamic_native_targets_and_input_global_resolve_without_fixed_calls():
    run_lua('''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready',g.failure)
assert(g:consume_select() and consumed==1)
assert(g:consume() and consumed==2)
put(base+0x5000+64,'X');local ok,why=g:consume_select()
assert(not ok and why:find('Grid code evidence changed',1,true) and consumed==2)
''')


def test_grid_snapshot_is_read_only_and_does_not_conflate_ring_index_with_selection():
    run_lua('''
local g=G.new(bridge,nil,backend)
local s=assert(g:snapshot({records={a={item_id=0x1234}}}))
assert(s.identity_mapping_verified==false and s.selected_kit_id==nil)
assert(s.selected_index==1 and s.item_count==2 and #s.widgets==1 and #s.records==1)
assert(s.widgets[1].ring_index==3 and s.records[1].ring_index==3)
assert(s.records[1].visual_matches_known_kit=='armor:00001234')
assert(s.widgets[1].named_image_material and not s.widgets[1].runtime_material_present)
assert(s.owner==nil and s.grid==nil and s.widgets[1].address==nil and consumed==0 and moves==0)
local text=G.format(s);assert(text:find('identity_mapping_verified=false',1,true))
assert(not text:find(tostring(owner),1,true))
''')


def test_grid_position_is_bounded_and_restores_only_owned_changes():
    run_lua('''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local s=assert(g:snapshot());assert(not g:position(s,100,800))
put(grid+600320,string.char(1,1,1,0));assert(g:position(s,100,80));assert(moves==1 and stops==1)
assert(not g:position(assert(g:snapshot()),100,60))
assert(g:restore_position());assert(moves==2)
s=assert(g:snapshot());assert(s.y==200);assert(g:position(s,100,80))
put(grid+8,f(90));assert(not g:restore_position() and moves==3)
''')


def test_snapshot_rejects_hidden_grid_ambiguous_registry_and_observation_race():
    run_lua('''
local g=G.new(bridge,nil,backend)
put(grid+272+84,f(0));assert(not g:snapshot());put(grid+272+84,f(1))
put(manager+0x166c,b(2,4));put(manager+0x1680,b(owner,8)..b(224,4)..b(0,4));assert(not g:snapshot())
put(manager+0x166c,b(1,4))
local visits=0
bridge.read=function(at,n)
 if at==grid+600308 then visits=visits+1;if visits==2 then return b(0,4)end end
 return read(at,n)
end
local s,why=g:snapshot();assert(not s and why:find('changed during observation'))
''')


def test_missing_or_ambiguous_code_never_enables_input_calls():
    run_lua('''
put(base+0x5000,'X');local g=G.new(bridge,nil,backend)
assert(ready(g)=='failed');assert(not g:consume_select() and consumed==0)
local code=patterns.consume[2]:gsub('%x%x',function(h)return string.char(tonumber(h,16))end)
put(base+0x5000,code);put(base+0x7000,code)
g=G.new(bridge,nil,backend);assert(ready(g)=='failed' and g.failure:find('ambiguous'))
assert(not g:consume_select() and consumed==0)
''')


def test_input_global_race_or_nonexecutable_target_stops_native_call():
    run_lua('''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
backend.executable=function()return false end;assert(not g:consume_select() and consumed==0)
backend.executable=function()return true end
local visits=0
bridge.read=function(at,n)
 if at==base+0x50020 then visits=visits+1;if visits==2 then return b(input+256,8)end end
 return read(at,n)
end
assert(not g:consume_select() and consumed==0)
''')

SELECTION=r'''
-- Optional production evidence uses real instruction bytes and the real decoder.
local S=require('src.debug_armory')
local selection_rva,thumbnail_rva=0x9000,0xb000
local selected_hex='448b87b0831f0033d24585c07431488b05000000008bca448b88e01c00004585c9741c4805e49c0b0044394004740dffc14883c018413bc972efeb038b5008899790000000'
local thumb_hex='40534883ec204533c9488bda488b1500000000418bc9448b82802b00004585c0'
local function unhex(h)return(h:gsub('%x%x',function(v)return string.char(tonumber(v,16))end))end
put(base+selection_rva,unhex(selected_hex));put(base+selection_rva+17,b(0x50028-(selection_rva+21),4))
local branch=selection_rva-100
put(base+branch,unhex('8b8fac831f0083e9010f84')..b(selection_rva-(branch+15),4))
put(base+thumbnail_rva,unhex(thumb_hex));put(base+thumbnail_rva+15,b(0x50030-(thumbnail_rva+19),4))
DebugArmory.decode=function(raw,rva)
 if rva==selection_rva or rva==thumbnail_rva then return S.decode(raw,rva,256)end
 return decode(raw,rva)
end
-- Extend the fixture UI owner for the independently proven selected descriptor.
for _,r in ipairs(memory)do if r.at==owner then r.raw=r.raw..string.rep('\0',1000000)end end
put(owner+0x1f83a0,b(0,4));put(owner+0x1f83ac,b(1,4));put(owner+0x1f83b0,b(77,4))
local progression,thumbnail=0x800000,0x900000
region(progression,0xc0000);region(thumbnail,13000)
put(base+0x50028,b(progression,8));put(base+0x50030,b(thumbnail,8))
put(progression+0x1ce0,b(2,4))
put(progression+0xb9ce4,b(0,4)..b(77,4)..b(0x1234,4))
put(progression+0xb9ce4+24,b(1,4)..b(88,4)..b(0x5678,4))
put(thumbnail+11052,b(7,4));put(thumbnail+1816+1832,b(8,4));put(thumbnail+1816+1836,b(3,4))
local thumbnail_item=thumbnail+1816+32+2*120
put(thumbnail_item+24,b(77,8));put(thumbnail_item+100,b(2,4))
put(widget+600,b(0x990000,8))
local catalog={records={one={item_id=0x1234,category=0},two={item_id=0x5678,category=0}}}
'''


def test_selected_armor_uses_proven_category_offer_mapping_not_grid_anchor():
    run_lua(SELECTION+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready',g.failure)
local s=assert(g:snapshot(catalog))
assert(s.identity_mapping_verified and s.selected_kit_id=='armor:00001234')
assert(s.selected_index==1 and s.native_category==1 and s.native_offer_id==77)
put(owner+0x1f83b0,b(88,4))
s=assert(g:snapshot(catalog));assert(s.selected_index==1 and s.selected_kit_id=='armor:00005678')
put(owner+0x1f83ac,b(0,4))
s=assert(g:snapshot(catalog));assert(s.identity_mapping_verified and s.selected_kit_id=='armor:00005678')
catalog.records.two.category=1
s=assert(g:snapshot(catalog));assert(not s.identity_mapping_verified and s.selected_kit_id==nil)
''')


def test_thumbnail_bindings_match_proven_offer_to_owned_catalog_kind_and_invalidate():
    run_lua(SELECTION+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local s=assert(g:snapshot(catalog));local preview=assert(s.appearance_previews['armor:00001234'])
assert(preview.material_pointer==0x990000 and preview.binding_verified and preview.valid())
assert(preview.uv[3]>preview.uv[1] and preview.uv[4]>preview.uv[2])
local text=G.format(s);assert(text:find('preview id=armor:00001234 binding_verified=true',1,true))
assert(not text:find(tostring(0x990000),1,true))
put(widget+600,b(0x990008,8));assert(not preview.valid())
put(widget+600,b(0x990000,8));assert(preview.valid())
put(menu+0x4294,b(0,4));assert(not preview.valid())
''')


GEOMETRY=r'''
put(widget+4,f(0)..f(0)..f(100)..f(200)) -- Local coordinates are deliberately useless.
put(widget+100,f(1.25));put(widget+140,f(.75))
put(widget+148,f(460));put(widget+156,f(300))
put(widget+272+4,f(0)..f(0)..f(80)..f(150))
put(widget+272+100,f(1.5));put(widget+272+140,f(.5))
put(widget+272+148,f(450));put(widget+272+156,f(320))
catalog.owned={['armor:00001234']=true}
local owned_checks=0
catalog.verify_owned=function(ids)
 owned_checks=owned_checks+1
 for _,id in ipairs(ids)do if catalog.owned[id]~=true then return false end end
 return true
end
'''


def test_widget_diagnostics_use_both_world_rects_and_fresh_owned_identity():
    run_lua(SELECTION+GEOMETRY+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local s=assert(g:snapshot(catalog));local w=s.widgets[1]
assert(w.x==0 and w.y==0)
assert(w.root_viewport_rect.x==460 and w.root_viewport_rect.y==300)
assert(w.root_viewport_rect.w==125 and w.root_viewport_rect.h==150)
assert(w.image_viewport_rect.x==450 and w.image_viewport_rect.y==320)
assert(w.image_viewport_rect.w==120 and w.image_viewport_rect.h==75)
assert(w.bound_owned_kit_id=='armor:00001234' and w.owned_identity_verified and owned_checks==1)
assert(not w.hitbox_verified and not w.rendering_verified)
assert(w.coordinate_space=='candidate_viewport_bottom_left')
local text=G.format(s)
assert(text:find('source=root_viewport_rect x=460 y=300 width=125 height=150',1,true))
assert(text:find('source=image_viewport_rect x=450 y=320 width=120 height=75',1,true))
assert(text:find('owned_kit=armor:00001234 owned_verified=true hitbox_verified=false rendering_verified=false',1,true))
assert(consumed==0 and moves==0 and stops==0)
assert(not text:find(tostring(widget),1,true) and not text:find(tostring(0x990000),1,true))
''')


def test_cached_missing_or_failed_owned_proof_never_exposes_a_matched_kit():
    run_lua(SELECTION+GEOMETRY+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
catalog.verify_owned=nil
local w=assert(g:snapshot(catalog)).widgets[1]
assert(w.root_viewport_rect and not w.bound_owned_kit_id and not w.owned_identity_verified)
catalog.verify_owned=function()return false end
w=assert(g:snapshot(catalog)).widgets[1];assert(not w.bound_owned_kit_id)
catalog.verify_owned=function()error('stale session')end
w=assert(g:snapshot(catalog)).widgets[1];assert(not w.bound_owned_kit_id)
catalog.owned={};catalog.verify_owned=function()error('No cached candidate should be checked')end
w=assert(g:snapshot(catalog)).widgets[1];assert(not w.bound_owned_kit_id)
''')


def test_geometry_candidates_fail_closed_without_affecting_valid_identity_diagnostics():
    run_lua(SELECTION+GEOMETRY+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
put(widget+100,f(0))
local w=assert(g:snapshot(catalog)).widgets[1]
assert(not w.root_viewport_rect and w.image_viewport_rect and w.owned_identity_verified)
put(widget+272+156,f(0/0))
w=assert(g:snapshot(catalog)).widgets[1]
assert(not w.root_viewport_rect and not w.image_viewport_rect)
put(widget+1984+21,string.char(0))
w=assert(g:snapshot(catalog)).widgets[1];assert(not w.bound_owned_kit_id)
put(widget+1984+21,string.char(1));put(widget+340,f(.5))
w=assert(g:snapshot(catalog)).widgets[1];assert(not w.bound_owned_kit_id)
put(widget+340,f(1));put(rec+8,b(2,4))
w=assert(g:snapshot(catalog)).widgets[1];assert(not w.bound_owned_kit_id)
''')


def test_world_geometry_changed_during_owned_verification_rejects_snapshot():
    run_lua(SELECTION+GEOMETRY+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
catalog.verify_owned=function()put(widget+272+148,f(999));return true end
local s,why=g:snapshot(catalog)
assert(not s and why:find('changed during observation') and consumed==0 and moves==0)
''')


def test_fresh_widget_ownership_checks_are_deduplicated_and_batched_at_sixteen():
    run_lua(SELECTION+'''
put(progression+0x1ce0,b(17,4));put(grid+597772,b(5,4));put(grid+600452,b(17,4))
catalog.records={};catalog.owned={}
for index=0,16 do
 local kit,offer=0x1000+index,100+index
 local id=string.format('armor:%08x',kit)
 catalog.records[id]={item_id=kit,category=0};catalog.owned[id]=true
 put(progression+0xb9ce4+index*24,b(index,4)..b(offer,4)..b(kit,4))
 local card,slot=math.floor(index/15),index%15
 local entry=thumbnail+card*1816+32+slot*120
 put(entry+24,b(offer,8));put(entry+100,b(2,4))
 local record_at=grid+602104+index*80
 put(record_at,b(kit,4)..b(0,4)..b(3,4));put(record_at+60,b(card,4)..b(slot,4))
 local row_index,column=math.floor(index/4),index%4
 local row_at=grid+2816+row_index*44752
 put(row_at+44724,b(row_index==4 and 1 or 4,4))
 local widget_at=row_at+9192+column*11112
 put(widget_at+1984,b(record_at,8));put(widget_at+1984+21,string.char(1));put(widget_at+340,f(1))
end
put(thumbnail+1832,b(8,4));put(thumbnail+1836,b(15,4))
put(thumbnail+1816+1832,b(8,4));put(thumbnail+1816+1836,b(2,4))
local batches={}
catalog.verify_owned=function(ids)batches[#batches+1]=ids;return #batches==1 end
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local s,why=g:snapshot(catalog);assert(s,why)
assert(#batches==2 and #batches[1]==16 and #batches[2]==1)
assert(#s.widgets==17)
for index=1,16 do assert(s.widgets[index].owned_identity_verified)end
assert(not s.widgets[17].bound_owned_kit_id and not s.widgets[17].owned_identity_verified)
assert(consumed==0 and moves==0)
''')


def test_unknown_or_conflicting_offer_never_authorizes_selected_identity():
    run_lua(SELECTION+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
put(progression+0xb9ce4+24+4,b(77,4))
local s=assert(g:snapshot(catalog));assert(not s.identity_mapping_verified and s.selected_kit_id==nil)
assert(next(s.appearance_previews)==nil)
put(owner+0x1f83b0,b(999,4));s=assert(g:snapshot(catalog));assert(not s.identity_mapping_verified)
''')


def test_changed_optional_mapping_does_not_disable_core_input_resolution():
    run_lua(SELECTION+'''
put(base+selection_rva-100,'X')
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(g:consume_select() and consumed==1)
local s=assert(g:snapshot(catalog));assert(not s.identity_mapping_verified)
''')

SIZE=r'''
local size_rva=0xd000
put(base+size_rva,(('48895c241848896c24204889542410565741574883ec20f30f10410c488bda0f'):gsub('%x%x',function(v)return string.char(tonumber(v,16))end)))
local old_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva)
 if rva==size_rva then return {{rva=rva,op='movss xmm0, [rcx+0xc]'},{rva=rva+5,op='movss xmm0, [rcx+0x10]'},{rva=rva+10,op='mov rbx, rdx'}}end
 return old_decode(raw,rva)
end
local old_executable=backend.executable
backend.executable=function(at)return at==base+size_rva or old_executable(at)end
local sizes=0
backend.size=function(at,object,w,h)assert(at==base+size_rva and object==grid);sizes=sizes+1;put(grid+12,f(w)..f(h));return true end
'''


def test_native_top_reservation_preserves_bottom_and_restores_hidden_same_owner():
    run_lua(SIZE+'''
put(grid+4,f(172)..f(-238)..f(644)..f(738))
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local result=assert(g:reserve_top(120))
assert(result.y==-358 and result.height==618 and result.bottom==-976 and not result.rendering_verified)
assert(moves==1 and sizes==1 and g:layout_active())
put(grid+272+84,f(0))
assert(g:restore_layout() and moves==2 and sizes==2 and not g:layout_active())
put(grid+272+84,f(1));local s=assert(g:snapshot());assert(s.y==-238 and s.height==738)
''')


def test_native_reservation_rolls_back_when_size_change_fails():
    run_lua(SIZE+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local old_size=backend.size;local attempts=0
backend.size=function(...)
 attempts=attempts+1
 if attempts==1 then return false end
 return old_size(...)
end
local result,why=g:reserve_top(100)
assert(not result and why:find('size change rejected'))
assert(not g:layout_active() and moves==2)
local s=assert(g:snapshot());assert(s.x==100 and s.y==200 and s.width==900 and s.height==700)
''')


def test_retired_grid_reservation_is_forgotten_without_stale_native_writes():
    run_lua(SIZE+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready');assert(g:reserve_top(100))
put(menu+0x4294,b(0,4));put(manager+0x166c,b(0,4))
local before_moves,before_sizes=moves,sizes
local ok,why=g:release_view();assert(ok and why:find('retired'))
assert(not g:layout_active() and moves==before_moves and sizes==before_sizes)
''')


def test_missing_native_size_support_never_moves_grid():
    run_lua('''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(not g:reserve_top(100) and moves==0 and not g:layout_active())
assert(g:consume_select())
''')


def test_reused_thumbnail_record_and_offer_invalidate_old_material_binding():
    run_lua(SELECTION+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local s=assert(g:snapshot(catalog));local p=assert(s.appearance_previews['armor:00001234']);assert(p.valid())
put(rec+72,b(8,4));assert(not p.valid());put(rec+72,b(7,4));assert(p.valid())
put(thumbnail_item+24,b(88,8));assert(not p.valid())
''')

HIGHLIGHT=r'''
local highlight_rva=0xf000
put(base+highlight_rva,('48895c24185556574883ec20448b89141f090033ed488bf9448bc58bf54585c9'):gsub('%x%x',function(v)return string.char(tonumber(v,16))end))
local previous_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva)
 if rva==highlight_rva then
  local ops={'mov r9d, [rcx+0x91f14]','mov ecx, [rdi+rax*4+0x92318]',
   'cmp [rdi+rax*4+0x92990], edx','mov [rdi+0x928e8], esi','mov [rdi+0x928ec], ebx',
   'mov [rdi+0x92988], ebp','mov al, 0x1','xor al, al'}
  local rows={};for i,op in ipairs(ops)do rows[i]={rva=rva+i,op=op}end;return rows
 end
 return previous_decode(raw,rva)
end
local previous_executable=backend.executable
backend.executable=function(at)return at==base+highlight_rva or previous_executable(at)end
local highlighted=0
backend.highlight=function(at,object,offer)
 assert(at==base+highlight_rva and object==grid)
 highlighted=highlighted+1;put(grid+0x92988,b(offer,4));return true
end
put(grid+0x91f14,b(1,4));put(grid+0x92318,b(2,4));put(grid+0x92990,b(88,4)..b(77,4))
put(progression+0x1ce4+0x14,b(2,4));put(progression+0x1ce4+184+0x14,b(4,4))
catalog.owned={['armor:00001234']=true,['armor:00005678']=true}
catalog.records['armor:00001234']=catalog.records.one;catalog.records.one=nil
catalog.records['armor:00005678']=catalog.records.two;catalog.records.two=nil
catalog.verify_owned=function(ids)return catalog.owned[ids[1]]==true end
'''


def test_native_highlight_uses_owned_visible_offer_and_never_marks_equipped():
    run_lua(SELECTION+HIGHLIGHT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local result=assert(g:select_kit('armor:00001234',catalog))
assert(result.offer_id==77 and result.kit_id=='armor:00001234' and highlighted==1)
assert(result.equipped==false and result.rendering_verified==false and moves==0 and consumed==0)
local s=assert(g:snapshot(catalog));assert(s.native_selected_offer==77)
''')


def test_native_highlight_rechecks_selected_offer_ownership_not_only_catalog_cache():
    run_lua(SELECTION+HIGHLIGHT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
put(progression+0x1ce4+0x14,b(1,4))
local result,why=g:select_kit('armor:00001234',catalog)
assert(not result and why:find('enabled owned offer') and highlighted==0)
put(progression+0x1ce4+0x14,b(2,4));put(progression+0x1ce4+0xb4,string.char(1))
assert(not g:select_kit('armor:00001234',catalog) and highlighted==0)
''')


def test_native_highlight_rejects_wrong_category_missing_list_offer_and_race():
    run_lua(SELECTION+HIGHLIGHT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
put(owner+0x1f83a0,b(1,4));assert(not g:select_kit('armor:00001234',catalog));put(owner+0x1f83a0,b(0,4))
put(grid+0x92994,b(99,4));assert(not g:select_kit('armor:00001234',catalog));put(grid+0x92994,b(77,4))
local verifies=0;catalog.verify_owned=function()verifies=verifies+1;return verifies==1 end
assert(not g:select_kit('armor:00001234',catalog) and highlighted==0)
''')


def test_native_highlight_success_requires_native_selected_offer_readback():
    run_lua(SELECTION+HIGHLIGHT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
backend.highlight=function()highlighted=highlighted+1;return true end
local result,why=g:select_kit('armor:00001234',catalog)
assert(not result and why:find('readback differs') and highlighted==1)
''')


def test_maximum_offer_table_and_visible_widgets_fit_observation_budget():
    run_lua(SELECTION+'''
for _,r in ipairs(memory)do if r.at==progression then r.raw=r.raw..string.rep('\\0',200000)end end
put(progression+0x1ce0,b(4096,4));put(grid+597772,b(12,4))
for row_index=0,11 do
 local row_at=grid+2816+row_index*44752;put(row_at+44724,b(4,4))
 for column=0,3 do put(row_at+9192+column*11112+1984,b(rec,8))end
end
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local total=0;local original=bridge.read
bridge.read=function(at,n)total=total+n;return original(at,n)end
local s,why=g:snapshot(catalog);assert(s,why)
assert(#s.widgets==48 and total<500000,'snapshot reread budget unexpectedly large: '..total)
''')

COMMIT=r'''
local commit_rva,apply_rva=0x12000,0x13000
put(base+selection_rva+69,string.char(0x33,0xd2,0x48,0x8b,0xcf,0xe8)..b(commit_rva-(selection_rva+79),4))
local former_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva)
 if rva==commit_rva then
  local ops={'mov eax, [rcx+0x90]','mov [rbx+0x40], eax','mov eax, [rcx+0x94]',
   'mov [rbx+0x44], eax','mov eax, [rcx+0x98]','mov [rbx+0x48], eax','lea rsi, [rcx+0x64]',
   'mov r8d, 0x2c','lea rbp, [rcx+0x38]','movups [rbp+0x0], xmm0','mov [rbp+0x28], eax'}
  local rows={};for i,op in ipairs(ops)do rows[#rows+1]={rva=rva+i,op=op}end
  rows[#rows+1]={rva=rva+26,op=string.format('mov rbx, [rip+0x%x]',0x50038-(rva+33))}
  rows[#rows+1]={rva=rva+33,op='xor dil, dil'}
  rows[#rows+1]={rva=rva+136,op=string.format('mov rax, [rip+0x%x]',0x50040-(rva+143))}
  rows[#rows+1]={rva=rva+143,op='cmp dword [rax+0x88], +0x00'}
  rows[#rows+1]={rva=rva+170,op='mov rcx, rsi'}
  rows[#rows+1]={rva=rva+173,op=string.format('call 0x%08x',apply_rva)}
  rows[#rows+1]={rva=rva+178,op='movups xmm0, [rsi]'}
  return rows
 elseif rva==apply_rva then
  local ops={'mov rdi, rcx','mov ebx, edx','xor esi, esi','mov eax, [rdi+0x4]',
   'mov eax, [rdi+0x8]','mov eax, [rdi+0xc]','cmp dword [rcx+0x28], +0x01',
   'cmp dword [rcx+0x28], +0x02','cmp [rcx+0x28], esi'}
  local rows={};for i,op in ipairs(ops)do rows[i]={rva=rva+i,op=op}end;return rows
 end
 return former_decode(raw,rva)
end
local settings,players,local_player=0xa00000,0xb00000,0xc00000
region(settings,256);region(players,512);region(local_player,32)
put(base+0x50038,b(settings,8));put(base+0x50040,b(players,8))
put(players+0x84,b(1,4)..b(1,4));put(players+0xe8,b(local_player,8));put(local_player+8,b(42,4))
local initial_profile=b(11,4)..b(22,4)..b(33,4)..b(0x1234,4)..string.rep('P',28)
put(owner+0x38,initial_profile);put(owner+0x64,initial_profile)
put(owner+0x90,b(0x1111,4)..b(0x2222,4)..b(0x3333,4));put(settings+0x40,read(owner+0x90,12))
local old_execute=backend.executable
backend.executable=function(at)return at==base+commit_rva or old_execute(at)end
local commits,armor_assignments=0,0
backend.write_armor=function(at,id)
 assert(at==owner+0x70,'only current profile armor field may be assigned')
 armor_assignments=armor_assignments+1;put(at,b(id,4));return true
end
backend.commit=function(at,object)
 assert(at==base+commit_rva and object==owner)
 commits=commits+1;put(owner+0x38,read(owner+0x64,44));return true
end
catalog.records['armor:00001234']=catalog.records.one;catalog.records.one=nil
catalog.records['armor:00005678']=catalog.records.two;catalog.records.two=nil
catalog.owned={['armor:00001234']=true,['armor:00005678']=true}
catalog.verify_owned=function(ids)return catalog.owned[ids[1]]==true end
'''


def test_commit_target_is_derived_and_only_actual_armor_field_is_changed():
    run_lua(SELECTION+COMMIT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(g:commit_capabilities().commit_verified and not g:commit_capabilities().cache_layout_verified)
local s=assert(g:commit_snapshot(catalog));assert(g:verify_commit(s))
assert(s.local_player_id==42 and s.controller_armor_id=='armor:00001234' and s.profile_armor_id=='armor:00001234')
assert(not s.pending_nonarmor)
local protected=s.other_key;local mirrors=read(owner+0x90,12)
assert(g:commit_owned('armor:00005678',s,catalog))
assert(commits==1 and armor_assignments==1 and read(owner+0x90,12)==mirrors)
local after=assert(g:commit_snapshot(catalog))
assert(after.controller_armor_id=='armor:00005678' and after.profile_armor_id=='armor:00005678')
assert(after.other_key==protected and after.session==s.session)
assert(not g:verify_commit(s))
''')


def test_native_commit_refuses_pending_nonarmor_stale_player_and_unowned_target():
    run_lua(SELECTION+COMMIT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
put(owner+0x64+4,b(999,4))
local s=assert(g:commit_snapshot(catalog));assert(s.pending_nonarmor)
s.pending_nonarmor=false;assert(not g:commit_owned('armor:00005678',s,catalog))
put(owner+0x64,initial_profile);s=assert(g:commit_snapshot(catalog))
catalog.owned['armor:00005678']=false;assert(not g:commit_owned('armor:00005678',s,catalog))
catalog.owned['armor:00005678']=true;put(local_player+8,b(43,4))
assert(not g:commit_owned('armor:00005678',s,catalog) and commits==0 and armor_assignments==0)
''')


def test_ownership_loss_after_ui_assignment_restores_before_any_commit_call():
    run_lua(SELECTION+COMMIT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local s=assert(g:commit_snapshot(catalog));local checks=0
catalog.verify_owned=function()checks=checks+1;return checks<3 end
local ok,why=g:commit_owned('armor:00005678',s,catalog)
assert(not ok and why:find('ownership changed') and commits==0 and armor_assignments==2)
assert(read(owner+0x64,44)==initial_profile)
''')


def test_failed_ui_assignment_is_recovered_without_claiming_native_commit():
    run_lua(SELECTION+COMMIT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready');local s=assert(g:commit_snapshot(catalog))
local ordinary=backend.write_armor;local writes=0
backend.write_armor=function(at,id)writes=writes+1;ordinary(at,id);return writes~=1 end
local ok=g:commit_owned('armor:00005678',s,catalog)
assert(not ok and commits==0 and read(owner+0x64,44)==initial_profile)
''')


def test_native_commit_requires_old_and_current_profile_readback_and_preserves_unknown_completion():
    run_lua(SELECTION+COMMIT+'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready');local s=assert(g:commit_snapshot(catalog))
backend.commit=function()commits=commits+1;return true end
local ok,why=g:commit_owned('armor:00005678',s,catalog)
assert(not ok and why:find('readback differs') and commits==1)
-- It may have enqueued native work: do not guess a rollback after invocation.
assert(read(owner+0x70,4)==b(0x5678,4))
''')


def test_cached_offer_decoding_tracks_changed_bytes_and_conflicting_duplicates():
    run_lua(SELECTION+r'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(g:snapshot(catalog).selected_kit_id=='armor:00001234')
assert(g:snapshot(catalog).selected_kit_id=='armor:00001234')
-- Same pointer/count, different mapping must immediately replace the decode.
put(progression+0xb9ce4+8,b(0x5678,4))
assert(g:snapshot(catalog).selected_kit_id=='armor:00005678')
put(progression+0xb9ce4+24+4,b(77,4))
put(progression+0xb9ce4+24+8,b(0x1234,4))
assert(not g:snapshot(catalog).identity_mapping_verified)
assert(not g:snapshot(catalog).identity_mapping_verified)
-- Shrinking the freshly read table removes the conflict.
put(progression+0x1ce0,b(1,4))
assert(g:snapshot(catalog).selected_kit_id=='armor:00005678')
''')
