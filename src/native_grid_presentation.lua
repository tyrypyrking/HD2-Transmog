-- Presentation-only construction policy. No FFI, addresses or native bindings.
-- The reviewed native bridge is injected by the Armory controller.
local M={}
local function integer(n,lo,hi)return type(n)=='number'and n%1==0 and n>=lo and n<=hi end
local function clone(v)
 if type(v)~='table'then return v end
 local out={};for k,item in pairs(v)do out[k]=clone(item)end;return out
end
local function check(value,message)assert(value==true,message)end
local function near(a,b)return type(a)=='number'and type(b)=='number'and a==a and b==b and math.abs(a-b)<.05 end
local function entry(value)
 assert(type(value)=='table'and integer(value.offer_id,1,0xffffffff),'real nonzero offer required')
 assert(type(value.kit_id)=='string'and value.kit_id:match('^armor:%x%x%x%x%x%x%x%x$')and value.owned==true,'owned Armor identity required')
 assert(integer(value.group_key,0,0xffffffff),'u32 presentation group required')
 assert(integer(value.flag_a,0,255)and integer(value.flag_b,0,255),'two exact native flag bytes required')
 return {offer_id=value.offer_id,kit_id=value.kit_id,owned=true,group_key=value.group_key,
  flag_a=value.flag_a,flag_b=value.flag_b}
