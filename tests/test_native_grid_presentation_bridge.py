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


def test_five_saved_cards_and_neighboring_row_boundaries_roundtrip_with_repeated_offers():
    # Exercise the actual bridge against the captured constructor memory contract.
    # Both policies use this grid contract; this does not simulate native rendering.
    run(r'''
local g=resolved();local P=dofile('src/native_grid_presentation.lua')
for count=1,8 do for _,create in ipairs({false,true})do for _,same_look in ipairs({false,true})do
 local api=g:presentation_bridge(catalog,'count-'..count..':'..tostring(create)..':'..tostring(same_look))
 local original=api.snapshot();local cards={}
 for i=1,count do cards[#cards+1]={key='saved:'..i,kind='variant',
  kit_id=(same_look or i%2==1)and 'armor:00001234'or 'armor:00005678'}end
 if create then cards[#cards+1]={key='create',kind='create',kit_id='armor:00001234'}end
 local coordinator=P.new(api,{allow_create=create})
 local result=coordinator:attempt(cards);assert(result.phase=='active',result.error)
 local custom=count+(create and 1 or 0)
 assert(n32(grid+0x92984)==10+custom and n32(grid+0x91f14)==4+math.ceil(custom/3))
 assert(n32(grid+0x9298c)==702,'equipped marker changed')
 for i=0,9 do assert(n32(grid+0x92990+(custom+i)*4)==701+i,'native offer order changed')end
 assert(coordinator:status().phase=='active')
 local restored=coordinator:restore();assert(restored.phase=='restored',restored.error)
 assert(P.matches(api.snapshot(),original),'repeated construction accumulated state')
end end end
''')


def test_presentation_checkpoints_bracket_calls_and_identify_failed_append():
    run(r'''
local log={}
local g=G.new(bridge,function(key,value)log[#log+1]={key=key,value=value}end,backend)
assert(ready(g)=='ready');log={}
local api=g:presentation_bridge(catalog,'logging');local s=api.snapshot();local t=api.begin(s)
assert(api.capture(true,t)and api.clear(t))
assert(log[#log-1].key=='grid.list_clear.begin'and log[#log].key=='grid.list_clear.returned')
local append=backend.list_append
backend.list_append=function(...)
 assert(log[#log].key=='grid.list_append.begin')
 assert(log[#log].value:find('armory:index=0:offer=701:kit=armor:00001234',1,true))
 error('simulated native call failure')
end
assert(not pcall(api.append,t,s.entries[1]))
assert(log[#log].key=='grid.list_append.begin','failed call falsely logged as returned')
backend.list_append=append
for _,entry in ipairs(s.entries)do assert(api.append(t,entry))end
assert(api.finish(t))
assert(log[#log-1].key=='grid.list_finish.begin'and log[#log].key=='grid.list_finish.returned')
assert(api.restore_view(t,{selected_offer_id=701,scroll_value=0},false))
assert(log[#log-1].key=='grid.presentation_highlight.begin'and log[#log].key=='grid.presentation_highlight.returned')
assert(api.end_update(t))
local n=#log
assert(api.owns(t)and api.same_menu(t))
assert(#log==n,'read-only presentation checks emit repeated logging')
''')


def test_retirement_identifies_changed_model_component_without_native_writes():
    run(r'''
local cases={
 {'geometry',4,f(101)}, {'row_count',0x91f14,b(5,4)},
 {'group_count',0x92748,b(3,4)}, {'item_count',0x92984,b(11,4)},
 {'row_items',0x92318,b(2,4)}, {'group_rows',0x9274c,b(1,4)},
 {'group_items',0x927d0,b(1,4)}, {'group_keys',0x92854,b(42,4)},
 {'offers',0x92990,b(710,4)}, {'flags_a',0x92dc2,string.char(9)},
 {'flags_b',0x92ec2,string.char(9)}}
local g=resolved()
for _,case in ipairs(cases)do
 local api=g:presentation_bridge(catalog,'reason-'..case[1])
 local snapshot=api.snapshot();local t=api.begin(snapshot);assert(api.end_update(t))
 local at=grid+case[2];local before=read(at,#case[3]);put(at,case[3])
 local owned,why=api.owns(t)
 assert(owned==false and why=='native model generation changed: '..case[1],tostring(why))
 assert(invoked.clear==0 and invoked.append==0 and invoked.finish==0)
 put(at,before);assert(api.owns(t))
end
''')
