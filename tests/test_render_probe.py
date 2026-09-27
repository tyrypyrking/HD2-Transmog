from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def test_material_probe_is_read_only_bounded_and_does_not_publish_handles():
    script=r'''
local P=dofile('src/render_probe.lua')
local ffi=require('ffi')
local function qword(n)local x=ffi.new('uint64_t[1]',n);return ffi.string(x,8)end
local resource='1234567890abcdef'
local raw='\239\205\171\144\120\86\52\18'
local payload=qword(131072)..string.rep('\0',24)
local material=string.rep('\0',24)..raw..string.rep('\0',96)
local reads,changed,proof=0,false,true
local engine={Material={id64=function()return resource end},IdString64={to_hex=function(x)return x end}}
local bridge={verify=function()return proof end,read=function(at,n)
 reads=reads+1;assert(n<=128)
 if at==65536 then return changed and string.rep('\0',32)or payload end
 if at==131072 then if changed then return string.rep('\0',128)end;return material end
end}
local result=assert(P.inspect(engine,{},bridge,function()return 65536 end))
assert(#result.candidates==1)
assert(result.candidates[1].payload_offset==0 and result.candidates[1].resource_offset==24)
local output=P.format(result)
assert(not output:find('131072',1,true)and not output:find('65536',1,true))
assert(output:find('raw_pointer_bitmap_supported=false',1,true))
assert(reads<=10)
proof=false;reads=0;assert(not P.inspect(engine,{},bridge,function()return 65536 end));assert(reads==0)
proof=true;local old=bridge.read;local count=0
bridge.read=function(at,n)
 count=count+1;if count==3 then changed=true end
 return old(at,n)
end
local rejected,why=P.inspect(engine,{},bridge,function()return 65536 end)
assert(not rejected and why:find('changed during inspection',1,true))
'''
    result=subprocess.run(['luajit','-'],input=script,text=True,capture_output=True,cwd=ROOT)
    assert result.returncode==0,result.stdout+result.stderr
