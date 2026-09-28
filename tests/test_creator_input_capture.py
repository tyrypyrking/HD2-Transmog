"""Creator navigation consumes proved menu actions without touching equipment."""
from test_native_grid import SELECTION, HIGHLIGHT, run_lua
from test_native_preview import PREVIEW
from test_native_variant_details import DETAILS
from test_native_equipment_feedback import FEEDBACK

FIXTURE = SELECTION+HIGHLIGHT+PREVIEW+DETAILS+FEEDBACK+r'''
local directory,direction=0x50400,0x27000
put(base+0x80+24+108,b(16,4))
put(base+0x80+24+112+24,b(directory,4)..b(36,4))
put(base+directory,b(0x24000,4)..b(0x25000,4)..b(0,4)
 ..b(direction,4)..b(direction+256,4)..b(0,4)
 ..b(0x29000,4)..b(0x29100,4)..b(0,4))
local decode_creator=DebugArmory.decode
local ambiguous=false
DebugArmory.decode=function(raw,rva,budget)
 if rva==direction then
  local out={}
  for i,id in ipairs({4,8,3,7,1,5,2,6})do
   out[#out+1]={rva=rva+i*20,op=string.format('mov rcx, 0x%08x00000000',id)}
   out[#out+1]={rva=rva+i*20+10,op='cmp byte [r9+rbx+0x328], 0x0'}
  end
  return out
 end
 local rows=decode_creator(raw,rva,budget)
 if rva==input_rva then
  rows[#rows+1]={rva=rva+100,op='mov rsi, rdx'}
  rows[#rows+1]={rva=rva+101,op='mov rcx, rsi'}
  rows[#rows+1]={rva=rva+104,op=string.format('call 0x%x',direction)}
  if ambiguous then
   rows[#rows+1]={rva=rva+110,op='mov rcx, rsi'}
   rows[#rows+1]={rva=rva+114,op=string.format('call 0x%x',direction+100)}
  end
 end
 return rows
end
put(grid-0x6d0+0x178c88+12,b(0,4))
local actions={}
backend.consume=function(at,object,action)
 assert(at==base+0x5000 and object==input);actions[#actions+1]=action or 10;return true
end
'''


def test_creator_capture_resolves_direction_actions_and_suppresses_native_menu_controls():
    run_lua(FIXTURE+r'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local ok,why=g:consume_creator();assert(ok,why)
local seen={};for _,id in ipairs(actions)do assert(not seen[id]);seen[id]=true end
for _,id in ipairs({1,2,3,4,5,6,7,8,10,11,12,18,19})do assert(seen[id])end
assert(#actions==13 and moves==0)
put(base+direction,'X')
assert(not g:consume_creator()and #actions==13,'changed direction code still consumed input')
''')


def test_unknown_direction_reader_does_not_disable_mouse_select_or_consume_unproved_actions():
    run_lua(FIXTURE+r'''
ambiguous=true
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(not g:consume_creator()and #actions==0)
assert(g:consume_select()and #actions==1 and actions[1]==10)
''')


def test_creator_does_not_capture_a_different_native_menu():
    run_lua(FIXTURE+r'''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
put(menu+0x4294,b(0,4))
assert(not g:consume_creator()and #actions==0)
''')


def test_direction_action_ids_are_parsed_without_64_bit_tonumber_conversion():
    run_lua(FIXTURE+r'''
local number=tonumber
tonumber=function(value,radix)
 if radix==16 and type(value)=='string'and #value>8 then return 0 end
 return number(value,radix)
end
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(g:consume_creator()and #actions==13)
''')