end
local function layout(entries,source)
 local out={entries=entries,rows={},groups={},item_count=#entries,content=0,
  kind=source.kind,compact=source.compact,root_geometry={x=source.root_geometry.x,y=source.root_geometry.y,
   width=source.root_geometry.width,height=source.root_geometry.height}}
 local current,previous=0,nil
 for i,value in ipairs(entries)do
  if previous~=value.group_key then
   if out.rows[current+1]and out.rows[current+1].count>0 then current=current+1 end
   assert(#out.groups<33,'native group capacity exceeded')
   out.groups[#out.groups+1]={key=value.group_key,first_row=current,first_item=i-1}
   previous=value.group_key
  end
  assert(current<256,'native logical row capacity exceeded')
  local row=out.rows[current+1]
  if not row then row={count=0,first_item=i-1,height=source.base_row_height};out.rows[current+1]=row end
  row.count=row.count+1
  if row.count==source.columns then current=current+1 end
 end
 for _,group in ipairs(out.groups)do
  out.rows[group.first_row+1].height=out.rows[group.first_row+1].height+source.header_height
 end
 for _,row in ipairs(out.rows)do out.content=out.content+row.height end
 out.row_count=#out.rows;out.group_count=#out.groups;return out
end
function M.matches(actual,expected)
 if type(actual)~='table'or actual.kind~=expected.kind or actual.compact~=expected.compact
  or actual.item_count~=expected.item_count or actual.row_count~=expected.row_count
  or actual.group_count~=expected.group_count or not near(actual.content,expected.content)then return false end
 for _,key in ipairs({'x','y','width','height'})do
  if not near(actual.root_geometry and actual.root_geometry[key],expected.root_geometry[key])then return false end
 end
 if type(actual.entries)~='table'or #actual.entries~=#expected.entries
  or type(actual.rows)~='table'or #actual.rows~=#expected.rows
  or type(actual.groups)~='table'or #actual.groups~=#expected.groups then return false end
 for i,value in ipairs(expected.entries)do
  local a=actual.entries[i]
  if type(a)~='table'or a.owned~=true then return false end
  for _,key in ipairs({'offer_id','kit_id','group_key','flag_a','flag_b'})do if a[key]~=value[key]then return false end end
 end
 for i,row in ipairs(expected.rows)do local a=actual.rows[i]
  if type(a)~='table'then return false end
  if a.count~=row.count or a.first_item~=row.first_item or not near(a.height,row.height)then return false end
 end
 for i,group in ipairs(expected.groups)do local a=actual.groups[i]
  if type(a)~='table'then return false end
  if a.key~=group.key or a.first_row~=group.first_row or a.first_item~=group.first_item then return false end
 end
 return true
end
function M.prepare(source,cards,policy)
 assert(type(source)=='table'and source.kind==4 and source.compact==false,'verified normal Armor grid required')
 assert(integer(source.columns,1,4)and source.layout_verified==true,'verified native column/layout contract required')
 assert(type(source.base_row_height)=='number'and source.base_row_height>0 and source.base_row_height<=4096
  and type(source.header_height)=='number'and source.header_height>=0 and source.header_height<=512,'native row/header heights rejected')
 assert(type(source.root_geometry)=='table','original root geometry required')
 for _,key in ipairs({'x','y','width','height'})do local n=source.root_geometry[key]
  assert(type(n)=='number'and n==n and math.abs(n)<=1000000,'original root geometry invalid')end
 assert(source.root_geometry.width>0 and source.root_geometry.height>0,'positive native viewport required')
 assert(type(source.entries)=='table'and #source.entries>=1 and #source.entries<=256,'native item capacity rejected')
 assert(type(cards)=='table'and #cards>=1 and #cards<=256 and #cards+#source.entries<=256,'custom item capacity rejected')
 local originals,offers,by_kit,keys,owned_ids,owned_seen={}, {}, {}, {}, {}, {}
 for _,value in ipairs(source.entries)do
  local v=entry(value);assert(not offers[v.offer_id],'original native offers must be unique')
  offers[v.offer_id]=true;keys[v.group_key]=true;originals[#originals+1]=v
  by_kit[v.kit_id]=by_kit[v.kit_id]or v
  if not owned_seen[v.kit_id]then owned_ids[#owned_ids+1]=v.kit_id;owned_seen[v.kit_id]=true end
 end
 local original=layout(originals,source);assert(M.matches(source,original),'original logical model does not match native constructor contract')
 assert(integer(source.selected_offer_id,0,0xffffffff)and integer(source.marker_offer_id,0,0xffffffff)
  and(source.selected_offer_id==0 or offers[source.selected_offer_id])
  and(source.marker_offer_id==0 or offers[source.marker_offer_id]),'original UI selection/marker identity invalid')
 assert(type(source.scroll_value)=='number'and source.scroll_value>=0 and source.scroll_value<=1,'original native scroll value invalid')
 local custom_key=0xffffffff;while keys[custom_key]do custom_key=custom_key-1 end
 local replay,presentation,card_keys={}, {}, {};local plus=0
 for i,card in ipairs(cards)do
  assert(type(card.key)=='string'and #card.key>0 and #card.key<=128 and not card_keys[card.key],'unique presentation identity required')
  card_keys[card.key]=true
  assert(card.kind=='variant'or card.kind=='create','custom card kind rejected')
  if card.kind=='create'then plus=plus+1;assert(i==#cards,'Create must follow saved variants')end
  local donor=assert(by_kit[card.kit_id],'custom card must borrow an original owned offer')
  local v=clone(donor);v.group_key=custom_key;replay[#replay+1]=v
  presentation[#presentation+1]={key=card.key,kind=card.kind,kit_id=v.kit_id,offer_id=v.offer_id,
   logical_index=i-1,opaque=card.kind=='create',input_capture_required=true}
 end
 if policy and policy.allow_create==false then
  assert(plus==0,'Create cards are unavailable in Equipment')
 else assert(plus==1,'exactly one final Create card required')end
 for _,v in ipairs(originals)do replay[#replay+1]=clone(v)end
 local proposed=layout(replay,source)
 -- Construction must fit the stricter readback observer as well as the
 -- native arrays. Reject before Clear rather than relying on restoration.
 assert(proposed.group_count<=32 and proposed.row_count<=128,'presentation exceeds verified readback capacity')
 return {original=original,proposed=proposed,cards=presentation,owned_ids=owned_ids,
  custom_count=#cards,custom_group_key=custom_key,
  original_view={selected_offer_id=source.selected_offer_id,marker_offer_id=source.marker_offer_id,scroll_value=source.scroll_value},
  rendering_verified=false}
end

-- Bridge contract: snapshot/verify/verify_owned; begin/owns/same_menu; input
-- capture; clear/append/finish; readback/restore_view/view_matches; end_update.
-- begin establishes the reviewed UI update boundary. There are no yields here.
function M.new(bridge,policy)
 local self={phase='idle'};local attempted_token;local ticket,plan,token;local restore_attempted=false
 local function owned(ids)
  for first=1,#ids,16 do local batch={};for i=first,math.min(first+15,#ids)do batch[#batch+1]=ids[i]end
   check(bridge.verify_owned(batch),'fresh ownership changed')end
 end
 local function current()check(bridge.same_menu(ticket),'native menu retired');check(bridge.owns(ticket),'native model generation changed')end
 local function rebuild(expected,view,custom)
  current();check(bridge.clear(ticket),'native Clear did not complete')
  for _,value in ipairs(expected.entries)do current();check(bridge.append(ticket,clone(value)),'native Append did not complete')end
  current();check(bridge.finish(ticket),'native Finish did not complete')
  current();check(bridge.restore_view(ticket,clone(view),custom),'native UI view restoration failed')
  local after=bridge.readback(ticket)
  check(M.matches(after,expected),'native logical readback differs')
  check(bridge.view_matches(ticket,view,custom),'native UI view readback differs')
  owned(plan.owned_ids)
 end
 local function release_capture()if ticket then pcall(bridge.capture,false,ticket)end end
 local function restore(reason)
  if restore_attempted then return false end
  restore_attempted=true
  local owns_ok,is_owned=pcall(bridge.owns,ticket);local menu_ok,same=pcall(bridge.same_menu,ticket)
  if not owns_ok or not is_owned or not menu_ok or not same then
   self.phase='retired';self.failure=reason;release_capture();return false
  end
  local ok,why=pcall(function()owned(plan.owned_ids);rebuild(plan.original,plan.original_view,false)end)
  if ok then self.phase='restored';self.failure=reason;release_capture()
  else self.phase='restore_failed';self.failure=tostring(why)end
  return ok
 end
 function self:attempt(cards)
  if self.phase=='active'or self.phase=='building'or self.phase=='preparing'or self.phase=='restore_failed'then
   return {phase=self.phase,error=self.failure,menu_token=token,rendering_verified=false,
    custom_count=plan and plan.custom_count or 0,attempt_repeated=false}
  end
  local mutated=false;local began=false;local retryable=false;local consumed_token=false
  local ok,why=pcall(function()
   assert(self.phase=='idle'or self.phase=='restored'or self.phase=='retired'or self.phase=='blocked'or self.phase=='waiting','presentation attempt already active or failed')
   local caps=bridge.capabilities or {}
   assert(caps.constructor_verified==true and caps.input_capture_verified==true and caps.view_restore_verified==true
    and caps.update_boundary_verified==true,'reviewed native presentation capabilities required')
   -- Snapshot readiness (including the native first-row/zero-scroll contract)
   -- can lag the visible menu. Nothing has been written and this must retry.
   retryable=true;local snapshot=bridge.snapshot();retryable=false
   assert(type(snapshot.menu_token)=='string'and #snapshot.menu_token>0 and #snapshot.menu_token<=128,'unique native menu token required')
   token=snapshot.menu_token
   if attempted_token==token then return end
   attempted_token=token;consumed_token=true;restore_attempted=false;ticket=nil;plan=nil
   self.phase='preparing'
   plan=M.prepare(snapshot,cards,policy);owned(plan.owned_ids)
   retryable=true;check(bridge.verify(snapshot),'native source model changed')
   ticket=assert(bridge.begin(snapshot),'native UI update boundary unavailable');began=true;retryable=false
   check(bridge.capture(true,ticket),'native selection capture unavailable')
   current();mutated=true;self.phase='building'
   rebuild(plan.proposed,plan.original_view,true)
   self.phase='active';self.failure=nil
  end)
  if not ok then
   if mutated then restore(tostring(why))else
    self.phase=retryable and 'waiting'or 'blocked';self.failure=tostring(why)
    if retryable and consumed_token then attempted_token=nil end
    release_capture()
   end
  end
  if began then local ended,err=pcall(bridge.end_update,ticket)
   if not ended or err~=true then self.phase='restore_failed';self.failure='native update boundary did not close' end
  end
  return {phase=self.phase,error=self.failure,menu_token=token,rendering_verified=false,
   custom_count=plan and plan.custom_count or 0,retryable=self.phase=='waiting'}
 end
 -- Item count alone cannot detect a same-menu native reconstruction. The
 -- bridge lease checks the full logical model and code proof without writes.
 -- Unreadable observations preserve ownership until a later successful check.
 function self:status()
  if self.phase=='active'then
   local menu_ok,same=pcall(bridge.same_menu,ticket)
   local owns_ok,is_owned,ownership_reason=pcall(bridge.owns,ticket)
   if(menu_ok and same==false)or(menu_ok and same==true and owns_ok and is_owned==false)then
    self.phase='retired';self.failure=same==false and 'native menu retired'or ownership_reason or 'native model generation changed'
    release_capture()
   elseif not menu_ok or not owns_ok then
    return {phase=self.phase,error='native presentation status unreadable',readable=false,menu_token=token}
   end
  end
  return {phase=self.phase,error=self.failure,readable=true,menu_token=token,
   custom_count=plan and plan.custom_count or 0}
 end
 function self:restore()
  if self.phase~='active'then return {phase=self.phase,error=self.failure}end
  local valid,why=pcall(current)
  if not valid then self.phase='retired';self.failure=tostring(why);release_capture();return {phase=self.phase,error=self.failure}end
  local began=false
  local ok,why=pcall(function()
   check(bridge.resume_update(ticket),'native restore update boundary unavailable');began=true
   restore(nil)
  end)
  if not ok then self.phase='restore_failed';self.failure=tostring(why)end
  if began then local ended,result=pcall(bridge.end_update,ticket)
   if not ended or result~=true then self.phase='restore_failed';self.failure='native restore boundary did not close'end
  end
  return {phase=self.phase,error=self.failure}
 end
 function self:retire()
  if not ticket then return true end
  local ok,same=pcall(bridge.same_menu,ticket)
  if not ok or same~=false then return nil,'native menu retirement not verified'end
  release_capture();self.phase='retired';return true
 end
 return self
end
return M
