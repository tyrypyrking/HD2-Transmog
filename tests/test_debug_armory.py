import json
import struct
import subprocess

import pytest

from test_runtime_adapter import BASE, CHUNK, DATA, ROOT, TEXT, fixture


@pytest.mark.parametrize("mode",["valid","proof_changed","no_xrefs","branches","leaf_wrapper"])
def test_semantic_probe_finds_boundary_xrefs_without_raw_output_or_calls(tmp_path,mode):
    path,_=fixture(tmp_path)
    memory=bytearray(path.read_bytes())
    menu=DATA+40;target=TEXT+0x78000
    # Boundary-spanning MOV, then actual argument and direct-call instructions.
    for at in [TEXT+CHUNK-3,TEXT+0x800]:
        code=b"\x48\x8b\x0d"+struct.pack("<i",menu-at-7)+b"\x48\x81\xc1\x88\x42\0\0"+b"\xba\x0c\0\0\0"
        code+=b"\xe8"+struct.pack("<i",target-at-24)+b"\xc3"
        memory[at:at+len(code)]=code if mode!="no_xrefs" else b"\0"*len(code)
    memory[target:target+6]=b"\xb8\x05\0\0\0\xc3"
    if mode in ("branches","leaf_wrapper"):
        # Exception metadata is allowed in an executable-readable section too
        # (the current game's packer puts .pdata inside .winlice).
        pdata=TEXT+0x79000
        caller=TEXT+0x500
        wrapper=TEXT+0x800
        callsite=caller+12
        code=b"\x48\x83\xec\x28\xba\x05\0\0\0\x45\x31\xc0"
        code+=b"\xe8"+struct.pack("<i",wrapper-callsite-5)+b"\x48\x83\xc4\x28\xc3"
        memory[caller:caller+len(code)]=code
        fake=TEXT+0x600
        fakecode=b"\xb8\xe8"+struct.pack("<i",wrapper-fake-6)+b"\xc3"
        memory[fake:fake+len(fakecode)]=fakecode
        entries=[(caller,caller+len(code)),(fake,fake+len(fakecode)),
                 (TEXT+CHUNK-3,TEXT+CHUNK+22),(target,target+6)]
        if mode=="leaf_wrapper":
            thunk=b"\x48\x8b\x0d"+struct.pack("<i",menu-wrapper-7)+b"\x48\x81\xc1\x88\x42\0\0"
            thunk+=b"\xe9"+struct.pack("<i",target-wrapper-19)+b"\xcc"
            memory[wrapper:wrapper+len(thunk)]=thunk
        else:entries.append((wrapper,wrapper+25))
        entries.sort()
        for i,(start,end) in enumerate(entries):struct.pack_into("<III",memory,pdata+i*12,start,end,0)
        struct.pack_into("<I",memory,0x80+24+108,16)
        struct.pack_into("<II",memory,0x80+24+136,pdata,len(entries)*12)
    path.write_bytes(memory)
    script=f"""
local D=dofile('src/debug_armory.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local memory=f:read('*a');f:close()
local large,proof,calls=0,true,0
local bridge={{base={BASE},menu_global={BASE+menu},verify=function()return proof end,
 read=function(at,n)
  calls=calls+1;assert(n<=262144)
  if n>200000 then large=large+1 end
  local offset=at-{BASE};if offset<0 or offset+n>#memory then return nil end
  return memory:sub(offset+1,offset+n)
 end}}
local observer=D.new(bridge)
local phase
for i=1,1000 do
 local before=large;phase=observer:step();assert(large-before<=1,'more than one code chunk per step')
 if {json.dumps(mode)}=='proof_changed'then proof=false end
 if phase~='resolving'then break end
end
local summary=observer:summary()
assert(summary:find('opens_armory=false',1,true))
assert(not summary:find('488b0d',1,true),'raw bytes leaked')
assert(not summary:find(tostring({BASE}),1,true),'absolute base leaked')
if {json.dumps(mode)}=='proof_changed'then
 assert(phase=='failed');local old=calls;observer:step();assert(calls==old)
elseif {json.dumps(mode)}=='no_xrefs'then
 assert(phase=='ready');assert(summary:find('xref_count=0',1,true))
else
 assert(phase=='ready',summary);assert(summary:find('xref_count=2',1,true),summary)
 assert(summary:find('direct_call_targets=1',1,true),summary)
 assert(summary:find('mov edx, 0xc',1,true),summary)
 assert(summary:find('mov eax, 0x5',1,true),summary)
 if {json.dumps(mode)}=='branches'or {json.dumps(mode)}=='leaf_wrapper'then
  assert(summary:find('branch=0x0000150c',1,true),summary)
  assert(not summary:find('branch=0x00001601',1,true),'immediate byte falsely accepted as call')
  assert(summary:find('mov edx, 0x5',1,true),summary)
  local text,why=D.inspect_code(bridge,0x150c,64);assert(text,why)
  assert(text:find('mov edx, 0x5',1,true),text)
  assert(not D.inspect_code(bridge,0x1601,64),'inspection accepted an immediate byte')
  assert(not D.inspect_code(bridge,{DATA},64),'inspection accepted data')
 end
end
"""
    process=subprocess.run(["luajit","-"],input=script,cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert process.returncode==0,process.stdout+process.stderr


@pytest.mark.parametrize("mutation",["valid","wrong_count","wrong_target","missing_proof"])
def test_switch_tables_require_instruction_proof_and_emit_only_targets(tmp_path,mutation):
    path,_=fixture(tmp_path)
    memory=bytearray(path.read_bytes());start=TEXT+0x800;table=TEXT+0x840;destination=TEXT+0x880;pdata=DATA+0x1000
    code=b"\x4c\x8d\x35"+struct.pack("<i",-start-7)+b"\x8b\xda\xff\xcb\x83\xfb\x04\x77\x00"
    code+=b"\x41\x8b\x8c\x9e"+struct.pack("<I",table)+b"\x4c\x01\xf1\xff\xe1"
    memory[start:start+len(code)]=code
    memory[destination]=0xC3
    for i in range(5):struct.pack_into("<I",memory,table+i*4,destination)
    struct.pack_into("<I",memory,0x80+24+108,16)
    struct.pack_into("<II",memory,0x80+24+136,pdata,24)
    struct.pack_into("<III",memory,pdata,start,table+20,0)
    struct.pack_into("<III",memory,pdata+12,destination,destination+1,0)
    if mutation=="wrong_target":struct.pack_into("<I",memory,table,DATA)
    if mutation=="missing_proof":memory[start+12]=0
    path.write_bytes(memory)
    count=4 if mutation=="wrong_count"else 5
    script=f"""
local D=dofile('src/debug_armory.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local memory=f:read('*a');f:close()
local bridge={{base={BASE},verify=function()return true end,read=function(at,n)
 local offset=at-{BASE};if offset<0 or offset+n>#memory then return nil end
 return memory:sub(offset+1,offset+n)
end}}
local text,why=D.inspect_switch(bridge,{table},{count})
if {json.dumps(mutation)}=='valid'then
 assert(text,why);assert(text:find('selector=5 target=0x00001880',1,true),text)
 assert(not text:find('418b8c9e',1,true),'raw bytes exported')
else assert(not text,'invalid switch accepted')end
"""
    process=subprocess.run(["luajit","-"],input=script,cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert process.returncode==0,process.stdout+process.stderr
