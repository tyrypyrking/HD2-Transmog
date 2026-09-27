"""Catalog bridge only exposes currently proven signature-derived globals."""
import json
import struct
import subprocess

import pytest

from test_runtime_adapter import BASE, DATA, ROOT, TEXT, fixture


@pytest.mark.parametrize("mode",["valid","missing","conflicting","proof_changed","optional_missing","optional_ambiguous"])
def test_catalog_bridge_requires_completed_consistent_current_proofs(tmp_path,mode):
    path,spec=fixture(tmp_path)
    memory=bytearray(path.read_bytes())
    locations={"armor_catalog":DATA+40,"progression":DATA+48,"engine_root":DATA+56}
    patterns=[]
    last_at=None
    for index,symbol in enumerate(["armor_catalog","progression","engine_root","armor_catalog"]):
        at=TEXT+0xA00+index*0x40
        target=locations[symbol]+(8 if mode=="conflicting" and index==3 else 0)
        code=b"\x48\x8b\x05"+struct.pack("<i",target-at-7)+bytes([0xC0+index,0xD0+index])
        memory[at:at+len(code)]=code
        patterns.append('{name="catalog'+str(index)+'",hex='+json.dumps(code.hex())+
                        ',optional='+('true' if symbol=='engine_root' else 'false')+
                        ',mask="ffffff00000000ffff",anchor='+json.dumps(code[7:].hex())+
                        ',anchor_offset=7,extracts={{offset=3,size=4,["end"]=7,adjust=0,symbol='+json.dumps(symbol)+'}}}')
        last_at=at
        if mode=="missing" and index==0:memory[at:at+len(code)]=b"\0"*len(code)
        if mode=="optional_missing" and symbol=="engine_root":memory[at:at+len(code)]=b"\0"*len(code)
        if mode=="optional_ambiguous" and symbol=="engine_root":
            memory[at+0x400:at+0x400+len(code)]=code
    spec=spec[:-1]+","+",".join(patterns)+"}"
    path.write_bytes(memory)
    script=f"""
local Adapter=dofile('src/runtime_adapter.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local memory=f:read('*a');f:close()
local reads,large=0,0
local input={{base={BASE},read=function(at,n)
 reads=reads+1;if n>200000 then large=large+1 end
 local offset=at-{BASE};if offset<0 or offset+n>#memory then return nil end
 return memory:sub(offset+1,offset+n)
end}}
local optional_events=0
local adapter=Adapter.new({{}},function(key,value)
 if key=='adapter.optional_unavailable' then assert(value=='catalog2');optional_events=optional_events+1 end
end,input,{spec},'catalog')
assert(not pcall(function()return adapter:data_bridge()end),'bridge exposed before resolution')
local failed
for i=1,1000 do
 local before=large;local ok,why=pcall(function()return adapter:step()end)
 assert(large-before<=1,'unbounded catalog resolver frame')
 if not ok then failed=why;break end
 if adapter.phase=='ready'then break end
end
if {json.dumps(mode)}=='missing' or {json.dumps(mode)}=='conflicting'then
 assert(failed and adapter.phase=='failed')
 assert(not pcall(function()return adapter:data_bridge()end))
 local before=reads;assert(not pcall(function()return adapter:step()end));assert(reads==before)
else
 assert(not failed,tostring(failed));local bridge=adapter:data_bridge()
 assert(bridge.armor_catalog=={BASE+locations['armor_catalog']})
 assert(bridge.progression=={BASE+locations['progression']})
 if {json.dumps(mode)}=='optional_missing' or {json.dumps(mode)}=='optional_ambiguous'then
  assert(bridge.engine_root==nil and optional_events==1,'optional localization must be absent, never guessed')
  local lookup,why=dofile('src/localization.lua').bind(bridge,{{
   executable=function()error('unverified localization was probed')end,
   lookup=function()error('unverified localization was called')end,
  }})
  assert(lookup==nil and why=='localization signature unavailable')
 else assert(bridge.engine_root=={BASE+locations['engine_root']} and optional_events==0)end
 assert(bridge.verify())
 assert(bridge.write==nil,'read-only bridge exposed writer')
 if {json.dumps(mode)}=='proof_changed'then
  local at={last_at};memory=memory:sub(1,at)..string.char(0)..memory:sub(at+2)
  assert(not bridge.verify(),'old bridge accepts changed code')
  assert(not pcall(function()return adapter:data_bridge()end),'new bridge accepts changed code')
 end
end
"""
    process=subprocess.run(["luajit","-"],input=script,cwd=ROOT,text=True,capture_output=True,timeout=10)
    assert process.returncode==0,process.stdout+process.stderr


def test_localization_and_local_player_are_optional_in_generated_catalog_contract():
    script = '''
local spec=dofile('src/catalog_compat.lua')
local optional=0
local expected={extra_localized_text='engine_root',loadout_state='players'}
for _,pattern in ipairs(spec)do
 if pattern.optional then
  optional=optional+1
  assert(expected[pattern.name])
  assert(#pattern.extracts==1 and pattern.extracts[1].symbol==expected[pattern.name])
  expected[pattern.name]=nil
 else assert(pattern.name~='extra_localized_text'and pattern.name~='loadout_state')end
end
assert(optional==2 and next(expected)==nil)
'''
    process = subprocess.run(['luajit','-'], input=script, cwd=ROOT,
                             text=True, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stdout + process.stderr
