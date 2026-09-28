-- Ship helmet editor. Preparation changes an unequipped appearance carrier;
-- the ordinary native Helmet Apply action owns the actual equipment transition.
local M={}
function M.new(host)
 local S=host.state;local domain=S.new();local editor=S.editor_new()
 local view={title='HELMET VARIANTS',apply_label='Prepare',tab='appearance',open=false,suspended=false,
  saved_section_enabled=false,notice='Choose owned helmet parts, then prepare and equip the look.'}
 local panel=host.panel;local result,patch,active,visible,armed,down,blocked,captured
 local function load()
  local raw,why=host.fs.read('helmets.state')
  if raw then
   local parsed,err=S.decode(raw)
   if parsed then domain=parsed;editor=S.editor_new();blocked=nil
   else blocked=err;view.notice='Saved helmet state needs recovery; saving disabled.'end
  elseif why~='missing'then blocked=why or 'unreadable';view.notice='Helmet state unreadable; saving disabled.'end
 end
 load()
 local function safe_target(id)
  local actor,why=host.player():sample();assert(actor,why)
  assert(actor.settled,'Wait for the equipment change to finish.')
  assert(actor.request.helmet_id~=id and actor.current.helmet_id~=id,'Equip another helmet before preparing or resetting this look.')
  assert(actor.verify(),'Equipment changed before preparation.')
  return actor
 end
 local self={}
 function self:is_active()return active~=nil end
 function self:clear()visible=false;armed=nil;down=nil;captured=false;panel:clear()end
 function self:before(input)
  if visible and (captured or input and input.down and panel:capture(input.x,input.y))then
   local fresh=host.snapshot()
   if not(fresh and fresh.native_category==1 and fresh.native_view_mode==0 and fresh.screen_kind=='armory')then self:clear();return end
   assert(host.consume(),'Helmet panel input capture unavailable')
   captured=input and input.down or false
   if not input then armed=nil;down=nil end
  end
 end
 function self:draw(sample,snapshot,catalog,input)
  if sample.kind~='armory' or not(snapshot and snapshot.native_category==1 and snapshot.native_view_mode==0)
   or not(catalog and catalog.capabilities.helmet_transmog_enabled)then self:clear();return false end
  visible=true
  if result~=catalog then assert(not active,'Active helmet baseline changed');result=catalog;patch=nil end
  S.reconcile_owned(domain,result.catalog,result.owned)
  result.context.current_kit_id=snapshot.helmet_selected_kit_id
  view.editor=S.editor_view(domain,editor,view.tab,result.context)
  local model=view.editor
  model.stats_summary={rows={},note='Copies native helmet weights; numeric totals unverified.'}
  model.can_apply=editor.draft~=nil and not active and domain.ownership_verified
  model.patch_active=active~=nil
  model.apply_note=active and 'Equip the chosen Look using the normal Helmet Apply button.'or 'Prepare an unequipped Look, then select it and equip normally.'
  model.can_save=model.can_save and not blocked
  if active then for _,key in ipairs({'can_new','can_duplicate','can_discard','can_previous','can_next','can_save'})do model[key]=false end end
  if not panel:draw(sample,view)then self:clear();return false end
  local target=panel:hit(input.x,input.y)
  if down==nil then down=input.down;return true end
  if input.down and not down then armed=target end
  if not input.down and down then
   if target and target==armed then
    local ok,why=pcall(function()
     if target=='toggle'then view.open=not view.open
     elseif target=='appearance'or target=='stats'or target=='passive'or target=='presets'then view.tab=target
     elseif target=='reload'then assert(not active,'Reset the prepared helmet first.');load()
     elseif target=='apply_variant'then
      assert(not active and editor.draft,'Choose a helmet variant first.')
      local actor=safe_target(editor.draft.appearance_id)
      -- Do not mutate a carrier while native preview work may still use it.
      local fresh=assert(host.snapshot(),'Helmet selection unavailable.')
      assert(fresh.native_category==1 and fresh.native_view_mode==0 and fresh.helmet_selected_kit_id
       and fresh.helmet_selected_kit_id~=editor.draft.appearance_id,
       'Select a different helmet in the native list before Prepare.')
      patch=patch or host.patch(result)
      local plan,reason=patch:plan(result,editor.draft);assert(plan,reason)
      assert(actor.verify(),'Equipment changed before preparation.')
      local applied,reason=patch:apply(plan)
      if not applied then
       local retained=patch:is_active()
       if retained~=false then active=plan end
       error(reason or 'Helmet preparation failed.')
      end
      active=plan;view.notice='Prepared. Select '..model.appearance_label..' in Helmets and equip it.'
     elseif target=='reset_variant'then
      assert(active,'No prepared helmet.');safe_target(active.target_id)
      local fresh=assert(host.snapshot(),'Helmet selection unavailable.')
      assert(fresh.native_category==1 and fresh.native_view_mode==0 and fresh.helmet_selected_kit_id
       and fresh.helmet_selected_kit_id~=active.target_id,
       'Select a different helmet in the native list before Reset.')
      local restored,reason=patch:reset();assert(restored,reason);active=nil
      view.notice='Original helmet restored.'
     else
      assert(not active,'Reset the prepared helmet before editing.')
      local handled,notice,candidate,event=S.editor_action(domain,editor,target,view.tab,result.context)
      if notice then view.notice=notice end
      if candidate then
       assert(not blocked,'Saved helmet state needs recovery.')
       local encoded,reason=S.encode(candidate);assert(encoded,reason)
       local wrote,error=host.fs.write_atomic('helmets.state',encoded);assert(wrote,error)
       domain=candidate;S.editor_saved(editor);view.saved=true
      end
      if event and event.open_editor then view.open=true end
     end
    end)
    if not ok then view.notice=tostring(why):gsub('^.-:%d+: ','');host.report('helmet.action_rejected',why)end
   end
   armed=nil
  end
  down=input.down;return true
 end
 function self:shutdown()
  self:clear()
  if patch then local ok,why=patch:reset();host.report('helmet.reset',ok or why)end
 end
 return self
end
return M
