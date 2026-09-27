-- Opt-in semantic inspection of native references to the proven menu global.
-- No native calls, writes, heap scan, raw-byte export, or Armory-open claim.
local M={}
local dis=NativeDisassembler or require('vendor.LuaJIT-disassembler.dis_x86')
local function u16(s,o)local a,b=s:byte(o+1,o+2);return a+b*256 end
local function u32(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local function i32(s,o)local n=u32(s,o);return n>=2147483648 and n-4294967296 or n end
local function scalar32(s)
 local n=u32(s,0);local sign=n>=2147483648 and -1 or 1;n=n%2147483648
 local exponent,mantissa=math.floor(n/8388608),n%8388608
 if exponent==255 then return nil end
 return sign*(exponent==0 and mantissa*2^-149 or (1+mantissa/8388608)*2^(exponent-127))
end
function M.decode(code,rva,limit)
 local rows={};local ctx=dis.create64(code,rva,function(line)
  local at,op=line:match('^(%x+)%s+([^\r\n]+)')
  if at and #rows<(limit or 40)then rows[#rows+1]={rva=tonumber(at,16),op=op}end
 end)
 ctx.hexdump=0;ctx:disass();return rows
end
-- Iterative semantic-only inspection, deliberately separate from any caller.
-- Requested RVA is normalized to its validated PE function entry, so a byte in
-- an immediate cannot become a guessed instruction boundary. No native call.
function M.inspect_code(bridge,rva,byte_count)
 local ok,result=pcall(function()
  assert(type(bridge)=='table'and type(bridge.verify)=='function'and bridge.verify(),'debug proof changed')
  assert(type(rva)=='number'and rva%1==0 and rva>=4096 and type(byte_count)=='number'
   and byte_count%1==0 and byte_count>=16 and byte_count<=4096,'bounded RVA and byte count required')
  local base=bridge.base
  local function read(at,n)
   local s=bridge.read(base+at,n);assert(type(s)=='string'and #s==n,'code metadata unreadable');return s
  end
  local dos=read(0,64);assert(dos:sub(1,2)=='MZ','invalid image');local pe=u32(dos,60)
  assert(pe>=64 and pe<=65536,'invalid PE');local nt=read(pe,24+144)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 required')
  local count,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(count>=1 and count<=96 and opt>=144 and opt<=4096 and size<=536870912,'invalid image bounds')
  local sections={}
  for i=0,count-1 do
   local h=read(pe+24+opt+i*40,40);local len,at,flags=u32(h,8),u32(h,12),u32(h,36)
   assert(at+len<=size,'section out of image')
   sections[#sections+1]={at=at,len=len,read=math.floor(flags/1073741824)%2==1,exec=math.floor(flags/536870912)%2==1,
    write=math.floor(flags/2147483648)%2==1}
  end
  local function contains(at,n,exec)
   for _,s in ipairs(sections)do if s.read and (not exec or s.exec)and at>=s.at and at+n<=s.at+s.len then return true end end
   return false
  end
  local pdata,len=u32(nt,24+136),u32(nt,24+140)
  assert(u32(nt,24+108)>=4 and len>=12 and len<=2400000 and len%12==0 and contains(pdata,len),'function metadata unavailable')
  local lo,hi,first,last=0,len/12-1
  while lo<=hi do
   local mid=math.floor((lo+hi)/2);local row=read(pdata+mid*12,12);local a,b=u32(row,0),u32(row,4)
   if rva<a then hi=mid-1 elseif rva>=b then lo=mid+1 else first,last=a,b;break end
  end
  assert(first and first<last and contains(first,last-first,true),'requested RVA has no validated function')
  assert(rva-first<=4096,'requested point too far from function entry')
  local n=math.min(last-first,rva-first+byte_count);assert(n<=8192,'code window too large')
  local code=read(first,n);local rows=M.decode(code,first,8192)
  local selected={};local boundary
  for index,row in ipairs(rows)do if row.rva==rva then boundary=index;break end end
  assert(boundary,'requested RVA is not an instruction boundary')
  selected[1]=string.format('HD2TRANSMOG_CODE_SEMANTICS 1\nfunction=0x%08x size=%d requested=0x%08x\nopens_armory=false',first,last-first,rva)
  for index=math.max(1,boundary-32),math.min(#rows,boundary+512)do
   local row=rows[index];selected[#selected+1]=string.format('0x%08x %s',row.rva,row.op)
   -- Export a typed scalar only when a decoded scalar-float instruction
   -- directly references read-only image data. Never expose arbitrary bytes.
   local mnemonic=row.op:match('^(%a+) ')
   if ({movss=true,addss=true,subss=true,mulss=true,divss=true,comiss=true,ucomiss=true})[mnemonic]and rows[index+1]then
    local direction,delta=row.op:match('%[rip([+-])0x(%x+)%]')
    if delta then
     local target=rows[index+1].rva+(direction=='-'and -1 or 1)*tonumber(delta,16)
     for _,section in ipairs(sections)do
      if section.read and not section.exec and not section.write and target>=section.at and target+4<=section.at+section.len then
       local raw=read(target,4);local value=scalar32(raw)
       if value then
        assert(read(target,4)==raw,'scalar operand changed')
        selected[#selected+1]=string.format('  read_only_f32=%.9g',value)
       end
       break
      end
     end
    end
   end
  end
  assert(read(first,n)==code and bridge.verify(),'code proof changed')
  return table.concat(selected,'\n')..'\n'
 end)
 if not ok then return nil,tostring(result)end;return result
end
-- Leaf functions can legitimately have no unwind entry. Their entry is accepted
-- only as the exact direct-call target of an already validated instruction.
-- This is semantic inspection, not a callable-address resolver.
function M.inspect_callee(bridge,callsite,byte_count)
 local ok,result=pcall(function()
  assert(type(byte_count)=='number'and byte_count%1==0 and byte_count>=16 and byte_count<=1024,'bounded callee window required')
  local caller,reason=M.inspect_code(bridge,callsite,16);assert(caller,reason)
  local wanted=string.format('0x%08x call 0x',callsite)
  local target
  for line in caller:gmatch('[^\n]+')do
   if line:sub(1,#wanted)==wanted then target=tonumber(line:sub(#wanted+1),16)end
  end
  assert(target,'validated instruction is not a direct call')
  local function read(rva,n)
   local s=bridge.read(bridge.base+rva,n);assert(type(s)=='string'and #s==n,'callee evidence unreadable');return s
  end
  local dos=read(0,64);local pe=u32(dos,60);local nt=read(pe,88)
  local count,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(count>=1 and count<=96 and opt>=112 and opt<=4096 and target+byte_count<=size,'callee image bounds rejected')
  local valid=false;local sections={}
  for i=0,count-1 do
   local h=read(pe+24+opt+i*40,40);local len,at,flags=u32(h,8),u32(h,12),u32(h,36)
   sections[#sections+1]={at=at,len=len,read=math.floor(flags/1073741824)%2==1,
    exec=math.floor(flags/536870912)%2==1,write=math.floor(flags/2147483648)%2==1}
   if math.floor(flags/1073741824)%2==1 and math.floor(flags/536870912)%2==1
    and target>=at and target+byte_count<=at+len then valid=true end
  end
  assert(valid and bridge.verify(),'callee is not current executable image code')
  local code=read(target,byte_count)
  local rows=M.decode(code,target,512)
  local out={string.format('HD2TM_DIRECT_CALLEE_SEMANTICS 1\ncallsite=0x%08x target=0x%08x\nno_native_call=true',callsite,target)}
  for _,row in ipairs(rows)do out[#out+1]=string.format('0x%08x %s',row.rva,row.op)end
  local ops={};for _,row in ipairs(rows)do ops[row.op]=true end
  if ops['mov r9d, 0x96']and ops['and eax, +0x0f']and ops['sar r9w, 0x04']then
   local masks,indices,base_proved
   for i,row in ipairs(rows)do
    local delta=row.op:match('^lea rcx, %[rip%-0x(%x+)%]$')
    if delta and rows[i+1]and rows[i+1].rva-tonumber(delta,16)==0 then base_proved=true end
    local a=row.op:match('^movzx r10d, word %[rcx%+rax%*2%+0x(%x+)%]$')
    local b=row.op:match('^mov rcx, %[rcx%+rax%*8%+0x(%x+)%]$')
    if a then masks=tonumber(a,16)end;if b then indices=tonumber(b,16)end
   end
   local function constant(at,n)
    if not at then return nil end
    for _,s in ipairs(sections)do
     if s.read and not s.exec and not s.write and at>=s.at and at+n<=s.at+s.len then
      local raw=read(at,n);assert(read(at,n)==raw,'typed truncation table changed');return raw
     end
    end
   end
   if base_proved then
    local a,b=constant(masks,32),constant(indices,16)
    if a and b then
     local values={};for i=0,15 do values[#values+1]=tostring(u16(a,i*2))end
     out[#out+1]='truncation_masks_u16='..table.concat(values,',')
     assert(u32(b,4)==0 and u32(b,12)==0,'truncation word indices outside uint32')
     out[#out+1]='truncation_word_indices_u64='..u32(b,0)..','..u32(b,8)
    end
   end
  end
  assert(read(target,byte_count)==code and bridge.verify(),'callee code changed')
  return table.concat(out,'\n')..'\n'
 end)
 if not ok then return nil,tostring(result)end;return result
end
-- Recognize the observed MSVC image-relative switch form before reading its
-- target table. Output is selector -> code RVA, never an arbitrary data read.
function M.inspect_switch(bridge,table_rva,count)
 local ok,result=pcall(function()
  assert(bridge.verify(),'debug proof changed')
  assert(type(table_rva)=='number'and table_rva%1==0 and table_rva>=4096
   and type(count)=='number'and count%1==0 and count>=1 and count<=64,'bounded switch request required')
  local base=bridge.base
  local function read(at,n)
   assert(at>=0 and n>=1 and n<=65536,'switch read rejected')
   local s=bridge.read(base+at,n);assert(type(s)=='string'and #s==n,'switch evidence unreadable');return s
  end
  local dos=read(0,64);assert(dos:sub(1,2)=='MZ','invalid image');local pe=u32(dos,60)
  assert(pe>=64 and pe<=65536,'invalid PE');local nt=read(pe,168)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 required')
  local n,opt,size=u16(nt,6),u16(nt,20),u32(nt,80);assert(n>=1 and n<=96 and opt>=144 and opt<=4096,'image bounds rejected')
  local sections={}
  for i=0,n-1 do
   local h=read(pe+24+opt+i*40,40);local at,len,flags=u32(h,12),u32(h,8),u32(h,36)
   assert(at+len<=size,'section bounds rejected')
   sections[#sections+1]={at=at,len=len,read=math.floor(flags/0x40000000)%2==1,exec=math.floor(flags/0x20000000)%2==1}
  end
  local function inside(at,len,exec)
   for _,s in ipairs(sections)do if s.read and (not exec or s.exec)and at>=s.at and at+len<=s.at+s.len then return true end end
   return false
  end
  assert(inside(table_rva,count*4),'switch table outside readable image')
  local pdata,len=u32(nt,160),u32(nt,164)
  assert(u32(nt,132)>=4 and len>=12 and len%12==0 and len<=2400000 and inside(pdata,len),'function metadata unavailable')
  -- Search nearby PE-declared fragments. Optimized logical functions may be
  -- split into multiple .pdata rows; no guessed backward instruction starts.
  local lo,hi,index=0,len/12-1
  while lo<=hi do
   local mid=math.floor((lo+hi)/2);local row=read(pdata+mid*12,12);local first,last=u32(row,0),u32(row,4)
   if table_rva<first then hi=mid-1 elseif table_rva>=last then lo=mid+1 else index=mid;break end
  end
  assert(index,'switch table has no containing function metadata')
  local rows,proofs={},{}
  for i=math.max(0,index-255),index do
   local meta=read(pdata+i*12,12);local first,last=u32(meta,0),u32(meta,4)
   if first>=table_rva-16384 and first<table_rva and first<last and inside(first,last-first,true)then
    local length=math.min(last-first,table_rva-first)
    assert(length<=16384,'switch fragment too large')
    local code=read(first,length);proofs[#proofs+1]={at=first,bytes=code}
    for _,row in ipairs(M.decode(code,first,16384))do rows[#rows+1]=row end
   end
  end
  local found,selector_base
  for i,row in ipairs(rows)do
   local dst,reg,indexreg,disp=row.op:match('^mov (%w+), %[(%w+)%+(%w+)%*4%+0x(%x+)%]$')
   if disp and tonumber(disp,16)==table_rva then
    local dst64=dst:gsub('^e','r');local ix32=indexreg:gsub('^r','e')
    if rows[i+1]and rows[i+2]and rows[i+1].op=='add '..dst64..', '..reg and rows[i+2].op=='jmp '..dst64 then
     local imagebase,bound,decrement=false,false,false
     for j=math.max(1,i-256),i-1 do
      local op=rows[j].op;local sign,delta=op:match('^lea '..reg..', %[rip([+-])0x(%x+)%]$')
      local reg32=reg:gsub('^r','e')
      if op:match('^%w+ '..reg..',')or op:match('^%w+ '..reg32..',')then imagebase=false end
      if delta and rows[j+1]then
       local address=rows[j+1].rva+(sign=='-'and -1 or 1)*tonumber(delta,16)
       if address==0 then imagebase=true end
      end
      if j>=i-40 then
       local maximum=op:match('^cmp '..ix32..', [+]?0x(%x+)$')
       if maximum and tonumber(maximum,16)+1==count and rows[j+1]and rows[j+1].op:match('^ja ')then bound=true end
       if op=='dec '..ix32 then decrement=true end
      end
     end
     if imagebase and bound then assert(not found,'ambiguous switch evidence');found=row.rva;selector_base=decrement and 1 or 0 end
    end
   end
  end
  assert(found,'requested table/count lack the supported switch instruction proof')
  local table_bytes=read(table_rva,count*4)
  local out={string.format('HD2TRANSMOG_SWITCH_SEMANTICS 1\ndispatch=0x%08x selectors=%d..%d\nopens_armory=false',found,selector_base,count-1+selector_base)}
  for i=0,count-1 do
   local target=u32(table_bytes,i*4);assert(inside(target,1,true),'switch target outside executable image')
   out[#out+1]=string.format('selector=%d target=0x%08x',i+selector_base,target)
  end
  for _,p in ipairs(proofs)do assert(read(p.at,#p.bytes)==p.bytes,'switch code changed')end
  assert(read(table_rva,count*4)==table_bytes and bridge.verify(),'switch proof changed')
  return table.concat(out,'\n')..'\n'
 end)
 if not ok then return nil,tostring(result)end;return result
end
function M.new(bridge,report)
 assert(type(bridge)=='table' and type(bridge.read)=='function' and type(bridge.verify)=='function','verified debug bridge required')
 assert(type(bridge.base)=='number' and type(bridge.menu_global)=='number','menu global proof required')
 report=report or function()end
 local self={phase='resolving'};local lines={'HD2TRANSMOG_NATIVE_ARMORY_PROBE 1','purpose=read_only_transition_research','opens_armory=false'}
 local base=bridge.base;local sections={};local deadline=0
 local function output(value)
  assert(#lines<32768,'semantic output budget exceeded');lines[#lines+1]=value
 end
 local function read(rva,n)
  assert(type(rva)=='number'and rva>=0 and rva%1==0 and n>=1 and n<=262144,'debug read bounds rejected')
  local s=bridge.read(base+rva,n);assert(type(s)=='string'and #s==n,'native code unreadable');return s
 end
 local function executable(rva,n)
  for _,section in ipairs(sections)do if section.exec and rva>=section.rva and rva+n<=section.rva+section.size then return true end end
  return false
 end
 local function run()
  assert(bridge.verify(),'menu proof changed')
  local dos=read(0,64);assert(dos:sub(1,2)=='MZ','invalid image')
  local pe=u32(dos,60);assert(pe>=64 and pe<=65536,'PE offset rejected')
  local nt=read(pe,88);assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 required')
  local count,opt,size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(count>=1 and count<=96 and opt>=112 and opt<=4096 and size<=536870912,'PE bounds rejected')
  output('image_timestamp='..u32(nt,8));output(string.format('menu_global_rva=0x%08x',bridge.menu_global-base))
  local total=0
  for i=0,count-1 do
   local h=read(pe+24+opt+i*40,40);local len,rva,flags=u32(h,8),u32(h,12),u32(h,36)
   if len>0 then
    assert(rva>=4096 and rva+len<=size,'section bounds rejected')
    local exec=math.floor(flags/536870912)%2==1;local readable=math.floor(flags/1073741824)%2==1
    if exec then assert(readable,'unreadable code');total=total+len end
    sections[#sections+1]={rva=rva,size=len,exec=exec,readable=readable}
   end
  end
  assert(total>0 and total<=134217728,'code scan budget rejected')
  local pdata,pdata_size
  if opt>=144 then
   local d=read(pe+24+108,36);local rva,len=u32(d,28),u32(d,32)
   if u32(d,0)>=4 and len>=12 and len%12==0 and len<=2400000 then
    for _,s in ipairs(sections)do
     if s.readable and rva>=s.rva and rva+len<=s.rva+s.size then pdata,pdata_size=rva,len end
    end
   end
  end
  local function bounds(rva)
   if not pdata then return end
   local lo,hi=0,pdata_size/12-1
   while lo<=hi do
    local mid=math.floor((lo+hi)/2);local row=read(pdata+mid*12,12)
    local first,last=u32(row,0),u32(row,4)
    if rva<first then hi=mid-1 elseif rva>=last then lo=mid+1
    else if first<last and executable(first,last-first)then return first,last end;return end
   end
  end
  local found,call_targets,wrappers={},{},{};local hits,emitted,scanned=0,0,0
  local function inspect(rva)
   if found[rva]then return end;found[rva]=true;hits=hits+1;assert(hits<=4096,'menu xref limit exceeded')
   local available=160
   while available>0 and not executable(rva,available)do available=available-1 end
   local code=read(rva,available)
   local rows=M.decode(code,rva,32)
   local member,callee
   for index,row in ipairs(rows)do
    if row.op:find('0x4288',1,true)then member=index end
    if member then
     local target=row.op:match('^call%s+0x(%x+)$')or row.op:match('^jmp%s+0x(%x+)$')
     if target then callee=tonumber(target,16);break end
    end
    if row.op=='ret'or row.op:match('^int3')then break end
   end
   if not member or not callee then return end
   local first,last=bounds(rva)
   -- Recognize forwarding wrappers only at a PE-declared function start.
   if first==rva and last-first<=256 then wrappers[rva]=true end
   -- A Windows leaf tail-call thunk commonly has no unwind-table row. The
   -- exact MOV-global / ADD-subobject / JMP / INT3 sequence is still a useful
   -- target candidate; its CALLERS must pass the .pdata boundary check below.
   if rows[1]and rows[2]and rows[3]and rows[4]
    and rows[1].op:match('^mov rcx, %[%s*rip')
    and rows[2].op=='add rcx, 0x4288'and rows[3].op:match('^jmp%s+0x%x+$')
    and rows[4].op=='int3' then wrappers[rva]=true end
   emitted=emitted+1;assert(emitted<=384,'menu transition candidate limit exceeded')
   if executable(callee,1024)then call_targets[callee]=(call_targets[callee]or 0)+1 end
   output(string.format('xref=0x%08x',rva))
   for _,row in ipairs(rows)do
    output(string.format('  0x%08x %s',row.rva,row.op))
    if row.op=='ret'or row.op:match('^int3')then break end
   end
   assert(read(rva,available)==code,'menu reference changed during decode')
  end
  for _,section in ipairs(sections)do if section.exec then
   local tail=''
   for offset=0,section.size-1,262144 do
    assert(bridge.verify(),'menu proof changed')
    local chunk=read(section.rva+offset,math.min(262144,section.size-offset))
    local code=tail..chunk;local origin=section.rva+offset-#tail;local at=1
    while at<=#code-6 do
     if os.clock()>=deadline then coroutine.yield()end
     -- A RIP-relative MOV/LEA encoding of the proven global is a candidate
     -- anchor, not yet a function/ABI proof. Decode forward from that anchor;
     -- do not interpret isolated E8 bytes as calls. Function-start/xref
     -- confirmation remains necessary before deriving a callable entry point.
     local hit=code:find('[\139\141]',at)
     if not hit or hit+5>#code then break end
     local modrm=code:byte(hit+1)
     if modrm%8==5 and modrm<64 then
      local start=hit;local prefix=hit>1 and code:byte(hit-1)or 0
      if prefix>=64 and prefix<=79 then start=hit-1 end
      local target=base+origin+hit+5+i32(code,hit+1)
      if target==bridge.menu_global then inspect(origin+start-1)end
     end
     at=hit+1
    end
    scanned=scanned+#chunk;tail=code:sub(-8);self.scanned_bytes=scanned
    coroutine.yield() -- at most one large image read per step
   end
  end end
  local targets={};for rva in pairs(call_targets)do targets[#targets+1]=rva end
  table.sort(targets,function(a,b)if call_targets[a]~=call_targets[b]then return call_targets[a]>call_targets[b]end;return a<b end)
  output('xref_count='..hits);output('transition_candidates='..emitted);output('direct_call_targets='..#targets)
  -- Follow only a bounded first layer of direct callees from menu references.
  -- These are research candidates, not approved callable entry points.
  for index,rva in ipairs(targets)do
   if index>48 then output('callee_listing_truncated=true');break end
   if os.clock()>=deadline then coroutine.yield()end
   local code=read(rva,1024)
   output(string.format('callee=0x%08x',rva))
   for _,row in ipairs(M.decode(code,rva,160))do
    output(string.format('  0x%08x %s',row.rva,row.op))
    if row.op:match('^int3')then break end
   end
   assert(read(rva,1024)==code,'callee changed during decode')
  end
  -- The actual Armory site may call a forwarding wrapper, so it need not
  -- reference the menu global. Scan direct branches to dynamically observed
  -- wrappers/common callees, then validate instruction boundaries by decoding
  -- from the containing PE function's entry. Never infer from a lone E8 byte.
  if pdata then
   local sought={};local sought_count=0
   for rva in pairs(wrappers)do sought[rva]=true;sought_count=sought_count+1 end
   for index,rva in ipairs(targets)do if index<=16 and not sought[rva]then sought[rva]=true;sought_count=sought_count+1 end end
   output('branch_target_count='..sought_count)
   local branches,seen_branches=0,{}
   local function inspect_branch(at,target)
    if seen_branches[at]then return end;seen_branches[at]=true
    local first,last=bounds(at)
    if not first or at-first>2048 or at+5>last then return end
    local length=math.min(last-first,at-first+96)
    local code=read(first,length);local rows=M.decode(code,first,2048);local found_at
    for index,row in ipairs(rows)do if row.rva==at then
     local actual=row.op:match('^call%s+0x(%x+)$')or row.op:match('^jmp%s+0x(%x+)$')
     if actual and tonumber(actual,16)==target then found_at=index end;break
    end end
    if not found_at then return end
    assert(read(first,length)==code,'branch function changed during decode')
    branches=branches+1;assert(branches<=256,'validated branch budget exceeded')
    output(string.format('branch=0x%08x target=0x%08x function=0x%08x size=%d',at,target,first,last-first))
    for index=math.max(1,found_at-32),math.min(#rows,found_at+4)do
     local row=rows[index];output(string.format('  0x%08x %s',row.rva,row.op))
    end
   end
   for _,s in ipairs(sections)do if s.exec then
    local tail=''
    for offset=0,s.size-1,262144 do
     assert(bridge.verify(),'menu proof changed during branch scan')
     local chunk=read(s.rva+offset,math.min(262144,s.size-offset));local code=tail..chunk
     local origin=s.rva+offset-#tail;local at=1
     while at<=#code-4 do
      if os.clock()>=deadline then coroutine.yield()end
      local hit=code:find('[\232\233]',at);if not hit or hit+4>#code then break end
      local target=origin+hit+4+i32(code,hit)
      if sought[target]then inspect_branch(origin+hit-1,target)end
      at=hit+1
     end
     tail=code:sub(-4);coroutine.yield()
    end
   end end
   output('validated_branches='..branches)
  else output('branch_scan=PE_function_metadata_unavailable')end
  assert(bridge.verify(),'menu proof changed before completion')
  self.phase='ready';report('debug_armory.xrefs',hits);report('debug_armory.status','semantic_probe_complete')
 end
 local worker=coroutine.create(run)
 function self:step()
  if self.phase~='resolving'then return self.phase,self.failure end
  deadline=os.clock()+0.006
  local ok,why=coroutine.resume(worker)
  if not ok then self.phase='failed';self.failure=tostring(why);output('failure='..self.failure);report('debug_armory.status',self.failure)end
  return self.phase,self.failure
 end
 function self:summary()return table.concat(lines,'\n')..'\n'end
 return self
end
return M
