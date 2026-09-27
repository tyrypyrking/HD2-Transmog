-- Read-only UI probe. Exact instruction facts are in compat_spec.lua.
-- Contract: sample() advances initialization by AT MOST ONE 256KiB code chunk
-- per call and returns nil,'resolving' until the scan completes; terminal
-- scan failures throw once and stay terminal (parent logs/retries with backoff).
-- Layout-offset evidence: the five data-global anchors do NOT validate the
-- probe's structural offsets. Those are gated by the layout instruction
-- anchors in compat_spec.lua, each of which encodes the constants the probe
-- reads: loadout_registration (manager+0x62a0 bucket, type 0xE5, owner ptr),
-- loadout_flags/loadout_state (owner+0x273990/0x2808 transition flags),
-- local_slot (owner+0x27d0 slot<4), record_peer (session+0xb398 peer),
-- loadout_payload/player_card_address/player_card_payload (card graph
-- 0x53a78/0x1ee18/0x1edf0/0x1edfc/0x9f0), loadout_view_setter/
-- loadout_view_stratagems (owner+8 view==1), equipment_button_owner/size/
-- top_attachment (card+0x1b820 widget rect). All must match uniquely or
-- resolution fails; a match validates that the compiler build still lays out
-- the structures the offsets assume. Guards make stale reads *unlikely*, not
-- impossible: guarded nils are reported as inactive, never as data.
local M={}
local ffi,bit=require('ffi'),require('bit')
local spec_default=CompatSpec or require('src.compat_spec')
local MAX=262144
local function u16(s,o)
 if not s or #s<o+2 then return nil end
 local a,b=s:byte(o+1,o+2);return a+256*b
end
local function u32(s,o)
 if not s or #s<o+4 then return nil end
 local a,b,c,d=s:byte(o+1,o+4);return a+256*b+65536*c+16777216*d
end
local function ptr(s,o)
 o=o or 0;local lo,hi=u32(s,o),u32(s,o+4)
 if not hi or hi>=32768 then return nil end
 local n=lo+hi*4294967296;return n>=65536 and n or nil
