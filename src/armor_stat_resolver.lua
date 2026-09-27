-- Optional read-only, current-image Armor-card formula capability.
-- Labels discover the UI; validated relative calls discover its helpers.
-- PE timestamps are provenance only. No native calls, writes or RVA fallback.
local M={}
local decoder=DebugArmory or require('src.debug_armory')
local recipes=ArmorStatSemantics or require('src.armor_stat_semantics')
local function u16(s,o)local a,b=s:byte(o+1,o+2);return a+b*256 end
local function u32(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local function packed(n)local t={};for i=1,4 do t[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(t)end
local function f32(s)
 local n=u32(s,0);local sign=n>=2147483648 and -1 or 1;n=n%2147483648
 local e,m=math.floor(n/8388608),n%8388608
 if e==255 then return nil end
 return sign*(e==0 and m*2^-149 or (1+m/8388608)*2^(e-127))
end
local function direct(op)local at=op:match('^call 0x(%x+)$');return at and tonumber(at,16)end
local function invalid(op)return op=='(unknown)'or op=='(incomplete)'or op:match('^db ')or op:find('(bad)',1,true)end
local function padding(op)return op=='nop'or op:match('^hintnop ')or op=='xchg ax, ax'end
local function reachable(rows,start)
 local by={};for i,row in ipairs(rows)do by[row.rva]=i end
 local queue,seen={start},{};local cursor=1
 while cursor<=#queue do
  local i=by[queue[cursor]];cursor=cursor+1
  while i and rows[i]and not seen[i]do
   local op=rows[i].op
   if invalid(op)then break end
   seen[i]=true
   local target=op:match('^jmp 0x(%x+)$')
   if target then queue[#queue+1]=tonumber(target,16);break end
   if op:match('^jmp ')or op:match('^ret')or op=='int3'or op=='ud2'then break end
   target=op:match('^j%w+ 0x(%x+)$');if target then queue[#queue+1]=tonumber(target,16)end
   i=i+1
  end
 end
 return seen,by
end
function M.new(bridge,report)
 assert(type(bridge)=='table'and type(bridge.read)=='function'and type(bridge.verify)=='function'
  and type(bridge.base)=='number'and type(bridge.armor_catalog)=='number','verified current-image catalog bridge required')
 local self={phase='resolving'};report=report or function()end
 local base=bridge.base;local sections,proofs,proof_keys={}, {},{}
 local read_count,scan_bytes,proof_bytes=0,0,0
 local deadline,step_reads,step_bytes=0,0,0
 local function pause(n)
  if step_reads>=64 or step_bytes+n>262144 or os.clock()>=deadline then coroutine.yield()end
 end
 local function read(at,n)
  assert(type(at)=='number'and at%1==0 and at>=0 and n>=1 and n<=262144,'stat resolver read bounds rejected')
  pause(n);read_count=read_count+1;step_reads=step_reads+1;step_bytes=step_bytes+n
  assert(read_count<=8192,'stat resolver read budget exceeded')
  local raw=bridge.read(base+at,n);assert(type(raw)=='string'and #raw==n,'stat proof unreadable');return raw
 end
 local function watch(at,raw)
  local key=at..':'..#raw
  if proof_keys[key]then assert(proof_keys[key]==raw,'stat proof changed')else
   proof_bytes=proof_bytes+#raw;assert(proof_bytes<=65536,'stat proof retention budget exceeded')
   proof_keys[key]=raw;proofs[#proofs+1]={rva=at,raw=raw}
  end
  return raw
 end
 local function observed(at,n)return watch(at,read(at,n))end
 local function contains(at,n,mode)
  for _,s in ipairs(sections)do
   if s.read and at>=s.at and at+n<=s.at+s.len and(mode~='code'or s.exec)
    and(mode~='constant'or(not s.exec and not s.write))then return true end
  end
  return false
 end
 local function scalar(at)
  assert(contains(at,4,'constant'),'stat scalar is not read-only image data')
  local value=f32(observed(at,4));assert(value,'nonfinite stat scalar');return value
 end
 local function relative(rows,i)
  local sign,delta=rows[i].op:match('%[rip([+-])0x(%x+)%]')
  assert(delta and rows[i+1],'relative stat operand unavailable')
  return rows[i+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
 end
 local function code(at,n)
  assert(contains(at,n,'code'),'stat helper is not bounded executable image code')
  local raw=read(at,n);local rows=decoder.decode(raw,at,n)
  local ending
  for i,row in ipairs(rows)do if row.op=='int3'then ending=i;break end end
  if ending then
   local used=rows[ending].rva-at+1
   watch(at,raw:sub(1,used));for i=#rows,ending,-1 do rows[i]=nil end
  else watch(at,raw)end
  return rows
 end
 local function normalize(rows,kind)
  local result={calls={},scalars={},coefficients={},external_targets={}};local positions={}
  local calls,externals,scalars,tables={},{},{},{}
  local function name(map,key,prefix,out)
   if not map[key]then
    local count=0;for _ in pairs(map)do count=count+1 end
    map[key]=prefix..(count+1);if out then out[count+1]=key end
   end
   return map[key]
  end
  local meaningful=0
  for _,row in ipairs(rows)do
   assert(not invalid(row.op),'stat semantic decode incomplete')
   if not padding(row.op)then meaningful=meaningful+1 end
   positions[row.rva]=meaningful+(padding(row.op)and 1 or 0)
  end
  local normalized={};local image_bases={}
  for i,row in ipairs(rows)do if not padding(row.op)then
   local op=row.op
   local mnemonic,target=op:match('^(%a+) 0x(%x+)$')
   if target and(mnemonic=='call'or mnemonic:sub(1,1)=='j')then
    target=tonumber(target,16)
    local label=mnemonic=='call'and name(calls,target,'call:',result.calls)
     or(positions[target]and 'row:'..positions[target]or name(externals,target,'outside:',result.external_targets))
    op=mnemonic..' '..label
   end
   if op:find('[rip',1,true)then
    local at=relative(rows,i);local replacement
    if op:match('^lea ')then
     assert(at==0,'stat table base is not the current image base')
     image_bases[op:match('^lea (%w+),')]=true;replacement='image_base'
    elseif op:match('^%a*ss ')then
     replacement=name(scalars,at,'scalar:')
     local index=tonumber(replacement:match('(%d+)$'));result.scalars[index]=scalar(at)
    else assert(base+at==bridge.armor_catalog,'stat helper uses a different catalog');replacement='catalog'end
    op=op:gsub('%[rip[+-]0x%x+%]','['..replacement..']')
   end
   if kind=='coefficient'and op:match('^movss xmm0, ')then
    local reg,index,offset=op:match('%[(r%d+)%+(r%w+)%*4%+0x(%x+)%]')
    if offset then
     assert(image_bases[reg],'coefficient table base was not established')
     local at=tonumber(offset,16);local label=name(tables,at,'coefficient:')
     local number=tonumber(label:match('(%d+)$'));assert(number<=3,'unexpected coefficient table')
     result.coefficients[number]={scalar(at),scalar(at+4),scalar(at+8)}
     op=op:gsub('%['..reg..'%+'..index..'%*4%+0x%x+%]','['..reg..'+'..index..'*4+'..label..']')
    end
   elseif kind=='truncation'then
    local at=op:match('^movzx r10d, word %[rcx%+rax%*2%+0x(%x+)%]$')
    if at then
     assert(image_bases.rcx,'truncation image base unavailable');at=tonumber(at,16)
     assert(contains(at,32,'constant'),'truncation masks are not read-only data')
     local raw=observed(at,32);for j=0,15 do assert(u16(raw,j*2)==2^j-1,'changed truncation masks')end
     result.masks_verified=true;op='movzx r10d, word [rcx+rax*2+low_masks]'
    end
    at=op:match('^mov rcx, %[rcx%+rax%*8%+0x(%x+)%]$')
    if at then
     assert(image_bases.rcx,'truncation image base unavailable');at=tonumber(at,16)
     assert(contains(at,16,'constant'),'truncation indices are not read-only data')
     local raw=observed(at,16)
     assert(u32(raw,0)==0 and u32(raw,4)==0 and u32(raw,8)==1 and u32(raw,12)==0,'changed truncation word indices')
     result.indices_verified=true;op='mov rcx, [rcx+rax*8+word_indices]'
    end
   elseif kind=='ui'then
    local prefix,value=op:match('^(mov dword %[rbp%-0x%x+%], )0x(%x+)$')
    if prefix and(prefix:find('-0x10]',1,true)or prefix:find('-0xc]',1,true)or prefix:find('-0x8]',1,true)
     or prefix:find('-0x20]',1,true)or prefix:find('-0x1c]',1,true)or prefix:find('-0x18]',1,true))then
     value=tonumber(value,16)
     assert(not result.initial_bits or result.initial_bits==value,'different initial native stat values')
     result.initial_bits=value;result.initial_value=assert(f32(packed(value)),'invalid initial native stat value')
     op=prefix..'initial_float'
    end
   end
   normalized[#normalized+1]=op
  end end
  local expected=recipes[kind];assert(#normalized==#expected,'changed '..kind..' semantic length')
  for i,op in ipairs(expected)do assert(normalized[i]==op,'changed '..kind..' operation '..i..': '..tostring(normalized[i]))end
  return result
 end
 local pdata,pdata_count,metadata={},0,{}
 local function entry(index)
  if metadata[index]then return unpack(metadata[index])end
  local raw=observed(pdata+index*12,12);local a,b=u32(raw,0),u32(raw,4)
  assert(a<b and contains(a,b-a,'code'),'invalid stat function fragment')
  metadata[index]={a,b};return a,b
 end
 local function fragment(point)
  local lo,hi=0,pdata_count-1
  while lo<=hi do
   local mid=math.floor((lo+hi)/2);local a,b=entry(mid)
   if point<a then hi=mid-1 elseif point>=b then lo=mid+1 else
    if mid>0 then local pa,pb=entry(mid-1);assert(pa<a and pb<=a,'overlapping stat fragments')end
    if mid+1<pdata_count then local na=entry(mid+1);assert(na>=b,'overlapping stat fragments')end
    return a,b
   end
  end
 end
 local function slice(rows,first,count)
  local out,n={},0
  for i=first,#rows do
   out[#out+1]=rows[i];if not padding(rows[i].op)then n=n+1 end
   if n==count then return out end
  end
  error('short stat semantic window')
 end
 local function validate(at)
  local first,last=fragment(at);assert(first and last-first<=8192,'stat labels lack bounded function evidence')
  local rows=decoder.decode(observed(first,last-first),first,8192);local anchor
  for i,row in ipairs(rows)do if row.rva==at then anchor=i;break end end
  assert(anchor and rows[anchor].op=='mov edx, 0x81b743c1','stat label is not an instruction boundary')
  local labels={'mov edx, 0x81b743c1','mov edx, 0x5c2d0ceb','mov edx, 0x10fb893b'}
  local label_call
  for j=0,2 do
   local i=anchor+j*3;assert(rows[i]and rows[i].op==labels[j+1],'stat label sequence changed')
   local target=direct(assert(rows[i+1]).op);assert(target,'stat label call changed')
   assert(not label_call or label_call==target,'different stat label helpers');label_call=target
   if j<2 then assert(rows[i+2].op:match('^lea rcx, %['),'stat label object sequence changed')end
  end
  local one,zero,block,round_target
  for i,row in ipairs(rows)do
   if i<anchor and row.op:match('^movss xmm8, %[rip')then assert(not one,'ambiguous stat identity scalar');one=scalar(relative(rows,i))end
   if i<anchor and row.op=='xorps xmm9, xmm9'then zero=0 end
   if row.op==recipes.ui[1]then assert(not block,'ambiguous native stat calculation');block=i end
   if row.op=='cvttss2si ebx, xmm0'then
    local target=i>1 and direct(rows[i-1].op);assert(target,'stat rounding call unavailable')
    assert(not round_target or round_target==target,'ambiguous stat rounding target');round_target=target
   end
  end
  assert(one==1 and zero==0 and block and round_target,'native stat identities/calculation unavailable')
  local ui=normalize(slice(rows,block,#recipes.ui),'ui')
  assert(#ui.calls==2 and ui.initial_value>0 and #ui.scalars==2 and ui.scalars[1]>0 and ui.scalars[2]>0,'native stat scales unavailable')
  -- The calculation must return to the actual three-stat display prelude,
  -- and that continuation must reach the rounding/conversion we certify.
  -- An unrelated CVTT elsewhere in the function is not sufficient evidence.
  local previous={};for i=1,anchor-1 do if not padding(rows[i].op)then previous[#previous+1]=i end end
  local continuation=previous[#previous-1];local count_store=previous[#previous]
  assert(continuation and rows[continuation].op:match('^lea rcx, %[rsi%+0x%x+%]$')
   and rows[count_store].op:match('^mov dword %[rsi%+0x%x+%], 0x3$'),'native stat display prelude changed')
  local seen,by=reachable(rows,ui.external_targets[2]);local landing=by[ui.external_targets[2]]
  while landing and rows[landing]and padding(rows[landing].op)do landing=landing+1 end
  assert(landing==continuation,'native stat calculation bypasses the display continuation')
  local conversion=false
  for i,row in ipairs(rows)do
   if seen[i]and row.op=='cvttss2si ebx, xmm0'and i>1 and seen[i-1]and direct(rows[i-1].op)==round_target then conversion=true end
  end
  assert(conversion,'native stat continuation cannot reach its rounding/conversion')
  local coefficient_rows=code(ui.calls[1],1024);local core,counter,counter_zero,stack_base
  for i,row in ipairs(coefficient_rows)do
   if row.op==recipes.coefficient[1]then core=i;break end
   if row.op:match('^movss xmm3, %[rip')then counter=scalar(relative(coefficient_rows,i))end
   if row.op=='xor r10d, r10d'then counter_zero=true end
   if row.op=='mov r11, rsp'then stack_base=true end
   assert(not direct(row.op)and not row.op:match('^j')and not row.op:match('^ret'),'unexpected coefficient entry control flow')
  end
  assert(core and core<=16 and counter==1 and counter_zero and stack_base,'coefficient gather initialization changed')
  local coefficient=normalize(slice(coefficient_rows,core,#recipes.coefficient),'coefficient')
  assert(#coefficient.coefficients==3,'three native coefficient tables required')
  local modifier=normalize(code(ui.calls[2],256),'modifier')
  assert(modifier.scalars[1]==1,'native passive multiplier identity changed')
  local rounding=normalize(code(round_target,128),'rounding')
  assert(#rounding.calls==1 and rounding.scalars[1]==-1 and rounding.scalars[2]==1,'native rounding sign steps changed')
  local truncation=normalize(code(rounding.calls[1],256),'truncation')
  assert(truncation.masks_verified and truncation.indices_verified,'native rounding lookup proof unavailable')
  return {initial_value=ui.initial_value,armor_scale=ui.scalars[1],speed_scale=ui.scalars[2],one=one,zero=zero,
   coefficients={armor_rating=coefficient.coefficients[3],speed=coefficient.coefficients[2],stamina_regen=coefficient.coefficients[1]},
   rounding='nearest_ties_away',verified=true,evidence='current-image Armor label/arithmetic/table/rounding semantic proof'}
 end
 local function run()
  assert(bridge.verify(),'stat adapter proof changed')
  local dos=observed(0,64);assert(dos:sub(1,2)=='MZ','invalid stat image')
  local pe=u32(dos,60);assert(pe>=64 and pe<=65536,'invalid stat PE offset')
  local nt=observed(pe,168)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 stat image required')
  local n,opt,size=u16(nt,6),u16(nt,20),u32(nt,80);self.image_timestamp=u32(nt,8)
  assert(n>=1 and n<=96 and opt>=144 and opt<=4096 and size<=536870912,'stat image bounds rejected')
  local executable=0
  for i=0,n-1 do
   local h=observed(pe+24+opt+i*40,40);local at,len,flags=u32(h,12),u32(h,8),u32(h,36)
   assert(at>=4096 and at+len<=size,'stat section bounds rejected')
   for _,s in ipairs(sections)do assert(at+len<=s.at or at>=s.at+s.len,'overlapping stat image sections')end
   local section={at=at,len=len,read=math.floor(flags/0x40000000)%2==1,exec=math.floor(flags/0x20000000)%2==1,write=math.floor(flags/0x80000000)%2==1}
   sections[#sections+1]=section;if section.read and section.exec then executable=executable+len end
  end
  assert(executable>0 and executable<=134217728,'stat executable scan budget exceeded')
  pdata=u32(nt,160);local plen=u32(nt,164)
  assert(u32(nt,132)>=4 and plen>=12 and plen<=2400000 and plen%12==0 and contains(pdata,plen),'stat function metadata unavailable')
  pdata_count=plen/12
  local candidates,seen={},{};local literal=packed(0x81b743c1)
  for _,s in ipairs(sections)do if s.read and s.exec then
   local tail=''
   for offset=0,s.len-1,262144 do
    assert(bridge.verify(),'stat adapter proof changed during scan')
    local chunk=read(s.at+offset,math.min(262144,s.len-offset));scan_bytes=scan_bytes+#chunk
    local raw=tail..chunk;local origin=s.at+offset-#tail;local cursor=1
    while true do
     local hit=raw:find(literal,cursor,true);if not hit then break end
     if hit>1 and raw:byte(hit-1)==0xba then
      local at=origin+hit-2
      if not seen[at]then seen[at]=true;candidates[#candidates+1]=at;assert(#candidates<=32,'too many stat label candidates')end
     end
     cursor=hit+1
    end
    tail=raw:sub(-4);coroutine.yield()
   end
  end end
  local accepted,errors={},{}
  for _,at in ipairs(candidates)do
   local ok,value=pcall(validate,at)
   if ok then accepted[#accepted+1]=value else errors[#errors+1]=tostring(value)end
   coroutine.yield()
  end
  assert(#accepted==1,#accepted>1 and 'ambiguous current-image stat semantics'or('native stat semantics unavailable: '..(errors[1]or 'labels not found')))
  for _,p in ipairs(proofs)do assert(read(p.rva,#p.raw)==p.raw,'stat evidence changed during resolution')end
  assert(bridge.verify(),'stat proof changed before publication')
  local function verify()
   local ok,value=pcall(function()
    if not bridge.verify()then return false end
    for _,p in ipairs(proofs)do if bridge.read(base+p.rva,#p.raw)~=p.raw then return false end end
    return true
   end)
   return ok and value==true
  end
  self.result={contract=accepted[1],verify=verify,provenance={image_timestamp=self.image_timestamp,scan_bytes=scan_bytes,
   label_candidates=#candidates,semantic_matches=#accepted,read_only=true}}
  self.phase='ready';report('armor_stats.status','current_image_semantics_verified')
 end
 local worker=coroutine.create(run)
 function self:step()
  if self.phase~='resolving'then return self.phase,self.result or self.failure end
  deadline,step_reads,step_bytes=os.clock()+0.005,0,0
  local ok,why=coroutine.resume(worker)
  if not ok then self.phase='failed';self.failure=tostring(why);self.result=nil;report('armor_stats.status',self.failure)end
  return self.phase,self.result or self.failure
 end
 return self
end
return M
