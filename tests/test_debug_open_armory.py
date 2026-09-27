"""Native opener graph/guard tests. The backend never invokes game functions."""
import json
import struct
import subprocess

import pytest

from test_runtime_adapter import BASE, DATA, ROOT, TEXT, fixture


@pytest.mark.parametrize("mode",["valid","scene","menu","proof","changed_code","changed_table","wrong_callback","wrong_kind","missing","ambiguous"])
def test_dynamic_open_path_and_last_moment_guards(tmp_path,mode):
    path,_=fixture(tmp_path)
    memory=bytearray(path.read_bytes());slot=DATA+40;manager=DATA;menu=0xD0000
    push,dispatch,top_case,factory,entering,gui_dispatch,gui_case,on_enter,register=0x3000,0x4000,0x4800,0x5000,0x5800,0x6000,0x6800,0x7000,0x7800
    for at,target in [(0x2000,push)]+([(0x2100,0x3400)]if mode=="ambiguous"else[]):
        code=b"\x48\x8b\x0d"+struct.pack("<i",slot-at-7)+b"\x48\x81\xc1\x88\x42\0\0\xe9"+struct.pack("<i",target-at-19)+b"\xcc"
        memory[at:at+len(code)]=code if mode!="missing"else b"\0"*len(code)
    struct.pack_into("<Q",memory,slot,BASE+menu)
    for at,target,count in [(DATA+0x1000,top_case,52),(DATA+0x2000,gui_case,34)]:
        for index in range(count):struct.pack_into("<I",memory,at+index*4,target)
    sequences={
        push:["mov [rsp+0x18], r8","movsxd rdi, edx","mov [rsi+rax*4+0x14], edi","inc dword [rsi+0x28]","mov [rsi+0xc], edi","mov r8, [rsp+0x90]","mov edx, edi","mov rcx, r12",f"call 0x{dispatch:08x}"],
        top_case:["mov rcx, [rip+0x123]","mov r8, rdi","mov edx, 0x2",f"jmp 0x{factory:08x}"],
        factory:["mov rsi, r8","mov edi, edx","mov [rbx], edi","mov r8, rsi","mov rdx, rbx","mov rcx, rbx",f"call 0x{entering:08x}"],
        entering:["mov r12, r8","mov r8, r12","mov rdx, r13","mov r9d, [r15]","mov rcx, r15",f"call 0x{gui_dispatch:08x}"],
        gui_case:["mov rcx, [rdi+0x60]","mov rdx, r15"if mode!="wrong_callback"else"mov rdx, rsi",f"call 0x{on_enter:08x}","jmp 0x00008000"],
        on_enter:["mov r13, rcx","mov [rcx+0x28], rdx","mov r8b, 0x1","mov rcx, r13",f"call 0x{register:08x}","int3"],
        register:[f"mov rdx, [rip+0x{manager-register-4:x}]","mov dword [rsp+0x48], 0xe0"if mode!="wrong_kind"else"mov dword [rsp+0x48], 0xe1","mov eax, [rdx+0x166c]","inc dword [rdx+0x166c]","add rax, 0x167"],
    }
    for at,table,count,prefix in [(dispatch,DATA+0x1000,52,["movsxd rbx, edx","mov rdi, r8"]),(gui_dispatch,DATA+0x2000,34,["mov ebx, r9d","mov rsi, r8"])]:
        sequences[at]=prefix+[f"lea r14, [rip-0x{at+12:x}]","dec ebx",f"cmp ebx, +0x{count-1:x}",f"mov ecx, [r14+rbx*4+0x{table:x}]","add rcx, r14","jmp rcx"]
    if mode=="ambiguous":sequences[0x3400]=sequences[push]
    if mode=="menu":struct.pack_into("<I",memory,menu+0x4294,5)
    path.write_bytes(memory)
    rows="{"+",".join(f"[{at}]="+"{"+",".join("{rva="+str(at+i*4)+",op="+json.dumps(op)+"}"for i,op in enumerate(ops))+"}"for at,ops in sequences.items())+"}"
    script=f"""
local reference={rows}
DebugArmory={{decode=function(code,rva)return reference[rva]or {{}}end}}
local M=dofile('src/debug_open_armory.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local memory=f:read('*a');f:close()
local large,proof,calls=0,true,0
local bridge={{base={BASE},menu_global={BASE+slot},manager_global={BASE+manager},verify=function()return proof end,
 read=function(at,n)
  if n>200000 then large=large+1 end
  local offset=at-{BASE};if offset<0 or offset+n>#memory then return nil end
  return memory:sub(offset+1,offset+n)
 end}}
local opener=M.new(bridge,function()return {json.dumps(mode)}~='scene'end,nil,{{invoke=function(at,object,screen)
 assert(at=={BASE+push} and object=={BASE+menu+0x4288} and screen==5);calls=calls+1
end}})
local phase,why
for i=1,1000 do
 local before=large;phase,why=opener:step();assert(large-before<=1,'unbounded code scan')
 if phase~='resolving'then break end
end
if {json.dumps(mode)}=='wrong_callback'or {json.dumps(mode)}=='wrong_kind'or {json.dumps(mode)}=='missing'or {json.dumps(mode)}=='ambiguous'then
 assert(phase=='failed',tostring(why));assert(not opener:open());assert(calls==0)
else
 assert(phase=='ready',tostring(why))
 if {json.dumps(mode)}=='proof'then proof=false end
 if {json.dumps(mode)}=='changed_code'then local at={push};memory=memory:sub(1,at)..'x'..memory:sub(at+2)end
 if {json.dumps(mode)}=='changed_table'then local at={DATA+0x1000};memory=memory:sub(1,at)..'x'..memory:sub(at+2)end
 local ok,message=opener:open()
 if {json.dumps(mode)}=='valid'then assert(ok,message);assert(calls==1)
 else assert(not ok,'guard accepted '..{json.dumps(mode)});assert(calls==0)end
 if {json.dumps(mode)}=='proof'or {json.dumps(mode)}=='changed_code'or {json.dumps(mode)}=='changed_table'then
  assert(opener.phase=='failed','changed call proof is not terminal');assert(not opener:open());assert(calls==0)
 end
end
"""
    process=subprocess.run(["luajit","-"],input=script,cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert process.returncode==0,process.stdout+process.stderr
