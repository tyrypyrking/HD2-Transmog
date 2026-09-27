-- Opt-in read-only inspection of current armor-catalog consumers. No native
-- calls, writes, process-wide memory scan or raw memory export.
local M={}
local decoder=DebugArmory or require('src.debug_armory')
local function u16(s,o)local a,b=s:byte(o+1,o+2);return a+b*256 end
local function u32(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local function i32(s,o)local n=u32(s,o);return n>=2147483648 and n-4294967296 or n end
local function f32(s)
 local n=u32(s,0);local sign=n>=2147483648 and -1 or 1;n=n%2147483648
 local e,m=math.floor(n/8388608),n%8388608
 if e==255 then return nil end
 return sign*(e==0 and m*2^-149 or (1+m/8388608)*2^(e-127))
end
function M.new(bridge,report)
 assert(type(bridge)=='table'and type(bridge.read)=='function'and type(bridge.verify)=='function'
  and type(bridge.base)=='number'and type(bridge.armor_catalog)=='number','catalog bridge required')
 report=report or function()end
 local self={phase='resolving'};local base=bridge.base;local sections={};local deadline=0
 local lines={'HD2TRANSMOG_ARMOR_CODE_PROBE 1','read_only=true'}
 local function out(line)assert(#lines<24000,'armor semantic output budget exceeded');lines[#lines+1]=line end
 local function image(rva,n)
  assert(rva>=0 and rva%1==0 and n>=1 and n<=262144,'armor image bounds rejected')
  local bytes=bridge.read(base+rva,n);assert(type(bytes)=='string'and #bytes==n,'armor code unreadable');return bytes
 end
 local function contains(rva,n,exec)
  for _,s in ipairs(sections)do if s.read and (not exec or s.exec)and rva>=s.rva and rva+n<=s.rva+s.size then return true end end
  return false
 end
 local callees={}
 local function inspect(rva,n,title,depth)
  if not contains(rva,n,true)then return end
  local code=image(rva,n);local rows=decoder.decode(code,rva,math.min(1024,n))
  -- The combined equipment display helper uses image-base indexed float tables
  -- and a different slot filter from the gameplay averages. Export typed table
  -- values only after proving that local image-base LEA and the indexed load.
  if depth==0 and rows[1]and rows[1].op:match('^mov r15, %[rip')and contains(rva,1024,true)then
   local window=image(rva,1024);local full=decoder.decode(window,rva,768)
   local facts,bases={},{}
   for _,row in ipairs(full)do facts[row.op]=true end
   if facts['cmp dword [rax+0xc], +0x00']and facts['cmp dword [rax+0x8], +0x00']
    and facts['test eax, 0xfffffff8']and facts['cmp edx, +0x03']then
    local emitted={}
    for index,row in ipairs(full)do
     local reg,sign,delta=row.op:match('^lea (r%d+), %[rip([+-])0x(%x+)%]$')
     if reg and full[index+1]then bases[reg]=full[index+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)end
     local table_base,table_offset=row.op:match('^movss xmm0, %[(r%d+)%+r%a+%*4%+0x(%x+)%]$')
     local table_rva=table_offset and bases[table_base]==0 and tonumber(table_offset,16)
     if table_rva and not emitted[table_rva]and contains(table_rva,16,false)then
      emitted[table_rva]=true;local values={}
      for weight=0,3 do values[#values+1]=assert(f32(image(table_rva+weight*4,4)),'display coefficient is not finite')end
      out(string.format('equipment_display_code=0x%08x table=0x%08x values=%.9g,%.9g,%.9g,%.9g helmet_slot=0 body_slots=2,4,5,6,7,8,9 weight_none_excluded=false',
       rva,table_rva,values[1],values[2],values[3],values[4]))
     end
    end
    assert(image(rva,1024)==window,'display coefficient proof changed')
   end
  end
  if depth==0 and rows[2]and rows[2].op=='xor r14d, r14d'and contains(rva,768,true)then
   local window=image(rva,768);local full=decoder.decode(window,rva,512)
   local facts={};for _,row in ipairs(full)do facts[row.op]=true end
   if facts['cmp edx, +0x14']and facts['cmp dword [rax+0xc], +0x00']
    and facts['cmp r8d, +0x03']and facts['addss xmm0, [r10+r8*4]']and facts['divss xmm0, xmm1']then
    for index,row in ipairs(full)do
     local sign,delta=row.op:match('^lea r10, %[rip([+-])0x(%x+)%]$')
     if delta and full[index+1]then
      local table_rva=full[index+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
      if contains(table_rva,12,false)then
       local values={}
       for weight=0,2 do values[#values+1]=assert(f32(image(table_rva+weight*4,4)),'weight coefficient is not finite')end
       out(string.format('weight_average_code=0x%08x table=0x%08x values=%.9g,%.9g,%.9g capacity=20 excluded_weight=3',
        rva,table_rva,values[1],values[2],values[3]))
       break
      end
     end
    end
    assert(image(rva,768)==window,'weight coefficient proof changed')
   end
  end
  local player_map=false
  for _,row in ipairs(rows)do if row.op:find('+0x938]',1,true)then player_map=true end end
  local emit=not(depth==0 and title=='xref'and player_map)
  if emit then out(title..string.format('=0x%08x',rva))end
  for i,row in ipairs(rows)do
   if emit then out(string.format('  0x%08x %s',row.rva,row.op))end
   local at=row.op:match('^call 0x(%x+)$')or row.op:match('^jmp 0x(%x+)$')
   if at and depth==0 then
    local target=tonumber(at,16);if contains(target,768,true)then callees[target]=(callees[target]or 0)+(player_map and 0.05 or 1)end
   end
   local sign,offset=row.op:match('%[rip([+-])0x(%x+)%]')
   if emit and sign and rows[i+1]and row.op:match('^%a*ss ')then
    local target=rows[i+1].rva+(sign=='-'and -1 or 1)*tonumber(offset,16)
    if contains(target,4,false)then
     local value=f32(image(target,4))
     if value then out(string.format('    constant_f32=%.9g source_rva=0x%08x',value,target))end
    end
   end
   if row.op=='int3' then break end
  end
  assert(image(rva,n)==code,'armor code changed during observation')
 end
 local function run()
  assert(bridge.verify(),'catalog code proof changed')
  local dos=image(0,64);assert(dos:sub(1,2)=='MZ','invalid image');local pe=u32(dos,60)
  assert(pe>=64 and pe<=65536,'invalid PE offset');local nt=image(pe,88)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 required')
  local count,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(count>=1 and count<=96 and opt>=112 and opt<=4096 and size<=536870912,'PE bounds rejected')
  local total=0
  for i=0,count-1 do
   local h=image(pe+24+opt+i*40,40);local rva,len,flags=u32(h,12),u32(h,8),u32(h,36)
   if len>0 then
    assert(rva>=4096 and rva+len<=size,'section bounds rejected')
    local section={rva=rva,size=len,exec=math.floor(flags/0x20000000)%2==1,read=math.floor(flags/0x40000000)%2==1}
    if section.exec then assert(section.read,'unreadable code');total=total+len end
    sections[#sections+1]=section
   end
  end
  assert(total>0 and total<=134217728,'armor code scan budget exceeded')
  out('image_timestamp='..u32(nt,8));out(string.format('armor_catalog_global=0x%08x',bridge.armor_catalog-base))
  local found,hits={},0
  local labels={{name='armor_rating',bytes='\193\67\183\129'},
   {name='speed',bytes='\235\12\45\92'},{name='stamina_regen',bytes='\59\137\251\16'}}
  for _,s in ipairs(sections)do if s.exec then
   local tail=''
   for offset=0,s.size-1,262144 do
    assert(bridge.verify(),'catalog code proof changed')
    local code=tail..image(s.rva+offset,math.min(262144,s.size-offset));local origin=s.rva+offset-#tail;local at=1
    while true do
     if os.clock()>=deadline then coroutine.yield()end
     local hit=code:find('[\139\141]',at);if not hit or hit+5>#code then break end
     local m=code:byte(hit+1)
     if m<64 and m%8==5 and base+origin+hit+5+i32(code,hit+1)==bridge.armor_catalog then
      local start=hit;local rex=hit>1 and code:byte(hit-1)or 0;if rex>=64 and rex<=79 then start=start-1 end
      local rva=origin+start-1
      if not found[rva]then
       found[rva]=true;hits=hits+1;assert(hits<=1024,'armor xref budget exceeded')
       inspect(rva,256,'xref',0)
      end
     end
     at=hit+1
    end
    for _,label in ipairs(labels)do
     local cursor=1
     while true do
      local hit=code:find(label.bytes,cursor,true);if not hit then break end
      local op=hit>1 and code:byte(hit-1)or 0
      if op>=184 and op<=191 then
       local start=hit-1;local rex=start>1 and code:byte(start-1)or 0
       if rex>=64 and rex<=79 then start=start-1 end
       local rva=origin+start-1
       if not found['label:'..rva]then found['label:'..rva]=true;inspect(rva,384,'label_'..label.name,0)end
      end
      cursor=hit+1
     end
    end
    tail=code:sub(-8);coroutine.yield()
   end
  end end
  out('xref_count='..hits)
  local sorted={};for rva in pairs(callees)do sorted[#sorted+1]=rva end
  table.sort(sorted,function(a,b)if callees[a]~=callees[b]then return callees[a]>callees[b]end;return a<b end)
  for index,rva in ipairs(sorted)do
   if index>48 then out('callee_limit_reached=true');break end
   if os.clock()>=deadline then coroutine.yield()end
   inspect(rva,768,'callee',1)
  end
  assert(bridge.verify(),'catalog proof changed before completion')
  self.phase='ready';report('native_armor_probe.xrefs',hits);report('native_armor_probe.status','semantic_observation_complete')
 end
 local worker=coroutine.create(run)
 function self:step()
  if self.phase~='resolving'then return self.phase,self.failure end
  deadline=os.clock()+0.006;local ok,why=coroutine.resume(worker)
  if not ok then self.phase='failed';self.failure=tostring(why);out('failure='..self.failure);report('native_armor_probe.failure',why)end
  return self.phase,self.failure
 end
 function self:summary()return table.concat(lines,'\n')..'\n'end
 return self
end
return M
