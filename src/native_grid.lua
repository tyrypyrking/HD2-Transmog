-- Optional native Armory grid diagnostics and narrow UI input/layout operations.
-- No fixed native call addresses, unlock writes, or list insertion. Selected kit
-- identity is optional and requires the current category/offer mapping proof.
-- Code entry points are scanned and semantically checked in the current image.
local M={}
local decoder=DebugArmory or require('src.debug_armory')
local function u16(s,o)local a,b=s:byte(o+1,o+2);return a+b*256 end
local function u32(s,o)
 if type(s)~='string'or #s<o+4 then return nil end
 local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216
end
local function pointer(s,o)
 o=o or 0;local lo,hi=u32(s,o),u32(s,o+4)
 if not hi or hi>=32768 then return nil end
 local n=lo+hi*4294967296;return n>=65536 and n or nil
end
local function f32(s,o)
 local n=u32(s,o);if not n then return nil end
 local sign=1;if n>=2147483648 then sign=-1;n=n-2147483648 end
 local exponent,mantissa=math.floor(n/8388608),n%8388608
 if exponent==255 then return nil end
 return sign*(exponent==0 and mantissa*2^-149 or (1+mantissa/8388608)*2^(exponent-127))
end
local function finite(v)return type(v)=='number'and v==v and math.abs(v)<=1000000 end
-- The existing scrollbar reference uses world translation +148/+156 and
-- width/height multiplied by world scale +100/+140. Applying that schema to
-- thumbnail root/image widgets is diagnostic until visually corroborated.
local function candidate_rect(raw,offset)
 offset=offset or 0
 local x,y=f32(raw,offset+148),f32(raw,offset+156)
 local sx,sy=f32(raw,offset+100),f32(raw,offset+140)
 local width,height=f32(raw,offset+12),f32(raw,offset+16)
 for _,value in ipairs({x,y,sx,sy,width,height})do if not finite(value)then return nil end end
 if not x or not y or not sx or not sy or not width or not height
  or sx<=0 or sy<=0 or sx>64 or sy>64 or width<=0 or height<=0
  or width>32768 or height>32768 or not finite(width*sx)or not finite(height*sy)then return nil end
 return {x=x,y=y,w=width*sx,h=height*sy,scale_x=sx,scale_y=sy}
