"""Real NativeGrid presentation bridge with isolated PE/memory/constructor fakes."""
from test_native_grid import run_lua, SELECTION, HIGHLIGHT
from test_native_grid_model import LOGICAL_PROOF

BUILDERS=r'''
local clear_rva,append_rva,finish_rva=0x1c000,0x1d000,0x1e000
local specs={
 [clear_rva]='48895c241048896c24184889742420574883ec70488bf9',
 [append_rva]='534883ec20448b9984290900',
 [finish_rva]='48895c2410574883ec30488bd90f297c24208b89141f09008bd181f900010000'}
for at,hex in pairs(specs)do put(base+at,unhex(hex))end
local old_decode=DebugArmory.decode
local builder_ops={
 [clear_rva]={'mov rdi, rcx','mov esi, 0x6','mov ecx, 0x100','mov [rdi+0x91f14], ebp',
  'mov [rdi+0x92748], ebp','mov [rdi+0x92960], rbp','mov [rdi+0x92968], ebp',
  'mov [rdi+0x92984], rbp','mov [rdi+0x9298c], ebp','lea rcx, [rdi+0x9274c]',
  'mov r8d, 0x18c','mov r8d, 0x400','ret'},
 [append_rva]={'mov r11d, [rcx+0x92984]','cmp r11d, 0x100','mov ebx, r8d','mov r10, rcx',
  'mov [r10+rcx*4+0x92854], ebx','mov [r10+rcx*4+0x9274c], eax','mov [r10+rcx*4+0x927d0], eax',
  'inc dword [r10+0x92748]','mov [rax+r10+0x92dc2], r9b','movzx eax, byte [rsp+0x50]',
  'mov [rcx+r10+0x92ec2], al','mov [r10+rax*4+0x92990], edx','inc dword [r10+0x92984]',
  'inc dword [r10+rax*4+0x92318]','ret'},
 [finish_rva]={'mov rbx, rcx','mov ecx, [rcx+0x91f14]','cmp ecx, 0x100','mov [rbx+0x91f14], edx',
  'movss [rbx+r9*4+0x91f18], xmm0','cmp r9d, [rbx+r10*4+0x9274c]','imul rcx, rax, 0x688',
  'movss [rbx+r9*4+0x91f18], xmm1','addss xmm0, [rbx+0x92968]',
  'movss [rbx+0x92968], xmm0','mov dword [rbx+0x928e8], 0x0',string.format('jmp 0x%08x',solver_rva)}}
DebugArmory.decode=function(raw,rva)
 if not builder_ops[rva]then return old_decode(raw,rva)end
 local out={};for i,op in ipairs(builder_ops[rva])do out[i]={rva=rva+i,op=op}end;return out
end
local executable=backend.executable
backend.executable=function(at)return specs[at-base]~=nil or executable(at)end
local function n32(at)local a,b,c,d=read(at,4):byte(1,4);return a+b*256+c*65536+d*16777216 end
local events={};local invoked={clear=0,append=0,finish=0,marker=0,highlight=0}
backend.list_clear=function(at,g)
 assert(at==base+clear_rva and g==grid);invoked.clear=invoked.clear+1;events[#events+1]='clear'
 put(g+0x91f14,b(0,4));put(g+0x91f18,string.rep('\0',0x830));put(g+0x92748,b(0,4))
 put(g+0x9274c,string.rep('\0',0x18c));put(g+0x92984,b(0,12));put(g+0x92990,string.rep('\0',0x400))
 put(g+0x92960,f(0));put(g+0x92968,f(0));put(g+0x928e8,b(0xffffffff,4)..b(0xffffffff,4)..b(0xffffffff,4));return true
end
backend.list_append=function(at,g,offer,key,a,flag_b)
 assert(at==base+append_rva and g==grid and a>=0 and a<=255 and flag_b>=0 and flag_b<=255)
 invoked.append=invoked.append+1;events[#events+1]='append'
 local count,groups,row=n32(g+0x92984),n32(g+0x92748),n32(g+0x91f14)
 assert(count<256)
 if groups==0 or n32(g+0x92854+(groups-1)*4)~=key then
  if n32(g+0x92318+row*4)>0 then row=row+1;put(g+0x91f14,b(row,4))end
  put(g+0x92854+groups*4,b(key,4));put(g+0x9274c+groups*4,b(row,4))
  put(g+0x927d0+groups*4,b(count,4));put(g+0x92748,b(groups+1,4))
 end
 put(g+0x92dc2+count,string.char(a));put(g+0x92ec2+count,string.char(flag_b))
 put(g+0x92990+count*4,b(offer,4));put(g+0x92984,b(count+1,4))
 local n=n32(g+0x92318+row*4)+1;put(g+0x92318+row*4,b(n,4))
 if n==3 then put(g+0x91f14,b(row+1,4))end
 return true
end
backend.write_armor=function(at,id)
 assert(at==grid+0x9298c,'presentation wrote outside its marker field')
 invoked.marker=invoked.marker+1;events[#events+1]='marker';put(at,b(id,4));return true
end
backend.list_finish=function(at,g)
 assert(at==base+finish_rva and g==grid and n32(g+0x9298c)==702,'marker was not restored before Finish')
 invoked.finish=invoked.finish+1;events[#events+1]='finish'
 local rows=n32(g+0x91f14);if rows<256 and n32(g+0x92318+rows*4)>0 then rows=rows+1;put(g+0x91f14,b(rows,4))end
 local starts={};for i=0,n32(g+0x92748)-1 do starts[n32(g+0x9274c+i*4)]=true end
 local content=0;for row=0,rows-1 do local height=starts[row]and 246 or 200
  put(g+0x91f18+row*4,f(height));content=content+height end
 put(g+0x92968,f(content));put(g+0x928e8,b(0,4));return true
end
backend.highlight=function(at,g,offer)
 assert(at==base+highlight_rva and g==grid);invoked.highlight=invoked.highlight+1
 local index=0
 for row=0,n32(g+0x91f14)-1 do
  for col=0,n32(g+0x92318+row*4)-1 do
   if n32(g+0x92990+index*4)==offer then
    local selected_group=0
    for group=0,n32(g+0x92748)-1 do if n32(g+0x9274c+group*4)<=row then selected_group=group end end
    put(g+0x928e8,b(row,4)..b(col,4)..b(selected_group,4));put(g+0x92988,b(offer,4));return true
   end
   index=index+1
  end
 end
 return false
end
-- Ten real offers, two proved owned kits; group2 has a partial final row.
put(progression+0x1ce0,b(10,4))
for i=0,9 do
 put(progression+0xb9ce4+i*24,b(i,4)..b(701+i,4)..b(i%2==0 and 0x1234 or 0x5678,4))
 put(grid+0x92990+i*4,b(701+i,4));put(grid+0x92dc2+i,string.char(1));put(grid+0x92ec2+i,string.char(i%4))
end
put(owner+0x1f83b0,b(701,4));put(grid+0x92984,b(10,4));put(grid+0x92988,b(701,4)..b(702,4))
put(grid+0x91f14,b(4,4));put(grid+0x92318,b(3,4)..b(3,4)..b(3,4)..b(1,4)..b(0,4))
put(grid+0x91f18,f(246)..f(200)..f(246)..f(200));put(grid+0x92968,f(892));put(grid+0x92960,f(0))
put(grid+0x92748,b(2,4));put(grid+0x9274c,b(0,4)..b(2,4)..b(0,4))
put(grid+0x927d0,b(0,4)..b(6,4));put(grid+0x92854,b(0,4)..b(1,4))
put(grid+0x928e8,b(0,4)..b(0,4)..b(0,4));put(grid+0x92fc4,b(4,4));put(grid+0x92fd1,'\0')
local function resolved()
 local g=G.new(bridge,nil,backend);assert(ready(g)=='ready',g.failure);return g
end
'''


