-- Bounded, read-only native kit/progression observation. No native calls, writes,
-- raw-memory export, address fallback, or ownership inference from equipped gear.
-- Offsets below are verified by catalog_data's typelib or by the independently
-- resolved gear_catalog_categories / progression_owned_layout signatures.
-- new(bridge, data, report):step() -> 'resolving'|'ready'|'failed', result|reason
-- bridge = {read, armor_catalog=<global slot>, progression=<global slot>,
--           verify=function() -> bool, localize=function(u32) -> string?}
-- Retain pristine records while a composition is active. refresh_ownership()
-- updates progression only; verify_owned still rechecks each operation. A changed
-- catalog session requires a new full observation when no retained patch uses it.
local M={}
local Helmets=HelmetCatalog or require('src.helmet_catalog')
local function u32(s,o)
 if not s or #s<o+4 then return nil end
 local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216
end
local function pointer(s,o)
 o=o or 0;local lo,hi=u32(s,o),u32(s,o+4)
 if not hi or hi>=32768 then return nil end
 local n=lo+hi*4294967296;return n>=65536 and n or nil
end
local function bytes(h)return(h:gsub('%x%x',function(v)return string.char(tonumber(v,16))end))end
local function id(n)return string.format('%08x',n)end
local function plain_effect(text)
 -- Localization is already bounded to <1024 bytes. Strip only the native
 -- color tags; retain wording, comparison signs and unknown literal markup.
 return(text:gsub('<[^>]+>',function(tag)
  if tag:match('^<[cC]=[^<>]+>$')or tag:match('^</[cC]>$')then return ''end
  return tag
 end))
