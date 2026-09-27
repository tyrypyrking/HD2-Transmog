import json
import struct
import subprocess
import pytest
from test_runtime_adapter import fixture,ROOT,BASE,TEXT,DATA

@pytest.mark.parametrize('mode',['visible','other_menu','stack_mismatch','hidden_grid','ambiguous','bad_count'])
def test_armory_identity_requires_menu_dispatch_and_visible_grid(tmp_path,mode):
    path,spec=fixture(tmp_path)
    mem=bytearray(path.read_bytes())
    def put(at,fmt,*v):struct.pack_into(fmt,mem,at,*v)
    at=TEXT+0x900;target=DATA+40
    code=b'\x48\x8b\x05'+struct.pack('<i',target-at-7)+b'\xe9\xf9'
    mem[at:at+9]=code
    pattern='{name="armory_menu",hex='+json.dumps(code.hex())+',mask="ffffff00000000ffff",anchor="e9f9",anchor_offset=7,extracts={{offset=3,size=4,["end"]=7,adjust=0,symbol="armory_menu"}}}'
    spec=spec[:-1]+','+pattern+'}'
    menu,manager,controller=0xd0000,0xa0000,0x100000
    put(target,'<Q',BASE+menu)
    put(menu+0x4294,'<I',14 if mode=='other_menu' else 5)
    put(menu+0x429c,'<I',14 if mode=='stack_mismatch' else 5)
    put(menu+0x429c+20,'<I',1)
    put(manager+5740,'<I',65 if mode=='bad_count' else 2 if mode=='ambiguous' else 1)
    put(manager+5744,'<QI',BASE+controller,224)
    if mode=='ambiguous':put(manager+5744+16,'<QI',BASE+controller+0x100,224)
    bar=controller+523752+272
    for offset,value in [(12,12),(16,800),(84,0 if mode=='hidden_grid' else 1),(100,1),(140,1),(148,1100),(156,100)]:put(bar+offset,'<f',value)
    path.write_bytes(mem)
    script='''
local A=dofile('src/runtime_adapter.lua')
local f=assert(io.open(PATH,'rb'));local m=f:read('*a');f:close()
local a=A.new({},nil,{base=BASE,read=function(at,n)
 local i=at-BASE;if i<0 or i+n>#m then return nil end;return m:sub(i+1,i+n)
end},SPEC)
local value,why
for i=1,1000 do value,why=a:sample();if a.phase=='ready' then break end end
assert(a.phase=='ready')
if MODE=='visible' then assert(value and value.kind=='armory',tostring(why));assert(value.anchor.x==1100)
else assert(not value,'accepted '..MODE)end
'''.replace('PATH',json.dumps(str(path))).replace('BASE',str(BASE)).replace('SPEC',spec).replace('MODE',json.dumps(mode))
    p=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True)
    assert p.returncode==0,p.stdout+p.stderr