def run(code):
    run_lua(SELECTION+HIGHLIGHT+LOGICAL_PROOF+BUILDERS+code)


def test_dynamic_builder_resolution_and_real_bridge_roundtrip_preserve_recipe_and_marker():
    run('''
local g=resolved();local api=g:presentation_bridge(catalog,'entry-one')
local original=api.snapshot();assert(original.item_count==10 and original.group_count==2 and original.marker_offer_id==702)
local P=dofile('src/native_grid_presentation.lua');local coordinator=P.new(api)
local cards={{key='saved',kind='variant',kit_id='armor:00001234'},{key='create',kind='create',kit_id='armor:00005678'}}
local result=coordinator:attempt(cards);assert(result.phase=='active',result.error)
assert(invoked.clear==1 and invoked.append==12 and invoked.finish==1 and invoked.marker==1)
assert(n32(grid+0x92984)==12 and n32(grid+0x9298c)==702 and n32(grid+0x92988)==701)
local restored=coordinator:restore();assert(restored.phase=='restored',restored.error)
assert(invoked.clear==2 and invoked.append==22 and invoked.finish==2 and invoked.marker==2)
assert(P.matches(api.snapshot(),original))
for i=0,9 do assert(read(grid+0x92ec2+i,1):byte()==i%4)end
for i,event in ipairs(events)do if event=='finish'then assert(events[i-1]=='marker')end end
assert(moves==0 and stops==0,'presentation moved the native root')
''')