end
local function bytes(h)return(h:gsub('%x%x',function(v)return string.char(tonumber(v,16))end))end
local function ident(v)return string.format('armor:%08x',v)end
local PATTERNS={
 {name='detail_input',hex='48895c241048896c2418565741564883ec308b8104e00b004d8bf0',length=1955,optional=true},
 {name='equip_audio_source',hex='3b9f8c290900740a8bd3488bcfe8',length=32,optional=true},
 {name='header_text',hex='ba421e1862488d8d10010000e8000000008bc785ff741883e801740c83f8017513bb1cbbde21',wild={{13,16}},length=95,optional=true},
 {name='category_text',hex='418b85f02809004d8d879899090083f8ff',length=201,optional=true},
 {name='text_string',hex='40534883ec20488bd94881c110010000e84bd8ffff84c0745b8b93b8000000',length=121,optional=true},
 {name='deployment_apply',hex='8b8f1c28000085c9743e83e901741f83f9017578488b0d587deb01448bc2418992280100008bd3e80f7740ffeb5e488b0d3e7deb01448bc2418992240100008bd3e8057540ffeb44488b0d247deb01448bc24189922c0100008bd3e8cb7840ffeb2a',wild={{23,26},{40,43},{49,52},{66,69},{75,78},{92,95}},length=98,optional=true},

 {name='preview_notify',hex='40574883ec2083b9888c170001488bf9',length=192,optional=true},
 {name='list_clear',hex='48895c241048896c24184889742420574883ec70488bf9',length=543,optional=true},
 {name='list_append',hex='534883ec20448b9984290900',length=270,optional=true},
 {name='position',hex='48895c241848896c24204889542410565741574883ec20f30f104104488bda0f',length=224},
 {name='size',hex='48895c241848896c24204889542410565741574883ec20f30f10410c488bda0f',length=224,optional=true},
 {name='animation_stop',hex='40534883ec40488b05000000004833c448894424300fb601',wild={{9,12}},length=96},
 {name='consume',hex='40534883ec204c8bd14c8bca488bcae800000000',wild={{16,19}},length=155},
 {name='highlight',hex='48895c24185556574883ec20448b89141f090033ed488bf9448bc58bf54585c9',length=434,optional=true},
 {name='logical_solver',hex='488bc45355565741544155415641574881ecf800000083b94827090001',length=505,optional=true},
 {name='logical_groups',hex='458b86e82809004539864c270900',length=56,optional=true},
 {name='list_finish',hex='48895c2410574883ec30488bd90f297c24208b89141f09008bd181f900010000',length=428,optional=true},
 {name='selection',hex='448b87b0831f0033d24585c07431488b05000000008bca448b88e01c00004585c9741c4805e49c0b0044394004740dffc14883c018413bc972efeb038b5008899790000000',wild={{17,20}},length=69,optional=true},
 {name='commit_source',hex='448b87b0831f0033d24585c07431488b05000000008bca448b88e01c00004585c9741c4805e49c0b0044394004740dffc14883c018413bc972efeb038b500889979000000033d2488bcfe800000000',wild={{17,20},{75,78}},length=79,optional=true},
 {name='thumbnail',hex='40534883ec204533c9488bda488b1500000000418bc9448b82802b00004585c0',wild={{15,18}},length=32,optional=true},
}
local GRID=523752
local native_text_buffers={}
local native_types
local function native()
 local ffi=require('ffi')
 for _,decl in ipairs({'size_t VirtualQuery(const void*,void*,size_t);','void *GetCurrentProcess(void);','int WriteProcessMemory(void*,void*,const void*,size_t,size_t*);'})do pcall(ffi.cdef,decl)end
 -- Parsing anonymous function signatures repeatedly consumes LuaJIT CType
 -- slots permanently. Retain each ABI once for the module's lifetime.
 native_types=native_types or {
  text_string=ffi.typeof('void (*)(void*, uint32_t, const char*)'),
  unary=ffi.typeof('void (*)(void*)'),
  append=ffi.typeof('void (*)(void*, uint32_t, uint32_t, uint8_t, uint8_t)'),
  commit=ffi.typeof('void (*)(void*, uint8_t)'),
  deployment_commit=ffi.typeof('void (*)(void*, uint32_t, uint32_t)'),
  detail=ffi.typeof('void (*)(void*, uint32_t, uint8_t)'),
  detail_stats=ffi.typeof('uint8_t (*)(void*, uint32_t, uint32_t, void*)'),
  detail_passive=ffi.typeof('void (*)(void*, uint32_t)'),
  consume=ffi.typeof('void (*)(void*, uint64_t, float)'),
  vector=ffi.typeof('void (*)(void*, uint64_t)'),
  highlight=ffi.typeof('uint8_t (*)(void*, uint32_t)'),
 }
 local select_action=ffi.new('uint64_t',0xA00000000)
 local kernel=ffi.load('kernel32');local info=ffi.new('uint8_t[48]')
 local xy,packed=ffi.new('float[2]'),ffi.new('uint64_t[1]')
 local armor_word,written=ffi.new('uint32_t[1]'),ffi.new('size_t[1]')
 local function executable(at)
  if kernel.VirtualQuery(ffi.cast('const void*',at),info,48)~=48 then return false end
  local raw=ffi.string(info,48)
  return u32(raw,32)==4096 and ({[16]=true,[32]=true,[64]=true,[128]=true})[u32(raw,36)]==true
 end
 return {executable=executable,
  button_state=function(at,widget,state)
   ffi.cast(native_types.detail_passive,at)(ffi.cast('void*',widget),state);return true
  end,
  equipment_sound=function(at,grid,offer)
   ffi.cast(native_types.detail_passive,at)(ffi.cast('void*',grid),offer);return true
  end,
  text_template=function(at,widget,key)
   ffi.cast(native_types.detail_passive,at)(ffi.cast('void*',widget),key);return true
  end,
  text_string=function(at,widget,key,value)
   if not native_text_buffers[value]then native_text_buffers[value]=ffi.new('char[?]',#value+1,value)end
   ffi.cast(native_types.text_string,at)(ffi.cast('void*',widget),key,native_text_buffers[value]);return true
  end,
  list_clear=function(at,grid)ffi.cast(native_types.unary,at)(ffi.cast('void*',grid));return true end,
  list_append=function(at,grid,offer,group,a,b)
   ffi.cast(native_types.append,at)(ffi.cast('void*',grid),offer,group,a,b);return true
  end,
  preview_notify=function(at,manager)ffi.cast(native_types.unary,at)(ffi.cast('void*',manager));return true end,
  preview_details=function(at,widget,offer,equipped)
   ffi.cast(native_types.detail,at)(ffi.cast('void*',widget),offer,equipped and 1 or 0);return true
  end,
  focus_row=function(at,row,column)
   ffi.cast(native_types.detail_passive,at)(ffi.cast('void*',row),column);return true
  end,
  detail_stats=function(at,widget,offer)
   return ffi.cast(native_types.detail_stats,at)(ffi.cast('void*',widget),offer,offer,nil)~=0
  end,
  detail_passive=function(at,widget,offer)
   ffi.cast(native_types.detail_passive,at)(ffi.cast('void*',widget),offer);return true
  end,
  list_finish=function(at,grid)ffi.cast(native_types.unary,at)(ffi.cast('void*',grid));return true end,
  write_armor=function(at,id)
   if kernel.VirtualQuery(ffi.cast('const void*',at),info,48)~=48 then return false end
   local raw=ffi.string(info,48);local first=pointer(raw);local size=u32(raw,24)+(u32(raw,28)or 0)*4294967296
   if not first or not size or at<first or at+4>first+size or u32(raw,32)~=4096 or (u32(raw,36)~=4 and u32(raw,36)~=8)then return false end
   armor_word[0]=id;written[0]=0
   return kernel.WriteProcessMemory(kernel.GetCurrentProcess(),ffi.cast('void*',at),armor_word,4,written)~=0 and tonumber(written[0])==4
  end,
  deployment_commit=function(at,profile,player,id)ffi.cast(native_types.deployment_commit,at)(ffi.cast('void*',profile),player,id);return true end,
  commit=function(at,owner)ffi.cast(native_types.commit,at)(ffi.cast('void*',owner),0);return true end,
  consume=function(at,input)
   ffi.cast(native_types.consume,at)(ffi.cast('void*',input),select_action,-1)
   return true
  end,
  position=function(at,widget,x,y)
   xy[0],xy[1]=x,y;ffi.copy(packed,xy,8)
   ffi.cast(native_types.vector,at)(ffi.cast('void*',widget),packed[0]);return true
  end,
  highlight=function(at,grid,offer)
   return ffi.cast(native_types.highlight,at)(ffi.cast('void*',grid),offer)~=0
  end,
  size=function(at,widget,w,h)
   xy[0],xy[1]=w,h;ffi.copy(packed,xy,8)
   ffi.cast(native_types.vector,at)(ffi.cast('void*',widget),packed[0]);return true
  end,
  stop=function(at,animation)
   ffi.cast(native_types.unary,at)(ffi.cast('void*',animation));return true
  end,
 }
end
function M.new(bridge,report,backend)
 assert(type(bridge)=='table'and type(bridge.read)=='function'and type(bridge.verify)=='function','verified UI bridge required')
 assert(type(bridge.base)=='number'and type(bridge.manager_global)=='number'and type(bridge.menu_global)=='number','UI global proof required')
 report=report or function()end
 local self={phase='resolving'};local base=bridge.base
 local proofs,sections,targets={}, {}, {};local input_global,progression_global,thumbnail_global,commit_info;local deadline=0
 local snapshots=setmetatable({}, {__mode='k'});local movement
 local commit_snapshots=setmetatable({}, {__mode='k'});local commit_session,commit_session_key
 local function read(at,n)
  assert(type(at)=='number'and at%1==0 and at>=65536 and at+n<140737488355328 and n>=1 and n<=262144,'grid read bounds rejected')
  local raw=bridge.read(at,n);assert(type(raw)=='string'and #raw==n,'grid evidence unreadable');return raw
 end
 local function inside(rva,n,exec)
  for _,section in ipairs(sections)do
   if section.read and (not exec or section.exec)and rva>=section.rva and rva+n<=section.rva+section.size then return true end
  end
  return false
 end
 local function code_current()
  if bridge.verify()~=true then self.code_failure='Armory adapter evidence changed';return false end
  for _,proof in ipairs(proofs)do if bridge.read(base+proof.rva,#proof.bytes)~=proof.bytes then
   self.code_failure='Grid code evidence changed at '..string.format('%08x',proof.rva);return false end end
  self.code_failure=nil
  return true
 end
 local function has(rows,op)for _,row in ipairs(rows)do if row.op==op then return true end end end
 local function resolve()
  assert(bridge.verify(),'grid UI proof changed')
  local dos=read(base,64);assert(dos:sub(1,2)=='MZ','invalid module')
  local pe=u32(dos,60);assert(pe>=64 and pe<=65536,'invalid PE offset')
  local nt=read(base+pe,88)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 required')
  local n,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(n>=1 and n<=96 and opt>=112 and opt<=4096 and size<=536870912,'invalid image bounds')
  for i=0,n-1 do
   local h=read(base+pe+24+opt+i*40,40);local len,rva,flags=u32(h,8),u32(h,12),u32(h,36)
   assert(rva>=4096 and rva+len<=size,'invalid section bounds')
   for _,old in ipairs(sections)do assert(rva+len<=old.rva or rva>=old.rva+old.size,'overlapping sections')end
   sections[#sections+1]={rva=rva,size=len,read=math.floor(flags/0x40000000)%2==1,exec=math.floor(flags/0x20000000)%2==1}
  end
  local patterns={};local overlap=0
  for _,spec in ipairs(PATTERNS)do
   local p={spec=spec,bytes=bytes(spec.hex),ignore={}}
   for _,range in ipairs(spec.wild or {})do for offset=range[1],range[2]do p.ignore[offset+1]=true end end
   p.anchor=p.bytes:sub(1,math.min(8,#p.bytes));patterns[#patterns+1]=p;overlap=math.max(overlap,#p.bytes-1)
  end
  local total=0
  for _,section in ipairs(sections)do if section.exec then
   assert(section.read,'unreadable code section');total=total+section.size;assert(total<=134217728,'grid scan budget exceeded')
   local tail=''
   for offset=0,section.size-1,262144 do
    local raw=tail..read(base+section.rva+offset,math.min(262144,section.size-offset))
    local origin=section.rva+offset-#tail
    for _,p in ipairs(patterns)do
     local start,hits=1,0
     while true do
      local at=raw:find(p.anchor,start,true);if not at then break end
      hits=hits+1;assert(hits<=4096,'grid anchor budget exceeded')
      local match=at+#p.bytes-1<=#raw
      if match then for j=1,#p.bytes do if not p.ignore[j]and p.bytes:byte(j)~=raw:byte(at+j-1)then match=false;break end end end
      if match then
       local rva=origin+at-1
       if p.found and p.found~=rva then if p.spec.optional then p.ambiguous=true else error('ambiguous grid function '..p.spec.name)end end
       p.found=rva
      end
      start=at+1
      if os.clock()>=deadline then coroutine.yield()end
     end
    end
    tail=raw:sub(math.max(1,#raw-overlap+1));coroutine.yield()
   end
  end end
  assert(total>0,'no executable image section')
  for _,p in ipairs(patterns)do
   if p.spec.optional and (not p.found or p.ambiguous)then report('grid.'..p.spec.name,'optional proof unavailable')
   else
   assert(p.found,'native grid function unavailable: '..p.spec.name)
   local proof_count=#proofs
   local valid,reason=pcall(function()
   assert(inside(p.found,p.spec.length,true),'grid function proof outside code')
   local raw=read(base+p.found,p.spec.length)
   proofs[#proofs+1]={rva=p.found,bytes=raw};targets[p.spec.name]=base+p.found
   local rows=decoder.decode(raw,p.found,p.spec.name=='detail_input'and 512 or 256)
   if p.spec.name=='header_text'then
    assert(has(rows,'lea rcx, [rbp+0x110]')and has(rows,'mov edx, 0x341f7711')
     and has(rows,'mov edx, 0x15d8f2e2'),'header text binding differs')
    local call=rows[3];local rva=tonumber(assert(call.op:match('^call 0x(%x+)$')),16)
    assert(inside(rva,152,true),'text template setter outside image')
    local body=read(base+rva,152);local ops=decoder.decode(body,rva,128)
    assert(has(ops,'cmp [rcx+0x110], edx')and has(ops,'mov [rcx+0x110], edx')
     and has(ops,'mov rdx, [rcx+0x270]'),'text template setter differs')
    proofs[#proofs+1]={rva=rva,bytes=body};targets.text_template=base+rva
   elseif p.spec.name=='category_text'then
    assert(has(rows,'lea r8, [r15+0x99998]')and has(rows,'mov eax, [r13+0x928f0]')
     and has(rows,'mov ecx, [r13+rax*4+0x92854]')and has(rows,'mov ebx, 0xddc08ca8')
     and has(rows,'mov ebx, 0x1bc93550'),'category binding differs')
    assert(has(rows,'mov ebx, 0x21debb1c'),'category weight labels differ')
   elseif p.spec.name=='text_string'then
    assert(has(rows,'add rcx, 0x110')and has(rows,'mov rbx, rcx'),'string widget ABI differs')
    local child
    for _,row in ipairs(rows)do child=row.op:match('^call 0x(%x+)$');if child then break end end
    local rva=tonumber(assert(child),16);assert(inside(rva,321,true),'string parameter outside image')
    local body=read(base+rva,321);local ops=decoder.decode(body,rva,256)
    for _,op in ipairs({'mov rdi, r8','movzx r11d, byte [rcx+0x158]',
     'mov [rsp+0x28], rdi','mov dword [rsp+0x24], 0x1','mov [rsi+0x10], rdi'})do
     assert(has(ops,op),'string parameter ABI differs: '..op)
    end
    proofs[#proofs+1]={rva=rva,bytes=body}
   elseif p.spec.name=='deployment_apply'then
    for _,op in ipairs({'mov ecx, [rdi+0x281c]','test ecx, ecx','mov r8d, edx','mov [r10+0x12c], edx','mov edx, ebx'})do
     assert(has(rows,op),'Equipment armor Apply contract differs: '..op)
    end
    local setter,global
    for i,row in ipairs(rows)do if row.op=='mov [r10+0x12c], edx'then
     assert(rows[i+1].op=='mov edx, ebx','Equipment player argument differs')
     setter=tonumber(assert(rows[i+2].op:match('^call 0x(%x+)$')),16)
     local load=rows[i-2];assert(load.op:match('^mov rcx, %[rip'),'Equipment profile argument differs')
     local displacement=u32(read(base+load.rva+3,4),0);if displacement>=2147483648 then displacement=displacement-4294967296 end
     global=base+load.rva+7+displacement
    end end
    assert(setter and global and inside(setter,318,true),'Equipment armor setter unavailable')
    local body=read(base+setter,318);local decoded=decoder.decode(body,setter,256)
    for _,op in ipairs({'mov rdi, rcx','mov r11d, [rcx+0x938]','mov esi, eax','shl rsi, 0x06',
     'cmp [rsi+rdi+0xa88], r8d','mov [rsi+rdi+0xa88], r8d'})do
     assert(has(decoded,op),'Equipment armor setter ABI differs: '..op)
    end
    proofs[#proofs+1]={rva=setter,bytes=body}
    targets.deployment_commit={entry=base+setter,profile_global=global}
   elseif p.spec.name=='detail_input'then
    -- Validate the common UI audio backend. The equipment event itself is
    -- resolved separately from the successful native equipment-selection path.
    for _,op in ipairs({'lea rdi, [rbx+0x49f0]','mov byte [rbx+0x91a3], 0x1',
     'mov edx, [rbx+0x91b0]'})do assert(has(rows,op),'native Equip input ABI differs: '..op)end
    local sound
    for i,row in ipairs(rows)do if row.op=='mov edx, [rbx+0x91b0]'then
     local call=rows[i+1]and rows[i+1].op:match('^call 0x(%x+)$')
     assert(call and not sound,'native Equip audio edge ambiguous');sound=tonumber(call,16)
    end end
    assert(sound and inside(sound,107,true),'native Equip audio unavailable')
    local raw=read(base+sound,107);local body=decoder.decode(raw,sound,128)
    for _,op in ipairs({'mov ebx, edx','mov rdx, [rax+0x288]','mov rcx, [rcx+0x10f8]',
     'mov rsi, [rax+0x338]','call rdx','mov ecx, ebx','xor r9d, r9d','jmp rax'})do
     assert(has(body,op),'native UI audio ABI differs: '..op)
    end
    proofs[#proofs+1]={rva=sound,bytes=raw};targets.equip_sound=base+sound
   elseif p.spec.name=='equip_audio_source'then
    -- Actual successful equipment selection calls this helper before updating
    -- the equipped marker. Button press/hold/release sounds are unrelated.
    assert(rows[1].op=='cmp ebx, [rdi+0x9298c]'and rows[2].op:match('^jz 0x')
     and rows[3].op=='mov edx, ebx'and rows[4].op=='mov rcx, rdi',
     'native equipment audio caller differs')
    local entry=tonumber(assert(rows[5].op:match('^call 0x(%x+)$')),16)
    assert(inside(entry,500,true),'native equipment audio helper unavailable')
    local raw=read(base+entry,500);local body=decoder.decode(raw,entry,256)
    for _,op in ipairs({'mov ecx, [rcx+0x92fc4]','cmp dword [rax], +0x0e',
     'mov r9d, [rcx+0x1ce0]','add rcx, 0x000b9ce4','cmp [rcx+0x4], edx',
     'mov edx, 0x7dc5fafe','mov edx, 0xe5126f17','mov edx, 0xf139f191','mov edx, 0x09ad679b'})do
     assert(has(body,op),'native equipment audio category route differs: '..op)
    end
    local getter,menu_slot,offers_slot
    for i,row in ipairs(body)do
     local sign,delta=row.op:match('^mov r9, %[rip([+-])0x(%x+)%]$')
     if delta then menu_slot=base+body[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)end
     sign,delta=row.op:match('^mov rcx, %[rip([+-])0x(%x+)%]$')
     if delta then
      local slot=base+body[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
      assert(not offers_slot or offers_slot==slot,'equipment audio offer tables differ');offers_slot=slot
     end
     if not getter and row.op=='mov ecx, [rcx+0x8]'then
      getter=tonumber(assert(body[i+1].op:match('^call 0x(%x+)$')),16)
     end
     local jump=row.op:match('^jmp 0x(%x+)$')
     if jump then
      local at=tonumber(jump,16)
      if at<entry or at>=entry+500 then assert(base+at==targets.equip_sound,'equipment audio dispatcher differs')end
     end
    end
    assert(menu_slot==bridge.menu_global and offers_slot and getter and inside(getter,46,true),
     'equipment audio context/lookup unavailable')
    local getter_raw=read(base+getter,46);local ops=decoder.decode(getter_raw,getter,64)
    for _,op in ipairs({'mov r9d, [r11+0x8]','mov r10, [r11]','mov rdx, [r10+rax*8]',
     'cmp [rdx], ecx','mov eax, [rdx+0x28]','mov eax, 0x3'})do
     assert(has(ops,op),'equipment audio item-category lookup differs: '..op)
    end
    local sign,delta=ops[1].op:match('^mov r11, %[rip([+-])0x(%x+)%]$')
    assert(delta,'equipment audio catalog global unavailable')
    local catalog_slot=base+ops[2].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
    assert(inside(catalog_slot-base,8,false)and inside(offers_slot-base,8,false),'equipment audio globals outside image')
    proofs[#proofs+1]={rva=entry,bytes=raw};proofs[#proofs+1]={rva=getter,bytes=getter_raw}
    targets.equipment_audio={entry=base+entry,offers_global=offers_slot,catalog_global=catalog_slot}
   elseif p.spec.name=='preview_notify'then
    for _,op in ipairs({'cmp dword [rcx+0x178c88], +0x01','mov rdi, rcx',
     'cmp byte [rcx+0x178c8e], 0x0','mov r9d, [rcx+0x92fbc]',
     'mov r8d, [rcx+0x92fb8]','add rcx, 0x6d0','mov edx, [rsp+0x30]',
     'lea rcx, [rdi+0x99d70]','cmp [rdi+0x9305c], edx','setz r8b'})do
     assert(has(rows,op),'native hover refresh ABI differs: '..op)
    end
    local mode_target,detail
    for i,row in ipairs(rows)do
     if row.op=='mov rdi, rcx'then mode_target=rows[i+1]and rows[i+1].op:match('^jnz 0x(%x+)$')end
     if row.op=='setz r8b'then
      assert(rows[i+1].op=='add rsp, +0x20'and rows[i+2].op=='pop rdi','hover tail ABI differs')
      detail=rows[i+3].op:match('^jmp 0x(%x+)$')
     end
    end
    assert(mode_target and detail,'hover mode0 route unavailable')
    local at_mode
    for _,row in ipairs(rows)do if row.rva==tonumber(mode_target,16)then at_mode=row end end
    assert(at_mode and at_mode.op=='cmp byte [rcx+0x178c8e], 0x0','hover mode0 dispatch differs')
    detail=tonumber(detail,16);assert(inside(detail,3072,true),'detail preview outside code')
    local detail_raw=read(base+detail,3072);local detail_rows=decoder.decode(detail_raw,detail,1024)
    for _,op in ipairs({'mov edi, [rcx+0xbe00c]','mov ebx, edx','mov [rcx+0xbe00c], ebx',
     'movzx r12d, r8b','mov ecx, [rdx+0x1ce0]','lea r15, [rdx+0xb9ce4]',
     'cmp [r15+0x4], ebx','lea rcx, [rbp+0x20640]'})do
     assert(has(detail_rows,op),'native owned detail preview contract differs: '..op)
    end
    local setter
    for i,row in ipairs(detail_rows)do if row.op=='lea rcx, [rbp+0x20640]'then
     for j=i+1,math.min(i+4,#detail_rows)do
      local target=detail_rows[j].op:match('^call 0x(%x+)$');if target then setter=tonumber(target,16);break end
     end
    end end
    assert(setter and inside(setter,192,true),'native preview kit setter unavailable')
    local setter_raw=read(base+setter,192);local setter_rows=decoder.decode(setter_raw,setter,128)
    for _,op in ipairs({'cmp [rcx+0xdc0], edx','mov [rbx+0xdc0], edx','mov r8d, 0x2',
     'cmp byte [rbx+0xdb0], 0x0','cmp byte [rbx+0xdb1], 0x0'})do
     assert(has(setter_rows,op),'native preview kit setter contract differs: '..op)
    end
    proofs[#proofs+1]={rva=detail,bytes=detail_raw};proofs[#proofs+1]={rva=setter,bytes=setter_raw}
    -- This is the actual tail target of the normal hover wrapper, with
    -- rcx=detail widget, edx=owned offer and r8b=equipped comparison. Calling
    -- it directly leaves the selected custom cell and scrollbar untouched.
    targets.preview_details=base+detail
    targets.detail_apply_hint=has(detail_rows,'lea rsi, [rbp+0x49f0]')
     and has(detail_rows,'lea edx, [r12+0x5]')and has(detail_rows,'mov rcx, rsi')
    local feedback_ok,feedback=pcall(function()
     local setter
     for i,row in ipairs(detail_rows)do if row.op=='lea edx, [r12+0x5]'then
      assert(detail_rows[i+1]and detail_rows[i+1].op=='mov rcx, rsi','Equip state receiver differs')
      local call=detail_rows[i+2]and detail_rows[i+2].op:match('^call 0x(%x+)$')
      assert(call and not setter,'Equip state setter ambiguous');setter=tonumber(call,16)
     end end
     assert(setter and inside(setter,281,true),'Equip state setter unavailable')
     local raw=read(base+setter,281);local body=decoder.decode(raw,setter,192)
     for _,op in ipairs({'mov edi, edx','mov rbx, rcx','mov [rbx+0x47b8], edx',
      'mov [rcx+0x47b8], edi','cmp byte [rcx+0x47b2], 0x0','mov byte [rcx+0x47b3], 0x0',
      'movss xmm2, [rbx+0x47b4]','mov edx, [rbx+0x47c8]','mov edx, [rbx+0x47c4]'})do
      assert(has(body,op),'Equip state setter ABI differs: '..op)
     end
     proofs[#proofs+1]={rva=setter,bytes=raw};return base+setter
    end)
    if feedback_ok then targets.equip_state=feedback end
    local widgets_ok,widget_proof=pcall(function()
     local stats,passive
     for i,row in ipairs(detail_rows)do
      if row.op=='lea rcx, [rbp+0xdff8]'and detail_rows[i+4]
       and detail_rows[i+1].op=='xor r9d, r9d'and detail_rows[i+2].op=='mov r8d, ebx'
       and detail_rows[i+3].op=='mov edx, ebx'then
       local at=detail_rows[i+4].op:match('^call 0x(%x+)$')
       assert(at and not stats,'native stat-widget edge ambiguous');stats=tonumber(at,16)
      end
      if row.op=='lea rcx, [rbp+0x21460]'and detail_rows[i+2]
       and detail_rows[i+1].op=='mov edx, ebx'then
       local at=detail_rows[i+2].op:match('^call 0x(%x+)$')
       assert(at and not passive,'native armor-passive edge ambiguous');passive=tonumber(at,16)
      end
     end
     assert(stats and passive and inside(stats,468,true)and inside(passive,830,true),'native stat/perk widget edges unavailable')
     local stats_raw=read(base+stats,468);local stats_rows=decoder.decode(stats_raw,stats,256)
     for _,op in ipairs({'mov [rcx+0x6308], esi','mov r12, r9','mov edi, r8d',
      'mov [rcx+0x6300], edx','mov [rcx+0x6304], r8d','mov r13, rcx',
      'mov ecx, [r15+0x1ce0]','lea rbp, [r15+0xb9ce4]','cmp [rbp+0x4], ebx',
      'lea r14, [r15+0xb9ce4]','cmp [r14+0x4], edi','cmp eax, +0x03',
      'mov ecx, [r14+0x8]','mov ecx, [rbp+0x8]','mov r8, rax','mov rdx, rax',
      'mov al, 0x1','xor al, al','ret'})do
      assert(has(stats_rows,op),'native stat-widget contract differs: '..op)
     end
     local passive_raw=read(base+passive,830);local passive_rows=decoder.decode(passive_raw,passive,512)
     for _,op in ipairs({'cmp [rcx+0x27e8], edx','mov [rcx+0x27e8], edx',
      'mov r8d, [r9+0xd1cf0]','mov r10d, [r9+0xd1cf4]','mov ecx, [r9+rax*4+0xd1d48]',
      'lea rcx, [r9+0xb9ce4]','cmp [rcx+rax*8+0x4], edx','mov esi, [rcx+0x1c]',
      'mov ecx, [r11+rax*4+0x30]','mov rax, [r11+0x20]','mov rsi, [rax+rcx*8]',
      'mov edx, [rsi+0x4]','lea rcx, [rbx+0x13d8]','mov rdx, [rsi+0x8]',
      'lea rcx, [rbx+0x1280]','mov rdi, [rsi+0x10]','mov eax, [rsi+0x18]',
      'lea rdi, [rbx+0x17a8]','mov r8d, 0x1000','mov [rbx+0x1748], eax','ret'})do
      assert(has(passive_rows,op),'native armor-passive contract differs: '..op)
     end
     return {stats=base+stats,passive=base+passive,
      proofs={{rva=stats,bytes=stats_raw},{rva=passive,bytes=passive_raw}}}
    end)
    if widgets_ok then
     targets.detail_stats=widget_proof.stats;targets.detail_passive=widget_proof.passive
     for _,proof in ipairs(widget_proof.proofs)do proofs[#proofs+1]=proof end
    else report('grid.variant_widgets',tostring(widget_proof))end
   elseif p.spec.name=='list_clear'then
    for _,op in ipairs({'mov rdi, rcx','mov esi, 0x6','mov ecx, 0x100',
     'mov [rdi+0x91f14], ebp','mov [rdi+0x92748], ebp',
     'mov [rdi+0x92960], rbp','mov [rdi+0x92968], ebp',
     'mov [rdi+0x92984], rbp','mov [rdi+0x9298c], ebp',
     'lea rcx, [rdi+0x9274c]','mov r8d, 0x18c','mov r8d, 0x400','ret'})do
     assert(has(rows,op),'native list clear contract differs: '..op)
    end
   elseif p.spec.name=='list_append'then
    for _,op in ipairs({'mov r11d, [rcx+0x92984]','cmp r11d, 0x100','mov ebx, r8d','mov r10, rcx',
     'mov [r10+rcx*4+0x92854], ebx','mov [r10+rcx*4+0x9274c], eax',
     'mov [r10+rcx*4+0x927d0], eax','inc dword [r10+0x92748]',
     'mov [rax+r10+0x92dc2], r9b','movzx eax, byte [rsp+0x50]',
     'mov [rcx+r10+0x92ec2], al','mov [r10+rax*4+0x92990], edx',
     'inc dword [r10+0x92984]','inc dword [r10+rax*4+0x92318]','ret'})do
     assert(has(rows,op),'native list append contract differs: '..op)
    end
   elseif p.spec.name=='list_finish'then
    for _,op in ipairs({'mov rbx, rcx','mov ecx, [rcx+0x91f14]','cmp ecx, 0x100',
     'mov [rbx+0x91f14], edx','movss [rbx+r9*4+0x91f18], xmm0',
     'cmp r9d, [rbx+r10*4+0x9274c]','imul rcx, rax, 0x688',
     'movss [rbx+r9*4+0x91f18], xmm1','addss xmm0, [rbx+0x92968]',
     'movss [rbx+0x92968], xmm0','mov dword [rbx+0x928e8], 0x0'})do
     assert(has(rows,op),'native list finish contract differs: '..op)
    end
    local tail=rows[#rows];local target=tail and tail.op:match('^jmp 0x(%x+)$')
    assert(target and targets.logical_solver and base+tonumber(target,16)==targets.logical_solver,'native finish solver relation differs')
   elseif p.spec.name=='position'then
    assert(has(rows,'movss xmm0, [rcx+0x4]')and has(rows,'movss xmm0, [rcx+0x8]')and has(rows,'mov rbx, rdx'),'native position ABI differs')
   elseif p.spec.name=='size'then
    assert(has(rows,'movss xmm0, [rcx+0xc]')and has(rows,'movss xmm0, [rcx+0x10]')and has(rows,'mov rbx, rdx'),'native size ABI differs')
   elseif p.spec.name=='animation_stop'then
    assert(has(rows,'movzx eax, byte [rcx]')and has(rows,'cmp eax, +0x07'),'native animation contract differs')
   elseif p.spec.name=='consume'then
    assert(has(rows,'mov r10, rcx')and has(rows,'mov r9, rdx')and has(rows,'mov byte [r11+r10+0x328], 0x0')
     and has(rows,'mov [r11+r10+0x32c], rbx')and has(rows,'mov [r11+r10+0x334], ebx')
     and has(rows,'mov r8d, 0x2')and has(rows,'mov rdx, r9'),'native input-consumption contract differs')
    local count=0
    for i,row in ipairs(rows)do
     local sign,delta=row.op:match('^mov rcx, %[rip([%+%-])0x(%x+)%]$')
     if delta then
      assert(rows[i+1],'input global instruction boundary unavailable')
      local rva=rows[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
      assert(inside(rva,8,false)and not inside(rva,8,true)and rva%8==0,'input global is not image data')
      input_global=base+rva;count=count+1
     end
    end
    assert(count==1,'input global ambiguous or unavailable')
   elseif p.spec.name=='highlight'then
    assert(has(rows,'mov r9d, [rcx+0x91f14]')and has(rows,'mov ecx, [rdi+rax*4+0x92318]')
     and has(rows,'cmp [rdi+rax*4+0x92990], edx')and has(rows,'mov [rdi+0x928e8], esi')
     and has(rows,'mov [rdi+0x928ec], ebx')and has(rows,'mov [rdi+0x92988], ebp')
     and has(rows,'mov al, 0x1')and has(rows,'xor al, al'),'native offer-highlight contract differs')
    local focused,focus_error=pcall(function()
     for _,op in ipairs({'imul rcx, rax, 0xaed0','add rcx, 0xb00','add rcx, rdi',
      'mov edx, 0xffffffff','mov edx, ebx','mov [rdi+0x928e4], r14d'})do
      assert(has(rows,op),'native exact-focus caller differs: '..op)
     end
     local callees={}
     for i,row in ipairs(rows)do
      local target=row.op:match('^call 0x(%x+)$')
      if target and rows[i-1]and rows[i-1].op=='add rcx, rdi'then callees[#callees+1]=tonumber(target,16)end
     end
     assert(#callees==2 and callees[1]==callees[2]and inside(callees[1],231,true),'native row-focus relation differs')
     local body=read(base+callees[1],231);local ops=decoder.decode(body,callees[1],128)
     for _,op in ipairs({'mov ebp, edx','mov rsi, rcx','cmp [rcx+0xaec0], edx',
      'mov [rcx+0xaec0], edx','cmp [rcx+0xaeb4], ebx','lea rdi, [rsi+0x110]',
      'imul rcx, rax, 0x2b68','movzx edx, word [rdi+0x2b5a]','cmp ebx, ebp',
      'setz al','and ax, r14w','or dx, +0x02','cmovnz dx, ax','mov [rdi+0x2b5a], dx',
      'cmp ebx, [rsi+0xaeb4]','ret'})do
      assert(has(ops,op),'native row-focus body differs: '..op)
     end
     assert(ops[#ops].op=='ret'and ops[#ops].rva==callees[1]+230,'native row-focus boundary differs')
     proofs[#proofs+1]={rva=callees[1],bytes=body};targets.focus_row=base+callees[1]
    end)
    if not focused then targets.focus_row=nil;report('grid.focus_row',tostring(focus_error))end
   elseif p.spec.name=='logical_solver'then
    for _,op in ipairs({'cmp dword [rcx+0x92748], +0x01','mov ecx, [rcx+0x91f14]',
      'movss xmm0, [rsi+r15*4+0x91f18]','add r13d, [rsi+r15*4+0x92318]',
      'subss xmm6, xmm0','cmp r13d, [rsi+rax*4+0x927d0]',
      'mov [rsi+0x928d8], r15d','movss [rsi+0x92964], xmm6'})do
     assert(has(rows,op),'native logical solver schema differs: '..op)
    end
    local extended=read(base+p.found,2700)
    local extended_rows=decoder.decode(extended,p.found,1024)
    if has(extended_rows,'mov [rsi+r8*4+0x92718], r15d')and has(extended_rows,'cmp r15d, [rsi+r8*4+0x92718]')then
     proofs[#proofs+1]={rva=p.found,bytes=extended};targets.logical_visible=true
    end
   elseif p.spec.name=='logical_groups'then
    for _,op in ipairs({'mov r8d, [r14+0x928e8]','cmp [r14+0x9274c], r8d',
      'cmp ecx, edx','lea esi, [rcx+0x1]','cmp [r14+rsi*4+0x9274c], r8d',
      'lea eax, [rsi-0x1]','mov [r14+0x928f0], eax'})do
     assert(has(rows,op),'native logical group schema differs: '..op)
    end
   elseif p.spec.name=='selection'then
    assert(has(rows,'mov r8d, [rdi+0x1f83b0]')and has(rows,'mov r9d, [rax+0x1ce0]')
     and has(rows,'add rax, 0x000b9ce4')and has(rows,'cmp [rax+0x4], r8d')
     and has(rows,'mov edx, [rax+0x8]')and has(rows,'mov [rdi+0x90], edx'),'native armor offer mapping differs')
    local count=0
    for i,row in ipairs(rows)do
     local sign,delta=row.op:match('^mov rax, %[rip([%+%-])0x(%x+)%]$')
     if delta then
      local rva=rows[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
      assert(inside(rva,8,false)and not inside(rva,8,true),'progression global outside data')
      progression_global=base+rva;count=count+1
     end
    end
    assert(count==1,'progression mapping ambiguous')
    -- The preceding native branch must explicitly route category 1 here.
    local first=math.max(4096,p.found-512);assert(inside(first,p.found-first,true),'selection branch outside code')
    local prior=read(base+first,p.found-first);local anchor=bytes('8b8fac831f0083e9010f84');local at,hits=1,0
    while true do
     local found=prior:find(anchor,at,true);if not found then break end
     if found+#anchor+3<=#prior then
      local delta=u32(prior,found+#anchor-1);if delta>=2147483648 then delta=delta-4294967296 end
      if first+found-1+#anchor+4+delta==p.found then hits=hits+1 end
     end
     at=found+1
    end
    assert(hits==1,'native category-1 armor branch not proven')
    proofs[#proofs+1]={rva=first,bytes=prior}
   elseif p.spec.name=='commit_source'then
    local entry
    for i,row in ipairs(rows)do
     if row.op=='mov [rdi+0x90], edx'and rows[i+1]and rows[i+2]and rows[i+3]
      and rows[i+1].op=='xor edx, edx'and rows[i+2].op=='mov rcx, rdi'then
      local value=rows[i+3].op:match('^call 0x(%x+)$');assert(value,'Armory commit edge changed')
      assert(not entry,'ambiguous Armory commit edge');entry=tonumber(value,16)
     end
    end
    assert(entry and inside(entry,250,true),'Armory commit function unavailable')
    local code=read(base+entry,250);proofs[#proofs+1]={rva=entry,bytes=code}
    local body=decoder.decode(code,entry,256)
    for _,op in ipairs({'mov eax, [rcx+0x90]','mov [rbx+0x40], eax','mov eax, [rcx+0x94]',
      'mov [rbx+0x44], eax','mov eax, [rcx+0x98]','mov [rbx+0x48], eax','lea rsi, [rcx+0x64]',
      'mov r8d, 0x2c','lea rbp, [rcx+0x38]','movups [rbp+0x0], xmm0','mov [rbp+0x28], eax'})do
     assert(has(body,op),'Armory commit profile contract changed: '..op)
    end
    local settings,players,apply
    for i,row in ipairs(body)do
     local sign,delta=row.op:match('^mov rbx, %[rip([%+%-])0x(%x+)%]$')
     if delta then assert(not settings,'ambiguous settings global');settings=body[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)end
     sign,delta=row.op:match('^mov rax, %[rip([%+%-])0x(%x+)%]$')
     if delta and body[i+1]and body[i+1].op=='cmp dword [rax+0x88], +0x00'then
      assert(not players,'ambiguous local-player global');players=body[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
     end
     if row.op=='mov rcx, rsi'and body[i+1]and body[i+2]and body[i+2].op=='movups xmm0, [rsi]'then
      local target=body[i+1].op:match('^call 0x(%x+)$');assert(target and not apply,'profile apply edge changed');apply=tonumber(target,16)
     end
    end
    assert(settings and players and inside(settings,8,false)and not inside(settings,8,true)
     and inside(players,8,false)and not inside(players,8,true)and apply and inside(apply,416,true),'commit global/callee contract changed')
    local profile_code=read(base+apply,416);proofs[#proofs+1]={rva=apply,bytes=profile_code}
    local profile_rows=decoder.decode(profile_code,apply,256)
    for _,op in ipairs({'mov rdi, rcx','mov ebx, edx','xor esi, esi','mov eax, [rdi+0x4]',
      'mov eax, [rdi+0x8]','mov eax, [rdi+0xc]','cmp dword [rcx+0x28], +0x01',
      'cmp dword [rcx+0x28], +0x02','cmp [rcx+0x28], esi'})do
     assert(has(profile_rows,op),'profile apply armor/helmet/cape contract changed: '..op)
    end
    commit_info={entry=base+entry,settings_global=base+settings,players_global=base+players}
   elseif p.spec.name=='thumbnail'then
    assert(has(rows,'mov rbx, rdx')and has(rows,'mov r8d, [rdx+0x2b80]'),'native thumbnail registry differs')
    local count=0
    for i,row in ipairs(rows)do
     local sign,delta=row.op:match('^mov rdx, %[rip([%+%-])0x(%x+)%]$')
     if delta then
      local rva=rows[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
      assert(inside(rva,8,false)and not inside(rva,8,true),'thumbnail global outside data')
      thumbnail_global=base+rva;count=count+1
     end
    end
    assert(count==1,'thumbnail global ambiguous')
   end
   end)
   if not valid then
    if not p.spec.optional then error(reason)end
    while #proofs>proof_count do table.remove(proofs)end
    targets[p.spec.name]=nil
    if p.spec.name=='selection'then progression_global=nil elseif p.spec.name=='thumbnail'then thumbnail_global=nil elseif p.spec.name=='commit_source'then commit_info=nil end
    report('grid.'..p.spec.name,tostring(reason))
   else report('grid.'..p.spec.name,'semantic proof verified')end
   end
  end
  assert(code_current(),'grid code changed during resolution')
  self.phase='ready';report('grid.bridge','resolved_current_image')
 end
 local worker=coroutine.create(resolve)
 local producer_scan
 function self:start_producer_scan()
  local ok,result=pcall(function()
   assert(self.phase=='ready'and targets.logical_solver and targets.highlight and code_current(),'current grid producer anchors unavailable')
   if not producer_scan then
    local inspector=NativeGridProducers or require('src.native_grid_producers')
    producer_scan=inspector.new({base=base,read=bridge.read,verify=code_current},
     {solver=targets.logical_solver-base,highlight=targets.highlight-base})
   end
   return producer_scan.phase
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 function self:producer_status()return producer_scan and producer_scan.phase or 'idle'end
 function self:producer_report()return producer_scan and producer_scan:report()or nil end
 function self:step_producer_scan()return producer_scan and producer_scan:step()or 'idle'end
 function self:step()
  if self.phase~='resolving'then
   if self.phase=='ready'and producer_scan and producer_scan.phase=='scanning'then producer_scan:step()end
   return self.phase,self.failure
  end
  deadline=os.clock()+.006
  local ok,why=coroutine.resume(worker)
  if not ok then self.phase='failed';self.failure=tostring(why);report('grid.bridge',self.failure)end
  return self.phase,self.failure
 end
 local function context(allow_hidden,scope_only)
  assert(bridge.verify(),'Armory UI proof changed')
  local watched,observed_bytes={},0;local function watch(at,n)
   observed_bytes=observed_bytes+n;assert(#watched<256 and observed_bytes<=196608,'grid observation budget exceeded')
   local raw=read(at,n);watched[#watched+1]={at=at,n=n,raw=raw};return raw end
  local function inactive_scope()
   assert(bridge.verify(),'UI proof changed during scope check')
   for _,span in ipairs(watched)do assert(read(span.at,span.n)==span.raw,'Equipment scope changed')end
   return false
  end
  local menu_slot=watch(bridge.menu_global,8);local menu=assert(pointer(menu_slot),'menu unavailable')
  local state=watch(menu+0x4294,32)
  local screen=u32(state,0);assert(screen==5 or screen==14,'not native Armor picker')
  local depth=u32(state,28);assert(depth>=1 and depth<=5 and u32(state,8+(depth-1)*4)==screen,'Armor picker stack changed')
  local manager_slot=watch(bridge.manager_global,8);local manager=assert(pointer(manager_slot),'UI manager unavailable')
  local owner,grid,payload,player_id
  if screen==14 then
   assert(bridge.deployment_picker_proven and targets.deployment_commit and code_current(),'Equipment layout proof unavailable')
   local bucket=watch(manager+0x62a0,24)
   if scope_only and u32(bucket,0)==0 then return inactive_scope()end
   assert(u32(bucket,0)==1 and u32(bucket,16)==0xe5,'Equipment controller unavailable')
   owner=assert(pointer(bucket,8),'Equipment controller invalid')
   local active=u32(watch(owner+8,4),0)==1 and watch(owner+0x273990,1)=='\1'
    and watch(owner+0x2808,1)=='\0'and u32(watch(owner+0x2818,4),0)==3
    and u32(watch(owner+0x281c,4),0)==0
   if scope_only and not active then return inactive_scope()end
   assert(active,'Equipment Armor picker unavailable')
   local slot=u32(watch(owner+0x27d0,4),0)
   assert(slot<4 and u32(watch(owner+0x27d4,4),0)==slot,'Equipment slot changed')
   local session=assert(pointer(watch(bridge.session_global,8)),'Equipment session unavailable')
   local peer=watch(session+0xb398,8)
   assert(peer~=string.rep('\0',8)and watch(owner+slot*0x9f0+0x9f8,8)==peer,'Equipment peer changed')
   payload=owner+slot*0x9f0+0x10
   local matched=false
   for i=0,3 do
    local card=owner+0x53a78+i*0x1ee18;local data=watch(card+0x1edf0,16)
    if pointer(data)==payload and u32(data,12)==slot then
     assert(not matched,'Equipment player card changed');matched=true
     player_id=u32(data,8);assert(player_id~=0xffffffff,'Equipment player unavailable')
    end
   end
   assert(matched,'Equipment local card unavailable')
   grid=owner+0xd2f20
  else
   local count=u32(watch(manager+0x166c,4),0);assert(count>=1 and count<=64,'UI registry bounds rejected')
   local rows=watch(manager+0x1670,count*16)
   for i=0,count-1 do if u32(rows,i*16+8)==224 then
    assert(not owner,'ambiguous Armory controller');owner=assert(pointer(rows,i*16),'invalid Armory controller')
   end end
   assert(owner,'Armory controller unavailable');grid=owner+GRID
  end
  local bar=watch(grid+272,164)
  local alpha=f32(bar,84);assert(alpha and alpha>=0 and alpha<=1.01,'native grid visibility invalid')
  if not allow_hidden then assert(alpha>=.95,'native Equipment grid hidden')end
  local root=watch(grid,20)
  local result={owner=owner,grid=grid,screen_kind=screen==14 and 'deployment'or 'armory',payload=payload,player_id=player_id,
   profile_address=payload or owner+0x38,profile_size=payload and 0x140 or 100,watched=watched,root=root,bar=bar,watch=watch}
  local function unchanged()
   if bridge.verify()~=true then return false end
   for _,item in ipairs(watched)do if bridge.read(item.at,item.n)~=item.raw then return false end end
   return true
  end
  result.unchanged=unchanged;return result
 end
 -- Native text widgets retain their own font, layout, clipping and draw order.
 local category_override
 function self:custom_headers(custom_count,selected)
  local ok,result=pcall(function()
   assert(targets.header_text and targets.category_text and targets.text_template and targets.text_string
    and code_current(),'native custom header proof unavailable')
   local ctx=context();local g=ctx.grid
   assert(u32(ctx.watch(g+0x92fc4,4),0)==4,'Armor grid required')
   local function widget(at,template)
    local raw=ctx.watch(at,0x2b0)
    assert(u32(raw,0x110)==template and raw:byte(0x269)<=14
     and pointer(raw,0xf8)and pointer(raw,0x2a8),'native text widget changed')
    return raw
   end
   local top=g-0x6d0+0x99998
   local top_raw=read(top,0x2b0);local top_key=u32(top_raw,0x110)
   if category_override and category_override.owner~=ctx.owner then category_override=nil end
   local tasks={}
   if selected then
    local checked=widget(top,top_key);local count=checked:byte(0x269)
    assert(count==0 or count==2 and u32(checked,0x118)==0x341f7711
     and u32(checked,0x130)==0x15d8f2e2,'native category parameter capacity changed')
    if top_key==0xddc08ca8 or top_key==0x1bc93550 or top_key==0x21debb1c then
     widget(top,top_key);category_override={owner=ctx.owner,key=top_key}
    elseif not(category_override and top_key==0x62181e42)then error('native category binding changed')end
    tasks[#tasks+1]={at=top,template=true}
   elseif category_override then
    if top_key==0x62181e42 then widget(top,top_key);tasks[#tasks+1]={at=top,restore=category_override.key}end
    category_override=nil
   end
   if custom_count and custom_count>0 then
    assert(custom_count<=256 and u32(ctx.watch(g+0x927d0,4),0)==0,'custom header range changed')
    local first=u32(ctx.watch(g+0x928d8,4),0)
    -- Visible logical row zero is independently checked by the caller.
    if first==0 and u32(ctx.watch(g+0x91f10,4),0)>0 then
     local at=g+0x83cc0+0x110;local raw=widget(at,0x62181e42)
     assert(raw:byte(0x269)==2 and u32(raw,0x118)==0x341f7711
      and u32(raw,0x130)==0x15d8f2e2,'native header parameters changed')
     tasks[#tasks+1]={at=at}
    end
   end
   assert(ctx.unchanged()and code_current(),'native header context changed')
   backend=backend or native()
   for _,task in ipairs(tasks)do
    if task.restore then assert(backend.text_template(targets.text_template,task.at,task.restore))
    else
     -- Both strings stay alive for the lifetime of the addon, not just this call.
     assert(backend.text_string(targets.text_string,task.at,0x341f7711,'Custom'))
     assert(backend.text_string(targets.text_string,task.at,0x15d8f2e2,'Variants'))
     if task.template then assert(backend.text_template(targets.text_template,task.at,0x62181e42))end
    end
   end
   return true
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 local offer_cache
 function self:snapshot(catalog_result)
  local ok,result=pcall(function()
   local ctx=context();local g,watch=ctx.grid,ctx.watch
   local count=u32(watch(g+600452,4),0);assert(count<=4096,'native item count rejected')
   local selected=u32(watch(g+600308,4),0);assert(selected==0xffffffff or selected<count,'native highlighted index rejected')
   local rows=u32(watch(g+597772,4),0);assert(rows<=12,'native visible-row bound rejected')
   local visible=watch(g+622656,8);local first,last=u32(visible,0),u32(visible,4)
   assert(first<=count and last<=count,'native visible-index bounds rejected')
   local out={status='read_only_grid_observed',identity_mapping_verified=false,selected_kit_id=nil,
    selected_index=selected==0xffffffff and -1 or selected,item_count=count,visible_first=first,visible_last=last,
    row_count=rows,kind=u32(watch(g+602052,4),0),anchor_index=u32(watch(g+602096,4),0),
    x=f32(ctx.root,4),y=f32(ctx.root,8),width=f32(ctx.root,12),height=f32(ctx.root,16),
    scale_x=f32(ctx.bar,100),scale_y=f32(ctx.bar,140),
    scroll=f32(watch(g+600416,4),0),content=f32(watch(g+600424,4),0),widgets={},records={}}
   for _,key in ipairs({'x','y','width','height','scroll','content'})do assert(finite(out[key]),'invalid grid '..key)end
   local known={};for _,record in pairs(catalog_result and catalog_result.records or {})do known[record.item_id]=record end
   out.appearance_previews={}
   local descriptor=bridge.read(ctx.grid-0x6d0+0x178c88,32)
   if type(descriptor)=='string'and #descriptor==32 then
    descriptor=watch(ctx.grid-0x6d0+0x178c88,32)
    out.native_view_mode=u32(descriptor,0);out.native_category=u32(descriptor,12);out.native_offer_id=ctx.payload and u32(watch(g+0x92988,4),0)or u32(descriptor,16);out.screen_kind=ctx.screen_kind
   end
   local offers={}
   if progression_global and code_current()then
    local progression=assert(pointer(watch(progression_global,8)),'progression unavailable')
    local n=u32(watch(progression+0x1ce0,4),0);assert(n>=1 and n<=4096,'offer bounds rejected')
    local entries=watch(progression+0xb9ce4,n*24)
    ctx.progression,ctx.progression_count,ctx.progression_entries=progression,n,entries
    -- Reuse only the decoding of byte-identical, freshly read evidence.
    -- Keep the bytes in this observation's watch set and recheck them below.
    if offer_cache and offer_cache.at==progression and offer_cache.entries==entries then
     offers=offer_cache.offers
    else
     for i=0,n-1 do
      local offer,kit=u32(entries,i*24+4),u32(entries,i*24+8)
      if offer~=0 then if offers[offer]and offers[offer]~=kit then offers[offer]=false elseif offers[offer]==nil then offers[offer]=kit end end
     end
     offer_cache={at=progression,entries=entries,offers=offers}
    end
    if out.native_view_mode==0 then
     local key=offers[out.native_offer_id]
     if key and known[key]and known[key].category==0 then
      out.selected_kit_id=ident(key);out.identity_mapping_verified=true
     end
    end
   end
   ctx.offers=offers
   if targets.highlight then
    out.logical_row_count=u32(watch(g+0x91f14,4),0)
    out.native_selected_offer=u32(watch(g+0x92988,4),0)
   end
   local thumbs
   if thumbnail_global and progression_global and code_current()then
    local manager=pointer(watch(thumbnail_global,8))
    if manager then
     local raw=watch(manager,12176)
     if u32(raw,11052)==7 then
      thumbs={}
      for card=0,5 do
       local off=card*1816;local state,n=u32(raw,off+1832),u32(raw,off+1836)
       assert(state<=8 and n<=15,'thumbnail card bounds rejected')
       for slot=0,n-1 do
        local item=off+32+slot*120;local kind=u32(raw,item+100)
        local offer,high=u32(raw,item+24),u32(raw,item+28)
        local kit=high==0 and kind>=2 and kind<=4 and offers[offer]or nil
        if kit and known[kit]and known[kit].category==0 and state==8 then
         thumbs[card*15+slot]={kit_id=ident(kit),offer=offer,manager=manager,item_address=manager+item,
          item_identity=raw:sub(item+25,item+32),kind=raw:sub(item+101,item+104),state_address=manager+off+1832}
        end
       end
      end
     end
    end
   end
   -- Ring-buffer index is explicitly diagnostic: no selected-index identity inference.
   local records=watch(g+602104,256*80)
   for index=0,255 do
    local at=index*80;local state=u32(records,at+8)
    if state==3 then
     local low,high=u32(records,at),u32(records,at+4)
     out.records[#out.records+1]={ring_index=index,state=state,card=u32(records,at+60),slot=u32(records,at+64),
      style=u32(records,at+72),visual_matches_known_kit=high==0 and known[low]and ident(low)or nil}
    end
   end
   out.headers={}
   if targets.logical_visible and code_current()then
    local header_count=u32(watch(g+0x91f10,4),0);assert(header_count<=33,'native visible header bound rejected')
    for i=0,header_count-1 do
     local raw=watch(g+0x83cc0+i*0x688,704)
     local rect=candidate_rect(raw,0)
     if rect and(f32(raw,84)or 0)>.95 then out.headers[#out.headers+1]={index=i,rect=rect}end
    end
   end
   local row_offsets,visible_map
   if targets.logical_visible and out.logical_row_count and out.logical_row_count<=128 then
    visible_map=watch(g+0x92718,rows*4);local counts=watch(g+0x92318,out.logical_row_count*4)
    row_offsets={};local first=0
    for i=0,out.logical_row_count-1 do row_offsets[i]=first;first=first+u32(counts,i*4)end
    assert(first==count,'native logical-to-visible item sum differs')
    local row=u32(watch(g+0x928e8,4),0);local column=u32(watch(g+0x928ec,4),0)
    if row_offsets[row]and column<u32(counts,row*4)then out.logical_selected_index=row_offsets[row]+column end
    out.first_visible_logical_row=u32(watch(g+0x928d8,4),0)
    out.logical_selected_group=u32(watch(g+0x928f0,4),0)
   end
   local owned_candidates={}
   for row=0,rows-1 do
    local rb=g+2816+row*44752;local columns=u32(watch(rb+44724,4),0);assert(columns<=4,'native row columns rejected')
    for column=0,columns-1 do
     local widget=rb+9192+column*11112;local tail=watch(widget+1984,24)
     local record=pointer(tail);local offset=record and record-(g+602104)or -1
     if offset>=0 and offset<256*80 and offset%80==0 then
      local header=watch(widget,704)
      local logical_row=visible_map and u32(visible_map,row*4)
      local logical_index=logical_row and row_offsets[logical_row]and row_offsets[logical_row]+column
      local observation={row=row,column=column,logical_row=logical_row,logical_index=logical_index,ring_index=offset/80,
       x=f32(header,4),y=f32(header,8),width=f32(header,12),height=f32(header,16),
       root_viewport_rect=candidate_rect(header,0),image_viewport_rect=candidate_rect(header,272),
       coordinate_space='candidate_viewport_bottom_left',hitbox_verified=false,rendering_verified=false,
       owned_identity_verified=false,
       image_alpha=f32(header,340),uv={f32(header,548),f32(header,552),f32(header,556),f32(header,560)},
       named_image_material=header:sub(609,616)==bytes('46e406554306ef27'),
       runtime_material_present=pointer(header,600)~=nil,bound=tail:byte(22)~=0}
      out.widgets[#out.widgets+1]=observation
      local rec=records:sub(offset+1,offset+80)
      local item=thumbs and thumbs[u32(rec,60)*15+u32(rec,64)]
      if item and out.native_view_mode==0 and u32(rec,8)==3 and observation.bound
       and observation.image_alpha and observation.image_alpha>.95
       and catalog_result and catalog_result.owned and catalog_result.owned[item.kit_id]==true then
       owned_candidates[item.kit_id]=owned_candidates[item.kit_id]or {}
       owned_candidates[item.kit_id][#owned_candidates[item.kit_id]+1]=observation
      end
      local material=pointer(header,600);local uv=out.widgets[#out.widgets].uv
      if item and material and tail:byte(22)~=0 and f32(header,340)>0.95
       and uv[1]and uv[2]and uv[3]and uv[4]and uv[1]>=0 and uv[2]>=0 and uv[3]>uv[1]and uv[4]>uv[2]and uv[3]<=1.001 and uv[4]<=1.001 then
       local material_bytes=header:sub(601,608);local binding=tail:sub(1,8)
       local widget_address=widget;local owner=ctx.owner
       out.appearance_previews[item.kit_id]={material_pointer=material,uv=uv,
        width=f32(header,12),height=f32(header,16),binding_verified=true,
        generation=tostring(out.selected_index)..':'..tostring(offset/80)..':'..tostring(item.offer),
        valid=function()
         local checked,current=pcall(context)
         return checked and current.owner==owner and code_current()
          and bridge.read(widget_address+1984,8)==binding and bridge.read(widget_address+600,8)==material_bytes
          and bridge.read(widget_address+548,16)==header:sub(549,564)
          and bridge.read(g+602104+offset,80)==rec
          and pointer(bridge.read(thumbnail_global,8))==item.manager
          and bridge.read(item.item_address+24,8)==item.item_identity
          and bridge.read(item.item_address+100,4)==item.kind
          and u32(bridge.read(item.state_address,4),0)==8
        end}
      end
     end
    end
   end
   -- A known catalog entry or cached owned flag cannot authorize a clickable
   -- identity. Expose only a fresh owned match, in bounded verification batches.
   -- Coordinates remain explicitly unverified even when identity is proven.
   if catalog_result and type(catalog_result.verify_owned)=='function'then
    local ids={};for id in pairs(owned_candidates)do ids[#ids+1]=id end;table.sort(ids)
    for first=1,#ids,16 do
     local batch={};for index=first,math.min(first+15,#ids)do batch[#batch+1]=ids[index]end
     local checked,owned=pcall(catalog_result.verify_owned,batch)
     if checked and owned==true then
      for _,id in ipairs(batch)do
       if catalog_result.owned[id]==true then
        for _,observation in ipairs(owned_candidates[id])do
         observation.bound_owned_kit_id=id;observation.owned_identity_verified=true
        end
       end
      end
     end
    end
   end
   assert(ctx.unchanged(),'native grid changed during observation')
   snapshots[out]=ctx;return out
  end)
  if not ok then return nil,tostring(result)end
  return result
 end
 -- Explicit diagnostic only; neither ordinary snapshots nor frame updates
 -- invoke this reader. The separate module has no mutation API.
 function self:inspect_model(catalog_result)
  local ok,result=pcall(function()
   assert(self.phase=='ready'and targets.highlight and targets.logical_solver and targets.logical_groups
    and progression_global and code_current(),'current logical model proof unavailable')
   local model=NativeGridModel or require('src.native_grid_model')
   local ctx=context();local watch=ctx.watch
   local descriptor=watch(ctx.grid-0x6d0+0x178c88,32)
   assert(u32(descriptor,0)==0,'native item view required')
   local progression=assert(pointer(watch(progression_global,8)),'progression unavailable')
   local n=u32(watch(progression+0x1ce0,4),0);assert(n>=1 and n<=4096,'offer bounds rejected')
   local raw=watch(progression+0xb9ce4,n*24);local mapping,known={},{}
   for _,record in pairs(catalog_result and catalog_result.records or {})do known[record.item_id]=record end
   for i=0,n-1 do
    local offer,kit=u32(raw,i*24+4),u32(raw,i*24+8)
    if offer~=0 then
     if mapping[offer]~=nil and mapping[offer]~=kit then mapping[offer]=false
     elseif mapping[offer]==nil then mapping[offer]=kit end
    end
   end
   local lookup={}
   for offer,kit in pairs(mapping)do if kit and known[kit]and known[kit].category==0 then
    local id=ident(kit);lookup[offer]={kit_id=id,owned=catalog_result.owned and catalog_result.owned[id]==true or false}
   end end
   assert(lookup[ctx.payload and u32(watch(ctx.grid+0x92988,4),0)or u32(descriptor,16)],'verified native Armor identity required')
   local out,why=model.capture(watch,ctx.grid,{schema_verified=true,offer_lookup=lookup,
    verify=function()return ctx.unchanged()and code_current()end,
    verify_owned=catalog_result and catalog_result.verify_owned})
   assert(out,why);return out
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 local function prepared()
  assert(self.phase=='ready'and code_current(),'native grid operations unavailable: '..tostring(self.code_failure or self.phase))
  backend=backend or native();return backend
 end
 -- Presentation constructors are optional and resolved from this image. The
 -- bridge is synchronous: only the mod's post-native-update callback may use it.
 function self:presentation_bridge(catalog_result,menu_token)
  local calls=prepared()
  for _,name in ipairs({'list_clear','list_append','list_finish','highlight'})do
   assert(targets[name]and calls.executable(targets[name]),'native presentation constructor unavailable: '..name)
  end
  local bound,sequence,active=nil,0,nil
  local function fingerprint(g)
   local n=u32(read(g+0x92984,4),0);local rows=u32(read(g+0x91f14,4),0);local groups=u32(read(g+0x92748,4),0)
   assert(n<=256 and rows<=256 and groups<=33,'native presentation bounds changed')
   return table.concat({read(g+4,16),read(g+0x91f14,4),read(g+0x92748,4),read(g+0x92984,4),
    read(g+0x92318,math.min(rows+1,256)*4),groups>0 and read(g+0x9274c,groups*4)or '',
    groups>0 and read(g+0x927d0,groups*4)or '',groups>0 and read(g+0x92854,groups*4)or '',
    n>0 and read(g+0x92990,n*4)or '',n>0 and read(g+0x92dc2,n)or '',n>0 and read(g+0x92ec2,n)or ''},'|')
  end
  local function same(t)
   if not(t and t==bound and code_current())then return false end
   local ok,c=pcall(context)
   return ok and c.owner==t.owner and c.grid==t.grid and u32(read(c.grid+0x92fc4,4),0)==4
    and read(c.grid+0x92fd1,1)=='\0'and u32(read(c.grid-0x6d0+0x178c88,4),0)==0
  end
  local function owns(t)return same(t)and fingerprint(t.grid)==t.fingerprint end
  local function changed(t)t.fingerprint=fingerprint(t.grid)end
  local function get_snapshot()
   local m,why=self:inspect_model(catalog_result);assert(m,why)
   local c=context();local g=c.grid
   assert(m.group_partition_verified and m.content_matches_height_sum,'native list partition unresolved')
   assert(u32(read(g+0x92fc4,4),0)==4 and read(g+0x92fd1,1)=='\0','normal Armor view required')
   local columns,base_height,header_height=0,nil,nil
   local starts={};for _,group in ipairs(m.groups)do starts[group.first_row]=true end
   for _,row in ipairs(m.rows)do
    columns=math.max(columns,row.item_count)
    if not starts[row.index]then
     assert(not base_height or math.abs(base_height-row.height)<.01,'nonuniform native row height');base_height=row.height
    end
   end
   assert(columns==3 and base_height,'normal three-column Armor rows required')
   for _,group in ipairs(m.groups)do
    local delta=m.rows[group.first_row+1].height-base_height
    assert(delta>0 and delta<=512 and(not header_height or math.abs(header_height-delta)<.01),'native header height differs')
    header_height=delta
   end
   local out={menu_token=tostring(menu_token),kind=4,compact=false,layout_verified=true,columns=columns,
    base_row_height=base_height,header_height=header_height,
    root_geometry={x=f32(c.root,4),y=f32(c.root,8),width=f32(c.root,12),height=f32(c.root,16)},
    entries=m.offers,rows={},groups={},item_count=m.item_count,row_count=m.row_count,group_count=m.group_count,
    content=m.content,selected_offer_id=m.selected_offer,marker_offer_id=m.marker_offer,scroll_value=m.scroll,
    verify=m.verify,selected_row=m.selected_row,selected_offer_matches=m.selected_offer_matches}
   for _,r in ipairs(m.rows)do out.rows[#out.rows+1]={count=r.item_count,first_item=r.first_item,height=r.height}end
   for _,r in ipairs(m.groups)do out.groups[#out.groups+1]={key=r.key,first_row=r.first_row,first_item=r.first_item}end
   return out,c
  end
  local bridge_out={capabilities={constructor_verified=true,input_capture_verified=true,view_restore_verified=true,update_boundary_verified=true}}
  bridge_out.snapshot=function()
   local s,c=get_snapshot();assert(s.scroll_value==0 and s.selected_offer_id~=0 and s.selected_offer_matches and s.selected_row==0,'open Armor at the top before custom presentation')
   -- A first-row selection can be restored with normal Highlight and zero scroll.
   local selected=false;for i=1,s.rows[1].count do if s.entries[i].offer_id==s.selected_offer_id then selected=true end end
   assert(selected,'first native row selection required for reversible presentation')
   s._owner=c.owner;s._grid=c.grid;s._fingerprint=fingerprint(c.grid);return s
  end
  bridge_out.verify=function(s)return s.verify()==true and fingerprint(s._grid)==s._fingerprint end
  bridge_out.verify_owned=function(ids)return catalog_result.verify_owned(ids)==true end
  bridge_out.begin=function(s)
   assert(bridge_out.verify(s),'presentation baseline changed');sequence=sequence+1
   bound={owner=s._owner,grid=s._grid,fingerprint=s._fingerprint,sequence=sequence,
    marker=s.marker_offer_id,original_selected=s.selected_offer_id,updating=true}
   active=bound;return bound
  end
  bridge_out.same_menu=same;bridge_out.owns=owns
  bridge_out.capture=function(enabled,t)
   if enabled then assert(same(t),'presentation menu changed');return self:consume_select()==true end
   return true
  end
  bridge_out.clear=function(t)
   assert(active==t and t.updating and owns(t),'presentation clear lease changed')
   calls.list_clear(targets.list_clear,t.grid);changed(t);t.finished=false
   return u32(read(t.grid+0x92984,4),0)==0 and u32(read(t.grid+0x92748,4),0)==0
  end
  bridge_out.append=function(t,entry)
   assert(active==t and t.updating and not t.finished and owns(t),'presentation append lease changed')
   local n=u32(read(t.grid+0x92984,4),0);assert(n<256,'presentation item cap')
   calls.list_append(targets.list_append,t.grid,entry.offer_id,entry.group_key,entry.flag_a,entry.flag_b);changed(t)
   return u32(read(t.grid+0x92984,4),0)==n+1 and u32(read(t.grid+0x92990+n*4,4),0)==entry.offer_id
  end
  bridge_out.finish=function(t)
   assert(active==t and t.updating and not t.finished and owns(t),'presentation finish lease changed')
   -- Normal population writes the equipped-marker offer before Finish.
   assert(calls.write_armor(t.grid+0x9298c,t.marker),'presentation marker restore rejected')
   t.finished=true;calls.list_finish(targets.list_finish,t.grid);changed(t);return true
  end
  bridge_out.restore_view=function(t,view,custom)
   assert(active==t and t.updating and owns(t)and view.scroll_value==0,'presentation view restore lease changed')
   local offer=custom and u32(read(t.grid+0x92990,4),0)or view.selected_offer_id
   assert(offer~=0 and calls.highlight(targets.highlight,t.grid,offer),'presentation highlight failed')
   t.view_offer=offer;changed(t);return true
  end
  bridge_out.view_matches=function(t,view,custom)
   return owns(t)and u32(read(t.grid+0x92988,4),0)==t.view_offer
    and u32(read(t.grid+0x9298c,4),0)==view.marker_offer_id and math.abs(f32(read(t.grid+0x92960,4),0))<.01
  end
  bridge_out.readback=function(t)assert(owns(t),'presentation readback lease changed');return get_snapshot()end
  bridge_out.end_update=function(t)assert(active==t,'presentation update owner changed');t.updating=false;active=nil;return true end
  bridge_out.resume_update=function(t)assert(owns(t)and not active,'presentation resume lease changed');active=t;t.updating=true;return true end
  return bridge_out
 end
 function self:input_scope()
  local ok,result=pcall(function()
   assert(self.phase=='ready'and code_current(),'native input scope proof unavailable')
   local raw=read(bridge.menu_global,8);local menu=assert(pointer(raw),'menu unavailable')
   local state=read(menu+0x4294,4);local screen=u32(state,0)
   if screen~=5 and screen~=14 then
    assert(read(bridge.menu_global,8)==raw and read(menu+0x4294,4)==state,'menu changed during scope check')
    return false
   end
   local ctx=context(true,true)
   if ctx==false then return false end
   local visible=f32(ctx.bar,84)>=.95
   local armor=u32(ctx.watch(ctx.grid+602052,4),0)==4
   if not visible or not armor then
    assert(ctx.unchanged()and code_current(),'native input scope changed');return false
   end
   local descriptor=ctx.watch(ctx.grid-0x6d0+0x178c88,16)
   local normal=u32(descriptor,0)==0 and descriptor:byte(7)==0 and u32(descriptor,12)==0
   assert(ctx.unchanged()and code_current(),'native input scope changed')
   return visible and armor and normal
  end)
  if not ok then return nil,tostring(result)end
  return result
 end
 function self:consume_select()
  local ok,result=pcall(function()
   local calls=prepared();assert(calls.executable(targets.consume),'input target not executable')
   local raw=read(input_global,8);local input=assert(pointer(raw),'input singleton unavailable')
   assert(read(input_global,8)==raw and code_current(),'input singleton or proof changed')
   return calls.consume(targets.consume,input)~=false
  end)
  if not ok or not result then return nil,ok and 'native input consume rejected'or tostring(result)end
  return true
 end
 self.consume=self.consume_select
 function self:idle_menu()
  local ok,result=pcall(function()
   assert(self.phase=='ready'and code_current(),'native menu proof unavailable')
   local slot=read(bridge.menu_global,8);local menu=assert(pointer(slot),'menu unavailable')
   local state=read(menu+0x4294,32)
   assert(read(bridge.menu_global,8)==slot and read(menu+0x4294,32)==state,'menu changed')
   return u32(state,0)==0 and u32(state,4)==0 and u32(state,28)==0
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 -- Startup refresh uses the already-proven native player armor setter. It
 -- changes only the live request; the persisted game profile retains its
 -- ordinary carrier ID throughout the temporary switch and restoration.
 function self:player_refresh_bridge(player,catalog,data_bridge,scene_guard)
  local ok,result=pcall(function()
   local info=targets.deployment_commit
   assert(self.phase=='ready'and info and code_current(),'native player armor setter unavailable')
   assert(info.profile_global==data_bridge.armor_catalog and data_bridge.verify(),
    'native armor manager proof differs')
   assert(type(scene_guard)=='function','startup scene guard required')
   local observations=setmetatable({},{__mode='k'})
   local function guard()
    return code_current()and data_bridge.verify()and self:idle_menu()==true and scene_guard()==true
   end
   local out={capabilities={commit_verified=true,cache_layout_verified=true}}
   function out.snapshot()
    if not guard()then return nil,'startup restoration requires an idle ship'end
    local actor,why=player:sample();if not actor then return nil,why end
    local slot=read(info.profile_global,8);local manager=assert(pointer(slot),'armor manager unavailable')
    local other={}
    for _,v in ipairs({actor.request,actor.current})do
     other[#other+1]=table.concat({v.body_type,v.helmet_id,v.cape_id},'|')
    end
    local pending=other[1]~=other[2]
    local state={session=tostring(actor.session_key),other_key=table.concat(other,'|'),pending_nonarmor=pending,
     controller_armor_id=actor.request_armor_id,profile_armor_id=actor.request_armor_id,
     request_armor_id=actor.request_armor_id,cache_armor_id=actor.cache_armor_id,cache_passive=actor.cache_passive_enum}
    local expected={};for k,v in pairs(state)do expected[k]=v end
    assert(guard()and actor.verify()and read(info.profile_global,8)==slot,'startup actor changed')
    observations[state]={actor=actor,slot=slot,manager=manager,expected=expected};return state
   end
   function out.verify(state)
    local saved=observations[state];if not saved or not guard()then return false end
    for k,v in pairs(saved.expected)do if state[k]~=v then return false end end
    for k,v in pairs(state)do if saved.expected[k]~=v then return false end end
    return read(info.profile_global,8)==saved.slot and saved.actor.verify()==true
   end
   function out.verify_owned(ids)return catalog.verify_owned(ids)==true end
   function out.owned_armors()
    local ids={};for id,owned in pairs(catalog.owned)do if owned then ids[#ids+1]=id end end;return ids
   end
   function out.commit_owned(id,state)
    local saved=observations[state]
    assert(saved and out.verify(state),'startup actor changed before native request')
    local record=catalog.records[id]
    assert(record and record.category==0 and catalog.owned[id]and catalog.verify_owned({id}),
     'startup armor ownership changed')
    local calls=prepared()
    assert(calls.executable(info.entry)and type(calls.deployment_commit)=='function','native armor setter unavailable')
    assert(calls.deployment_commit(info.entry,saved.manager,saved.actor.local_player_id,record.item_id)~=false,
     'native startup armor request failed')
    local after,why=player:sample();assert(after,why)
    assert(after.session_key==saved.actor.session_key and after.request_armor_id==id,
     'startup armor request readback differs')
    for _,part in ipairs({'request','current'})do
     for _,key in ipairs({'body_type','helmet_id','cape_id'})do
      assert(after[part][key]==saved.actor[part][key],'startup request changed other equipment')
     end
    end
    assert(guard()and read(info.profile_global,8)==saved.slot,'startup context changed during native request')
    return true
   end
   return out
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 function self:position(snapshot,x,y)
  local ok,result=pcall(function()
   assert(not movement,'restore the previous grid move first')
   assert(finite(x)and finite(y),'invalid grid position')
   local ctx=assert(snapshots[snapshot],'fresh grid snapshot required')
   assert(math.abs(x-snapshot.x)<=512 and math.abs(y-snapshot.y)<=512,'grid move exceeds UI bound')
   assert(ctx.unchanged(),'grid changed before positioning')
   local calls=prepared();assert(calls.executable(targets.position),'position target not executable')
   local active=read(ctx.grid+600320,4)
   if active:byte(3)~=0 then
    assert(active:byte(1)<=7 and calls.executable(targets.animation_stop),'animation contract unavailable')
    assert(calls.stop(targets.animation_stop,ctx.grid+600320)~=false,'animation stop rejected')
   end
   assert(code_current(),'grid code changed before position')
   local live=context();assert(live.owner==ctx.owner and live.grid==ctx.grid,'grid owner changed before position')
   movement={ctx=ctx,original_x=snapshot.x,original_y=snapshot.y,original_width=snapshot.width,original_height=snapshot.height,
    x=x,y=y,width=snapshot.width,height=snapshot.height}
   assert(calls.position(targets.position,ctx.grid,x,y)~=false,'native position rejected')
   local after=read(ctx.grid+4,8)
   assert(math.abs(f32(after,0)-x)<.01 and math.abs(f32(after,4)-y)<.01,'native position readback differs')
   return true
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 function self:restore_position()
  if not movement then return true end
  local ok,result=pcall(function()
   local live=context(true);assert(live.owner==movement.ctx.owner and live.grid==movement.ctx.grid,'grid owner changed; restoration refused')
   local current=read(live.grid+4,16)
   local names={'x','y','width','height'}
   for i,name in ipairs(names)do
    local value=f32(current,(i-1)*4)
    assert(finite(value)and (math.abs(value-movement[name])<.01 or math.abs(value-movement['original_'..name])<.01),'grid layout changed independently')
   end
   local calls=prepared();assert(calls.executable(targets.position),'position target not executable')
   if movement.resize then
    assert(targets.size and calls.executable(targets.size),'size target not executable')
    assert(calls.size(targets.size,live.grid,movement.original_width,movement.original_height)~=false,'native size restoration rejected')
   end
   assert(calls.position(targets.position,live.grid,movement.original_x,movement.original_y)~=false,'native restoration rejected')
   local after=read(live.grid+4,16)
   for i,name in ipairs(names)do assert(math.abs(f32(after,(i-1)*4)-movement['original_'..name])<.01,'native restoration readback differs')end
   movement=nil;return true
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 self.restore_layout=self.restore_position
 function self:reserve_top(height,snapshot)
  local ok,result=pcall(function()
   assert(finite(height)and height>=1 and height<=256,'reserved height must be 1..256 native units')
   assert(not movement,'restore the previous native reservation first')
   local calls=prepared();assert(targets.size and calls.executable(targets.size)and type(calls.size)=='function','native size setter unavailable')
   snapshot=snapshot or assert(self:snapshot())
   assert(snapshot.height-height>=160 and snapshot.width>=160,'reserved native viewport too small')
   local moved,why=self:position(snapshot,snapshot.x,snapshot.y-height);assert(moved,why)
   movement.resize=true;movement.height=snapshot.height-height
   assert(code_current(),'grid code changed before sizing')
   assert(calls.size(targets.size,movement.ctx.grid,snapshot.width,movement.height)~=false,'native size change rejected')
   local raw=read(movement.ctx.grid+4,16)
   assert(math.abs(f32(raw,0)-snapshot.x)<.01 and math.abs(f32(raw,4)-(snapshot.y-height))<.01
    and math.abs(f32(raw,8)-snapshot.width)<.01 and math.abs(f32(raw,12)-(snapshot.height-height))<.01,'native reserved viewport readback differs')
   return {status='native_layout_readback_verified',x=snapshot.x,y=snapshot.y-height,width=snapshot.width,
    height=snapshot.height-height,reserved=height,bottom=snapshot.y-snapshot.height,rendering_verified=false}
  end)
  if not ok then
   local original=tostring(result)
   if movement then local restored,why=self:restore_position();if not restored then original=original..'; restoration requires attention: '..tostring(why)end end
   return nil,original
  end
  return result
 end
 function self:select_kit(id,catalog_result,duplicate_presentations)
  local ok,result=pcall(function()
   assert(type(id)=='string'and id:match('^armor:%x%x%x%x%x%x%x%x$'),'stable armor identity required')
   local record=catalog_result and catalog_result.records and catalog_result.records[id]
   assert(record and record.category==0 and catalog_result.owned and catalog_result.owned[id]==true
    and type(catalog_result.verify_owned)=='function'and catalog_result.verify_owned({id})==true,'fresh owned armor required')
   local calls=prepared()
   assert(targets.highlight and progression_global and calls.executable(targets.highlight)and type(calls.highlight)=='function','native offer-highlight capability unavailable')
   local snapshot,why=self:snapshot(catalog_result);assert(snapshot,why)
   assert(snapshot.native_view_mode==0 and snapshot.identity_mapping_verified and snapshot.selected_kit_id,'open a verified native Armor item before selecting a variant')
   local ctx=assert(snapshots[snapshot]);local watch,g=ctx.watch,ctx.grid
   local rows=u32(watch(g+0x91f14,4),0);assert(rows>=1 and rows<=128,'native logical row bounds rejected')
   local counts=watch(g+0x92318,rows*4);local total=0
   for row=0,rows-1 do local n=u32(counts,row*4);assert(n<=8,'native row-item bounds rejected');total=total+n end
   assert(total==snapshot.item_count and total>=1 and total<=384,'native offer-list bounds differ')
   local list=watch(g+0x92990,total*4);local indices={}
   for i=0,total-1 do
    local offer=u32(list,i*4);assert(offer~=0 and(duplicate_presentations==true or not indices[offer]),'duplicate or empty native offer identity')
    indices[offer]=indices[offer]or i
   end
   local qualifying={};local count=assert(ctx.progression_count)
   for i=0,count-1 do
    local at=i*24;local entry=ctx.progression_entries
    local index,offer,kit=u32(entry,at),u32(entry,at+4),u32(entry,at+8)
    if kit==record.item_id and indices[offer]~=nil and ctx.offers[offer]==kit then
     assert(index<count,'owned offer index out of bounds')
     local state=ctx.progression+0x1ce4+index*184
     local status=u32(watch(state+0x14,4),0)
     if (status==2 or status==4)and watch(state+0xb4,1)=='\0'then qualifying[offer]=true end
    end
   end
   local chosen
   for i=0,total-1 do local offer=u32(list,i*4);if qualifying[offer]then chosen=offer;break end end
   assert(chosen,'no enabled owned offer for this armor is present in the native list')
   assert(ctx.unchanged()and code_current()and catalog_result.verify_owned({id})==true,'selection evidence or ownership changed')
   assert(calls.highlight(targets.highlight,g,chosen)==true,'native highlight rejected the offer')
   assert(code_current()and u32(read(g+0x92988,4),0)==chosen,'native highlighted offer readback differs')
   return {status='native_highlight_readback_verified',kit_id=id,offer_id=chosen,equipped=false,rendering_verified=false}
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 function self:focus_index(index,id,catalog_result)
  local ok,result=pcall(function()
   local calls=prepared()
   assert(targets.focus_row and targets.logical_visible and targets.logical_groups
    and calls.executable(targets.focus_row)and type(calls.focus_row)=='function'
    and type(calls.write_armor)=='function','native exact row-focus capability unavailable')
   local helper=NativeGridFocus or require('src.native_grid_focus')
   local bound_owner,bound_grid,initial,initial_ctx,protected
   local function observe()
    local model,why=self:inspect_model(catalog_result);assert(model,why)
    local ctx=context();local g,watch=ctx.grid,ctx.watch
    assert(u32(watch(g+0x92fc4,4),0)==4 and watch(g+0x92fd1,1)=='\0'
     and u32(watch(ctx.grid-0x6d0+0x178c88,4),0)==0,'normal native Armor focus required')
    if bound_owner then assert(ctx.owner==bound_owner and g==bound_grid,'native focus owner changed')end
    local n=u32(watch(g+0x91f0c,4),0);assert(n>=1 and n<=12,'native focus visible row bound rejected')
    local mapping=watch(g+0x92718,n*4)
    local visible={verified=true,logical_rows={},selected_slot=u32(watch(g+0x928e4,4),0),rows={}}
    for slot=0,n-1 do
     local logical=u32(mapping,slot*4);assert(logical<model.row_count,'native visible logical row changed')
     local at=g+0xb00+slot*0xaed0
     local count=u32(watch(at+0xaeb4,4),0)
     assert(count>=1 and count<=4 and count==model.rows[logical+1].item_count,'native focus row shape changed')
     local selected=u32(watch(at+0xaec0,4),0)
     assert(selected==0xffffffff or selected<count,'native row focus column rejected')
     local bits={}
     for column=0,count-1 do bits[column+1]=math.floor(watch(at+0x110+column*0x2b68+0x2b5a,1):byte()/2)%2 end
     visible.logical_rows[slot+1]=logical
     visible.rows[slot+1]={address=at,count=count,selected=selected,bits=bits}
    end
    local original_verify=model.verify
    model.focus_view=visible
    model.verify=function()return original_verify()==true and ctx.unchanged()and code_current()end
    assert(model.verify(),'native focus observation changed')
    return model,ctx
   end
   initial,initial_ctx=observe();bound_owner,bound_grid=initial_ctx.owner,initial_ctx.grid
   protected={profile=read(initial_ctx.profile_address,initial_ctx.profile_size),scroll=read(bound_grid+0x92960,4),
    scrollbar=read(bound_grid+0x110+0x7b8,4),marker=read(bound_grid+0x9298c,4)}
   local function preserved()
    local ctx=context()
    return ctx.owner==bound_owner and ctx.grid==bound_grid and code_current()
     and read(initial_ctx.profile_address,initial_ctx.profile_size)==protected.profile
     and read(bound_grid+0x92960,4)==protected.scroll
     and read(bound_grid+0x110+0x7b8,4)==protected.scrollbar
     and read(bound_grid+0x9298c,4)==protected.marker
   end
   local requested
   local focus_bridge={capabilities={exact_index_focus_verified=true,row_focus_verified=true,
    update_boundary_verified=true,input_capture_verified=true}}
   focus_bridge.verify=function(model)return model==initial and model.verify()==true and preserved()end
   focus_bridge.capture=function()return self:consume_select()==true end
   focus_bridge.focus_exact=function(plan)
    assert(focus_bridge.verify(initial),'native exact focus became stale')
    assert(catalog_result.verify_owned({id})==true,'native exact focus ownership changed')
    local target=plan.to;requested=target
    local rows=initial.focus_view.rows
    local old=plan.from.visible_slot~=nil and rows[plan.from.visible_slot+1]or nil
    local current=assert(rows[target.visible_slot+1],'native target row retired')
    assert(target.index==index and target.kit_id==id and target.column<current.count,'native focus plan identity changed')
    -- The native row helper owns child focus bits and their visual animations.
    -- The broader Highlight finalizer scrolls/rebinds rows, so do not call it.
    report('grid.focus.begin',id..':index='..index..':offer='..target.offer_id)
    if old then report('grid.focus.clear_begin',id);assert(calls.focus_row(targets.focus_row,old.address,0xffffffff)==true,'native old-row focus clear failed');report('grid.focus.clear_returned',id)end
    for _,field in ipairs({{0x928e4,target.visible_slot},{0x928e8,target.row},{0x928ec,target.column},
     {0x928f0,target.group},{0x92988,target.offer_id}})do
     assert(calls.write_armor(bound_grid+field[1],field[2])==true,'native exact focus mirror write rejected')
    end
    report('grid.focus.target_begin',id)
    assert(calls.focus_row(targets.focus_row,current.address,target.column)==true,'native target-row focus failed')
    report('grid.focus.target_returned',id)
    assert(preserved(),'native exact focus changed scroll, marker, profile, or owner')
    return true
   end
   focus_bridge.readback=function()
    assert(requested and preserved(),'native exact focus readback context changed')
    local after=observe()
    for slot,row in ipairs(after.focus_view.rows)do
     local expected=slot-1==requested.visible_slot and requested.column or 0xffffffff
     assert(row.selected==expected,'native visible row retains an unexpected focus')
     for column,bit in ipairs(row.bits)do
      assert(bit==(column-1==expected and 1 or 0),'native card focus bit readback differs')
     end
    end
    return after
   end
   local focused,why=helper.new(focus_bridge):select(initial,index,id);assert(focused,why)
   return focused
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 function self:selection_index()
  local ok,index=pcall(function()
   assert(self.phase=='ready'and targets.highlight and code_current(),'selection proof unavailable')
   local ctx=context();local g=ctx.grid
   assert(u32(ctx.watch(g+0x92fc4,4),0)==4,'normal Armor grid required')
   local rows=u32(ctx.watch(g+0x91f14,4),0);assert(rows>=1 and rows<=128,'selection row bounds rejected')
   local counts=ctx.watch(g+0x92318,rows*4)
   local selected=ctx.watch(g+0x928e8,8);local row,column=u32(selected,0),u32(selected,4)
   assert(row<rows and column<u32(counts,row*4),'selection is outside current rows')
   local flat=column;for i=0,row-1 do flat=flat+u32(counts,i*4)end
   assert(ctx.unchanged(),'selection changed during capture check');return flat
  end)
  if not ok then return nil,tostring(index)end;return index
 end
 -- The normal hover path updates only the detail/preview widgets. Apply
 -- remains the game's separate confirmation path and is never called here.
 function self:preview_kit(id,catalog_result,options)
  local ok,result=pcall(function()
   local calls=prepared();assert(targets.preview_notify and calls.executable(targets.preview_notify),'native look preview unavailable')
   options=options or {}
   local selected,why
   if options.focus_index~=nil then selected,why=self:focus_index(options.focus_index,id,catalog_result)
   else selected,why=self:select_kit(id,catalog_result,true)end
   assert(selected,why)
   local snapshot,reason=self:snapshot(catalog_result);assert(snapshot,reason)
   local ctx=assert(snapshots[snapshot]);local manager=ctx.grid-0x6d0
   local descriptor=ctx.watch(manager+0x178c88,32)
   assert(u32(descriptor,0)==0 and descriptor:byte(7)==0 and snapshot.kind==4,'normal unblocked Armor preview required')
   assert(snapshot.native_selected_offer==selected.offer_id,'native hover selection changed')
   local profile=ctx.watch(ctx.profile_address,ctx.profile_size)
   assert(ctx.unchanged()and code_current()and catalog_result.verify_owned({id})==true,'preview context changed')
   calls.preview_notify(targets.preview_notify,manager)
   local current=context()
   assert(current.owner==ctx.owner and current.grid==ctx.grid and code_current(),'native preview owner or code changed during notification')
   assert(read(ctx.profile_address,ctx.profile_size)==profile,'native hover unexpectedly changed a profile or selection mirror')
   assert(u32(read(ctx.grid-0x6d0+0x99d70+0xbe00c,4),0)==selected.offer_id,'native detail offer readback differs')
   assert(ident(u32(read(ctx.grid-0x6d0+0x99d70+0x20640+0xdc0,4),0))==id,'native large preview kit readback differs')
   return {status='native_preview_readback_verified',kit_id=id,offer_id=selected.offer_id,equipped=false,rendering_verified=false}
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 local function detail_context()
  assert(self.phase=='ready'and targets.preview_details and code_current(),'native detail preview unavailable')
  local ctx=context();local manager=ctx.grid-0x6d0
  local descriptor=ctx.watch(manager+0x178c88,32)
  assert(u32(descriptor,0)==0 and descriptor:byte(7)==0
   and u32(ctx.watch(ctx.grid+602052,4),0)==4,'normal unblocked Armor preview required')
  ctx.preview_manager=manager;ctx.detail_widget=manager+0x99d70
  return ctx
 end
 -- A small, fresh observation for the workflow's frame-separated same-kit
 -- refresh. This deliberately avoids thumbnail capture and never writes a
 -- sentinel to the game's preview cache.
 function self:detail_state()
  local ok,result=pcall(function()
   local ctx=detail_context();local watch=ctx.watch
   local out={status='native_detail_state_observed',
    offer_id=u32(watch(ctx.detail_widget+0xbe00c,4),0),
    kit_id=ident(u32(watch(ctx.detail_widget+0x20640+0xdc0,4),0)),
    stats_offer_id=u32(watch(ctx.detail_widget+0xdff8+0x6300,4),0),
    passive_offer_id=u32(watch(ctx.detail_widget+0x21460+0x27e8,4),0),
    equipped_offer_id=u32(watch(ctx.preview_manager+0x9305c,4),0)}
   assert(ctx.unchanged()and code_current(),'native detail state changed during observation')
   return out
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 -- Render the game's own description, comparison bars, passive icon/text and
 -- Apply view using the composed carrier. The custom grid item still points
 -- at its appearance donor, so changing the native selection here would move
 -- focus to a different row (and to the first duplicate look).
 -- requires_apply is a presentation hint: a changed composition needs Apply
 -- even when its carrier is already equipped. It never commits equipment.
 function self:preview_details(id,catalog_result,options)
  local ok,result=pcall(function()
   options=options or {};assert(type(options)=='table','native detail options required')
   assert(type(id)=='string'and id:match('^armor:%x%x%x%x%x%x%x%x$'),'stable armor identity required')
   local record=catalog_result and catalog_result.records and catalog_result.records[id]
   assert(record and record.category==0 and catalog_result.owned and catalog_result.owned[id]==true
    and type(catalog_result.verify_owned)=='function'and catalog_result.verify_owned({id})==true,'fresh owned armor required')
   local calls=prepared()
   assert(targets.preview_details and calls.executable(targets.preview_details)
    and type(calls.preview_details)=='function','native detail preview unavailable')
   assert(options.requires_apply~=true or targets.detail_apply_hint,'native Apply presentation proof unavailable')
   local ctx=detail_context();local watch=ctx.watch
   local progression=assert(pointer(watch(assert(progression_global,'owned offer mapping unavailable'),8)),'progression unavailable')
   local count=u32(watch(progression+0x1ce0,4),0);assert(count>=1 and count<=4096,'offer bounds rejected')
   local entries=watch(progression+0xb9ce4,count*24);local matches={};local chosen
   for i=0,count-1 do
    local at=i*24;local index,offer,kit=u32(entries,at),u32(entries,at+4),u32(entries,at+8)
    if offer~=0 then
     assert(not matches[offer]or matches[offer]==kit,'ambiguous native offer identity');matches[offer]=kit
     if kit==record.item_id then
      assert(index<count,'owned offer index out of bounds')
      local state=progression+0x1ce4+index*184;local status=u32(watch(state+0x14,4),0)
      if (status==2 or status==4)and watch(state+0xb4,1)=='\0'then chosen=chosen or offer end
     end
    end
   end
   assert(chosen,'no enabled owned offer for native details')
   local equipped=watch(ctx.preview_manager+0x9305c,4)
   local profile=watch(ctx.profile_address,ctx.profile_size)
   local selected=watch(ctx.grid+0x928e8,8);local highlighted=watch(ctx.grid+0x92988,8)
   local scroll=watch(ctx.grid+0x92960,8)
   local is_equipped=u32(equipped,0)==chosen and options.requires_apply~=true
   assert(ctx.unchanged()and code_current()and catalog_result.verify_owned({id})==true,'native detail context changed')
   report('grid.details.begin',id)
   local accepted=calls.preview_details(targets.preview_details,ctx.detail_widget,chosen,is_equipped)
   report('grid.details.returned',id)
   assert(accepted~=false,'native detail call rejected')
   local current=detail_context()
   assert(current.owner==ctx.owner and current.grid==ctx.grid,'native detail owner changed during notification')
   assert(read(ctx.profile_address,ctx.profile_size)==profile,'native details unexpectedly changed a profile or selection mirror')
   assert(read(ctx.grid+0x928e8,8)==selected and read(ctx.grid+0x92988,8)==highlighted
    and read(ctx.grid+0x92960,8)==scroll,'native details unexpectedly changed grid focus or scroll')
   assert(u32(read(ctx.detail_widget+0xbe00c,4),0)==chosen,'native detail offer readback differs')
   assert(ident(u32(read(ctx.detail_widget+0x20640+0xdc0,4),0))==id,'native large preview kit readback differs')
   assert(code_current(),'native detail proof changed during notification')
   return {status='native_preview_readback_verified',kit_id=id,offer_id=chosen,
    native_detail_view=true,native_apply_pending=options.requires_apply==true,
    selection_preserved=true,equipped=false,rendering_verified=false}
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 local function mask_armor(profile)return profile:sub(1,12)..profile:sub(17)end
 local function packed_u32(value)
  local out={};for i=1,4 do out[i]=string.char(value%256);value=math.floor(value/256)end;return table.concat(out)
 end
 local function scoped_passive(record,enum,catalog_result,calls,expected,callback)
  assert(type(enum)=='number'and enum%1==0 and enum>=0 and enum<=255,'verified passive enum required')
  assert(type(catalog_result.verify_session)=='function'and catalog_result.verify_session()==true,'current catalog session required')
  assert(read(record.address,64)==expected,'stat carrier changed before native widget preview')
  local original=expected:sub(29,32);local desired=packed_u32(enum)
  local scoped=expected:sub(1,28)..desired..expected:sub(33)
  local attempted=false
  local ok,result=pcall(function()
   if original~=desired then
    assert(type(calls.write_armor)=='function','scoped passive writer unavailable')
    report('grid.passive_scope.begin',ident(record.item_id)..':original='..u32(original,0)..':temporary='..enum)
    attempted=true
    assert(calls.write_armor(record.address+28,enum)==true,'scoped passive write failed')
    report('grid.passive_scope.written',ident(record.item_id))
   end
   assert(read(record.address,64)==scoped,'scoped passive readback differs')
   return callback()
  end)
  local restored,reason=true
  if attempted then
   restored,reason=pcall(function()
    assert(catalog_result.verify_session()==true,'catalog changed before passive restoration')
    local current=read(record.address,64)
    assert(current:sub(1,28)==expected:sub(1,28)and current:sub(33)==expected:sub(33),
     'stat carrier changed independently before passive restoration')
    for i=1,4 do local byte=current:byte(28+i)
     assert(byte==original:byte(i)or byte==desired:byte(i),'passive changed independently before restoration')
    end
    report('grid.passive_scope.restore_begin',ident(record.item_id))
    assert(calls.write_armor(record.address+28,u32(original,0))==true
     and read(record.address,64)==expected,'original passive restoration failed')
    report('grid.passive_scope.restored',ident(record.item_id))
   end)
  end
  assert(restored,'native preview passive recovery required: '..tostring(reason))
  assert(ok,result)
  assert(read(record.address,64)==expected,'native widget preview changed the stat carrier')
  return result
 end
 -- Saved browsing keeps the actor on an original owned appearance. Only the
 -- synchronous stat/perk widgets see a temporarily borrowed passive enum;
 -- body descriptors and packages are never changed to prepare this preview.
 function self:preview_variant_details(appearance_id,stats_id,passive_id,catalog_result,options)
  local ok,result=pcall(function()
   options=options or {};assert(type(options)=='table','native variant preview options required')
   local calls=prepared()
   assert(targets.detail_stats and targets.detail_passive and calls.executable(targets.detail_stats)
    and calls.executable(targets.detail_passive)and type(calls.detail_stats)=='function'
    and type(calls.detail_passive)=='function','native stat/perk widget proof unavailable')
   local key=type(stats_id)=='string'and stats_id:match('^native%-stats:(%x%x%x%x%x%x%x%x)$')
   local stats_kit_id=key and 'armor:'..key or stats_id
   local records=catalog_result and catalog_result.records
   local appearance=records and records[appearance_id];local stats=records and records[stats_kit_id]
   assert(appearance and appearance.category==0 and stats and stats.category==0,'owned Armor preview donors required')
   local passive=catalog_result.context and catalog_result.context.passive_variants
    and catalog_result.context.passive_variants[passive_id]
   assert(passive and type(passive.enum)=='number','exact passive preview unavailable')
   local donor_ids={};for id,entry in pairs(catalog_result.catalog or {})do
    if entry.passive_variant_id==passive_id and catalog_result.owned[id]==true and records[id]
     and u32(records[id].bytes,28)==passive.enum then donor_ids[#donor_ids+1]=id end
   end
   table.sort(donor_ids);local passive_donor=assert(donor_ids[1],'owned exact passive donor unavailable')
   local ids={appearance_id,stats_kit_id,passive_donor}
   for _,id in ipairs(ids)do assert(catalog_result.owned[id]==true,'variant preview donor is not owned')end
   assert(type(catalog_result.verify_owned)=='function'and catalog_result.verify_owned(ids)==true,'variant preview ownership changed')
   assert(type(catalog_result.verify_session)=='function'and catalog_result.verify_session()==true,'current catalog session required')
   local expected_appearance=read(appearance.address,64)
   local original_appearance=expected_appearance==appearance.bytes
   local function appearance_current()
    if read(appearance.address,64)~=expected_appearance then return false end
    if original_appearance then return true end
    -- A separate host proof must establish source_id==target_id==this look
    -- for its retained applied plan. A verified stats composition alone does
    -- not establish that the carrier still depicts its original appearance.
    return type(options.verify_appearance)=='function'
     and options.verify_appearance(appearance_id,expected_appearance)==true
     and expected_appearance:sub(1,28)==appearance.bytes:sub(1,28)
     and expected_appearance:sub(33,48)==appearance.bytes:sub(33,48)
   end
   assert(appearance_current(),
    'This look is currently used by an applied variant. Choose another look before changing it.')
   local expected=read(stats.address,64)
   assert(expected==stats.bytes or(type(options.verify_composition)=='function'
    and options.verify_composition(stats_kit_id,expected)==true),'stat carrier differs from its verified base profile')
   if expected:sub(49,64)~=stats.bytes:sub(49,64)then
    -- A live composition can change this appearance's weights. Native stat
    -- getters must read a pristine owned equivalent, never the modified donor
    -- and never a temporarily replaced visual/body descriptor.
    local profiles=catalog_result.context.stats_profiles or {}
    local function tuple(id)
     local p=profiles['native-stats:'..id:sub(7)]
     local v=p and p.base_values_verified==true and p.base_values
     if not v then return nil end
     local values={}
     for _,field in ipairs({'armor_rating','speed','stamina_regen'})do
      if type(v[field])~='number'then return nil end;values[#values+1]=v[field]
     end
     return table.concat(values,':')
    end
    local wanted=tuple(stats_kit_id);local candidates={}
    for id,record in pairs(records)do
     if wanted and id~=stats_kit_id and catalog_result.owned[id]==true and record.category==0
      and tuple(id)==wanted and read(record.address,64)==record.bytes then candidates[#candidates+1]=id end
    end
    table.sort(candidates)
    stats_kit_id=assert(candidates[1],'Original base stats need an unchanged owned equivalent before preview')
    stats=records[stats_kit_id];expected=stats.bytes;ids[#ids+1]=stats_kit_id
    assert(catalog_result.verify_owned(ids)==true,'Equivalent base-stat donor ownership changed')
   end
   assert(u32(expected,0)==stats.item_id and u32(expected,40)==0,'stat carrier identity or category changed')
   if options.widgets_only then
    local shown,why=self:detail_state()
    assert(shown and shown.kit_id==appearance_id,why or 'Selected model changed before widget refresh')
   else
    local selected,why
    if options.focus_index~=nil then selected,why=self:focus_index(options.focus_index,appearance_id,catalog_result)
    else selected,why=self:select_kit(appearance_id,catalog_result,true)end
    assert(selected,why)
    assert(appearance_current(),'appearance changed before native model preview')
    local shown,error=self:preview_details(appearance_id,catalog_result,{requires_apply=options.requires_apply~=false});assert(shown,error)
   end
   local ctx=detail_context();local watch=ctx.watch
   local progression=assert(pointer(watch(assert(progression_global,'owned offer mapping unavailable'),8)),'progression unavailable')
   local count=u32(watch(progression+0x1ce0,4),0);assert(count>=1 and count<=4096,'offer bounds rejected')
   local entries=watch(progression+0xb9ce4,count*24);local offers={}
   for i=0,count-1 do local at=i*24;local value,kit=u32(entries,at+4),u32(entries,at+8)
    if value~=0 then assert(not offers[value]or offers[value]==kit,'ambiguous native offer identity');offers[value]=kit end
   end
   -- The armor-passive binder searches this current filtered offer span, not
   -- every progression offer. Choose both bindings from that same real list.
   local bounds=watch(progression+0xd1cf0,8);local first,last=u32(bounds,0),u32(bounds,4)
   assert(first<last and last<=count,'native Armor offer span rejected')
   local indices=watch(progression+0xd1d48+first*4,(last-first)*4)
   local offer,alternate,alternate_id
   for i=0,last-first-1 do
    local at=u32(indices,i*4);assert(at<count,'native Armor offer index rejected')
    at=at*24;local index,value,kit=u32(entries,at),u32(entries,at+4),u32(entries,at+8)
    local id=ident(kit)
    if value~=0 and catalog_result.owned[id]==true and records[id]and records[id].category==0
     and((not offer and kit==stats.item_id)or(not alternate and kit~=stats.item_id))then
     assert(index<count,'owned offer index out of bounds')
     local state=progression+0x1ce4+index*184;local status=u32(watch(state+0x14,4),0)
     if (status==2 or status==4)and watch(state+0xb4,1)=='\0'then
      if kit==stats.item_id then offer=value else alternate=value;alternate_id=id end
     end
    end
   end
   assert(offer,'no enabled owned offer for native stat/perk widgets')
   local cached_passive=watch(ctx.detail_widget+0x21460+0x27e8,4)
   if u32(cached_passive,0)==offer then
    assert(alternate,'Another owned armor is needed to refresh the passive preview.')
    ids[#ids+1]=alternate_id
   end
   local profile=watch(ctx.profile_address,ctx.profile_size)
   local look=watch(appearance.address,64)
   assert(look==expected_appearance and appearance_current(),'appearance changed before native stat/perk widgets')
   assert(ctx.unchanged()and code_current()and catalog_result.verify_owned(ids)==true,'native variant widget context changed')
   scoped_passive(stats,passive.enum,catalog_result,calls,expected,function()
    report('grid.variant_stats.begin',stats_kit_id)
    assert(calls.detail_stats(targets.detail_stats,ctx.detail_widget+0xdff8,offer)~=false,'native stat widget update rejected')
    report('grid.variant_stats.returned',stats_kit_id)
    local live=detail_context();assert(live.owner==ctx.owner,'native menu changed before passive widget update')
    report('grid.variant_passive.begin',passive_id)
    if u32(cached_passive,0)==offer then
     report('grid.passive_refresh.begin',tostring(alternate))
     assert(calls.detail_passive(targets.detail_passive,ctx.detail_widget+0x21460,alternate)~=false,'native passive refresh rejected')
     report('grid.passive_refresh.returned',tostring(alternate))
     local current=detail_context();assert(current.owner==ctx.owner,'native menu changed during passive refresh')
     assert(u32(read(ctx.detail_widget+0x21460+0x27e8,4),0)==alternate,'native passive refresh readback differs')
    end
    assert(code_current()and catalog_result.verify_owned(ids)==true,'native passive preview evidence changed')
    report('grid.passive_bind.begin',tostring(offer)..':enum='..passive.enum)
    assert(calls.detail_passive(targets.detail_passive,ctx.detail_widget+0x21460,offer)~=false,'native passive widget update rejected')
    report('grid.passive_bind.returned',tostring(offer))
    assert(u32(read(ctx.detail_widget+0x21460+0x27e8,4),0)==offer,'native passive offer readback differs')
    local stat_offers=read(ctx.detail_widget+0xdff8+0x6300,8)
    assert(u32(stat_offers,0)==offer and u32(stat_offers,4)==offer,'native stat offers readback differs')
    report('grid.variant_passive.returned',passive_id)
    return true
   end)
   local live=detail_context();assert(live.owner==ctx.owner and live.grid==ctx.grid,'native variant preview owner changed')
   assert(read(ctx.profile_address,ctx.profile_size)==profile,'native variant preview changed player profile fields')
   assert(read(appearance.address,64)==look,'native variant preview changed the appearance kit')
   assert(ident(u32(read(ctx.detail_widget+0x20640+0xdc0,4),0))==appearance_id,'native variant preview changed the appearance model')
   assert(catalog_result.verify_owned(ids)==true,'variant preview ownership changed after widget update')
   return {status='native_variant_widgets_updated',kit_id=appearance_id,appearance_id=appearance_id,
    stats_kit_id=stats_kit_id,stats_offer_id=offer,passive_offer_id=offer,
    passive_variant_id=passive_id,native_detail_view=true,
    temporary_passive_restored=true,appearance_data_unchanged=true,equipped=false,rendering_verified=false}
  end)
  if not ok then report('grid.variant_preview.failed',result);return nil,tostring(result)end
  report('grid.variant_preview.complete',appearance_id);return result
 end
 -- Presentation only, after the coordinator has confirmed the armor/passive
 -- cache. Do not re-enter native Apply or restart the appearance preview.
 function self:equipment_feedback(id,catalog_result)
  local ok,result=pcall(function()
   local audio=targets.equipment_audio
   assert(targets.equip_state and audio and code_current(),'native Equip feedback unavailable')
   local calls=prepared()
   assert(type(calls.button_state)=='function'and type(calls.equipment_sound)=='function'
    and calls.executable(targets.equip_state)and calls.executable(audio.entry),'native Equip feedback backend unavailable')
   local committed,why=self:commit_snapshot(catalog_result);assert(committed,why)
   assert(committed.profile_armor_id==id and committed.controller_armor_id==id
    and not committed.pending_nonarmor,'armor changed before Equip feedback')
   local ctx=detail_context();local button=ctx.detail_widget+0x49f0
   local kit=ident(u32(ctx.watch(ctx.detail_widget+0x20640+0xdc0,4),0))
   assert(kit==id and catalog_result.verify_owned({id})==true,'selected armor changed before Equip feedback')
   local state=ctx.watch(button+0x47b8,4)
   local offer=u32(ctx.watch(ctx.detail_widget+0xbe00c,4),0)
   assert(offer and offer~=0 and audio.offers_global==progression_global,'native equipment sound offer unavailable')
   local progression=assert(pointer(ctx.watch(progression_global,8)),'native audio progression unavailable')
   local offer_count=u32(ctx.watch(progression+0x1ce0,4),0)
   assert(offer_count>=1 and offer_count<=4096,'native audio offer bounds rejected')
   local offers=ctx.watch(progression+0xb9ce4,offer_count*24);local matched=false
   for i=0,offer_count-1 do if u32(offers,i*24+4)==offer then
    assert(ident(u32(offers,i*24+8))==id,'native audio offer points to another item');matched=true
   end end
   assert(matched,'native audio offer has no item mapping')
   local catalog=assert(pointer(ctx.watch(audio.catalog_global,8)),'native audio catalog unavailable')
   local header=ctx.watch(catalog,12);local entries,count=pointer(header),u32(header,8)
   local record=catalog_result.records[id]
   assert(entries and count>0 and count<=4096 and record and record.slot_address
    and record.slot_address>=entries and record.slot_address<entries+count*8
    and (record.slot_address-entries)%8==0 and pointer(ctx.watch(record.slot_address,8))==record.address
    and ident(u32(ctx.watch(record.address,4),0))==id and u32(ctx.watch(record.address+40,4),0)==0,
    'native equipment audio category is not the verified body armor')
   local profile=ctx.watch(ctx.profile_address,ctx.profile_size)
   assert(ctx.unchanged()and self:verify_commit(committed)and code_current(),'Equip feedback context changed')
   if u32(state,0)==6 then return {status='native_equipped_feedback_already_set',sound_played=false}end
   assert(calls.button_state(targets.equip_state,button,6)~=false,'native equipped state rejected')
   local current=detail_context()
   assert(current.owner==ctx.owner and current.grid==ctx.grid and code_current()
    and read(ctx.profile_address,ctx.profile_size)==profile and u32(read(button+0x47b8,4),0)==6,
    'native equipped button readback differs')
   assert(calls.equipment_sound(audio.entry,ctx.grid,offer)~=false,'native equipment sound rejected')
   return {status='native_equipped_feedback_verified',sound_played=true}
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 function self:commit_capabilities()
  return {commit_verified=self.phase=='ready'and commit_info~=nil and code_current(),cache_layout_verified=false}
 end
 function self:commit_snapshot(catalog_result)
  local ok,result=pcall(function()
   assert(self.phase=='ready'and commit_info and code_current(),'native Armory commit proof unavailable')
   local view,why=self:snapshot(catalog_result);assert(view,why)
   assert(view.native_view_mode==0 and view.identity_mapping_verified,'verified native Armor context required')
   local ctx=assert(snapshots[view]);local watch=ctx.watch
   if ctx.payload then
    assert(targets.deployment_commit,'Equipment Apply unavailable')
    local players=assert(pointer(watch(commit_info.players_global,8)),'Equipment players unavailable')
    local n=u32(watch(players+0x84,4),0);assert(n>=1 and n<=4,'Equipment player bounds rejected')
    local local_player=assert(pointer(watch(players+0xe8,8)),'Equipment local player unavailable')
    assert(u32(watch(local_player+8,4),0)==ctx.player_id,'Equipment local player changed')
    local flags=u32(watch(players+0x3ac,4),0)
    assert(math.floor(flags/8)%2==0 and math.floor(flags/2048)%2==0,'Unready before applying a variant')
    local payload=watch(ctx.payload,0x9e0)
    local profile_slot=watch(targets.deployment_commit.profile_global,8)
    local profile=assert(pointer(profile_slot),'Equipment profile unavailable')
    local key=tostring(ctx.owner)..':'..tostring(ctx.payload)..profile_slot
    if key~=commit_session_key then commit_session_key=key;commit_session={}end
    local armor=ident(u32(payload,0x12c))
    local out={session=commit_session,local_player_id=ctx.player_id,controller_armor_id=armor,profile_armor_id=armor,
     other_key=payload:sub(1,0x12c)..payload:sub(0x131),pending_nonarmor=false}
    assert(ctx.unchanged()and code_current(),'Equipment snapshot changed')
    commit_snapshots[out]={ctx=ctx,payload=payload,profile=profile,player_id=ctx.player_id}
    return out
   end
   local old,current=watch(ctx.owner+0x38,44),watch(ctx.owner+0x64,44)
   local mirrors=watch(ctx.owner+0x90,12)
   local settings_slot=watch(commit_info.settings_global,8);local settings=assert(pointer(settings_slot),'native settings unavailable')
   local settings_fields=watch(settings+0x40,12)
   local player_slot=watch(commit_info.players_global,8);local players=assert(pointer(player_slot),'local-player manager unavailable')
   local counts=watch(players+0x84,8);local n,local_count=u32(counts,0),u32(counts,4)
   assert(n>=1 and n<=4 and local_count>=1 and local_count<=4,'local-player bounds rejected')
   local player=assert(pointer(watch(players+0xe8,8)),'local player unavailable')
   local player_id=u32(watch(player+8,4),0);assert(player_id~=0xffffffff,'local player sentinel rejected')
   local key=tostring(ctx.owner)..':'..settings_slot..player_slot..packed_u32(player_id)
   if key~=commit_session_key then commit_session_key=key;commit_session={}end
   local out={session=commit_session,local_player_id=player_id,
    controller_armor_id=ident(u32(current,12)),profile_armor_id=ident(u32(old,12)),
    other_key=mask_armor(old)..mask_armor(current)..mirrors..settings_fields,
    pending_nonarmor=mask_armor(old)~=mask_armor(current)or mirrors~=settings_fields}
   assert(ctx.unchanged()and code_current(),'commit snapshot changed')
   commit_snapshots[out]={ctx=ctx,current=current,old=old,mirrors=mirrors,settings=settings,settings_fields=settings_fields,player_id=player_id}
   return out
  end)
  if not ok then return nil,tostring(result)end;return result
 end
 function self:verify_commit(snapshot)
  local saved=commit_snapshots[snapshot]
  if not saved then return false end
  local ok,value=pcall(function()return code_current()and saved.ctx.unchanged()end)
  return ok and value==true
 end
 function self:commit_owned(id,expected,catalog_result)
  local attempted=false;local changed=false;local saved
  local ok,result=pcall(function()
   local record=catalog_result and catalog_result.records and catalog_result.records[id]
   assert(record and record.category==0 and catalog_result.owned and catalog_result.owned[id]==true
    and type(catalog_result.verify_owned)=='function'and catalog_result.verify_owned({id})==true,'fresh owned armor required for native commit')
   saved=assert(commit_snapshots[expected],'native commit snapshot required')
   if saved.ctx.payload then
    assert(self:verify_commit(expected),'Equipment changed before Apply')
    local info=assert(targets.deployment_commit);local calls=prepared()
    assert(calls.executable(info.entry)and type(calls.deployment_commit)=='function','Equipment commit backend unavailable')
    local at=saved.ctx.payload+0x12c;local desired=packed_u32(record.item_id)
    assert(catalog_result.verify_owned({id})==true,'Equipment ownership changed')
    changed=true;assert(calls.write_armor(at,record.item_id)==true and read(at,4)==desired,'Equipment armor assignment failed')
    local live=context();assert(live.owner==saved.ctx.owner and live.payload==saved.ctx.payload and code_current(),'Equipment changed before native call')
    local data=read(live.payload,0x9e0)
    assert(data==saved.payload:sub(1,0x12c)..desired..saved.payload:sub(0x131),'Unrelated Equipment changed')
    for _,span in ipairs(saved.ctx.watched)do
     local required=span.at==saved.ctx.payload and span.n==0x9e0 and data or span.raw
     assert(read(span.at,span.n)==required,'Equipment evidence changed after assignment')
    end
    assert(catalog_result.verify_owned({id})==true,'Equipment ownership changed before native call')
    attempted=true;assert(calls.deployment_commit(info.entry,saved.profile,saved.player_id,record.item_id)~=false,'Equipment native Apply failed')
    live=context();assert(live.owner==saved.ctx.owner and live.payload==saved.ctx.payload,'Equipment owner changed during Apply')
    assert(read(live.payload,0x9e0)==data and code_current(),'Equipment changed during Apply')
    return true
   end
   assert(not expected.pending_nonarmor and mask_armor(saved.old)==mask_armor(saved.current)
    and saved.mirrors==saved.settings_fields and self:verify_commit(expected),'native profile/ownership changed before commit')
   local calls=prepared();assert(commit_info and calls.executable(commit_info.entry)and type(calls.write_armor)=='function'and type(calls.commit)=='function','native commit backend unavailable')
   local at=saved.ctx.owner+0x70;local desired=packed_u32(record.item_id)
   assert(read(at,4)==saved.current:sub(13,16)and catalog_result.verify_owned({id})==true,'armor changed before native commit')
   if read(at,4)~=desired then
    changed=true
    assert(calls.write_armor(at,record.item_id)==true and read(at,4)==desired,'native controller armor assignment failed')
   end
   local current=read(saved.ctx.owner+0x64,44)
   assert(mask_armor(current)==mask_armor(saved.current)and read(saved.ctx.owner+0x90,12)==saved.mirrors
    and read(saved.settings+0x40,12)==saved.settings_fields and code_current(),'unrelated native profile changed before commit')
   for _,span in ipairs(saved.ctx.watched)do
    local required=span.raw
    if span.at==saved.ctx.owner+0x64 and span.n==44 then required=saved.current:sub(1,12)..desired..saved.current:sub(17)end
    assert(read(span.at,span.n)==required,'native commit inputs changed after assignment')
   end
   assert(catalog_result.verify_owned({id})==true,'ownership changed before native commit call')
   attempted=true;assert(calls.commit(commit_info.entry,saved.ctx.owner)~=false,'native commit call failed')
   local live=context();assert(live.owner==saved.ctx.owner and live.grid==saved.ctx.grid,'native UI changed during commit')
   local after_old,after_current=read(saved.ctx.owner+0x38,44),read(saved.ctx.owner+0x64,44)
   assert(u32(after_old,12)==record.item_id and u32(after_current,12)==record.item_id,'native committed armor readback differs')
   assert(mask_armor(after_old)==mask_armor(saved.old)and mask_armor(after_current)==mask_armor(saved.current)
    and read(saved.ctx.owner+0x90,12)==saved.mirrors and read(saved.settings+0x40,12)==saved.settings_fields,'native commit changed unrelated gear/cosmetics')
   assert(code_current(),'native commit proof changed')
   return true
  end)
  if not ok then
   -- Before any native call, restore only our own whole 32-bit UI assignment.
   -- Once the normal game commit was invoked, do not guess how far its engine
   -- request progressed; the frame coordinator must observe the resulting state.
   if changed and not attempted and saved then
    local restored,recovery=pcall(function()
    local live=context();assert(live.owner==saved.ctx.owner and code_current())
    if saved.ctx.payload then
     assert(live.payload==saved.ctx.payload,'Equipment payload changed before recovery')
     -- Matching addresses alone do not preserve the player: the game may
     -- reuse this controller/payload for another peer. Recheck the original
     -- evidence, including session, peer, player card and profile pointer.
     -- Only our armor assignment may differ from the captured journal.
     for _,span in ipairs(saved.ctx.watched)do
      if not(span.at==saved.ctx.payload and span.n==0x9e0)then
       assert(read(span.at,span.n)==span.raw,'Equipment identity/evidence changed before recovery')
      end
     end
     assert(live.unchanged(),'Equipment changed during recovery checks')
     local at=live.payload+0x12c;local record=catalog_result.records[id]
     if read(at,4)==packed_u32(record.item_id)then
      assert(prepared().write_armor(at,u32(saved.payload,0x12c))==true
       and read(at,4)==saved.payload:sub(0x12d,0x130),'Equipment recovery failed')
     end
     return
    end
    local at=live.owner+0x70;local record=catalog_result.records[id]
    if read(at,4)==packed_u32(record.item_id)then
     backend.write_armor(at,u32(saved.current,12))
    end
    end)
    if not restored then result=tostring(result)..'; recovery refused or unverified: '..tostring(recovery)end
   end
   return nil,tostring(result)
  end
  return result
 end
 function self:release_view()
  if not movement then return true,'no native reservation' end
  local restored,why=self:restore_position()
  if restored then return true,'original native layout restored' end
  -- A removed controller owns no live layout to restore. Forget only after
  -- observing its absence from the current guarded registry; never dereference it.
  local ok,retired=pcall(function()
   assert(bridge.verify(),'UI proof changed')
   local slot=read(bridge.manager_global,8);local manager=assert(pointer(slot),'UI manager unavailable')
   local n=u32(read(manager+0x166c,4),0);assert(n<=64,'UI registry bound rejected')
   local raw=n>0 and read(manager+0x1670,n*16)or ''
   for i=0,n-1 do if u32(raw,i*16+8)==224 and pointer(raw,i*16)==movement.ctx.owner then return false end end
   assert(read(bridge.manager_global,8)==slot and u32(read(manager+0x166c,4),0)==n
    and (n==0 or read(manager+0x1670,n*16)==raw)and bridge.verify(),'registry changed while releasing layout')
   movement=nil;snapshots=setmetatable({}, {__mode='k'});return true
  end)
  if ok and retired then return true,'retired native owner discarded; no stale write' end
  return nil,why
 end
 function self:layout_active()return movement~=nil end

 return self
end
function M.format(result)
 local out={'HD2TM_ARMORY_GRID 1','identity_mapping_verified='..tostring(result.identity_mapping_verified),
  'selected_kit_id='..tostring(result.selected_kit_id)}
 for _,key in ipairs({'status','selected_index','item_count','visible_first','visible_last','row_count','kind','anchor_index','x','y','width','height','scroll','content','scale_x','scale_y','native_view_mode','native_category','native_offer_id','logical_row_count','native_selected_offer','logical_selected_index','first_visible_logical_row'})do out[#out+1]=key..'='..tostring(result[key])end
 for _,header in ipairs(result.headers or {})do local r=header.rect;out[#out+1]=string.format('header index=%d x=%s y=%s width=%s height=%s',header.index,r.x,r.y,r.w,r.h)end
 for _,record in ipairs(result.records or {})do
  out[#out+1]=string.format('record ring=%d state=%d card=%d slot=%d style=%d known_kit=%s',record.ring_index,record.state,record.card,record.slot,record.style,tostring(record.visual_matches_known_kit or 'unproven'))
 end
 for _,widget in ipairs(result.widgets or {})do
  out[#out+1]=string.format('widget row=%d column=%d ring=%d x=%s y=%s width=%s height=%s alpha=%s named_material=%s runtime_material=%s bound=%s',widget.row,widget.column,widget.ring_index,tostring(widget.x),tostring(widget.y),tostring(widget.width),tostring(widget.height),tostring(widget.image_alpha),tostring(widget.named_image_material),tostring(widget.runtime_material_present),tostring(widget.bound))
  out[#out+1]='widget_logical row='..widget.row..' column='..widget.column..' logical_row='..tostring(widget.logical_row)..' logical_index='..tostring(widget.logical_index)
  out[#out+1]=string.format('widget_identity row=%d column=%d owned_kit=%s owned_verified=%s hitbox_verified=false rendering_verified=false coordinate_space=candidate_viewport_bottom_left',
   widget.row,widget.column,tostring(widget.bound_owned_kit_id or 'unproven'),tostring(widget.owned_identity_verified==true))
  for _,field in ipairs({'root_viewport_rect','image_viewport_rect'})do
   local rect=widget[field]
   if rect then
    out[#out+1]=string.format('widget_rect row=%d column=%d source=%s x=%s y=%s width=%s height=%s scale_x=%s scale_y=%s',
     widget.row,widget.column,field,tostring(rect.x),tostring(rect.y),tostring(rect.w),tostring(rect.h),tostring(rect.scale_x),tostring(rect.scale_y))
   else out[#out+1]=string.format('widget_rect row=%d column=%d source=%s unavailable=true',widget.row,widget.column,field)end
  end
 end
 local ids={};for id in pairs(result.appearance_previews or {})do ids[#ids+1]=id end;table.sort(ids)
 for _,id in ipairs(ids)do out[#out+1]='preview id='..id..' binding_verified=true' end
 return table.concat(out,'\n')..'\n'
end
return M
