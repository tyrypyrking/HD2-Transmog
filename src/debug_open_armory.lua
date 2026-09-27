-- Development-only real native menu entry. No persisted addresses or guessed
-- menu-field writes. Every call target is derived from current RIP-relative
-- code and the two current switch tables, then checked again before invocation.
local M={}
local decoder=DebugArmory or require('src.debug_armory')
local function u16(s,o)local a,b=s:byte(o+1,o+2);return a+256*b end
local function u32(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+256*b+65536*c+16777216*d end
local function i32(s,o)local n=u32(s,o);return n>=2147483648 and n-4294967296 or n end
local function ptr(s)
 if type(s)~='string'or #s~=8 then return nil end
 local hi=u32(s,4);if hi>=32768 then return nil end
 local n=u32(s,0)+hi*4294967296;return n>=65536 and n or nil
end
local function call_target(row,kind)
 local value=row and row.op:match('^'..(kind or 'call')..' 0x(%x+)$')
 return value and tonumber(value,16)or nil
end
local entry_type
local function native()
 local ffi=require('ffi');pcall(ffi.cdef,'size_t VirtualQuery(const void*,void*,size_t);')
 entry_type=entry_type or ffi.typeof('void (*)(void *, uint32_t, void *)')
 local kernel=ffi.load('kernel32');local region=ffi.new('uint8_t[48]')
 return {invoke=function(at,object,screen)
  assert(kernel.VirtualQuery(ffi.cast('const void*',at),region,48)==48,'native entry unavailable')
  local raw=ffi.string(region,48);local protection=u32(raw,36)
  assert(u32(raw,32)==4096 and ({[16]=true,[32]=true,[64]=true,[128]=true})[protection],'native entry not executable')
  ffi.cast(entry_type,at)(ffi.cast('void*',object),screen,nil)
 end}
end
function M.new(bridge,scene_guard,report,backend)
 assert(type(bridge)=='table'and type(bridge.read)=='function'and type(bridge.verify)=='function','verified bridge required')
 assert(type(bridge.base)=='number'and type(bridge.menu_global)=='number'and type(bridge.manager_global)=='number'
  and type(scene_guard)=='function','menu, manager and live scene guard required')
 report=report or function()end
 local self={phase='resolving'};local base=bridge.base;local proofs,sections={},{};local deadline,proof_bytes=0,0
 local push_rva,entry_rva
 local function read(at,n)
  assert(type(at)=='number'and at%1==0 and at>=65536 and at+n<140737488355328 and n>=1 and n<=262144,'open read bounds rejected')
  local s=bridge.read(at,n);assert(type(s)=='string'and #s==n,'open evidence unreadable');return s
 end
 local function image(rva,n)return read(base+rva,n)end
 local function inside(rva,n,exec)
  for _,s in ipairs(sections)do if s.read and (not exec or s.exec)and rva>=s.rva and rva+n<=s.rva+s.size then return true end end
  return false
 end
 local function watch(rva,n,exec)
  assert(inside(rva,n,exec),'open evidence outside current image')
  assert(#proofs<32 and proof_bytes+n<=16384,'open proof budget exceeded');proof_bytes=proof_bytes+n
  local s=image(rva,n);proofs[#proofs+1]={rva=rva,bytes=s};return s
 end
 local function instructions(rva,n)return decoder.decode(watch(rva,n,true),rva,2048)end
 local function has(rows,op)
  for _,row in ipairs(rows)do if row.op==op then return true end end;return false
 end
 local function following(rows,ops)
  local target
  for i=1,#rows-#ops do
   local match=true;for j,op in ipairs(ops)do if rows[i+j-1].op~=op then match=false;break end end
   if match then
    local at=call_target(rows[i+#ops]);assert(at,'expected native relative call')
    assert(not target or target==at,'ambiguous native call path');target=at
   end
  end
  return assert(target,'native call path changed')
 end
 local function switch_target(rows,selector)
  local found
  for i,row in ipairs(rows)do
   local table_hex=row.op:match('^mov ecx, %[r14%+rbx%*4%+0x(%x+)%]$')
   if table_hex and rows[i+1]and rows[i+2]and rows[i+1].op=='add rcx, r14'and rows[i+2].op=='jmp rcx'then
    local count,zero,decrement
    for j=math.max(1,i-40),i-1 do
     local max=rows[j].op:match('^cmp ebx, %+?0x(%x+)$')
     if max then count=tonumber(max,16)+1 end
     if rows[j].op=='dec ebx'then decrement=true end
     local delta=rows[j].op:match('^lea r14, %[rip%-0x(%x+)%]$')
     if delta and rows[j+1]and rows[j+1].rva-tonumber(delta,16)==0 then zero=true end
    end
    assert(zero and decrement and count and count<=64 and selector<=count,'native switch bounds/base changed')
    local table_rva=tonumber(table_hex,16);local bytes=watch(table_rva,count*4,false)
    for j=0,count-1 do assert(inside(u32(bytes,j*4),1,true),'invalid native switch target')end
    local target=u32(bytes,(selector-1)*4);assert(not found,'ambiguous native switch');found=target
   end
  end
  return assert(found,'native switch proof unavailable')
 end
 local function resolve()
  assert(bridge.verify(),'UI compatibility changed')
  local dos=image(0,64);assert(dos:sub(1,2)=='MZ','invalid image');local pe=u32(dos,60)
  assert(pe>=64 and pe<=65536,'invalid PE');local nt=image(pe,88)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 required')
  local count,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(count>=1 and count<=96 and opt>=112 and opt<=4096 and size<=536870912,'invalid PE bounds')
  local total=0
  for i=0,count-1 do
   local h=image(pe+24+opt+i*40,40);local n,rva,flags=u32(h,8),u32(h,12),u32(h,36)
   if n>0 then
    assert(rva>=4096 and rva+n<=size,'invalid section')
    local s={rva=rva,size=n,read=math.floor(flags/0x40000000)%2==1,exec=math.floor(flags/0x20000000)%2==1}
    if s.exec then assert(s.read,'unreadable code');total=total+n end;sections[#sections+1]=s
   end
  end
  assert(total>0 and total<=134217728,'open scan budget rejected')
  local seen,matched={},{}
  for _,s in ipairs(sections)do if s.exec then
   local tail=''
   for offset=0,s.size-1,262144 do
    assert(bridge.verify(),'UI compatibility changed while resolving')
    local bytes=tail..image(s.rva+offset,math.min(262144,s.size-offset));local origin=s.rva+offset-#tail;local at=1
    while true do
     if os.clock()>=deadline then coroutine.yield()end
     local hit=bytes:find('\72\139\13',at,true);if not hit then break end
     if hit+19<=#bytes and bytes:sub(hit+7,hit+13)=='\72\129\193\136\66\0\0'
      and bytes:byte(hit+14)==233 and bytes:byte(hit+19)==204 then
      local rva=origin+hit-1;local slot=base+rva+7+i32(bytes,hit+2)
      if slot==bridge.menu_global then
       local target=rva+19+i32(bytes,hit+14)
       if not seen[target]and inside(target,1024,true)then
        seen[target]=true;local rows=decoder.decode(image(target,1024),target,512)
        if rows[1]and rows[1].op=='mov [rsp+0x18], r8'
         and has(rows,'movsxd rdi, edx')and has(rows,'mov [rsi+rax*4+0x14], edi')
         and has(rows,'inc dword [rsi+0x28]')and has(rows,'mov [rsi+0xc], edi')then
          matched[#matched+1]={rva=target,wrapper=rva}
        end
       end
      end
     end
     at=hit+1
    end
    tail=bytes:sub(-20);coroutine.yield()
   end
  end end
  assert(#matched==1,'unique native menu-push entry not resolved')
  push_rva=matched[1].rva;watch(matched[1].wrapper,20,true)
  local rows=instructions(push_rva,1024)
  local dispatcher=following(rows,{'mov r8, [rsp+0x90]','mov edx, edi','mov rcx, r12'})
  rows=instructions(dispatcher,160)
  assert(has(rows,'movsxd rbx, edx')and has(rows,'mov rdi, r8'),'menu payload dispatch changed')
  local top_case=switch_target(rows,5);rows=instructions(top_case,48)
  assert(rows[2]and rows[2].op=='mov r8, rdi'and rows[3]and rows[3].op=='mov edx, 0x2','Armory GUI mapping changed')
  local factory
  for _,row in ipairs(rows)do local at=call_target(row,'jmp');if at then factory=at;break end end
  assert(factory,'GUI factory branch unavailable')
  rows=instructions(factory,224)
  assert(has(rows,'mov rsi, r8')and has(rows,'mov edi, edx')and has(rows,'mov [rbx], edi'),'GUI factory ABI changed')
  local entering=following(rows,{'mov r8, rsi','mov rdx, rbx','mov rcx, rbx'})
  rows=instructions(entering,288)
  assert(has(rows,'mov r12, r8')and has(rows,'mov r8, r12'),'GUI enter payload preservation changed')
  local gui_dispatch=following(rows,{'mov rdx, r13','mov r9d, [r15]','mov rcx, r15'})
  rows=instructions(gui_dispatch,160)
  assert(has(rows,'mov ebx, r9d')and has(rows,'mov rsi, r8'),'GUI selector ABI changed')
  local gui_case=switch_target(rows,2);rows=instructions(gui_case,32)
  assert(rows[1]and rows[1].op=='mov rcx, [rdi+0x60]'and rows[2]and rows[2].op=='mov rdx, r15','Armory callback mapping changed')
  entry_rva=assert(call_target(rows[3]),'Armory on-enter callback unavailable')
  assert(call_target(rows[4],'jmp'),'Armory case must terminate without reading optional payload')
  rows=instructions(entry_rva,1024)
  assert(has(rows,'mov r13, rcx')and has(rows,'mov [rcx+0x28], rdx')and has(rows,'mov r8b, 0x1'),'Armory callback ABI changed')
  local body={};for _,row in ipairs(rows)do if row.op=='int3'then break end;body[#body+1]=row end
  local register_rva=following(body,{'mov rcx, r13'})
  rows=instructions(register_rva,256)
  assert(has(rows,'mov dword [rsp+0x48], 0xe0')and has(rows,'mov eax, [rdx+0x166c]')
   and has(rows,'inc dword [rdx+0x166c]')and has(rows,'add rax, 0x167'),'selected callback is not the proven Armory controller')
  local manager_match=false
  for i,row in ipairs(rows)do
   local sign,delta=row.op:match('^mov rdx, %[rip([+-])0x(%x+)%]$')
   if delta and rows[i+1]and base+rows[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)==bridge.manager_global then manager_match=true end
  end
  assert(manager_match,'Armory registration uses a different UI manager')
  for _,proof in ipairs(proofs)do assert(image(proof.rva,#proof.bytes)==proof.bytes,'open proof changed during resolution')end
  assert(bridge.verify(),'UI compatibility changed after resolution')
  self.phase='ready';report('debug_open_armory.status','native_call_path_verified')
 end
 local worker=coroutine.create(resolve)
 function self:step()
  if self.phase~='resolving'then return self.phase,self.failure end
  deadline=os.clock()+0.006;local ok,why=coroutine.resume(worker)
  if not ok then self.phase='failed';self.failure=tostring(why);report('debug_open_armory.failure',self.failure)end
  return self.phase,self.failure
 end
 function self:open()
  local ok,value=pcall(function()
   assert(self.phase=='ready','native Armory entry not resolved')
   local intact,why=pcall(function()
    assert(bridge.verify(),'UI compatibility changed')
    for _,proof in ipairs(proofs)do assert(image(proof.rva,#proof.bytes)==proof.bytes,'native entry code/table changed')end
   end)
   if not intact then self.phase='failed';self.failure=tostring(why);error(self.failure,0)end
   local menu_bytes=read(bridge.menu_global,8);local menu=assert(ptr(menu_bytes),'menu manager unavailable')
   local state=read(menu+0x4294,32)
   assert(u32(state,0)==0 and u32(state,4)==0 and u32(state,28)==0,'close the current native menu before opening Armory')
   assert(scene_guard()==true,'current main world is not a verified ship scene')
   backend=backend or native()
   assert(read(bridge.menu_global,8)==menu_bytes and read(menu+0x4294,32)==state and bridge.verify(),'menu context changed before native entry')
   assert(scene_guard()==true,'ship scene changed before native entry')
   backend.invoke(base+push_rva,menu+0x4288,5)
   report('debug_open_armory.native_request',true)
   return 'Native Armory transition invoked; waiting for verified Armory view'
  end)
  if not ok then return nil,tostring(value)end;return true,value
 end
 return self
end
return M