def test_missing_or_semantically_wrong_append_never_enables_constructors():
    run('''
put(base+append_rva,'X');local g=resolved()
local ok,why=pcall(function()return g:presentation_bridge(catalog,'entry')end)
assert(not ok and tostring(why):find('list_append'))
assert(invoked.clear==0 and invoked.append==0 and g:consume_select())
''')
    run('''
builder_ops[append_rva][10]='movzx eax, byte [rsp+0x48]'
local g=resolved();assert(not pcall(function()g:presentation_bridge(catalog,'entry')end))
assert(invoked.clear==0 and invoked.append==0)
''')


def test_partial_row_count_tampering_revokes_lease_before_next_native_append():
    run('''
local api=resolved():presentation_bridge(catalog,'entry');local original=api.snapshot()
local t=api.begin(original);assert(api.capture(true,t) and api.clear(t))
assert(api.append(t,original.entries[1]) and n32(grid+0x91f14)==0)
put(grid+0x92318,b(2,4))
assert(not api.owns(t))
assert(not pcall(api.append,t,original.entries[2]) and invoked.append==1)
assert(not pcall(api.finish,t) and invoked.finish==0)
''')


def test_active_menu_code_or_original_model_change_prevents_mutation():
    run('''
local api=resolved():presentation_bridge(catalog,'entry');local original=api.snapshot()
put(grid+0x92ec2,string.char(99));assert(not api.verify(original))
assert(not pcall(api.begin,original) and invoked.clear==0)
''')
    run('''
local api=resolved():presentation_bridge(catalog,'entry');local original=api.snapshot();local t=api.begin(original)
put(base+clear_rva+100,'X');assert(not api.same_menu(t) and not api.owns(t))
assert(not pcall(api.clear,t) and invoked.clear==0)
''')
    run('''
local api=resolved():presentation_bridge(catalog,'entry');local original=api.snapshot();local t=api.begin(original)
put(menu+0x4294,b(0,4));assert(not api.same_menu(t))
assert(not pcall(api.clear,t) and invoked.clear==0)
''')


def test_finish_cannot_repeat_without_clear_and_update_must_be_resumed_for_restore():
    run('''
local api=resolved():presentation_bridge(catalog,'entry');local original=api.snapshot();local t=api.begin(original)
assert(api.capture(true,t) and api.clear(t))
for _,entry in ipairs(original.entries)do assert(api.append(t,entry))end
assert(api.finish(t));assert(not pcall(api.finish,t) and invoked.finish==1)
assert(api.end_update(t));assert(not pcall(api.clear,t) and invoked.clear==1)
assert(api.resume_update(t) and api.clear(t) and invoked.clear==2)
''')


def test_non_top_or_inconsistent_selection_never_yields_reversible_snapshot():
    run('''
local api=resolved():presentation_bridge(catalog,'entry')
put(grid+0x92960,f(1));assert(not pcall(api.snapshot));put(grid+0x92960,f(0))
put(grid+0x928e8,b(1,4));assert(not pcall(api.snapshot))
assert(invoked.clear==0 and invoked.append==0)
''')