end
local function field_labels(data,bridge,pause,passives_verified,category)
 category=category or 0
 local labels={appearance_id={},stats_id={},passive_variant_id={}}
 local details={appearance_id={},stats_id={},passive_variant_id={}}
 local stats_profiles,passive_variants={},{}
 local localized={}
 local function name(loc,fallback)
  pause()
  if localized[loc]~=nil then return localized[loc]or fallback end
  if type(bridge.localize)=='function' then
   local ok,value=pcall(bridge.localize,loc)
   if ok and type(value)=='string' and #value>0 and #value<1024 then localized[loc]=value;return value end
  end
  localized[loc]=false
  return fallback
 end
 for key,kit in pairs(data.kits)do if kit.category==category then
  local label=name(kit.name_cased,(category==1 and 'Helmet 'or 'Armor ')..id(key))
  labels.appearance_id[kit.id]=label
  details.appearance_id[kit.id]=category==1 and {'Uses a helmet you own.'}or {'Uses an armor you own.','Helmet and cape are separate choices.'}
  local stat='native-stats:'..id(key)
  labels.stats_id[stat]=label
  details.stats_id[stat]=category==1 and {'Copies this helmet’s native weight profile.','Numeric totals and passive stacking require live validation.'}
   or {"Uses this armor's base weight profile.",'Your selected perk is applied once to that base.'}
  local body_weights={}
  for _,body in ipairs(kit.bodies)do
   local entries={}
   for _,piece in ipairs(body.pieces)do entries[#entries+1]={slot=piece.slot,kind=piece.type,weight=piece.weight}end
   body_weights[#body_weights+1]={body_type=body.type,pieces=entries}
  end
  stats_profiles[stat]={source_kit_id=kit.id,base_profile_id=stat,base_only=true,
   weight_profile_verified=true,body_weights=body_weights,native_perk_variant_id=kit.passive_variant_id}
  local passive=data.passives[kit.passive_enum]
  if not passive_variants[passive.variant_id]then
  labels.passive_variant_id[passive.variant_id]=name(passive.name_loc,'Passive '..tostring(kit.passive_enum))
  local clauses={}
  for _,effect in ipairs(passive.modifiers)do
   local text=name(effect.description_loc,nil)
   if text then
    local value=effect.value;local bonus=string.format('%g',value);local sign=value<0 and '-'or '+'
    if effect.type==2 then
     bonus=tostring(math.floor(math.abs(value-1)*100+0.5))..'%';sign=value<1 and '-'or '+'
    elseif effect.type==3 then bonus=bonus..' seconds'end
    text=text:gsub('#BONUS',function()return bonus end):gsub('#SIGN',function()return sign end)
    clauses[#clauses+1]=plain_effect(text)
   elseif effect.modifier_id~=0 then
    clauses[#clauses+1]='Additional effect - description unavailable'
   end
  end
  if not passives_verified then clauses[#clauses+1]='Effect values from pinned catalog; live bundle not verified'end
  details.passive_variant_id[passive.variant_id]=clauses
  passive_variants[passive.variant_id]={enum=passive.enum,icon_hash=passive.icon,
   name=labels.passive_variant_id[passive.variant_id],effects=clauses,
   modifiers=passive.modifiers,stat_modifiers=passive.stat_modifiers,
   behavior_tag=passive.behavior_tag,live_effects_verified=passives_verified==true}
  end
 end end
 return labels,details,stats_profiles,passive_variants
end
function M.new(bridge,data,report)
 assert(type(bridge)=='table' and type(bridge.read)=='function','read bridge required')
 assert(type(data)=='table' and type(data.kits)=='table' and type(data.passives)=='table','catalog reference required')
 report=report or function()end
 local self={phase='resolving'}
 local deadline,reads,read_bytes=0,0,0
 local function pause(n)
  if reads>=64 or read_bytes+(n or 0)>65536 or os.clock()>=deadline then coroutine.yield();reads=0;read_bytes=0 end
 end
 local watched={}
 local function read(at,n)
  assert(type(at)=='number' and at>=65536 and at%1==0 and n>=1 and n<=65536 and at+n<140737488355328,'catalog read bounds rejected')
  pause(n);reads=reads+1;read_bytes=read_bytes+n
  local s=bridge.read(at,n)
  assert(type(s)=='string' and #s==n,'catalog data unreadable')
  return s
 end
 local function watch(at,n)
  local s=read(at,n);watched[#watched+1]={at=at,size=n,bytes=s};return s
 end
 local function ptr(at)return assert(pointer(watch(at,8)),'catalog pointer unavailable')end
 local function run()
  if bridge.verify then assert(bridge.verify(),'catalog compatibility evidence changed')end
  local reference_count=0;for _ in pairs(data.kits)do reference_count=reference_count+1 end
  local catalog_at=ptr(bridge.armor_catalog)
  local catalog_slot=watch(bridge.armor_catalog,8)
  local header=watch(catalog_at,12)
  local first,n=pointer(header),u32(header,8)
  assert(first and n and n>=1 and n<=2048,'catalog bounds rejected')
  local kit_slots=watch(first,n*8)
  -- Unknown/changed content is isolated, but structural ambiguity, unreadable
  -- memory, invalid bounds/pointers and races still invalidate the provider.
  local records,seen,matched_kits,diagnostics={},{},{},{}
  local helmet_passives={}
  local function helmet_passive(enum)
   if helmet_passives[enum]then return helmet_passives[enum]end
   assert(enum>=0 and enum<=255,'helmet passive enum bounds rejected')
   local h=watch(catalog_at+0x20,12);local array,n=pointer(h),u32(h,8)
   assert(array and n>=1 and n<=256,'helmet passive catalog bounds rejected')
   local index=u32(watch(catalog_at+0x30+enum*4,4),0)
   assert(index<n,'helmet passive index rejected')
   local raw=watch(ptr(array+index*8),56)
   assert(u32(raw,0)==enum,'helmet passive identity differs')
   local function float(s,o)
    local v=u32(s,o);local sign=v>=2147483648 and -1 or 1
    local e=math.floor(v/8388608)%256;local m=v%8388608
    assert(e<255,'non-finite helmet passive modifier')
    return sign*(e==0 and m*2^-149 or (1+m/8388608)*2^(e-127))
   end
   local function hex(s)return(s:gsub('.',function(c)return string.format('%02x',c:byte())end))end
   local p={enum=enum,name_loc=u32(raw,4),icon=hex(raw:sub(9,16):reverse()),behavior_tag=u32(raw,48),
    modifiers={},stat_modifiers={},raw_modifiers={},raw_stat_modifiers={}}
   for _,spec in ipairs({{16,16,'modifiers','raw_modifiers'},{32,12,'stat_modifiers','raw_stat_modifiers'}})do
    local count,high=u32(raw,spec[1]+8),u32(raw,spec[1]+12)
    assert(high==0 and count<=64,'helmet passive modifier bounds rejected')
    local at=count>0 and assert(pointer(raw,spec[1]),'helmet passive modifier pointer unavailable')
    for j=0,count-1 do
     local value=watch(at+j*spec[2],spec[2]);p[spec[4]][j+1]=hex(value)
     p[spec[3]][j+1]=spec[1]==16 and {modifier_id=u32(value,0),type=u32(value,4),value=float(value,8),description_loc=u32(value,12)}
      or {stat=u32(value,0),add_value=float(value,4),mul_value=float(value,8)}
    end
   end
   local fingerprint=table.concat(p.raw_modifiers)..'|'..table.concat(p.raw_stat_modifiers)..'|'..p.behavior_tag
   local known=data.passives[enum]
   if known and fingerprint==table.concat(known.raw_modifiers)..'|'..table.concat(known.raw_stat_modifiers)..'|'..known.behavior_tag then
    p.variant_id=known.variant_id
   else
    local a,b=5381,52711
    for j=1,#fingerprint do a=(a*33+fingerprint:byte(j))%4294967296;b=(b*65599+fingerprint:byte(j))%4294967296 end
    p.variant_id=string.format('helmet-passive:%d:%08x%08x',enum,a,b)
   end
   helmet_passives[enum]=p;return p
  end
  local matched_count,matched_armors,unknown_count,changed_count=0,0,0,0
  for i=0,n-1 do
   local slot_at=first+i*8
   local slot_bytes=kit_slots:sub(i*8+1,i*8+8)
   local at=assert(pointer(slot_bytes),'catalog pointer unavailable');local raw=watch(at,64);local key=u32(raw,0)
   assert(key and key~=0 and not seen[key],'invalid or duplicate kit identity');seen[key]=true
   local expected=data.kits[key]
   if expected then expected=Helmets.reference(expected,raw)end
   if not expected then
    unknown_count=unknown_count+1;diagnostics[#diagnostics+1]={id='armor:'..id(key),reason='unknown_reference'}
   else
    local mismatch
    local function differs(reason)if not mismatch then mismatch=reason end end
    if raw:sub(1,44)~=bytes(expected.header)then differs('header_mismatch')end
    local body_count,high=u32(raw,56),u32(raw,60)
    assert(high==0 and body_count and body_count<=8,'kit body bounds rejected')
    if body_count~=#expected.bodies then differs('body_count_mismatch')end
    local bodies_at=body_count>0 and assert(pointer(raw,48),'body pointer unavailable')or nil
    local bodies={}
    for j=1,body_count do
     local body=expected.bodies[j]
     local body_at=bodies_at+(j-1)*24;local body_raw=watch(body_at,24)
     local body_type,piece_count,piece_high=u32(body_raw,0),u32(body_raw,16),u32(body_raw,20)
     assert(piece_high==0 and piece_count and piece_count<=64,'piece bounds rejected')
     if body and body_type~=body.type then differs('body_type_mismatch')end
     if not body or piece_count~=#body.pieces then differs('piece_count_mismatch')end
     local pieces_at=piece_count>0 and assert(pointer(body_raw,8),'piece pointer unavailable')or nil
     local piece_array=piece_count>0 and watch(pieces_at,piece_count*96)or ''
     local pieces={}
     for k=1,piece_count do
      local piece=body and body.pieces[k]
      local piece_at=pieces_at+(k-1)*96;local piece_raw=piece_array:sub((k-1)*96+1,k*96)
      if piece then Helmets.piece(piece,piece_raw,expected)end
      if not piece or piece_raw~=bytes(piece.raw)then differs('piece_mismatch')end
      if piece then
       pieces[k]={address=piece_at,bytes=piece_raw,slot=piece.slot,kind=piece.type,weight=piece.weight,path=piece.path}
      end
     end
     bodies[j]={address=body_at,bytes=body_raw,type=body_type,pieces=pieces}
    end
    if expected.category==1 then
     local ok,passive=pcall(helmet_passive,expected.passive_enum)
     if ok then expected.passive_variant_id=passive.variant_id else differs('unverified_helmet_passive')end
    end
    if mismatch then
     changed_count=changed_count+1;diagnostics[#diagnostics+1]={id=expected.id,reason=mismatch}
    else
     matched_count=matched_count+1;matched_kits[key]=expected
     if expected.category==0 then matched_armors=matched_armors+1 end
     records[expected.id]={address=at,bytes=raw,item_id=key,category=expected.category,bodies=bodies,reference=expected,
      slot_address=slot_at}
     -- Retain the exact observed array slot for selected-record freshness.
     records[expected.id].slot_bytes=slot_bytes
    end
   end
  end
  assert(matched_armors>0,'no verified armor records available')
  table.sort(diagnostics,function(a,b)return a.id<b.id end)
  report('catalog.kits_observed',n);report('catalog.kits_matched',matched_count)
  report('catalog.kits_unknown',unknown_count);report('catalog.kits_changed',changed_count)
  for _,entry in ipairs(diagnostics)do report('catalog.unavailable.'..entry.id,entry.reason)end
  -- Native passive lookup is evidenced by the current Armory description path:
  -- manager+0x30[enum] -> index, manager+0x20[index] -> 56-byte settings record.
  -- Every scalar and nested modifier byte is compared with the current typelib
  -- reference. A failure disables this optional evidence, never ownership.
  local live_passives={}
  local passive_watch_start=#watched
  local passive_ok,passive_why=pcall(function()
   local passive_header=watch(catalog_at+0x20,12)
   local first_passive,passive_count=pointer(passive_header),u32(passive_header,8)
   assert(first_passive and passive_count and passive_count>=1 and passive_count<=256,'passive catalog bounds rejected')
   local known=0;for _ in pairs(data.passives)do known=known+1 end
   assert(passive_count>=known,'passive catalog is shorter than the reference')
   local used={}
   for enum,expected in pairs(data.passives)do
    assert(type(enum)=='number'and enum>=0 and enum<=255,'passive enum bounds rejected')
    local index=u32(watch(catalog_at+0x30+enum*4,4),0)
    assert(index and index<passive_count and not used[index],'passive enum map rejected');used[index]=true
    local at=ptr(first_passive+index*8);local raw=watch(at,56)
    assert(u32(raw,0)==enum and u32(raw,4)==expected.name_loc,'passive identity mismatch')
    assert(raw:sub(9,16)==bytes(expected.icon):reverse(),'passive icon mismatch')
    assert(u32(raw,48)==expected.behavior_tag,'passive behavior mismatch')
    local function modifiers(offset,size,list)
     local count,high=u32(raw,offset+8),u32(raw,offset+12)
     assert(high==0 and count==#list and count<=64,'passive modifier count mismatch')
     if count==0 then return end
     local array=assert(pointer(raw,offset),'passive modifier pointer unavailable')
     for i,value in ipairs(list)do assert(watch(array+(i-1)*size,size)==bytes(value),'passive modifier bytes changed')end
    end
    modifiers(16,16,expected.raw_modifiers);modifiers(32,12,expected.raw_stat_modifiers)
    live_passives[expected.variant_id]={address=at,bytes=raw,enum=enum,reference=expected}
   end
  end)
  if not passive_ok then
   live_passives={}
   for i=#watched,passive_watch_start+1,-1 do watched[i]=nil end
   report('catalog.passives_unavailable',tostring(passive_why))
  else report('catalog.passive_effects_verified',true)end
  local progression=ptr(bridge.progression)
  local progression_slot=watch(bridge.progression,8)
  local count=u32(watch(progression+0x1ce0,4),0)
  assert(count and count>=1 and count<=4096,'progression count rejected')
  local ownership,ownership_proofs={},{}
  -- Only Armor ownership is consumed by this provider. Read offer columns in
  -- bounded batches, then inspect states for matched armor identities. Cache
  -- no ownership across observations; the selected fields are reread below.
  local entry_batch,batch_first,batch_count
  for i=0,count-1 do
   if not entry_batch or i>=batch_first+batch_count then
    batch_first=i;batch_count=math.min(128,count-i)
    local at=progression+0xb9ce4+i*24
    entry_batch=read(at,(batch_count-1)*24+12)
    watched[#watched+1]={at=at,size=#entry_batch,bytes=entry_batch,stride=24,width=12,count=batch_count}
   end
   local offset=(i-batch_first)*24
   local entry=entry_batch:sub(offset+1,offset+12)
   local index,item=u32(entry,0),u32(entry,8)
   assert(index<count,'progression index rejected')
   local kit=matched_kits[item]
   if kit and (kit.category==0 or kit.category==1) then
   local state=progression+0x1ce4+index*184
   local status=u32(watch(state+0x14,4),0)
   local enabled=watch(state+0xb4,1):byte()==0
   local allowed=(status==2 or status==4)and enabled
   -- Several offers may grant the same item. Mirror the reference's positive
   -- per-item union: one enabled status-2/4 offer proves ownership; an unrelated
   -- locked/disabled offer for that item never revokes the positive evidence.
   if item~=0 and allowed then
    ownership[item]=true
    if not ownership_proofs[item]then
     ownership_proofs[item]={entry_address=progression+0xb9ce4+i*24,entry_bytes=entry,state_address=state}
    end
   end
   end
  end
  -- Re-read only observed spans; a race invalidates the entire result.
  for _,span in ipairs(watched)do
   local current=read(span.at,span.size)
   if span.stride then
    -- Unused offer payload bytes were read only to batch the known columns.
    -- They are neither interpreted nor promoted into compatibility evidence.
    for i=0,span.count-1 do
     local first=i*span.stride+1;local last=first+span.width-1
     assert(current:sub(first,last)==span.bytes:sub(first,last),'catalog or ownership changed during observation')
    end
   else assert(current==span.bytes,'catalog or ownership changed during observation')end
  end
  if bridge.verify then assert(bridge.verify(),'catalog compatibility evidence changed')end
  local catalog,owned,owned_count={}, {},0
  for key,kit in pairs(matched_kits)do if kit.category==0 then
   catalog[kit.id]={appearance_id=kit.id,stats_id='native-stats:'..id(key),passive_variant_id=kit.passive_variant_id}
   if ownership[key] then owned[kit.id]=true;owned_count=owned_count+1 end
  end end
  local labels,details,stats_profiles,passive_variants=field_labels({kits=matched_kits,passives=data.passives},bridge,pause,passive_ok)
  local helmet_catalog,helmet_owned={},{}
  for key,kit in pairs(matched_kits)do if kit.category==1 then
   helmet_catalog[kit.id]={appearance_id=kit.id,stats_id='native-stats:'..id(key),passive_variant_id=kit.passive_variant_id}
   if ownership[key]then helmet_owned[kit.id]=true end
  end end
  local hl,hd,hs,hp=field_labels({kits=matched_kits,passives=helmet_passives},bridge,pause,true,1)
  local helmet_caps=Helmets.capabilities(matched_kits,helmet_passives)
  -- Fast freshness checks for a later application transaction. These functions
  -- are called outside our coroutine: never use the yielding reader here.
  -- Preserve only the selected progression evidence, never serialize it.
  local function session_valid()
   return type(bridge.verify)=='function' and bridge.verify()
    and bridge.read(bridge.armor_catalog,8)==catalog_slot
    and bridge.read(catalog_at,12)==header
    and bridge.read(bridge.progression,8)==progression_slot
  end
  local function verify_session()
   local ok,value=pcall(session_valid);return ok and value==true
  end
  local function verify_owned(ids)
   local ok,value=pcall(function()
    if not session_valid()or type(ids)~='table' or u32(bridge.read(progression+0x1ce0,4),0)~=count then return false end
    local requested={};local checked=0
    for key,value in pairs(ids)do
     local kit_id=type(key)=='number' and value or (value==true and key or nil)
     if type(kit_id)~='string'then return false end
     requested[kit_id]=true;checked=checked+1;if checked>16 then return false end
    end
    for kit_id in pairs(requested)do
     local record=records[kit_id]
     local proof=record and ownership_proofs[record.item_id]
     -- Recheck the qualifying offer retained above. If it changes, demand a
     -- new observation even if another offer may now grant the same item.
     if not proof or (record.category~=0 and record.category~=1) or bridge.read(record.slot_address,8)~=record.slot_bytes
      or bridge.read(proof.entry_address,12)~=proof.entry_bytes then return false end
     local status=u32(bridge.read(proof.state_address+0x14,4),0)
     if (status~=2 and status~=4)or bridge.read(proof.state_address+0xb4,1)~='\0' then return false end
    end
    return checked>0 and session_valid()
   end)
   return ok and value==true
  end
  self.result={catalog=catalog,owned=owned,records=records,passives=live_passives,
   context={labels=labels,details=details,stats_profiles=stats_profiles,passive_variants=passive_variants,
    catalog_status=(unknown_count+changed_count>0)and 'verified native subset; other records unavailable'or 'native kit and ownership observed'},
   diagnostics=diagnostics,
   source_commit=data.source_commit,counts={kits=n,observed=n,matched=matched_count,unavailable=unknown_count+changed_count,
    unknown=unknown_count,changed=changed_count,missing_reference=reference_count-matched_count-changed_count,
    verified_armors=matched_armors,owned_armors=owned_count,progression=count},
   capabilities={kit_records_verified=true,ownership_verified=true,numeric_stats_verified=false,exact_passive_effects_verified=passive_ok},
   verify_session=verify_session,verify_owned=verify_owned}
  self.result.helmets={category=1,catalog=helmet_catalog,owned=helmet_owned,records=records,passives=live_passives,
   context={labels=hl,details=hd,stats_profiles=hs,passive_variants=hp},
   capabilities={kit_records_verified=true,ownership_verified=true,helmet_transmog_enabled=helmet_caps.enabled},
   detected=helmet_caps,verify_session=verify_session,verify_owned=verify_owned}
  -- Ownership may change while a composed carrier remains live. Refresh only
  -- progression evidence; the kit records above are pristine reset baselines.
  local ownership_worker
  local function ownership_session_valid()
   return type(bridge.verify)=='function'and bridge.verify()
    and read(bridge.armor_catalog,8)==catalog_slot and read(catalog_at,12)==header
    and read(bridge.progression,8)==progression_slot
  end
  local function refresh_owned()
   assert(ownership_session_valid(),'catalog session changed during ownership refresh')
   local spans={}
   local function observed(at,n)
    local value=read(at,n);spans[#spans+1]={at=at,bytes=value};return value
   end
   local next_count=u32(observed(progression+0x1ce0,4),0)
   assert(next_count and next_count>=1 and next_count<=4096,'progression count rejected')
   local next_owned,next_proofs,next_helmets={},{},{}
   local next_total=0
   for i=0,next_count-1 do
    local entry_at=progression+0xb9ce4+i*24
    local entry=observed(entry_at,12)
    local index,item=u32(entry,0),u32(entry,8)
    assert(index and index<next_count,'progression index rejected')
    local kit=matched_kits[item]
    if kit and (kit.category==0 or kit.category==1) then
     local record=records[kit.id]
     assert(observed(record.slot_address,8)==record.slot_bytes,'catalog record slot changed')
     local state=progression+0x1ce4+index*184
     local status=u32(observed(state+0x14,4),0)
     local enabled=observed(state+0xb4,1):byte()==0
     if (status==2 or status==4)and enabled then
      if kit.category==0 then
       if not next_owned[kit.id]then next_total=next_total+1 end
       next_owned[kit.id]=true
      else next_helmets[kit.id]=true end
      if not next_proofs[item]then
       next_proofs[item]={entry_address=entry_at,entry_bytes=entry,state_address=state}
      end
     end
    end
   end
   for _,span in ipairs(spans)do
    assert(read(span.at,#span.bytes)==span.bytes,'ownership changed during refresh')
   end
   assert(ownership_session_valid(),'catalog session changed during ownership refresh')
   local changed=self.result.capabilities.ownership_verified~=true
   self.result.helmets.owned=next_helmets
   self.result.helmets.capabilities.ownership_verified=true
   for key in pairs(next_owned)do if not self.result.owned[key]then changed=true end end
   for key in pairs(self.result.owned)do if not next_owned[key]then changed=true end end
   count=next_count;ownership_proofs=next_proofs
   self.result.owned=next_owned
   self.result.counts.owned_armors=next_total;self.result.counts.progression=next_count
   self.result.capabilities.ownership_verified=true
   return changed
  end
  function self.result.refresh_ownership()
   if not ownership_worker then ownership_worker=coroutine.create(refresh_owned)end
   deadline=os.clock()+0.006;reads=0;read_bytes=0
   local ok,value=coroutine.resume(ownership_worker)
   if not ok then
    ownership_worker=nil;ownership_proofs={};self.result.owned={}
    self.result.helmets.owned={};self.result.helmets.capabilities.ownership_verified=false
    self.result.counts.owned_armors=0;self.result.capabilities.ownership_verified=false
    return 'failed',tostring(value)
   end
   if coroutine.status(ownership_worker)=='dead'then ownership_worker=nil;return 'ready',value end
   return 'resolving'
  end
  self.phase='ready';watched={}
  report('catalog.owned_armors',owned_count);report('catalog.status',(unknown_count+changed_count>0)and 'native_catalog_subset_verified'or 'native_catalog_verified')
 end
 local worker=coroutine.create(run)
 function self:step()
  if self.phase=='ready'then return 'ready',self.result end
  if self.phase=='failed'then return 'failed',self.failure end
  deadline=os.clock()+0.006;reads=0;read_bytes=0
  local ok,why=coroutine.resume(worker)
  if not ok then self.failure=tostring(why);self.phase='failed';watched={};report('catalog.status',self.failure)end
  return self.phase,self.result or self.failure
 end
 return self
end
return M
