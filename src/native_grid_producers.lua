-- Explicit, bounded, read-only discovery of possible logical grid producers.
-- Field literals identify candidates, not the identity of their base object.
-- PE-declared code fragments and reachable instructions constrain decoding.
local M={}
local decoder=DebugArmory or require('src.debug_armory')
local FIELDS={[0x91f14]='row_count',[0x92748]='group_count',[0x92984]='item_count',[0x92990]='offers'}
local LIMIT={radius=131072,raw_hits=512,fragments=64,fragment_bytes=8192,callees=16,
 lines=512,output_bytes=61440,watched_bytes=1048576,total_reads=4096,total_bytes=3145728}
local function u16(s,o)local a,b=s:byte(o+1,o+2);return a+b*256 end
local function u32(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local function packed(n)local t={};for i=1,4 do t[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(t)end
local STORE={mov=true,movss=true,movsd=true,movaps=true,movups=true,movdqa=true,movdqu=true,
 movq=true,movd=true,inc=true,dec=true,add=true,sub=true,and_=true,or_=true,xor_=true,
 bts=true,btr=true,btc=true,cmpxchg=true,xchg=true}
STORE['and'],STORE['or'],STORE['xor']=true,true,true
function M.write_field(op)
 local name,args=op:match('^(%S+)%s+(.+)$');if not name or not STORE[name]then return nil end
 local first,rest=args:match('^([^,]+),?(.*)$')
 local memory=first and first:match('%[([^%]]+)%]')
 if not memory and name=='xchg'then memory=rest:match('%[([^%]]+)%]')end
 if not memory or memory:find('rip',1,true)then return nil end
 local sign,value=memory:match('([+-])0x(%x+)$')
 if sign~='+'then return nil end
 local offset=tonumber(value,16);return FIELDS[offset],offset
end
local function invalid(op)
 return op:match('^db%s')or op:match('^%.')or op:find('(bad)',1,true)or op:find('invalid',1,true)
  or op:find('(unknown)',1,true)or op:find('(incomplete)',1,true)
end
-- Linear decoder output is filtered through reachable basic blocks so jump-
-- over data or return padding cannot masquerade as a producer instruction.
function M.reachable(rows,first,last,start)
 local by={};for i,row in ipairs(rows)do by[row.rva]=i end
 local queue,seen,edges={start or first},{},0;local at=1
 while at<=#queue do
  local index=by[queue[at]];at=at+1
  if not index then edges=edges+1 end
  while index and rows[index]and rows[index].rva<last and not seen[index]do
   local row=rows[index];if invalid(row.op)then edges=edges+1;break end
   seen[index]=true
   local op=row.op;local target=op:match('^jmp 0x(%x+)$')
   if target then
    target=tonumber(target,16);if target>=first and target<last then queue[#queue+1]=target else edges=edges+1 end;break
   elseif op:match('^jmp ')or op:match('^ret')or op=='int3'or op=='ud2' then
    if op:match('^jmp ')then edges=edges+1 end;break
   end
   target=op:match('^j%w+ 0x(%x+)$')
   if target then target=tonumber(target,16);if target>=first and target<last then queue[#queue+1]=target else edges=edges+1 end end
   index=index+1
  end
 end
 return seen,edges
end

function M.new(bridge,anchors)
 assert(type(bridge)=='table'and type(bridge.read)=='function'and type(bridge.verify)=='function','verified read bridge required')
 assert(type(anchors)=='table'and type(anchors.solver)=='number'and type(anchors.highlight)=='number','resolved grid anchors required')
 local self={phase='scanning'};local lines,output_size={},0;local partial={};local counts={raw_hits=0,fragments=0,writers=0,callees=0}
 local proofs,proof_keys,watched={}, {},0;local total_reads,total_bytes=0,0
 local step_reads,step_bytes,deadline=0,0,0;local base=bridge.base
 local function checkpoint(n)
  if step_reads>=64 or step_bytes+n>16384 or os.clock()>=deadline then coroutine.yield()end
 end
 local function read(rva,n,watch)
  assert(type(rva)=='number'and rva%1==0 and rva>=0 and n>=1 and n<=8192,'producer read bounds rejected')
  checkpoint(n);total_reads=total_reads+1;total_bytes=total_bytes+n;step_reads=step_reads+1;step_bytes=step_bytes+n
  assert(total_reads<=LIMIT.total_reads and total_bytes<=LIMIT.total_bytes,'producer read budget exceeded')
  local raw=bridge.read(base+rva,n);assert(type(raw)=='string'and #raw==n,'producer evidence unreadable')
  if watch then
   local key=rva..':'..n
   if not proof_keys[key]then watched=watched+n;assert(watched<=LIMIT.watched_bytes,'producer proof budget exceeded')
    proofs[#proofs+1]={rva=rva,n=n,raw=raw};proof_keys[key]=raw
   else assert(proof_keys[key]==raw,'producer evidence changed')end
  end
  return raw
 end
 local function emit(line)
  if #lines>=LIMIT.lines or output_size+#line+1>LIMIT.output_bytes then partial.output_cap=true;return false end
  lines[#lines+1]=line;output_size=output_size+#line+1;return true
 end
 local function run()
  assert(type(base)=='number'and base>=65536 and bridge.verify(),'producer anchor proof changed')
  local dos=read(0,64,true);assert(dos:sub(1,2)=='MZ','invalid image')
  local pe=u32(dos,60);assert(pe>=64 and pe<=65536,'invalid PE offset')
  local nt=read(pe,168,true)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 required')
  local n,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(n>=1 and n<=96 and opt>=144 and opt<=4096 and size<=536870912,'producer image bounds rejected')
  local sections={}
  for i=0,n-1 do
   local h=read(pe+24+opt+i*40,40,true);local a,len,flags=u32(h,12),u32(h,8),u32(h,36)
   assert(a>=4096 and a+len<=size,'producer section bounds rejected')
   for _,old in ipairs(sections)do assert(a+len<=old.at or a>=old.at+old.len,'overlapping image sections')end
   sections[#sections+1]={at=a,len=len,read=math.floor(flags/0x40000000)%2==1,exec=math.floor(flags/0x20000000)%2==1}
  end
  local function inside(at,len,exec)
   for _,s in ipairs(sections)do if s.read and(not exec or s.exec)and at>=s.at and at+len<=s.at+s.len then return true end end
   return false
  end
  local pdata,plen=u32(nt,160),u32(nt,164)
  assert(u32(nt,132)>=4 and plen>=12 and plen<=2400000 and plen%12==0 and inside(pdata,plen),'producer function metadata unavailable')
  local entries={}
  local function entry(index)
   if entries[index]then return entries[index][1],entries[index][2]end
   local meta=read(pdata+index*12,12,true);local a,b=u32(meta,0),u32(meta,4)
   assert(a>=4096 and a<b and inside(a,b-a,true),'invalid declared code fragment');entries[index]={a,b};return a,b
  end
  local function fragment(point)
   local lo,hi=0,plen/12-1
   while lo<=hi do
    local mid=math.floor((lo+hi)/2);local a,b=entry(mid)
    if point<a then hi=mid-1 elseif point>=b then lo=mid+1 else
     if mid>0 then local pa,pb=entry(mid-1);assert(pa<a and pb<=a,'overlapping or unsorted code fragments')end
     if mid+1<plen/12 then local na=entry(mid+1);assert(na>=b,'overlapping code fragments')end
     return a,b
    end
   end
  end
  local low_anchor,high_anchor=math.min(anchors.solver,anchors.highlight),math.max(anchors.solver,anchors.highlight)
  assert(inside(low_anchor,1,true)and inside(high_anchor,1,true)and high_anchor-low_anchor<=LIMIT.radius*2,'producer anchors outside bounded executable region')
  local center=math.floor((low_anchor+high_anchor)/2)
  local low,high=math.max(4096,center-LIMIT.radius),math.min(size,center+LIMIT.radius)
  self.window_first,self.window_last=low,high
  emit('HD2TM_ARMORY_PRODUCERS 1');emit('read_only=true');emit('model_object_identity_unproven=true')
  emit(string.format('scan_first=0x%08x scan_last=0x%08x max_radius=%d',low,high,LIMIT.radius))
  local candidates,found={},{};local stop=false
  for _,s in ipairs(sections)do if s.read and s.exec then
   local first,last=math.max(low,s.at),math.min(high,s.at+s.len);local tail=''
   for offset=first,last-1,4096 do
    if stop then break end
    local chunk=read(offset,math.min(4096,last-offset),true);local raw=tail..chunk;local origin=offset-#tail
    for field in pairs(FIELDS)do
     local from=1
     while true do
      local hit=raw:find(packed(field),from,true);if not hit then break end
      counts.raw_hits=counts.raw_hits+1
      if counts.raw_hits>LIMIT.raw_hits then partial.raw_hit_cap=true;stop=true;break end
      local a,b=fragment(origin+hit-1)
      if a and not found[a]then
       if #candidates>=LIMIT.fragments then partial.fragment_cap=true;stop=true;break end
       found[a]=true;candidates[#candidates+1]={first=a,last=b}
      elseif not a then partial.unmapped_literals=true end
      from=hit+1
     end
     if stop then break end
    end
    tail=raw:sub(math.max(1,#raw-2));coroutine.yield()
   end
  end end
  table.sort(candidates,function(a,b)return a.first<b.first end)
  local callee_targets,callee_seen={},{}
  for _,item in ipairs(candidates)do
   counts.fragments=counts.fragments+1
   if item.first<low or item.last>high then partial.boundary_fragments=true
   elseif item.last-item.first>LIMIT.fragment_bytes then partial.large_fragments=true
   else
    local code=read(item.first,item.last-item.first,true);local rows=decoder.decode(code,item.first,LIMIT.fragment_bytes)
    local reachable,edges=M.reachable(rows,item.first,item.last);if edges>0 then partial.unresolved_control_flow=true end
    local writes={}
    for i,row in ipairs(rows)do if reachable[i]and M.write_field(row.op)then writes[#writes+1]=i end end
    if #writes>0 then
     counts.writers=counts.writers+1
     emit(string.format('candidate fragment=0x%08x end=0x%08x explicit_field_writes=%d callable_entry_unproven=true',item.first,item.last,#writes))
     local printed={}
     for _,i in ipairs(writes)do
      if partial.output_cap then break end
      emit('  field='..M.write_field(rows[i].op))
      for j=math.max(1,i-3),math.min(#rows,i+3)do if reachable[j]and not printed[j]then
       emit(string.format('  0x%08x %s',rows[j].rva,rows[j].op));printed[j]=true
      end end
     end
     local calls=0
     for i,row in ipairs(rows)do if reachable[i]then
      local target=row.op:match('^call 0x(%x+)$')
      if target then
       target=tonumber(target,16);calls=calls+1
       if calls<=8 then
        local executable=inside(target,1,true);local a,b;if executable then a,b=fragment(target)end
        emit(string.format('  direct_call site=0x%08x target=0x%08x executable=%s declared_fragment=%s',row.rva,target,tostring(executable),a and string.format('0x%08x',a)or 'none'))
        if a and not callee_seen[target]then
         if #callee_targets<LIMIT.callees then callee_seen[target]=true;callee_targets[#callee_targets+1]={first=a,last=b,target=target}
         else partial.callee_cap=true end
        end
       else partial.calls_per_fragment_cap=true end
      end
     end end
    end
   end
   coroutine.yield()
  end
  for _,callee in ipairs(callee_targets)do
   if partial.output_cap then break end
   if callee.target-callee.first+512>LIMIT.fragment_bytes then partial.large_callee_prefix=true
   else
    local last=math.min(callee.last,callee.target+512)
    local rows=decoder.decode(read(callee.first,last-callee.first,true),callee.first,LIMIT.fragment_bytes)
    local reach=M.reachable(rows,callee.first,last);local boundary
    for i,row in ipairs(rows)do if row.rva==callee.target and reach[i]then boundary=i end end
    if boundary then
     counts.callees=counts.callees+1
     emit(string.format('callee target=0x%08x declared_fragment=0x%08x no_native_call=true',callee.target,callee.first))
     local seen=M.reachable(rows,callee.first,last,callee.target);local printed=0
     for i=boundary,#rows do if seen[i]then
      if printed>=24 then partial.callee_output_cap=true;break end
      emit(string.format('  0x%08x %s',rows[i].rva,rows[i].op));printed=printed+1
     end end
    else partial.unverified_callee_boundary=true end
   end
   coroutine.yield()
  end
  -- Verification itself is incremental; a stale candidate is never published.
  for _,p in ipairs(proofs)do assert(read(p.rva,p.n,false)==p.raw,'producer evidence changed during scan')end
  assert(bridge.verify(),'producer anchor proof changed during scan')
  self.phase='complete'
 end
 local worker=coroutine.create(run)
 function self:step()
  if self.phase~='scanning'then return self.phase end
  step_reads,step_bytes,deadline=0,0,os.clock()+.003
  local ok,why=pcall(bridge.verify)
  if ok and why==true then ok,why=coroutine.resume(worker)else ok=false;why='producer anchor proof changed'end
  if not ok then self.phase='failed';self.failure=tostring(why);lines={}end
  return self.phase
 end
 function self:report()
  local out={'HD2TM_ARMORY_PRODUCER_STATUS 1','phase='..self.phase,'read_only=true'}
  for _,key in ipairs({'raw_hits','fragments','writers','callees'})do out[#out+1]=key..'='..counts[key]end
  if self.phase=='failed'then out[#out+1]='error='..self.failure
  elseif self.phase=='complete'then
   local reasons={};for key in pairs(partial)do reasons[#reasons+1]=key end;table.sort(reasons)
   out[#out+1]='coverage='..(#reasons>0 and 'partial'or 'bounded_literal_scan')
   for _,reason in ipairs(reasons)do out[#out+1]='limitation='..reason end
   out[#out+1]='limitation=precomputed_addresses_bulk_writes_and_aliased_objects_not_resolved'
   for _,line in ipairs(lines)do out[#out+1]=line end
  end
  return table.concat(out,'\n')..'\n'
 end
 return self
end
return M
