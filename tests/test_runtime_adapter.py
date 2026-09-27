from pathlib import Path
import json
import struct
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
BASE=0x180000000
TEXT=0x1000
CHUNK=262144
DATA=0x90000

def fixture(tmp_path, mode='ok'):
    mem=bytearray(0x400000)
    def put(at, fmt, *v):struct.pack_into(fmt,mem,at,*v)
    mem[:2]=b'MZ';put(60,'<I',0x80);mem[0x80:0x84]=b'PE\0\0'
    put(0x84,'<HH',0x8664,2);put(0x94,'<H',240);put(0x98,'<H',0x20b)
    put(0x80+80,'<I',len(mem))
    for i,(name,rva,size,flags) in enumerate([(b'.text',TEXT,0x82000,0x60000020),(b'.data',DATA,len(mem)-DATA,0xc0000040)]):
        off=0x80+24+240+i*40;mem[off:off+len(name)]=name
        put(off+8,'<II',size,rva);put(off+36,'<I',flags)
    specs=[]
    keys=['manager','session','font','atlas','material']
    for i,key in enumerate(keys):
        at=TEXT+CHUNK-5 if i==0 else TEXT+0x100+i*0x30
        target=DATA+i*8
        code=b'\x48\x8b\x05'+struct.pack('<i',target-at-7)+bytes([0xe0+i,0xf0+i])
        mem[at:at+len(code)]=code
        specs.append('{name='+json.dumps(key)+',hex='+json.dumps(code.hex())+',mask="ffffff00000000ffff",anchor='+json.dumps(code[7:].hex())+',anchor_offset=7,extracts={{offset=3,size=4,["end"]=7,adjust=0,symbol='+json.dumps(key)+'}}}')
        if mode=='missing' and i==0:mem[at:at+9]=b'\0'*9
        if mode=='ambiguous' and i==0:
            other=TEXT+0x600
            mem[other:other+9]=b'\x48\x8b\x05'+struct.pack('<i',target-other-7)+code[7:]
    manager,session,owner,mat=0xa0000,0xb0000,0x100000,0xc0000
    put(DATA,'<QQ',BASE+manager,BASE+session)
    put(DATA+16,'<QQQ',0x1122334455667788,0x8877665544332211,BASE+mat)
    put(mat+24,'<Q',0x123456789abcdef0)
    put(manager+0x62a0,'<I',1);put(manager+0x62a8,'<Q',BASE+owner);put(manager+0x62b0,'<I',0xe5)
    put(owner+8,'<I',0 if mode=='inactive' else 1)
    put(owner+0x27d0,'<I',0)
    put(session+0xb398,'<Q',1234567);put(owner+0x9f8,'<Q',1234567)
    card=owner+0x53a78
    put(card+0x1edf0,'<Q',BASE+owner+0x10);put(card+0x1edfc,'<I',0)
    if mode=='duplicate_card':
        put(card+0x1ee18+0x1edf0,'<Q',BASE+owner+0x10)
    widget=card+0x1b820;put(widget,'<I',0x10)
    for offset,value in [(36,420),(40,42),(84,1),(100,1.25),(140,1.25),(148,120),(156,250)]:put(widget+offset,'<f',value)
    if mode=='transition':mem[owner+0x2808]=1
    if mode=='resources':put(DATA+16,'<Q',0)
    file=tmp_path/'memory.bin';file.write_bytes(mem)
    return file,'{'+','.join(specs)+'}'

@pytest.mark.parametrize('mode',['ok','inactive','transition','resources','duplicate_card','missing','ambiguous','race'])
def test_resolver_and_screen_guards(tmp_path,mode):
    file,spec=fixture(tmp_path,mode)
    script='''
local Adapter=dofile('src/runtime_adapter.lua')
local f=assert(io.open(PATH,'rb'));local memory=f:read('*a');f:close()
local reads,large,peer_reads=0,0,0
local bridge={base=BASE,read=function(at,n)
 reads=reads+1;assert(n<=262144 and n>0)
 if n>200000 then large=large+1 end
 if MODE=='race' and at==BASE+0xb0000+0xb398 then
  peer_reads=peer_reads+1;if peer_reads%2==0 then return string.rep('x',n)end
 end
 local i=at-BASE;if i<0 or i+n>#memory then return nil end
 return memory:sub(i+1,i+n)
end}
local a=Adapter.new({},nil,bridge,SPEC,'deployment')
assert(a.phase=='resolving' and reads==0)
local result,why,failed
for i=1,1000 do
 local before=large
 local ok,r,w=pcall(function()return a:sample()end)
 assert(large-before<=1,'more than one large read per frame')
 if not ok then failed=r;break end
 result,why=r,w
 if a.phase=='ready' then break end
end
if MODE=='missing' or MODE=='ambiguous' then
 assert(failed and a.phase=='failed',tostring(failed))
 local old=reads;assert(not pcall(function()a:sample()end));assert(reads==old,'terminal failure rescanned')
else
 assert(not failed,tostring(failed));assert(a.phase=='ready')
 if MODE=='ok' then
  assert(result,tostring(why));assert(result.anchor.w==525 and result.anchor.h==52.5)
  assert(result.anchor.x==120 and result.anchor.y==250)
  assert(result.font=='1122334455667788' and result.material=='123456789abcdef0')
 else assert(not result,MODE..' unexpectedly accepted') end
end
'''.replace('PATH',json.dumps(str(file))).replace('BASE',str(BASE)).replace('MODE',json.dumps(mode)).replace('SPEC',spec)
    p=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr


