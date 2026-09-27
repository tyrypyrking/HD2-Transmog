-- Exact logical-card focus policy, independent of native addresses and FFI.
-- Duplicate offer IDs are expected: only the requested logical index chooses
-- the card. The injected bridge owns proved row-focus calls and UI mirrors.
-- Offscreen/stale/unowned requests fail before capture or mutation; there is
-- no fallback to offer Highlight, list rebuilding, scrolling, or equipment.
local M={}
local function integer(v,lo,hi)return type(v)=='number'and v%1==0 and v>=lo and v<=hi end
local function copy(v)
 if type(v)~='table'then return v end
 local out={};for k,item in pairs(v)do out[k]=copy(item)end;return out
end
local function same(a,b)
 if type(a)~=type(b)then return false end
 if type(a)~='table'then return a==b end
 for k,v in pairs(a)do if not same(v,b[k])then return false end end
 for k in pairs(b)do if a[k]==nil then return false end end
 return true
end
local function structure(model)
 local out={item_count=model.item_count,row_count=model.row_count,group_count=model.group_count,
  scroll=model.scroll,content=model.content,marker_offer=model.marker_offer,rows={},offers={},groups={},
  visible_rows=copy(model.focus_view.logical_rows)}
 for i,row in ipairs(model.rows)do out.rows[i]={row.index,row.first_item,row.item_count,row.height}end
 for i,item in ipairs(model.offers)do out.offers[i]={item.index,item.offer_id,item.kit_id,item.group_key,item.flag_a,item.flag_b}end
 for i,group in ipairs(model.groups)do out.groups[i]={group.index,group.key,group.first_row,group.end_row,group.first_item,group.end_item}end
 return out
end
local function prepare(model,index,kit_id)
 assert(type(model)=='table'and model.status=='read_only_logical_model','fresh logical model required')
 assert(type(model.verify)=='function'and model.verify()==true,'logical focus model is stale')
 assert(model.group_partition_verified==true and model.selected_offer_matches==true
  and model.selected_group_matches==true,'logical focus invariants unresolved')
 assert(integer(model.item_count,1,256)and integer(model.row_count,1,128)
  and integer(model.group_count,1,32),'logical focus bounds rejected')
 assert(type(model.offers)=='table'and #model.offers==model.item_count
  and type(model.rows)=='table'and #model.rows==model.row_count
  and type(model.groups)=='table'and #model.groups==model.group_count,'logical focus model is incomplete')
 assert(integer(index,0,model.item_count-1),'exact logical card index required')
 local item=model.offers[index+1]
 assert(type(kit_id)=='string'and kit_id:match('^armor:%x%x%x%x%x%x%x%x$')
  and item.index==index and item.kit_id==kit_id and item.owned==true
  and integer(item.offer_id,1,0xffffffff),'requested card is not the expected owned armor')
 local row,column,total=nil,nil,0
 for i,r in ipairs(model.rows)do
  assert(r.index==i-1 and r.first_item==total and integer(r.item_count,0,8),'logical row partition changed')
  if index>=total and index<total+r.item_count then row,column=i-1,index-total end
  total=total+r.item_count
 end
 assert(total==model.item_count and row~=nil,'logical row index unresolved')
 local group
 for i,g in ipairs(model.groups)do
  assert(g.index==i-1 and integer(g.first_row,0,model.row_count-1)
   and integer(g.end_row,g.first_row+1,model.row_count),'logical group bounds changed')
  if row>=g.first_row and row<g.end_row then assert(not group,'logical groups overlap');group=i-1 end
 end
 assert(group~=nil,'logical group index unresolved')
 local visible=model.focus_view
 assert(type(visible)=='table'and visible.verified==true and type(visible.logical_rows)=='table'
  and #visible.logical_rows>=1 and #visible.logical_rows<=12,'fresh native visible-row mapping required')
 local slot,clear_slot,seen=nil,nil,{}
 for i,logical in ipairs(visible.logical_rows)do
  assert(integer(logical,0,model.row_count-1)and not seen[logical],'native visible-row map is ambiguous')
  seen[logical]=true
  if logical==row then slot=i-1 end
  if logical==model.selected_row then clear_slot=i-1 end
 end
 assert(slot~=nil,'requested card is outside the native visible rows')
 if clear_slot~=nil then assert(visible.selected_slot==clear_slot,'native selected visible row changed')end
 assert(type(model.verify_owned)=='function'and model.verify_owned({kit_id})==true,'fresh owned focus identity required')
 assert(model.verify()==true,'logical focus model changed before dispatch')
 return {status='exact_focus_plan',from={row=model.selected_row,column=model.selected_column,
   group=model.selected_group,index=model.selected_index,offer_id=model.selected_offer,visible_slot=clear_slot},
  to={row=row,column=column,group=group,index=index,offer_id=item.offer_id,kit_id=kit_id,visible_slot=slot},
  unchanged=structure(model),scroll=false,equipped=false}
end
function M.prepare(model,index,kit_id)
 local ok,value=pcall(prepare,model,index,kit_id)
 if not ok then return nil,tostring(value)end;return value
end
function M.new(bridge)
 assert(type(bridge)=='table','exact focus bridge required')
 local self={}
 function self:select(model,index,kit_id)
  local ok,value=pcall(function()
   local caps=bridge.capabilities or {}
   for _,key in ipairs({'exact_index_focus_verified','row_focus_verified','update_boundary_verified','input_capture_verified'})do
    assert(caps[key]==true,'native exact focus capability unavailable: '..key)
   end
   for _,key in ipairs({'verify','capture','focus_exact','readback'})do assert(type(bridge[key])=='function','native exact focus method unavailable: '..key)end
   local plan,why=M.prepare(model,index,kit_id);assert(plan,why)
   assert(bridge.verify(model)==true,'native exact focus evidence changed')
   assert(bridge.capture()==true,'native exact focus input capture unavailable')
   assert(bridge.verify(model)==true,'native exact focus changed during capture')
   assert(bridge.focus_exact(copy(plan))==true,'native exact focus rejected')
   local after=bridge.readback()
   assert(type(after)=='table'and type(after.verify)=='function'and after.verify()==true,'native exact focus readback unavailable')
   assert(type(after.focus_view)=='table'and after.focus_view.verified==true,'native focused-row readback unavailable')
   assert(same(structure(after),plan.unchanged),'native focus changed the list, scroll, or equipped marker')
   local target=plan.to
   assert(after.selected_index==target.index and after.selected_row==target.row and after.selected_column==target.column
    and after.selected_group==target.group and after.selected_offer==target.offer_id
    and after.selected_offer_matches==true and after.selected_group_matches==true
    and after.focus_view.selected_slot==target.visible_slot,'native focus did not select the exact requested card')
   assert(after.verify()==true,'native exact focus readback changed')
   return {status='native_exact_focus_readback_verified',logical_index=index,kit_id=kit_id,
    offer_id=target.offer_id,row=target.row,column=target.column,equipped=false,rendering_verified=false}
  end)
  if not ok then return nil,tostring(value)end;return value
 end
 return self
end
return M
