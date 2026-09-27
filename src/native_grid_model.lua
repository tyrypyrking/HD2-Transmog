-- Read-only logical grid evidence and detached presentation planning.
-- This module has no writer, FFI, native calls, or apply/restore method.
local M={}
local function u32(s,o)
 assert(type(s)=='string'and #s>=o+4,'logical grid read truncated')
 local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216
end
local function float(s,o)
 local n=u32(s,o);local sign=1;if n>=2147483648 then n=n-2147483648;sign=-1 end
 local e,m=math.floor(n/8388608),n%8388608
 assert(e~=255,'logical grid float invalid')
 return sign*(e==0 and m*2^-149 or (1+m/8388608)*2^(e-127))
end
local function copy(v)
 if type(v)~='table'then return v end
 local out={};for k,item in pairs(v)do out[k]=copy(item)end;return out
end
local function integer(n,low,high)return type(n)=='number'and n%1==0 and n>=low and n<=high end
local function attempt(fn)local ok,result=pcall(fn);if ok then return result end;return nil,tostring(result)end

-- read must be the caller's bounded observation journal; verify must reread it.
-- These are inspection limits, NOT a claim about native writable capacity.
function M.capture(read,grid,guard)
 return attempt(function()
  assert(type(guard)=='table'and guard.schema_verified==true and type(guard.verify)=='function','current logical schema proof required')
  local rows=u32(read(grid+0x91f14,4),0);assert(integer(rows,1,128),'logical row count rejected')
  local total=u32(read(grid+0x92984,4),0);assert(integer(total,1,256),'logical item count rejected')
  local heights,counts=read(grid+0x91f18,rows*4),read(grid+0x92318,rows*4)
  local offers=read(grid+0x92990,total*4)
  local flags_a,flags_b=read(grid+0x92dc2,total),read(grid+0x92ec2,total)
  local out={status='read_only_logical_model',mutation_supported=false,rows={},offers={},groups={},warnings={},
   row_count=rows,item_count=total,duplicate_offers={},height_sum=0,inspection_limits={rows=128,items=256,groups=32}}
  local seen,index={},0
  for i=0,rows-1 do
   local h,n=float(heights,i*4),u32(counts,i*4)
   assert(h>0 and h<=4096 and n<=8,'logical row geometry rejected')
   out.rows[i+1]={index=i,height=h,item_count=n,first_item=index,top=out.height_sum}
   index=index+n;out.height_sum=out.height_sum+h
  end
  assert(index==total,'logical row/item sum mismatch')
  for i=0,total-1 do
   local offer=u32(offers,i*4);assert(offer~=0,'empty logical offer')
   local mapped=guard.offer_lookup and guard.offer_lookup[offer]
   local item={index=i,offer_id=offer,flag_a=flags_a:byte(i+1),flag_b=flags_b:byte(i+1),kit_id=mapped and mapped.kit_id or nil,owned=mapped and mapped.owned==true or false}
   out.offers[i+1]=item
   if seen[offer]then out.duplicate_offers[#out.duplicate_offers+1]={offer_id=offer,first=seen[offer]-1,duplicate=i}
   else seen[offer]=i+1 end
  end
  local selection=read(grid+0x928d8,32)
  out.first_visible_row=u32(selection,0);out.selected_row=u32(selection,16)
  out.selected_column=u32(selection,20);out.selected_group=u32(selection,24)
  out.selected_offer=u32(read(grid+0x92988,4),0)
  out.marker_offer=u32(read(grid+0x9298c,4),0)
  local row=out.rows[out.selected_row+1]
  if row and out.selected_column<row.item_count then
   out.selected_index=row.first_item+out.selected_column
   out.selected_offer_matches=out.offers[out.selected_index+1].offer_id==out.selected_offer
  else out.selected_offer_matches=false end
  out.scroll=float(read(grid+0x92960,4),0);out.content=float(read(grid+0x92968,4),0)
  assert(out.scroll>=0 and out.scroll<=1000000 and out.content>0 and out.content<=1000000,'logical scroll bounds rejected')
  out.content_matches_height_sum=math.abs(out.content-out.height_sum)<.01
  local n=u32(read(grid+0x92748,4),0);assert(integer(n,1,32),'logical group count rejected')
  local bounds=read(grid+0x9274c,(n+1)*4);local thresholds=read(grid+0x927d0,n*4)
  local group_keys=read(grid+0x92854,n*4)
  out.group_count=n;out.group_row_terminal=u32(bounds,n*4);out.raw_group_starts={};out.group_partition_verified=true
  local function warning(text)out.warnings[#out.warnings+1]=text;out.group_partition_verified=false end
  local prior=0
  for i=0,n-1 do
   local first=u32(bounds,i*4)
   -- Append stores group starts only. The unused terminal remains zero after Clear.
   local last=i==n-1 and rows or u32(bounds,(i+1)*4)
   out.raw_group_starts[i+1]=first
   local bounded=first<=last and last<=rows
   if not bounded then warning('group '..i..' raw boundary interval is not a bounded logical row interval')end
   if first~=prior then warning('group '..i..' does not continue the assumed row partition')end;prior=last
   local threshold=u32(thresholds,i*4)
   -- The solver compares skipped_items > threshold. Its inclusive/exclusive
   -- convention and relation to header padding remain observations to resolve.
   if threshold>total then warning('group '..i..' raw item threshold exceeds observed items')end
   out.groups[i+1]={index=i,key=u32(group_keys,i*4),first_row=first,end_row=last,item_threshold=threshold,
    bounded_row_interval=bounded,
    first_item=first<=rows and (first<rows and out.rows[first+1].first_item or total)or nil,
    end_item=last<=rows and (last<rows and out.rows[last+1].first_item or total)or nil}
  end
  if u32(bounds,0)~=0 then warning('first raw group start is not zero')end
  if prior~=rows then warning('group row partition is incomplete')end
  for _,group in ipairs(out.groups)do
   if group.bounded_row_interval and group.first_item==group.item_threshold then
    for i=group.first_item+1,group.end_item do out.offers[i].group_key=group.key end
   else warning('group first-item boundary differs from native Append contract')end
  end
  local selected_group=out.groups[out.selected_group+1]
  out.selected_group_matches=selected_group~=nil and selected_group.bounded_row_interval
   and out.selected_row>=selected_group.first_row and out.selected_row<selected_group.end_row
  out.verify=guard.verify;out.verify_owned=guard.verify_owned
  assert(guard.verify()==true,'logical grid changed during observation')
  return out
 end)
end

-- A pure proposal, deliberately not byte offsets or a transaction write set.
-- Header representation and item-threshold rules are NOT guessed here.
function M.plan_prefix(model,cards,options)
 return attempt(function()
  assert(type(model)=='table'and model.status=='read_only_logical_model','logical model required')
  assert(type(model.verify)=='function'and model.verify()==true,'logical model stale')
  assert(model.group_partition_verified and model.selected_offer_matches and model.selected_group_matches,'logical group or selection invariant unresolved')
  assert(#model.duplicate_offers==0,'source offers already ambiguous')
  assert(type(cards)=='table'and #cards>=1 and #cards<=32,'custom card count rejected')
  options=options or {};local columns,height=options.columns,options.card_height
  assert(integer(columns,1,8),'explicit native column count required')
  local measured=false
  for _,row in ipairs(model.rows)do if row.item_count==columns and row.height==height then measured=true end end
  assert(measured,'card row shape was not observed in native model')
  local by_kit,keys,owned_ids={}, {}, {};local create_count=0
  for _,offer in ipairs(model.offers)do if offer.kit_id and offer.owned and not by_kit[offer.kit_id]then by_kit[offer.kit_id]=offer end end
  local prefix={};local names={}
  for i,card in ipairs(cards)do
   assert(type(card)=='table'and type(card.key)=='string'and #card.key>0 and #card.key<=128 and not keys[card.key],'unique presentation card identity required')
   assert(card.kind=='variant'or card.kind=='create','custom card kind rejected')
   keys[card.key]=true
   if card.kind=='create'then create_count=create_count+1;assert(i==#cards,'create card must follow saved variants')end
   local offer=by_kit[card.kit_id];assert(offer,'custom card requires an owned appearance already in native offers')
   prefix[i]={key=card.key,kind=card.kind,kit_id=card.kit_id,offer_id=offer.offer_id,owned=true,
    source_index=offer.index,requires_input_capture=true,opaque=card.kind=='create'}
   if not names[card.kit_id]then owned_ids[#owned_ids+1]=card.kit_id;names[card.kit_id]=true end
  end
  assert(create_count==1,'exactly one final create card required')
  assert(type(model.verify_owned)=='function'and model.verify_owned(owned_ids)==true,'fresh owned appearances required')
  local added_rows=math.ceil(#prefix/columns)
  assert(model.row_count+added_rows<=model.inspection_limits.rows and model.item_count+#prefix<=model.inspection_limits.items
   and model.group_count+1<=model.inspection_limits.groups,'proposal exceeds inspection limits')
  local out={status='detached_prefix_proposal',mutation_supported=false,native_capacity_verified=false,
   cards=prefix,rows={},offers={},groups={},added_rows=added_rows,added_items=#prefix,
   row_count=model.row_count+added_rows,item_count=model.item_count+#prefix,group_count=model.group_count+1,
   group_row_terminal=model.group_row_terminal+added_rows,
   selected_offer=model.selected_offer,selected_row=model.selected_row+added_rows,
   selected_column=model.selected_column,selected_group=model.selected_group+1,
   requires={'native array capacity','header label/metadata construction','item threshold convention',
    'header height accounting','native refresh ordering','duplicate offer selection and equip interception'}}
  for i=1,added_rows do
   out.rows[i]={index=i-1,height=height,item_count=math.min(columns,#prefix-(i-1)*columns),first_item=(i-1)*columns,custom=true}
  end
  for i,card in ipairs(prefix)do local v=copy(card);v.index=i-1;out.offers[i]=v end
  for _,row in ipairs(model.rows)do local v=copy(row);v.index=v.index+added_rows;v.first_item=v.first_item+#prefix;v.top=nil;out.rows[#out.rows+1]=v end
  for _,offer in ipairs(model.offers)do local v=copy(offer);v.index=v.index+#prefix;out.offers[#out.offers+1]=v end
  out.groups[1]={index=0,label='Custom Variant',first_row=0,end_row=added_rows,first_item=0,end_item=#prefix}
  for _,group in ipairs(model.groups)do local v=copy(group);v.index=v.index+1;v.first_row=v.first_row+added_rows;v.end_row=v.end_row+added_rows
   v.first_item=v.first_item+#prefix;v.end_item=v.end_item+#prefix;v.item_threshold=nil;out.groups[#out.groups+1]=v end
  out.original_selection_index=model.selected_index+#prefix
  assert(out.offers[out.original_selection_index+1].offer_id==model.selected_offer,'prefix changed original selection identity')
  assert(model.verify()==true and model.verify_owned(owned_ids)==true,'prefix evidence changed during planning')
  return out
 end)
end
function M.format(model)
 local out={'HD2TM_ARMORY_LOGICAL_MODEL 1','mutation_supported=false'}
 for _,key in ipairs({'status','row_count','item_count','group_count','group_row_terminal','group_partition_verified',
  'height_sum','content','content_matches_height_sum','scroll','selected_row','selected_column','selected_group',
  'selected_offer','selected_offer_matches','selected_group_matches','first_visible_row'})do out[#out+1]=key..'='..tostring(model[key])end
 for i,v in ipairs(model.raw_group_starts or {})do out[#out+1]=string.format('raw_group_start index=%d value=%u',i-1,v)end
 for _,v in ipairs(model.groups or {})do out[#out+1]=string.format('group index=%d raw_start=%u raw_next=%u bounded_interval=%s first_item=%s end_item=%s item_threshold=%u',v.index,v.first_row,v.end_row,tostring(v.bounded_row_interval),tostring(v.first_item),tostring(v.end_item),v.item_threshold)end
 for _,v in ipairs(model.warnings or {})do out[#out+1]='warning='..v end
 for _,v in ipairs(model.rows or {})do out[#out+1]=string.format('row index=%d height=%s count=%d first_item=%d top=%s',v.index,tostring(v.height),v.item_count,v.first_item,tostring(v.top))end
 for _,v in ipairs(model.offers or {})do out[#out+1]=string.format('offer index=%d offer=%u kit=%s owned=%s',v.index,v.offer_id,tostring(v.kit_id or 'unmapped'),tostring(v.owned))end
 for _,v in ipairs(model.duplicate_offers or {})do out[#out+1]=string.format('duplicate offer=%u first=%d duplicate=%d',v.offer_id,v.first,v.duplicate)end
 return table.concat(out,'\n')..'\n'
end
return M