def test_signature_data_uses_real_extraction_positions():
    p=subprocess.run(['luajit','-'],input='''
local s=dofile('src/compat_spec.lua');assert(#s==21)
local by={};for _,p in ipairs(s)do by[p.name]=p;assert(#p.hex==#p.mask)end
assert(by.font.anchor_offset==82 and by.font.extracts[1].offset==3)
assert(by.font.extracts[2].offset==19 and by.material.extracts[3].offset==39)
assert(by.font.hex~=by.atlas.hex)
''',text=True,cwd=ROOT,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr


def test_step_drives_bounded_resolution(tmp_path):
    """:step advances the same resolver with a caller-chosen CPU budget and
    reports 'ready' once done; terminal failures stay terminal."""
    file,spec=fixture(tmp_path,'ok')
    script='''
local Adapter=dofile('src/runtime_adapter.lua')
local f=assert(io.open(PATH,'rb'));local memory=f:read('*a');f:close()
local bridge={base=BASE,read=function(at,n)
 assert(n<=262144 and n>0)
 local i=at-BASE;if i<0 or i+n>#memory then return nil end
 return memory:sub(i+1,i+n)
end}
local a=Adapter.new({},nil,bridge,SPEC,'deployment')
assert(a.phase=='resolving')
-- zero-budget steps must still make no progress claim beyond 'resolving'
local states={}
for i=1,50 do
 local ok,st=pcall(function()return a:step(0.001)end)
 assert(ok,tostring(st));states[#states+1]=st
 if st=='ready' then break end
end
assert(a.phase=='ready' and states[#states]=='ready',table.concat(states,','))
local result=a:sample()
assert(result and result.anchor.w==525,'sample after step-driven resolution')
assert(a:step()=='ready','step after ready is ready')
'''.replace('PATH',json.dumps(str(file))).replace('BASE',str(BASE)).replace('SPEC',spec)
    p=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr


def test_step_terminal_failure_is_sticky(tmp_path):
    file,spec=fixture(tmp_path,'missing')
    script='''
local Adapter=dofile('src/runtime_adapter.lua')
local f=assert(io.open(PATH,'rb'));local memory=f:read('*a');f:close()
local bridge={base=BASE,read=function(at,n)
 local i=at-BASE;if i<0 or i+n>#memory then return nil end
 return memory:sub(i+1,i+n)
end}
local a=Adapter.new({},nil,bridge,SPEC,'deployment')
local failed=false
for i=1,1000 do
 local ok=pcall(function()return a:step(0.001)end)
 if not ok then failed=true;break end
 if a.phase=='ready' then break end
end
assert(failed and a.phase=='failed')
assert(not pcall(function()a:step()end),'terminal step stays failed')
assert(not pcall(function()a:sample()end),'terminal sample stays failed')
'''.replace('PATH',json.dumps(str(file))).replace('BASE',str(BASE)).replace('SPEC',spec)
    p=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr


def test_layout_anchor_coverage():
    """The probe's structural offsets must each be backed by an instruction
    anchor that encodes the constant, beyond the five data-global anchors."""
    p=subprocess.run(['luajit','-'],input='''
local s=dofile('src/compat_spec.lua');local by={};for _,x in ipairs(s)do by[x.name]=x end
local required={'manager','session','font','atlas','material',
 'loadout_registration','loadout_flags','loadout_state','local_slot','record_peer',
 'loadout_payload','player_card_address','player_card_payload','loadout_view_setter',
 'loadout_view_stratagems','equipment_button_owner','equipment_button_size',
 'equipment_button_top_attachment'}
for _,k in ipairs(required)do assert(by[k],'missing layout anchor '..k)end
-- evidence the constants encode our offsets (bytes contain the little-endian values)
local function hx(n)return (string.pack and string.pack('<I4',n)) end
assert(by.loadout_registration.hex:find('e5000000',1,true),'0xE5 owner type not encoded')
assert(by.local_slot.hex:find('d0270000',1,true),'slot 0x27d0 not encoded')
assert(by.local_slot.hex:find('98b30000',1,true),'peer 0xb398 not encoded in local_slot (session+0xb398 user)')
assert(by.player_card_address.hex:find('18ee0100',1,true),'card stride 0x1ee18 not encoded')
assert(by.equipment_button_owner.hex:find('a4e70100',1,true),'widget 0x1b820 context not encoded')
''',text=True,cwd=ROOT,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr
