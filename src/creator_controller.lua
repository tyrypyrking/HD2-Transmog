-- Pure, owned-choice creator navigation. No native calls or cursor emulation.
local M={}
local function key(a)return a and table.concat({a.type or '',a.id or '',a.label or ''},'|')end
local function direction(input)
 local x,y=input.nav_x or 0,input.nav_y or 0
 if math.abs(x)<.55 and math.abs(y)<.55 then return end
 if math.abs(x)>math.abs(y)then return x>0 and 'right'or 'left'end
 return y>0 and 'up'or 'down'
end
local function neutral(input)
 return not(input.confirm_down or input.back_down or input.cancel_down or input.page_prev_down or input.page_next_down or direction(input))
end
function M.new()
 local self={active=false};local source,scope,primed,prev,armed,dir,next_repeat,last_now
 local index,control,last_index=1,nil,1
 local last_passive
 local function clear_gesture()primed=false;prev={};armed=nil;dir=nil;next_repeat=nil end
 local function controls(view)
  local out={}
  if view.can_create then out[#out+1]={type='create'}end
  if view.can_back then out[#out+1]={type='back'}end
  if view.can_cancel then out[#out+1]={type='cancel'}end
  return out
 end
 local function selected(view)
  local list=controls(view)
  if control then return list[control]end
  return view.options and view.options[index]and view.options[index].action
 end
 function self:activate()self.active=true end
 function self:wants(input)
  return input and input.controller_source and not input.down and (self.active or not neutral(input))or false
 end
 function self:reset()self.active=false;source=nil;scope=nil;last_now=nil;index=1;control=nil;last_index=1;last_passive=nil;clear_gesture()end
 function self:interrupt()source=nil;clear_gesture()end
 function self:update(view,input,now,page_size)
  if not view.open then self:reset();return end
  if not(input and input.controller_source)then self:interrupt();return end
  -- Keep the layout stable under a mouse press; switching back to the native
  -- grid here could make the release hit a different armor than the press.
  if input.down then self:interrupt();return end
  now=type(now)=='number'and now or 0;page_size=math.max(1,page_size or 3)
  if last_now and now<last_now then clear_gesture()end;last_now=now
  local parts={tostring(view.step)}
  for _,option in ipairs(view.options or {})do parts[#parts+1]=option.id end
  local current=table.concat(parts,'|')
  if scope~=current then
   scope=current;index=1;control=nil;last_index=1;last_passive=nil;clear_gesture()
   for i,option in ipairs(view.options or {})do if option.selected then index=i;last_index=i;break end end
  end
  if source~=input.controller_source then source=input.controller_source;clear_gesture()end
  local list=controls(view);local count=#(view.options or {})
  if count==0 then control=control or 1 end
  if control then control=math.min(control,math.max(1,#list))else index=math.min(math.max(1,index),math.max(1,count))end
  local passive=view.selection and view.selection.passive_variant_id
  if self.active and view.can_create and passive~=last_passive then control=1;armed=nil end
  last_passive=passive
  if self:wants(input)then self.active=true end
  if not primed then
   if neutral(input)then primed=true end
   return
  end
  if not self.active then return end
  if view.saving then armed=nil;return end
  local d=direction(input)
  local move=d and (d~=dir or now>=(next_repeat or math.huge))
  if move then
   armed=nil
   if view.controller_native_looks and not control then
    local columns=view.controller_columns or 3
    local column=(index-1)%columns
    local delta=d=='down'and columns or d=='up'and -columns or d=='right'and 1 or -1
    local candidate=index+delta
    if candidate<1 or candidate>count or d=='right'and column==columns-1 or d=='left'and column==0 then
     if #list>0 then last_index=index;control=1 end
    else index=candidate;last_index=index end
   elseif d=='left'or d=='right'then
    if control and count>0 then control=nil;index=math.min(last_index,count)
    elseif not control and #list>0 then last_index=index;control=1 end
   elseif control then
    local next_control=control+(d=='down'and 1 or -1)
    if next_control<1 or next_control>#list then control=nil;index=d=='down'and 1 or math.max(1,count)
    else control=next_control end
   else
    local next_index=index+(d=='down'and 1 or -1)
    if next_index<1 or next_index>count then
     if #list>0 then last_index=index;control=d=='down'and 1 or #list end
    else index=next_index;last_index=index end
   end
   next_repeat=now+(d~=dir and 350 or 140)
  end
  dir=d;if not d then next_repeat=nil end
  for _,button in ipairs({'page_prev_down','page_next_down'})do
   if input[button]and not prev[button]and count>0 then
    armed=nil;control=nil
    index=math.max(1,math.min(count,index+(button=='page_next_down'and page_size or -page_size)));last_index=index
   end
  end
  local action
  local buttons={'confirm_down','back_down','cancel_down'};local pressed=0
  for _,button in ipairs(buttons)do if input[button]then pressed=pressed+1 end end
  if pressed>1 then armed=nil;primed=false
  else
   for _,button in ipairs(buttons)do
    local target=button=='confirm_down'and selected(view)
     or button=='back_down'and(view.can_back and {type='back'}or view.can_cancel and {type='cancel'})
     or button=='cancel_down'and view.can_cancel and {type='cancel'}or nil
    if input[button]and not prev[button]then armed=target and {button=button,key=key(target),action=target,scope=scope}or nil
    elseif input[button]and prev[button]and armed and armed.button==button and armed.key~=key(target)then armed=nil
    elseif not input[button]and prev[button]and armed and armed.button==button then
     if armed.scope==scope and armed.key==key(target)then action=target end
     armed=nil
    end
   end
  end
  for _,button in ipairs({'confirm_down','back_down','cancel_down','page_prev_down','page_next_down'})do prev[button]=input[button]==true end
  return action
 end
 function self:mouse_action(action,view,page_size)
  if not self.active or not view.open then return end
  if action.type=='panel_page'and action.target=='options'and (action.delta==1 or action.delta==-1)then
   local count=#(view.options or {})
   if count>0 then
    index=math.max(1,math.min(count,index+action.delta*math.max(1,page_size or 3)))
    last_index=index;control=nil;clear_gesture()
   end
  elseif action.type=='select_passive'then
   for i,option in ipairs(view.options or {})do
    if key(option.action)==key(action)then index=i;last_index=i;control=nil;clear_gesture();break end
   end
  end
 end
 function self:decorate(view,page_size)
  if view.open and self.active then
   view.controller_mode=true;view.controller_focus=selected(view)
   view.controller_page=math.floor((index-1)/math.max(1,page_size or 3))+1
  end
  return view
 end
 return self
end
return M