end
local function unhex(s)return(s:gsub('%x%x',function(v)return string.char(tonumber(v,16))end))end
local function hash(s)
 if not s or #s~=8 or s==string.rep('\0',8) then return nil end
 local t={};for i=8,1,-1 do t[#t+1]=string.format('%02x',s:byte(i))end;return table.concat(t)
end
local function float(s,o)
 local n=u32(s,o);if not n then return nil end
 local sign=1;if n>=2147483648 then sign=-1;n=n-2147483648 end
 local e,m=math.floor(n/8388608),n%8388608
 if e==255 then return nil end
 if e==0 then return sign*m*2^-149 end
 return sign*(1+m/8388608)*2^(e-127)
end
local function native()
 for _,d in ipairs({'void *GetModuleHandleA(const char*);','void *GetCurrentProcess(void);',
 'int ReadProcessMemory(void*,const void*,void*,size_t,size_t*);'})do pcall(ffi.cdef,d)end
 local k=ffi.load('kernel32');local process=k.GetCurrentProcess();local base=k.GetModuleHandleA('game.dll')
 assert(base~=nil,'game.dll unavailable')
 local buf,count=ffi.new('uint8_t[?]',MAX),ffi.new('size_t[1]')
 return {base=tonumber(ffi.cast('uintptr_t',base)),read=function(at,n)
  count[0]=0
  if k.ReadProcessMemory(process,ffi.cast('const void*',at),ffi.cast('void*',buf),n,count)==0 or tonumber(count[0])~=n then return nil end
  return ffi.string(buf,n)
 end}
end
function M.new(engine,report,bridge,spec,target)
 target=target or 'armory'
 assert(target=='armory' or target=='deployment' or target=='catalog','unknown adapter target')
 report=report or function()end;bridge=bridge or native();spec=spec or spec_default
 local base=assert(bridge.base);local self={phase='resolving'};local globals,proofs={},{};local deployment_picker_proven=false;local deadline=0
 local function read(at,n)
  if type(at)~='number' or at<65536 or at+n>=140737488355328 or n<1 or n>MAX or n%1~=0 then return nil end
  local s=bridge.read(at,n);return type(s)=='string' and #s==n and s or nil
 end
 local function image(rva,n)return assert(read(base+rva,n),'unreadable module bytes')end
 local function resolve()
  local dos=image(0,64);assert(dos:sub(1,2)=='MZ','bad MZ')
  local pe=u32(dos,60);assert(pe>=64 and pe<=65536,'bad PE offset')
  local nt=image(pe,88);assert(nt:sub(1,4)=='PE\0\0' and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'expected PE64')
  local count,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(count>=1 and count<=96 and opt>=112 and opt<=4096 and size>=4096 and size<=536870912,'bad PE bounds')
  local sections={}
  for i=0,count-1 do
   local h=image(pe+24+opt+i*40,40);local len,rva,flags=u32(h,8),u32(h,12),u32(h,36)
   if len>0 then
    assert(rva>=4096 and rva+len<=size,'bad section bounds')
    for _,s in ipairs(sections)do assert(rva+len<=s.rva or rva>=s.rva+s.size,'overlapping sections')end
    sections[#sections+1]={rva=rva,size=len,read=bit.band(flags,0x40000000)~=0,exec=bit.band(flags,0x20000000)~=0}
   end
  end
  local patterns,overlap={},0
  for _,s in ipairs(spec)do
   local p={s=s,bytes=unhex(s.hex),mask=unhex(s.mask),anchor=unhex(s.anchor)}
   assert(#p.bytes==#p.mask and #p.anchor>0,'bad pattern');patterns[#patterns+1]=p;overlap=math.max(overlap,#p.bytes-1)
  end
  local function matches(p,data,at)
   if at<1 or at+#p.bytes-1>#data then return false end
   for i=1,#p.bytes do if p.mask:byte(i)~=0 and data:byte(at+i-1)~=p.bytes:byte(i)then return false end end
   return true
  end
  local total=0
  for _,s in ipairs(sections)do if s.exec then
   assert(s.read,'unreadable code section');total=total+s.size;assert(total<=134217728,'scan budget exceeded')
   local tail=''
   for offset=0,s.size-1,MAX do
    local data=tail..image(s.rva+offset,math.min(MAX,s.size-offset));local origin=s.rva+offset-#tail
    for _,p in ipairs(patterns)do
     if os.clock()>=deadline then coroutine.yield() end
      local at,hits=1,0
     while true do
      local hit=data:find(p.anchor,at,true);if not hit then break end
      hits=hits+1;assert(hits<=4096,'ambiguous anchor '..p.s.name)
      local start=hit-p.s.anchor_offset
      if matches(p,data,start)then
       local rva=origin+start-1
       if p.found and p.found~=rva then
        if p.s.optional then p.ambiguous=true else error('ambiguous signature '..p.s.name)end
       end
       p.found=rva;p.actual=data:sub(start,start+#p.bytes-1)
      end
      at=hit+1;if os.clock()>=deadline then coroutine.yield() end
     end
    end
    tail=data:sub(math.max(1,#data-overlap+1));coroutine.yield() -- one chunk per resume
   end
  end end
  assert(total>0,'no executable section')
  for _,p in ipairs(patterns)do
   if not p.found or p.ambiguous then
    assert(p.s.optional,'unsupported UI layout: '..p.s.name..' missing')
    report('adapter.optional_unavailable',p.s.name)
   else
   assert(image(p.found,#p.actual)==p.actual,'code changed during scan')
   report('adapter.pattern.'..p.s.name,string.format('0x%08x',p.found))
   proofs[#proofs+1]={rva=p.found,bytes=p.actual}
   if p.s.name=='deployment_picker_grid'then deployment_picker_proven=true end
   for _,e in ipairs(p.s.extracts)do
    local v=e.size==1 and p.actual:byte(e.offset+1)or u32(p.actual,e.offset);local limit=e.size==1 and 256 or 4294967296
    if v>=limit/2 then v=v-limit end
    local rva=p.found+e['end']+v+e.adjust;local valid=false
    for _,s in ipairs(sections)do if s.read and not s.exec and rva>=s.rva and rva+8<=s.rva+s.size then valid=true end end
    assert(valid,'invalid data global '..e.symbol)
    assert(not globals[e.symbol] or globals[e.symbol]==rva,'conflicting data global '..e.symbol);globals[e.symbol]=rva
   end
   end
  end
  local required=target=='catalog' and {'armor_catalog','progression'} or {'manager','session','font','atlas','material'}
  for _,k in ipairs(required)do assert(globals[k],'missing '..k)end
  if target=='armory' then assert(globals.armory_menu,'Armory menu global unresolved') end
  self.pe_timestamp=u32(nt,8)
  self.phase='ready';report('adapter.pe_timestamp',self.pe_timestamp);report('adapter.patterns',#patterns);report('adapter.status','resolved')
 end
 local worker=coroutine.create(resolve)
 local function armory_probe()
  if not globals.armory_menu then return nil,'Armory menu signature unavailable' end
  local observed={}
  local function watch(at,n)
   local s=read(at,n);if s then observed[#observed+1]={at=at,n=n,s=s} end;return s
  end
  local menu_bytes=watch(base+globals.armory_menu,8)
  local menu=ptr(menu_bytes);if not menu then return nil,'Armory menu unavailable' end
  -- +0x4294 is encoded in BOTH newly resolved instruction signatures.
  local state_bytes=watch(menu+0x4294,4);local state=u32(state_bytes,0)
  if state==nil then return nil,'Armory state unreadable' end
  if state~=5 and state~=14 then
   if read(base+globals.armory_menu,8)~=menu_bytes or read(menu+0x4294,4)~=state_bytes then return nil,'Armory state transitioning'end
   return nil,'not ship Armory'
  end
  -- Secondary corroboration from the reference menu-stack reader, not a fallback.
  local stack=watch(menu+0x429c,24);local depth=u32(stack,20)
  if not depth or depth<1 or depth>5 or u32(stack,(depth-1)*4)~=state then return nil,'Armory stack transitioning' end
  local mb=watch(base+globals.manager,8);local manager=ptr(mb)
  if not manager then return nil,'UI dispatch unavailable' end
  local controller,grid,screen_kind
  if state==14 then
   if not deployment_picker_proven then return nil,'Equipment picker layout unverified'end
   local bucket=watch(manager+0x62a0,24)
   if u32(bucket,0)~=1 or u32(bucket,16)~=0xe5 then return nil,'Equipment picker inactive'end
   controller=ptr(bucket,8)
   if not controller or u32(watch(controller+8,4),0)~=1
    or watch(controller+0x273990,1)~='\1' or watch(controller+0x2808,1)~='\0'
    or u32(watch(controller+0x2818,4),0)~=3 or u32(watch(controller+0x281c,4),0)~=0 then
    return nil,'Equipment Armor picker inactive'
   end
   local slot=u32(watch(controller+0x27d0,4),0)
   local selected_slot=u32(watch(controller+0x27d4,4),0)
   local session=ptr(watch(base+globals.session,8))
   if not slot or slot>=4 or selected_slot~=slot or not session then return nil,'Equipment local slot unavailable'end
   local peer=watch(session+0xb398,8)
   if not peer or peer==string.rep('\0',8)or watch(controller+slot*0x9f0+0x9f8,8)~=peer then return nil,'Equipment peer changed'end
   grid=controller+0xd2f20;screen_kind='deployment'
  else
   local count=u32(watch(manager+5740,4),0)
   if not count or count<1 or count>64 then return nil,'UI dispatch bounds rejected' end
   local rows=watch(manager+5744,count*16);if not rows then return nil,'UI dispatch unreadable' end
   for i=0,count-1 do
    if u32(rows,i*16+8)==224 then
     if controller then return nil,'ambiguous Armory controller' end
     controller=ptr(rows,i*16)
    end
   end
   if not controller then return nil,'Armory controller unregistered' end
   grid=controller+523752;screen_kind='armory'
  end
  -- Both menus use the same native picker; its parent must be fully visible.
  local bar=watch(grid+272,164)
  local alpha=bar and float(bar,84)
  if not alpha or alpha<0.95 or alpha>1.01 then return nil,'Armory Equipment grid hidden' end
  local x,y,w,h,sx,sy=float(bar,148),float(bar,156),float(bar,12),float(bar,16),float(bar,100),float(bar,140)
  if not x or not y or not w or not h or not sx or not sy or w<=0 or h<=0 or sx<=0 or sy<=0 then return nil,'Armory grid geometry unavailable' end
  local box={x=x,y=y,w=w*sx,h=h*sy}
  -- This is the scrollbar's transformed rectangle. Reserving a native row can
  -- temporarily clip its bottom during layout, while the proven Armor view
  -- remains active. Screen identity comes from menu/registry/alpha evidence;
  -- a partially clipped scrollbar is not a different screen.
  for _,k in ipairs({'x','y'})do if math.abs(box[k])>32768 then return nil,'Armory grid bounds rejected' end end
  if box.w<=0 or box.h<=0 or box.w>32768 or box.h>32768 then return nil,'Armory grid bounds rejected' end
  local font,atlas=hash(watch(base+globals.font,8)),hash(watch(base+globals.atlas,8))
  local mat=ptr(watch(base+globals.material,8));local material=mat and hash(watch(mat+24,8))
  if not font or not atlas or not material then return nil,'font resources unavailable' end
  for _,v in ipairs(observed)do if read(v.at,v.n)~=v.s then return nil,'Armory changed during sample' end end
  return {kind=screen_kind,anchor=box,font=font,atlas=atlas,material=material,token=menu_bytes..mb..tostring(controller)}
 end
 local function probe()
  local observed={}
  local function watch(at,n)local s=read(at,n);if s then observed[#observed+1]={at=at,n=n,s=s}end;return s end
  local mb,sb=watch(base+globals.manager,8),watch(base+globals.session,8)
  local manager,session=ptr(mb),ptr(sb);if not manager or not session then return nil,'manager/session unavailable'end
  local bucket=watch(manager+0x62a0,24);if u32(bucket,0)~=1 or u32(bucket,16)~=0xe5 then return nil,'loadout inactive'end
  local owner=ptr(bucket,8);if not owner then return nil,'owner unavailable'end
  if u32(watch(owner+8,4),0)~=1 then return nil,'not Equipment view'end
  if watch(owner+0x273990,1)~='\0' or watch(owner+0x2808,1)~='\0' then return nil,'transitioning'end
  local slot=u32(watch(owner+0x27d0,4),0);if not slot or slot>=4 then return nil,'invalid slot'end
  local peer=watch(session+0xb398,8)
  if not peer or peer==string.rep('\0',8)or watch(owner+slot*0x9f0+0x9f8,8)~=peer then return nil,'peer mismatch'end
  local card
  for i=0,3 do
   local c=owner+0x53a78+i*0x1ee18
   if ptr(watch(c+0x1edf0,8))==owner+slot*0x9f0+0x10 and u32(watch(c+0x1edfc,4),0)==slot then
    if card then return nil,'ambiguous card'end;card=c
   end
  end
  if not card then return nil,'card unavailable'end
  local widget=watch(card+0x1b820,164)
  if not widget or bit.band(u32(widget,0),0x10)==0 then return nil,'Equipment hidden'end
  local opacity,sx,sy=float(widget,84),float(widget,100),float(widget,140)
  if not opacity or not sx or not sy or opacity<0.995 or opacity>1.01 or sx<0.3 or sx>4 or math.abs(sx-sy)>0.01 then return nil,'layout transitioning'end
  local w,h=float(widget,36),float(widget,40);if not w or not h then return nil,'invalid size'end
  local box={x=float(widget,148),y=float(widget,156),w=w*sx,h=h*sy}
  for _,k in ipairs({'x','y','w','h'})do local v=box[k];if not v or v<0 or v>32768 then return nil,'invalid bounds'end end
  if box.w<100 or box.h<10 then return nil,'small widget'end
  local font,atlas=hash(watch(base+globals.font,8)),hash(watch(base+globals.atlas,8))
  local mat=ptr(watch(base+globals.material,8));local material=mat and hash(watch(mat+24,8))
  if not font or not atlas or not material then return nil,'font resources unavailable'end
  for _,v in ipairs(observed)do if read(v.at,v.n)~=v.s then return nil,'screen changed during sample'end end
  return {anchor=box,font=font,atlas=atlas,material=material,token=mb..sb..bucket..tostring(slot)..peer}
 end
  -- Advance the resolver by exactly one 256KiB chunk; 'ready'|'resolving'.
  -- Terminal resolution failures throw once and stay terminal, like sample.
  function self:step()
   if self.failure then error(self.failure,0)end
   if self.phase~='resolving'then return 'ready' end
   deadline=os.clock()+0.008;local ok,why=coroutine.resume(worker)
   if not ok then self.phase='failed';self.failure=tostring(why);error(self.failure,0)end
   if coroutine.status(worker)=='dead' then self.phase='ready' end
   return self.phase=='ready' and 'ready' or 'resolving'
  end

 function self:data_bridge()
  assert(target=='catalog','not a catalog resolver')
  assert(self.phase=='ready' and not self.failure,'catalog signatures not ready')
  for _,p in ipairs(proofs)do assert(read(base+p.rva,#p.bytes)==p.bytes,'catalog code changed')end
  local function verify()
   for _,p in ipairs(proofs)do if read(base+p.rva,#p.bytes)~=p.bytes then return false end end
   return true
  end
  return {base=base,read=read,armor_catalog=base+globals.armor_catalog,progression=base+globals.progression,
    engine_root=globals.engine_root and base+globals.engine_root or nil,
    players=globals.players and base+globals.players or nil,
    pe_timestamp=self.pe_timestamp,verify=verify}
 end
 function self:debug_bridge()
  assert(target=='armory' and self.phase=='ready' and not self.failure,'Armory UI signatures not ready')
  local function verify()
   for _,p in ipairs(proofs)do if read(base+p.rva,#p.bytes)~=p.bytes then return false end end
   return true
  end
  assert(verify(),'Armory UI evidence changed')
  return {base=base,read=read,menu_global=base+globals.armory_menu,
    manager_global=base+globals.manager,session_global=base+globals.session,
    deployment_picker_proven=deployment_picker_proven,verify=verify}
 end
 function self:sample()
  if self.failure then error(self.failure,0)end
  if self.phase=='resolving' then
   deadline=os.clock()+0.008;local ok,why=coroutine.resume(worker) -- at most one 256KiB chunk per call
   if not ok then self.phase='failed';self.failure=tostring(why);error(self.failure,0)end
   if coroutine.status(worker)=='dead' then self.phase='ready' end
   if self.phase~='ready'then return nil,'resolving'end
  end
  for _,p in ipairs(proofs)do if read(base+p.rva,#p.bytes)~=p.bytes then self.phase='failed';self.failure='verified code changed';error(self.failure,0)end end
  local ok,result,why=pcall(target=='armory' and armory_probe or probe);if not ok then return nil,'screen read failed'end
  return result,why
 end
 return self
end
return M
