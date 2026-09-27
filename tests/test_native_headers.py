"""Native header text uses current-image setters and guarded existing widgets."""
import json
from test_native_grid import run_lua
from pathlib import Path

CODE=json.loads((Path(__file__).parent/'native_header_code.json').read_text())
SETUP='\n'.join("local %s_hex='%s'"%(k,v) for k,v in CODE.items())+r'''
local function unhex(h)return(h:gsub('%x%x',function(v)return string.char(tonumber(v,16))end))end
local function code(at,h)put(base+at,unhex(h))end
code(0x10000,header_hex);code(0x12000,category_hex);code(0x14000,string_hex)
code(0x11860,param_hex);code(0x16000,template_hex)
put(base+0x10000+13,b(0x16000-(0x10000+17),4))
local real=dofile('src/debug_armory.lua')
DebugArmory={decode=function(raw,rva,n)
 if rva>=0x10000 then return real.decode(raw,rva,n)end
 return decode(raw,rva)
end}
G=dofile('src/native_grid.lua')
local top=grid-0x6d0+0x99998;local header=grid+0x83cc0+0x110
local function text_widget(at,key,count)
 put(at+0x110,b(key,4));put(at+0xf8,b(0x700000,8));put(at+0x2a8,b(0x700100,8))
 put(at+0x268,b(count,1))
end
text_widget(top,0xddc08ca8,0);text_widget(header,0x62181e42,2)
put(header+0x118,b(0x341f7711,4));put(header+0x130,b(0x15d8f2e2,4))
put(grid+0x92fc4,b(4,4));put(grid+0x928d8,b(0,4));put(grid+0x91f10,b(1,4))
local calls={}
backend.text_string=function(at,widget,key,value)
 assert(at==base+0x14000);calls[#calls+1]={widget=widget,key=key,value=value};return true
end
backend.text_template=function(at,widget,key)
 assert(at==base+0x16000);calls[#calls+1]={widget=widget,template=key}
 put(widget+0x110,b(key,4));return true
end
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
'''


def test_native_headers_and_category_restore_use_existing_widgets():
    run_lua(SETUP+r'''
assert(g:custom_headers(11,true));assert(#calls==5)
assert(calls[1].widget==top and calls[1].value=='Custom')
assert(calls[3].template==0x62181e42 and calls[4].widget==header)
assert(g:custom_headers(0,false)and #calls==6)
assert(calls[6].widget==top and calls[6].template==0xddc08ca8)
-- Scrolling past the custom header must not relabel a native group.
put(grid+0x928d8,b(4,4));assert(g:custom_headers(11,false)and #calls==6)
''')


def test_bad_header_parameters_fail_before_any_native_setter():
    run_lua(SETUP+r'''
put(header+0x130,b(0x1234,4))
assert(not g:custom_headers(11,true)and #calls==0)
''')


def test_header_changed_code_and_hidden_menu_refuse_mutation():
    run_lua(SETUP+r'''
put(grid+272+84,f(0));assert(not g:custom_headers(11,true)and #calls==0)
put(grid+272+84,f(1));put(base+0x11860+200,'X')
assert(not g:custom_headers(11,true)and #calls==0)
''')


def test_full_or_unrelated_category_parameters_refuse_insertion():
    run_lua(SETUP+r'''
put(top+0x268,b(14,1))
assert(not g:custom_headers(11,true)and #calls==0)
put(top+0x268,b(2,1));put(top+0x118,b(0x1234,4))
assert(not g:custom_headers(11,true)and #calls==0)
''')
