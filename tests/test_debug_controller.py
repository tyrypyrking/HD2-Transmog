"""Bounded controller metadata observation without calling a native method."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run_lua(code):
    result = subprocess.run(['luajit', '-'], input=code, text=True, cwd=ROOT,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


FIXTURE = '''
local D=dofile('src/debug_controller.lua')
local memory={}
local function bytes(n,size)
 local out={};for i=1,size do out[i]=string.char(n%256);n=math.floor(n/256)end
 return table.concat(out)
end
local function put(at,s)for i=1,#s do memory[at+i-1]=s:sub(i,i)end end
local function get(at,n)
 local out={};for i=1,n do if not memory[at+i-1]then return nil end;out[i]=memory[at+i-1]end
 return table.concat(out)
end
local base,manager,menu,controller=0x100000,0x300000,0x400000,0x500000
put(base,string.rep('\\0',0x9000))
put(base,'MZ');put(base+60,bytes(0x80,4))
put(base+0x80,'PE\\0\\0');put(base+0x84,bytes(0x8664,2));put(base+0x86,bytes(3,2))
put(base+0x94,bytes(240,2));put(base+0x98,bytes(0x20b,2));put(base+0xd0,bytes(0x9000,4))
put(base+0x98+108,bytes(16,4));put(base+0x98+136,bytes(0x4000,4));put(base+0x98+140,bytes(12,4))
local section=base+0x80+24+240
for i,s in ipairs({{0x1000,0x1000,0x60000020},{0x3000,0x1000,0x40000040},{0x4000,0x1000,0x40000040}})do
 local at=section+(i-1)*40;put(at+8,bytes(s[2],4));put(at+12,bytes(s[1],4));put(at+36,bytes(s[3],4))
end
put(base+0x4000,bytes(0x1000,4)..bytes(0x1100,4)..bytes(0x4100,4))
put(base+0x3500,bytes(manager,8));put(base+0x3508,bytes(menu,8))
put(manager+0x166c,bytes(1,4));put(manager+0x1670,bytes(controller,8)..bytes(224,4)..bytes(0,4))
put(controller,bytes(base+0x3100,8)..bytes(1,4)..bytes(0,4))
put(menu,string.rep('\\0',512));put(menu+0x68,bytes(controller,8))
put(menu+0x4288,string.rep('\\0',44))
put(menu+0x4294,bytes(5,4));put(menu+0x429c,bytes(5,4));put(menu+0x42b0,bytes(1,4))
put(base+0x3100,bytes(base+0x1000,8)..bytes(base+0x1080,8)..bytes(base+0x1200,8)..bytes(0,8))
local calls=0
local bridge={base=base,read=get,manager_global=base+0x3500,menu_global=base+0x3508,
 verify=function()return true end,decode=function(code,rva)
  calls=calls+1;assert(#code==256 and rva==0x1000);return {{rva=rva,op='ret'}}
 end}
'''


def test_candidate_vtable_slots_use_function_extents_without_exporting_bytes():
    run_lua(FIXTURE + '''
local result=assert(D.inspect(bridge))
assert(result.vtable_rva==0x3100 and result.menu_owner_offsets[1]==0x68)
assert(result.controller_u32_at_8==1 and #result.slots==3)
assert(result.menu_current==5 and result.menu_stack_depth==1 and result.menu_stack_top==5)
assert(result.slots[1].slot==0 and result.slots[1].rva==0x1000)
assert(result.slots[1].function_start==0x1000 and result.slots[1].function_size==256)
assert(result.slots[2].function_start==0x1000)
assert(result.slots[3].function_start==nil and result.slots[3].instructions==nil)
assert(result.reads<2048 and result.bytes_read<65536 and calls==2)
assert(result.bytes==nil and result.controller==nil)
local text=D.format(result)
assert(text:find('slot=0 target_rva=0x1000',1,true))
assert(text:find('00001000 ret',1,true))
assert(not text:find('SOURCEPK',1,true))
''')


def test_non_vtable_header_is_not_guessed_to_be_callable():
    run_lua(FIXTURE + '''
put(controller,bytes(5,8))
local result=assert(D.inspect(bridge))
assert(#result.slots==0 and result.vtable_rva==nil and calls==0)
assert(result.menu_owner_offsets[1]==0x68)
    ''')


def test_menu_state_available_before_armory_controller_is_registered():
    run_lua(FIXTURE + '''
put(manager+0x1678,bytes(225,4))
local result=assert(D.inspect(bridge))
assert(result.status=='Armory controller is not registered')
assert(result.menu_current==5 and result.menu_stack_top==5 and #result.slots==0)
''')


def test_registry_races_ambiguity_and_invalid_exception_ranges_fail_closed():
    run_lua(FIXTURE + '''
local reads=0
bridge.read=function(at,n)
 if at==manager+0x1670 then
  reads=reads+1
  if reads==2 then return string.rep('\\0',n)end
 end
 return get(at,n)
end
local result,why=D.inspect(bridge);assert(not result and why:find('changed'))
bridge.read=get
put(manager+0x166c,bytes(2,4));put(manager+0x1680,bytes(controller,8)..bytes(224,4)..bytes(0,4))
result,why=D.inspect(bridge);assert(not result and why:find('ambiguous'))
put(manager+0x166c,bytes(1,4));put(base+0x98+140,bytes(2400012,4))
result=assert(D.inspect(bridge))
assert(result.function_metadata:find('unavailable') and #result.slots==3)
assert(result.slots[1].function_start==nil)
''')


def test_readable_executable_exception_table_is_valid_for_packed_images():
    run_lua(FIXTURE + '''
put(section+2*40+36,bytes(0x60000040,4))
local result=assert(D.inspect(bridge))
assert(result.function_metadata=='sampled readable function table')
assert(result.slots[1].function_start==0x1000 and result.slots[1].function_size==256)
''')


def test_unsorted_exception_metadata_degrades_without_hiding_vtable_inventory():
    run_lua(FIXTURE + '''
put(base+0x98+140,bytes(24,4))
put(base+0x4000,bytes(0x1100,4)..bytes(0x1200,4)..bytes(0x4100,4))
put(base+0x400c,bytes(0x1000,4)..bytes(0x1100,4)..bytes(0x4100,4))
local result=assert(D.inspect(bridge))
assert(result.function_metadata:find('unsorted'))
assert(#result.slots==3 and result.slots[1].function_start==nil and calls==0)
''')
