import json
import struct
import subprocess

import pytest
from test_runtime_adapter import BASE, CHUNK, DATA, ROOT, TEXT, fixture


@pytest.mark.parametrize("changed",[False,True])
def test_armor_reference_probe_is_bounded_read_only_and_describes_float_operands(tmp_path,changed):
    path,_=fixture(tmp_path)
    memory=bytearray(path.read_bytes());at=TEXT+CHUNK-3;slot=DATA+40;constant=DATA+0x100;callee=TEXT+0x71000
    code=b"\x48\x8b\x0d"+struct.pack("<i",slot-at-7)
    code+=b"\xf3\x0f\x10\x05"+struct.pack("<i",constant-at-15)
    code+=b"\xe8"+struct.pack("<i",callee-at-20)+b"\xc3"
    memory[at:at+len(code)]=code;memory[callee]=0xC3
    struct.pack_into("<f",memory,constant,50)
    path.write_bytes(memory)
    script=f"""
local M=dofile('src/native_armor_probe.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local bytes=f:read('*a');f:close()
local large,reads,proof=0,0,true
local p=M.new({{base={BASE},armor_catalog={BASE+slot},verify=function()return proof end,read=function(at,n)
 reads=reads+1;if n>200000 then large=large+1 end
 local offset=at-{BASE};if offset<0 or offset+n>#bytes then return nil end
 return bytes:sub(offset+1,offset+n)
end}})
local state
for i=1,1000 do
 local before=large;state=p:step();assert(large-before<=1)
 if {str(changed).lower()} then proof=false end
 if state~='resolving'then break end
end
local text=p:summary()
if {str(changed).lower()} then
 assert(state=='failed');local before=reads;p:step();assert(reads==before)
else
 assert(state=='ready',text);assert(text:find('xref_count=1',1,true),text)
 assert(text:find('constant_f32=50',1,true),text)
 assert(text:find('callee=0x00072000',1,true),text)
 assert(not text:find('488b0d',1,true),'raw memory bytes exported')
end
"""
    process=subprocess.run(["luajit","-"],input=script,text=True,cwd=ROOT,capture_output=True,timeout=10)
    assert process.returncode==0,process.stdout+process.stderr


def test_combined_equipment_display_tables_require_image_base_and_slot_filters(tmp_path):
    path,_=fixture(tmp_path)
    memory=bytearray(path.read_bytes());at=TEXT+0x200;slot=DATA+40;table=DATA+0x100
    code=b'\x4c\x8b\x3d'+struct.pack('<i',slot-at-7)
    code+=b'\x83\x78\x0c\0\x83\x78\x08\0\xa9\xf8\xff\xff\xff\x83\xfa\x03'
    code+=b'\x4c\x8d\x1d'+struct.pack('<i',-at-len(code)-7)
    code+=b'\xf3\x41\x0f\x10\x84\x8b'+struct.pack('<I',table)+b'\xc3'
    memory[at:at+len(code)]=code;struct.pack_into('<ffff',memory,table,50,100,150,0)
    path.write_bytes(memory)
    script=f"""
local M=dofile('src/native_armor_probe.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local bytes=f:read('*a');f:close()
local p=M.new({{base={BASE},armor_catalog={BASE+slot},verify=function()return true end,
 read=function(at,n)local offset=at-{BASE};return bytes:sub(offset+1,offset+n)end}})
for i=1,1000 do if p:step()~='resolving'then break end end
local text=p:summary();assert(p.phase=='ready',text)
assert(text:find('values=50,100,150,0',1,true),text)
assert(text:find('body_slots=2,4,5,6,7,8,9 weight_none_excluded=false',1,true),text)
"""
    process=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=10)
    assert process.returncode==0,process.stdout+process.stderr
