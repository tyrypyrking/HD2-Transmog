-- Mouse/controller orchestration. Apply, controller confirmation and a card
-- double-click dispatch verified equipment work; single clicks only preview.
local M={}
-- The platform currently reports mouse `down`. Hosts may also report held
-- keyboard/controller confirmation as `confirm_down` or `select_down`. A nil
-- sample (focus loss) never proves that a captured press has been released.
local function held(input)
 if type(input)~='table'then return false end
 return input.down==true or input.confirm_down==true or input.select_down==true
end
local function released(input)
 if type(input)~='table'or held(input)then return false end
 return type(input.down)=='boolean'or type(input.confirm_down)=='boolean'or type(input.select_down)=='boolean'
end
local function action_key(action)
 if type(action)~='table'then return nil end
 local keys={};for key,value in pairs(action)do
  if type(key)=='string'and (type(value)=='string'or type(value)=='number'or type(value)=='boolean')then keys[#keys+1]=key end
 end
 table.sort(keys);local out={}
 for _,key in ipairs(keys)do local value=tostring(action[key]);out[#out+1]=key..':'..#value..':'..value end
 return table.concat(out,'|')
end
function M.new(state_api,wizard_api,panel,host)
 assert(type(host)=='table'and type(host.current)=='function'and type(host.persist)=='function','UI host required')
 local wizard=wizard_api.new(state_api,{allow_create=host.allow_create~=false})
 local self={};local previous,armed,release_latch,last_view=nil,nil,false,nil
 local last_click,double_apply
 local function clear_double()last_click=nil;double_apply=nil end
 local function click_time()
  if type(host.now)~='function'then return nil end
  local ok,now=pcall(host.now)
  if ok and type(now)=='number'and now==now and now>=0 and now<math.huge then return now end
 end
 local selected_variant
 local native_navigation=false
 local confirm_previous,confirm_source,confirm_armed
 local function clear_confirm()confirm_previous=nil;confirm_source=nil;confirm_armed=nil end
 local function confirm_action(view)
  if view.open or view.native_details~=true or view.can_apply~=true or view.apply_pending==true then return nil end
  local action
  if view.native_override==true and view.native_override_id then
   action={type='apply_variant',id=view.native_override_id}
  elseif view.selected_variant then
   action={type='apply_variant',label=view.selected_variant.label}
  end
  if action and host.validate_confirm then
   local ok,valid=pcall(host.validate_confirm,action)
   if not ok or valid~=true then return nil end
  end
  return action
 end
 local function consume()
  if type(host.consume_select)~='function'then return false end
  local ok,captured,reason=pcall(host.consume_select)
  return ok and captured==true,ok and reason or tostring(captured)
 end
 local function context()
  local domain,display=host.current();assert(domain and display,'current owned UI context required');return domain,display
 end
 function self:is_open()return wizard:is_open()end
 function self:view()
  local domain,display=context();local view=wizard:view(domain,display)
  view.native_picker=host.native_picker==true
  if not view.open and selected_variant and domain.presets[selected_variant.label]then
   selected_variant.display_name=wizard_api.display_name(display,selected_variant.request,selected_variant.label)
   view.selected_variant=selected_variant
   view.can_remove=host.allow_create~=false and type(host.remove_variant)=='function'
  end
  if not view.open and host.variant_view then
   local state=host.variant_view();if type(state)~='table'then state={}end
   if selected_variant or state.native_override==true or type(state.apply_notice)=='string'then
    for _,key in ipairs({'native_details','native_override','native_override_id','can_apply','apply_pending','apply_notice','variant_phase'})do view[key]=state[key]end
    if type(view.apply_notice)=='string'then view.apply_notice=view.apply_notice:gsub('^.-%.lua:%d+: ','')end
   end
  end
  return view
 end
 function self:before(input)
  if host.input_scope and host.input_scope()==false then
   panel:clear();previous=nil;armed=nil;release_latch=false;native_navigation=false;clear_confirm();clear_double()
   return true
  end
  -- Poll native input only while this UI owns an active Armor picker. XInput
  -- device discovery can be expensive even when no controller is connected.
  if type(input)=='function'then input=input()end
  if not input then clear_confirm();clear_double();previous=nil;armed=nil end
  if input and confirm_source and input.controller_source~=confirm_source then clear_confirm()end
  local open=wizard:is_open()
  -- Native tabs own their entire mouse gesture, including release. A saved
  -- selection's continuous confirmation guard must not swallow unrelated UI.
  -- A drag begun on our controls never acquires navigation passthrough.
  if native_navigation then
   if released(input)then native_navigation=false;release_latch=false end
   return true
  end
  if input and input.down==true and previous==false and not armed
   and input.confirm_down~=true and input.select_down~=true
   and type(host.native_navigation_at)=='function'
   and host.native_navigation_at(input.x,input.y)==true then
   native_navigation=true;release_latch=false;clear_double()
   return true
  end
  -- Ask the host before the native update, not after a draw has observed the
  -- press. It owns fresh native prefix bounds/selection-index proof. The hook
  -- is intentionally consulted even when mouse down is false: keyboard or
  -- controller Select can confirm a currently selected custom placeholder.
  local prefix_capture,check_failed=false,false
  if type(host.should_capture)=='function'then
   local ok,value=pcall(host.should_capture,input)
   prefix_capture=not ok or value==true
   check_failed=not ok
  end
  if prefix_capture or (open and held(input))then release_latch=true end
  -- Consume the game's generic Select while creation is open. Native look
  -- selection is routed explicitly through a separately proved thumbnail hit.
  -- The OS button remains available to this controller's own hit testing.
  if open or release_latch then
   local captured,reason=consume()
   if not captured then armed=nil;clear_confirm();panel:clear();return nil,'Native input capture is unavailable: '..tostring(reason or 'capture rejected')end
   -- Keep the capture through drag-off, focus loss, and confirmation release.
   -- A fresh host capture request wins over a neutral mouse-only sample.
   if not prefix_capture and released(input)then release_latch=false end
  end
  if check_failed then armed=nil;panel:clear();return nil,'Native input capture check failed' end
  return true
 end
 function self:action(action)
  clear_double()
  if host.report then host.report('ui.action',action_key(action))end
  local domain,display=context()
  if panel.handle and panel:handle(action)then return true end
  if host.allow_create==false and action and action.type~='select_variant'
   and action.type~='select_native_look'and action.type~='apply_variant' then
   return nil,'Create variants in the ship Armory.'
  end
  if action and action.type=='remove_variant'then
   local view=self:view()
   if not(view.can_remove and view.selected_variant and action.label==view.selected_variant.label
    and not view.open and view.apply_pending~=true)then return nil,'Select a variant and wait for its preview before removing it.'end
   local done,why=host.remove_variant(action.label)
   if not done then return nil,why end
   selected_variant=nil
   return true
  end
  if action and action.type=='apply_variant'then
   local view=self:view()
   if not((view.selected_variant or view.native_override==true)and view.native_details==true and view.can_apply==true and view.apply_pending~=true)then
    return nil,'Select a ready variant before applying it.'
   end
   if action.label~=nil and(not view.selected_variant or action.label~=view.selected_variant.label)then return nil,'The selected variant changed.'end
   if view.native_override==true and action.id~=view.native_override_id then return nil,'The selected armor changed.'end
   if not host.apply_variant then return nil,'Variant equipment is unavailable.'end
   return host.apply_variant()
  end
  if action and action.type=='select_native_look'then
   if wizard:is_open()then return nil,'Native browsing is unavailable while the creator is open' end
   if domain.ownership_verified~=true or not(domain.owned and domain.owned[action.id]==true
    and domain.catalog and type(domain.catalog[action.id])=='table')then
    return nil,'Choose a currently owned native armor'
   end
   if type(host.preview_native_look)~='function'then return nil,'Native armor preview is unavailable' end
   local called,ready,reason=pcall(host.preview_native_look,action.id,action.index)
   if not called then return nil,tostring(ready)end
   if ready~=true then return nil,reason or 'Native armor preview was not confirmed'end
   selected_variant=nil
   return true
  end
  if action and action.type=='open'and not consume()then return nil,'Native input capture is unavailable' end
  if action and action.type=='open'and host.begin_creation then
   local ready,why=host.begin_creation();if not ready then return nil,why end
  end
  if action and action.type=='select_look'then
   local view=wizard:view(domain,display);local offered=false
   if view.step==1 then for _,option in ipairs(view.options)do if option.id==action.id then offered=true;break end end end
   if not offered then return nil,'Choose a currently owned look in the first step' end
   if not host.preview_look then return nil,'Native look preview is unavailable' end
   local ready,reason=host.preview_look(action.id)
   if not ready then return nil,reason end
  end
  local handled,reason,tx=wizard:action(domain,display,action)
  if not handled then return nil,reason end
  if tx and tx.kind=='save_variant'then
   local valid,why=wizard:validate_transaction(tx,domain,display)
   if valid and host.verify_create then valid,why=host.verify_create(tx)end
   if not valid then wizard:failed(tx,why);return nil,why end
   local saved,adopted=host.persist(tx)
   if not saved then wizard:failed(tx,adopted);return nil,adopted end
   local complete,problem=wizard:saved(tx,adopted)
   if not complete then return nil,problem end
   if host.created then host.created(tx.label)end
  elseif tx and tx.kind=='select_variant'then
   if host.intent then local done,why=host.intent(tx);if done==false or done==nil then return nil,why end end
   selected_variant={label=tx.label,request=tx.request}
  elseif tx and host.intent then host.intent(tx)end
  if action and action.type=='open'then selected_variant=nil end
  if action and action.type=='cancel'and host.end_creation then host.end_creation()end
  return true,reason
 end
 function self:draw(sample,input)
  local domain,display=context();last_view=self:view()
  local shown=panel:draw(sample,last_view,display)
  if not shown or not input then previous=nil;armed=nil;clear_confirm();clear_double();return shown end
  -- A double-click may finish before preview readback. Wait briefly for the
  -- same selection to become ready; never carry intent across focus/navigation.
  if double_apply then
   local queued=double_apply;local now=click_time()
   local focused=true
   if host.validate_confirm then
    local ok,value=pcall(host.validate_confirm,queued.action);focused=ok and value==true
   end
   if not now or now<queued.at or now>queued.at+1500 or held(input) or last_view.open or not focused
    or last_view.variant_phase=='preview_failed' or last_view.variant_phase=='equipped' then
    double_apply=nil
   else
    local target=confirm_action(last_view)
    if target then
     double_apply=nil
     if action_key(target)==action_key(queued.action)then
      local ok,why=self:action(target)
      if not ok and host.notice then host.notice(why)end
     end
    end
   end
  end
  -- A confirms the current semantic selection, never whatever is under the
  -- mouse cursor. Require a neutral sample from the same device before arming.
  if type(input.confirm_down)=='boolean'and type(input.controller_source)=='string'then
   local target=(input.confirm_down or confirm_previous==true)and confirm_action(last_view)or nil
   if confirm_source~=input.controller_source or confirm_previous==nil then
    confirm_source=input.controller_source;confirm_armed=nil
   elseif input.down or previous==true or armed then
    confirm_armed=nil
   elseif input.confirm_down and not confirm_previous then
    confirm_armed=target and {key=action_key(target),action=target}or nil
   elseif input.confirm_down and confirm_previous then
    if not target or not confirm_armed or confirm_armed.key~=action_key(target)then confirm_armed=nil end
   elseif not input.confirm_down and confirm_previous then
    local action=confirm_armed and target and confirm_armed.key==action_key(target)and target
    confirm_armed=nil
    if action then
     local ok,why=self:action(action)
     if not ok and host.notice then host.notice(why)end
     if ok and host.controller_confirmed then host.controller_confirmed(input.controller_source)end
    end
   end
   confirm_previous=input.confirm_down
  else clear_confirm()end
  if previous==nil then previous=input.down;return true end
  local target=panel:hit(input.x,input.y)
  -- The host captures original-grid presses before native update and returns
  -- only freshly matched owned entries outside the custom prefix range.
  if not target and not last_view.open and(input.down==true or previous==true)
   and type(host.browse_look_at)=='function'then
   local id,index=host.browse_look_at(input.x,input.y)
   if id then target={type='select_native_look',id=id,index=index}end
  end
  if not target and last_view.open and last_view.step==1 and host.look_at then
   local policy=panel:input_policy();local r=policy and policy.native_picker_rect
   if r and input.x>=r.x and input.y>=r.y and input.x<r.x+r.w and input.y<r.y+r.h then
    local id=host.look_at(input.x,input.y)
    if id then target={type='select_look',id=id}end
   end
  end
  if input.down and not previous then
   double_apply=nil
   if not target or(target.type~='select_variant'and target.type~='select_native_look')then last_click=nil end
   armed=target and {key=action_key(target),action=target}or nil
   if target or (panel.capture and panel:capture(input.x,input.y))then release_latch=true end
  elseif input.down and previous and armed and (armed.action.type=='select_native_look'or armed.action.type=='select_variant')
   and (not target or armed.key~=action_key(target))then
   clear_double();armed=nil -- A browse drag never becomes a new selection on return/release.
  elseif not input.down and previous then
   local action=armed and target and armed.key==action_key(target)and target
   armed=nil
   if not action then clear_double()end
   if action and action.type~='panel_background'then
    local now=click_time()
    local card=action.type=='select_variant'or action.type=='select_native_look'
    local repeated=card and last_click and now and now>=last_click.at and now-last_click.at<=1500
     and last_click.key==action_key(action) and math.abs(input.x-last_click.x)<=8 and math.abs(input.y-last_click.y)<=8
    local ok,why
    if repeated then
     local apply=action.type=='select_variant'and {type='apply_variant',label=action.label}
      or {type='apply_variant',id=action.id}
     last_click=nil;double_apply={action=apply,at=now};ok=true
     if host.report then host.report('ui.double_click',action_key(apply))end
    else
     clear_double()
     ok,why=self:action(action)
     if ok and card and now then last_click={key=action_key(action),at=now,x=input.x,y=input.y}end
    end
    if not ok and host.notice then host.notice(why)end
    -- The original card's release is already consumed. If the host now marks
    -- that original selection safe, its next native Apply must not be swallowed
    -- by a latch left over from a previously selected custom card.
    if ok and action.type=='select_native_look'and released(input)then release_latch=false end
   end
  end
  previous=input.down
  return true
 end
 function self:leave()
  local domain,display=host.current()
  if domain and display then wizard:action(domain,display,{type='cancel'})end
  panel:clear();previous=nil;armed=nil;last_view=nil;selected_variant=nil;native_navigation=false;clear_confirm();clear_double()
  if host.end_creation then host.end_creation()end
 end
 function self:clear()panel:clear();previous=nil;armed=nil;clear_confirm();clear_double()end
 function self:clear_selected_variant()selected_variant=nil;clear_double();return true end
 function self:automation_snapshot()
  return {view=self:view(),regions=panel.regions or {}}
 end
 function self:metrics()return panel.metrics and panel:metrics()or {}end
 function self:input_policy()return panel:input_policy()end
 return self
end
return M
