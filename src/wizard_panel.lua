-- Native-adjacent presentation for VariantWizard; no native memory or calls.
-- Coordinates use viewport pixels with a bottom-left origin.
--
-- panel:draw(sample, wizard:view(domain, context), context) -> true|false
-- panel:hit(x,y) -> structured action or {type='panel_background'}
-- panel:capture(x,y) -> whether an owned surface must consume input
-- panel:handle(action) -> true for panel_page actions (redraw afterwards)
-- panel:input_policy() -> controller instructions; keyboard enforcement belongs
--   to the caller. Native grid clicks choose a look only while native_look_pick.
-- panel:metrics() -> draw_count, rebuild_count, signature_ms,
--   signature_total_ms, signature_bytes (local counters only; no engine calls).
-- panel:clear() removes owned GUI primitives and input capture.
--
-- sample.custom_section is REQUIRED for the browse section. It must describe
-- a row already reserved by the native controller. There is no fallback row,
-- no automatic native resize, and no overlay on existing native armor tiles.
-- Alternatively sample.native_prefix={verified=true,clip={x,y,w,h},
--   headers={{rect={x,y,w,h},text='Custom Variant'}},
--   cells={{rect={x,y,w,h},key='stable-key',kind='variant'|'create',
--     image_rect={x,y,w,h},label='saved name',
--     passive={icon_hash='material hash'},selected=false}}}
-- supplies actual native header/cell geometry and takes browse precedence.
-- Geometry must be sampled in the same update as draw; callers must not reuse
-- a throttled grid snapshot. Fully clipped-out rectangles are skipped. Partial
-- cells capture only their visible intersection, without actions. Decorations
-- remain anchored to the full native card/image, never the clipped rectangle.
-- Variants keep native thumbnails; only visible name/badge areas are
-- covered. Only these measured surfaces capture mouse input. This
-- route never reads, converts, validates, or draws borrowed native handles.
-- sample.wizard_layout may override header/picker/review/apply/footer rects.
-- sample.font/material/atlas use the same observed resources as Panel.
-- Optional view.selected_variant={label,request={appearance_id,stats_id,
-- passive_variant_id}} shows a read-only saved review while browsing. It keeps
-- prefix cards live and covers native donor details/Apply without adding any
-- Create, Apply, or equipment action. The controller supplies this metadata.
-- A strict view.native_details=true confirms that the selected variant is
-- already shown by the native stat/perk/Apply views and removes that review.
-- Native Apply and its footer hint remain visually untouched. Their invisible
-- regions emit apply_variant only while can_apply=true; apply_pending captures
-- without dispatching. The controller, never this renderer, equips the variant.
--
-- Look uses the ORIGINAL native grid. Stats and passive options use the pure
-- model's ordering. Review remains alongside the native 3D model; it covers
-- the donor title/stats/perk/Apply while creation is open. Create saves only.
-- Raw material_pointer descriptors are rejected. Borrowed engine material
-- handles additionally require native_handle_verified, engine handle_source,
-- and a fresh valid() proof. Resource thumbnails require verified=true.
-- Known passive hashes prefer verified original DDS-derived icon geometry;
-- these retained rectangles need no texture residency or material binding.

local M = {}
local Layout=UiLayout or require('src.ui_layout')
local STAT_FIELDS = {'armor_rating', 'speed', 'stamina_regen'}
local STAT_LABELS = {'ARMOR RATING', 'SPEED', 'STAMINA REGEN'}

local function chars(value)
  local out={}
  for char in tostring(value or ''):gmatch('[%z\1-\127\194-\244][\128-\191]*') do out[#out+1]=char end
  return out
end
local function wrap(value, limit)
  local lines,line,count={}, {},0
  for _,char in ipairs(chars(value)) do
    local size=char:byte()>=0xE3 and 2 or 1
    if char=='\n' or count+size>limit then
      lines[#lines+1]=table.concat(line);line,count={},0
    end
    if char~='\n' then line[#line+1],count=char,count+size end
  end
  if #line>0 then lines[#lines+1]=table.concat(line) end
  return lines
end
local function clip(value, limit)
  local lines=wrap(tostring(value or ''):gsub('%c',' '),limit)
  return (lines[1] or '')..(#lines>1 and '...' or '')
end
local function number(value)
  return type(value)=='number' and value==value and value~=math.huge and value~=-math.huge
end
local function resource(value)
  return type(value)=='string' and #value==16 and not value:find('[^%x]')
end
local function inside(r,x,y)
  return x>=r.x and x<r.x+r.w and y>=r.y and y<r.y+r.h
end
local function valid_rect(r,width,height)
  if type(r)~='table' then return false end
  for _,key in ipairs({'x','y','w','h'}) do if not number(r[key]) then return false end end
  return r.x>=0 and r.y>=0 and r.w>0 and r.h>0 and r.x+r.w<=width and r.y+r.h<=height
end
local function contained(r,clip,width,height)
  return valid_rect(r,width,height) and r.x>=clip.x and r.y>=clip.y
    and r.x+r.w<=clip.x+clip.w and r.y+r.h<=clip.y+clip.h
end
local function intersection(r,bounds)
  local x,y=math.max(r.x,bounds.x),math.max(r.y,bounds.y)
  local right,top=math.min(r.x+r.w,bounds.x+bounds.w),math.min(r.y+r.h,bounds.y+bounds.h)
  if right<=x or top<=y then return nil end
  return {x=x,y=y,w=right-x,h=top-y}
end
local function prefix_cell_rect(cell,clip,width,height,scale)
  local r=cell.rect
  if type(r)~='table'then return nil end
  for _,key in ipairs({'x','y','w','h'})do if not number(r[key])then return nil end end
  if r.w<64*scale or r.h<64*scale then return nil end
  if contained(r,clip,width,height)then return r,false,r end
  local visible=intersection(r,clip)
  if visible then return r,true,visible end
end
local function badge_rect(cell,r,scale)
  local image=cell.image_rect
  if type(image)=='table' then
    for _,key in ipairs({'x','y','w','h'})do if not number(image[key])then image=nil;break end end
  end
  if type(image)~='table' or image.w<64*scale or image.h<64*scale or image.x<r.x or image.y<r.y
    or image.x+image.w>r.x+r.w or image.y+image.h>r.y+r.h then image=r end
  local size=math.min(28*scale,image.w/4,image.h/4)
  -- Keep the native selected/equipped marker at the top-right unobscured.
  return {x=image.x+5*scale,y=image.y+image.h-size-5*scale,w=size,h=size}
end
local function saved_review(value)
  if type(value)~='table' or type(value.label)~='string' or #value.label==0
    or #value.label>256 or type(value.request)~='table' then return nil end
  for _,field in ipairs({'appearance_id','stats_id','passive_variant_id'})do
    local id=value.request[field]
    if type(id)~='string' or #id==0 or #id>128 or id:find('[%c%s]') then return nil end
  end
  return value
end
local function valid_uv(uv)
  if type(uv)~='table' or #uv~=4 then return false end
  for i=1,4 do if not number(uv[i]) or uv[i]<0 or uv[i]>1 then return false end end
  return uv[3]>uv[1] and uv[4]>uv[2]
end
local function stamp(value,depth)
  depth=depth or 0
  if type(value)~='table' then
    if type(value)=='string' then return #value..':'..value end
    if type(value)=='number' or type(value)=='boolean' then return tostring(value) end
    return type(value)
  end
  if depth>8 then return '{}' end
  local keys,out={},{}
  for key in pairs(value) do if type(key)=='string' or type(key)=='number' then keys[#keys+1]=key end end
  table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
  for _,key in ipairs(keys) do out[#out+1]=stamp(key,depth+1)..stamp(value[key],depth+1) end
  return '{'..table.concat(out)..'}'
end

function M.new(engine)
  local A,W,G=engine.Application,engine.World,engine.Gui
  local icon_art
  if type(PassiveIconDraw)=='table'and type(PassiveIconDraw.new)=='function'and type(PassiveIconGeometry)=='table'then
    local ok,value=pcall(PassiveIconDraw.new,engine,PassiveIconGeometry)
    if ok then icon_art=value end
  end
  local self={regions={},captures={},pages={options=1,section=1,review=1},page_limits={},
    handles=setmetatable({},{__mode='k'}),handle_serial=0,policy={},resource_materials={}}
  local metrics={draw_count=0,rebuild_count=0,signature_ms=0,signature_total_ms=0,signature_bytes=0,
    original_icon_available=icon_art~=nil,original_icon_draws=0,original_icon_rectangles=0}
  local function alive(world)
    for _,candidate in ipairs(A.worlds() or {}) do if candidate==world then return true end end
    return false
  end
  function self:clear()
    if self.gui and alive(self.world) then W.destroy_gui(self.world,self.gui) end
    self.gui,self.world,self.signature=nil,nil,nil
    self.resource_materials={}
    self.regions,self.captures,self.policy,self.page_limits={},{},{},{}
  end
  function self:capture(x,y)
    for _,r in ipairs(self.captures) do if inside(r,x,y) then return true end end
    return false
  end
  function self:hit(x,y)
    for _,r in ipairs(self.regions) do if inside(r,x,y) then return r.action end end
    if self:capture(x,y) then return {type='panel_background'} end
  end
  function self:input_policy() return self.policy end
  function self:metrics()
    local copy={};for key,value in pairs(metrics)do copy[key]=value end;return copy
  end
  function self:handle(action)
    if type(action)~='table' or action.type~='panel_page' then return false end
    local target=action.target
    if not self.page_limits[target] or (action.delta~=1 and action.delta~=-1) then return false end
    self.pages[target]=math.min(self.page_limits[target],math.max(1,self.pages[target]+action.delta))
    return true
  end
  function self:controller_capacity(view,sample)
    if view.step==1 and view.controller_native_looks then return 9 end
    local width,height=G.resolution();local layout=Layout.resolve(width,height,true)
    local picker=sample and sample.wizard_layout and sample.wizard_layout.picker or layout.picker
    local row_h=(view.step==3 and 208 or 122)*layout.scale
    return math.max(1,math.floor((picker.h-44*layout.scale)/row_h))
  end
  function self:draw(sample,view,context)
    metrics.draw_count=metrics.draw_count+1
    context=context or {}
    local preview_icons=context.passive_preview_icons~=false
    local width,height=G.resolution()
    if (sample.kind~='armory'and sample.kind~='deployment') or width<640 or height<480 then self:clear();return false end
    local world
    for _,candidate in ipairs(A.worlds() or {}) do if candidate~=A.main_world() then world=candidate;break end end
    if not world then self:clear();return false end
    local base_layout=Layout.resolve(width,height,view.open)
    local scale=base_layout.scale
    local native_details=not view.open and view.native_details==true
    local native_override=not view.open and view.native_override==true
    local native_override_id=native_override and type(view.native_override_id)=='string'
      and #view.native_override_id>0 and #view.native_override_id<=128
      and not view.native_override_id:find('[%c%s]')and view.native_override_id or nil
    local apply_notice=type(view.apply_notice)=='string'and #view.apply_notice>0 and view.apply_notice
      or not view.open and view.apply_pending==true and 'Loading preview…'or nil
    local equipped=not view.open and view.variant_phase=='equipped'
    local native_apply=not view.open and (native_details or native_override or view.apply_pending==true or apply_notice~=nil)
    local apply_enabled=native_details and view.can_apply==true and view.apply_pending~=true
      and (not native_override or native_override_id~=nil)
    local saved_variant=not view.open and saved_review(view.selected_variant) or nil
    local selected_variant=view.native_picker~=true and not native_details and view.apply_pending~=true and saved_variant or nil
    if view.native_picker==true and saved_variant then native_apply=true end
    local prefix
    if not view.open then prefix=sample.native_prefix end
    if prefix~=nil and (type(prefix)~='table' or prefix.verified~=true
      or not valid_rect(prefix.clip,width,height) or type(prefix.headers)~='table'
      or type(prefix.cells)~='table' or #prefix.headers>32 or #prefix.cells>256
      or prefix.original_badges~=nil and(type(prefix.original_badges)~='table'or #prefix.original_badges>256)) then
      self:clear();return false
    end
    local section=not prefix and sample.custom_section or nil
    if section and (not valid_rect(section,width,height) or section.w<350*scale or section.h<100*scale) then
      self:clear();return false
    end
    if not view.open and not section and not prefix and not selected_variant and not native_apply then self:clear();return true end
    local supplied=sample.wizard_layout or {}
    local layout={
      header=supplied.header or base_layout.header,
      picker=supplied.picker or base_layout.picker,
      review=supplied.review or base_layout.review,
      apply=supplied.apply or base_layout.apply,
      footer=supplied.footer or base_layout.footer,
    }
    if view.open then
      for _,r in pairs(layout) do if not valid_rect(r,width,height) then self:clear();return false end end
      if layout.header.w<500*scale or layout.header.h<56*scale
        or layout.picker.w<400*scale or layout.picker.h<280*scale
        or layout.review.w<920*scale or layout.review.h<420*scale
        or layout.apply.w<160*scale or layout.apply.h<44*scale then self:clear();return false end
    elseif selected_variant then
      for _,key in ipairs({'review','apply','footer'})do
        if not valid_rect(layout[key],width,height) then self:clear();return false end
      end
      if layout.review.w<920*scale or layout.review.h<420*scale
        or layout.apply.w<160*scale or layout.apply.h<44*scale then self:clear();return false end
    end
    if native_apply then
      for _,key in ipairs({'apply','footer'})do
        if not valid_rect(layout[key],width,height)then self:clear();return false end
      end
    end
    local native_summary
    if native_apply and not selected_variant and (saved_variant or apply_notice or equipped)then
      local r={x=layout.review.x+16*scale,y=layout.apply.y+2*scale,
        w=layout.apply.x-layout.review.x-32*scale,h=layout.apply.h-4*scale}
      if valid_rect(r,width,height)and r.w>=180*scale and r.h>=44*scale then native_summary=r end
    end
    if self.last_step~=view.step then
      self.pages.options,self.pages.review=1,1
      self.last_step=view.step
    end
    local review_request=selected_variant and selected_variant.request or view.selection or {}
    local review_key=stamp({label=selected_variant and (selected_variant.display_name or selected_variant.label) or view.label,
      appearance_id=review_request.appearance_id,stats_id=review_request.stats_id,
      passive_variant_id=review_request.passive_variant_id})
    if self.last_review_key~=review_key then self.pages.review=1;self.last_review_key=review_key end
    if view.controller_mode and view.controller_page then self.pages.options=view.controller_page end
    local signature_started=os.clock()
    local proof,proof_stamp={},{}
    local function check(spec,thumbnail)
      if type(spec)~='table' or spec.material_pointer~=nil then return false end
      if spec.material_handle~=nil then
        local handle=spec.material_handle
        if spec.native_handle_verified~=true or spec.handle_source~='engine_material'
          or (type(handle)~='userdata' and type(handle)~='cdata') or type(spec.valid)~='function' then return false end
        local ok,value=pcall(spec.valid)
        if not ok or value~=true then return false end
        if not self.handles[handle] then self.handle_serial=self.handle_serial+1;self.handles[handle]=self.handle_serial end
        return true,self.handles[handle]
      end
      return (not thumbnail or spec.verified==true) and resource(spec.material),0
    end
    -- Check borrowed handles before deciding that retained primitives are safe
    -- to reuse. A failed proof destroys their previous GUI in this same draw.
    local function remember(spec,thumbnail)
      if type(spec)~='table' then return end
      local ok,token=check(spec,thumbnail)
      proof[spec]=ok;proof_stamp[#proof_stamp+1]={ok,token}
    end
    local function image_signature(spec,thumbnail)
      if type(spec)~='table'then return false end
      remember(spec,thumbnail)
      local uv=type(spec.uv)=='table'and {spec.uv[1],spec.uv[2],spec.uv[3],spec.uv[4]}or nil
      return {material=resource(spec.material)and spec.material or false,uv=uv,has_uv=spec.uv~=nil,
        has_texture=spec.texture~=nil,verified=spec.verified==true,
        native_handle_verified=spec.native_handle_verified==true,engine_handle_source=spec.handle_source=='engine_material',
        has_pointer=spec.material_pointer~=nil,has_handle=spec.material_handle~=nil}
    end
    local function icon_signature(passive_id,hash,resource_only)
      if icon_art and icon_art:has(hash)then return {original_icon=hash:lower()}end
      if resource_only then return {material=hash}end
      local spec=context.passive_icons and context.passive_icons[passive_id]or {material=hash}
      return image_signature(spec,false)
    end
    local function caption_signature(field,key)
      local names=context.labels and context.labels[field]
      return key and (names and names[key]or key)or 'Not selected'
    end
    local function tuple_signature(values)
      local out={}
      for _,field in ipairs(STAT_FIELDS)do out[field]=values and values[field]end
      return out
    end
    local function page_signature(target,pages)
      self.pages[target]=math.min(pages,math.max(1,self.pages[target]))
      return {page=self.pages[target],pages=pages}
    end
    -- Project only fields that this draw uses. In particular, the complete
    -- catalog's body weights, modifier definitions and offscreen previews do
    -- not belong in a per-frame retained-GUI signature.
    local rendered={width=width,height=height,font=sample.font,material=sample.material,atlas=sample.atlas}
    if prefix then
      local saved,add={},nil
      for _,tile in ipairs((view.section or {}).tiles or {})do
        if tile.kind=='variant'then saved[tile.label]=tile elseif tile.kind=='add'then add=tile end
      end
      local visible={clip=prefix.clip,headers={},cells={},original_badges={}}
      if type(prefix.category)=='table'and prefix.category.text=='CUSTOM VARIANTS'
        and valid_rect(prefix.category.rect,width,height)then visible.category=prefix.category end
      for _,cell in ipairs(preview_icons and prefix.original_badges or {})do
        local r=type(cell)=='table'and prefix_cell_rect(cell,prefix.clip,width,height,scale)
        local passive=type(cell)=='table'and type(cell.passive)=='table'and cell.passive or {}
        if r then visible.original_badges[#visible.original_badges+1]={badge=badge_rect(cell,r,scale),
          icon=resource(passive.icon_hash)and passive.icon_hash or passive.material}end
      end
      for _,header in ipairs(prefix.headers)do
        local r=type(header)=='table'and header.rect
        if type(header)=='table'and header.text=='Custom Variant'and contained(r,prefix.clip,width,height)
          and r.w>=180*scale and r.h>=24*scale then visible.headers[#visible.headers+1]={rect=r,text=header.text}end
      end
      for _,cell in ipairs(prefix.cells)do
        local tile=type(cell)=='table'and (cell.kind=='create'and add or cell.kind=='variant'and saved[cell.label])
        local r,partial,visible_rect
        if tile and type(cell.key)=='string'and #cell.key>0 and #cell.key<=256 then
          r,partial,visible_rect=prefix_cell_rect(cell,prefix.clip,width,height,scale)
        end
        if r then
          local passive=type(cell.passive)=='table'and cell.passive or {}
          visible.cells[#visible.cells+1]={rect=r,visible_rect=visible_rect,
            badge=preview_icons and cell.kind=='variant'and badge_rect(cell,r,scale)or nil,
            partial=partial,kind=cell.kind,label=cell.label,display_name=tile.display_name,selected=cell.selected,
            enabled=tile.enabled,icon=resource(passive.icon_hash)and passive.icon_hash or passive.material}
        end
      end
      rendered.prefix=visible
    elseif not view.open and section then
      local tiles=(view.section or {}).tiles or {}
      local columns=math.max(1,math.floor(section.w/(146*scale)))
      local pages=math.max(1,math.ceil(#tiles/columns))
      local visible={rect=section,paging=page_signature('section',pages),tiles={}}
      for index=(self.pages.section-1)*columns+1,math.min(#tiles,self.pages.section*columns)do
        local tile=tiles[index]
        visible.tiles[#visible.tiles+1]={kind=tile.kind,label=tile.label,display_name=tile.display_name,enabled=tile.enabled,action=tile.action,
          preview=tile.kind~='add'and image_signature(tile.preview,true)or nil,
          icon=preview_icons and tile.kind~='add'and icon_signature(tile.request and tile.request.passive_variant_id,tile.icon_hash)or nil}
      end
      rendered.section=visible
    elseif view.open then
      local visible={step=view.step,step_number=view.step_number,step_count=view.step_count,
        controller_mode=view.controller_mode,controller_native_looks=view.controller_native_looks,controller_notice=view.controller_notice,controller_focus=view.controller_focus,controller_page=view.controller_page,
        stats_follow_look=view.stats_follow_look,title=view.title,header=layout.header,can_back=view.can_back,can_cancel=view.can_cancel,
        empty_options_notice=view.empty_options_notice}
      if view.step~=1 or view.controller_mode and not view.controller_native_looks then
        local options=view.options or {}
        local row_h=(view.step~=3 and 122 or 208)*scale
        local count=math.max(1,math.floor((layout.picker.h-44*scale)/row_h))
        local pages=math.max(1,math.ceil(#options/count))
        visible.picker=layout.picker;visible.paging=page_signature('options',pages);visible.options={}
        for index=(self.pages.options-1)*count+1,math.min(#options,self.pages.options*count)do
          local item=options[index]
          if view.step==1 then
            visible.options[#visible.options+1]={action=item.action,label=item.label,preview=image_signature(item.preview,true)}
          elseif view.step==2 then
            visible.options[#visible.options+1]={action=item.action,selected=item.selected,base=tuple_signature(item.base_values)}
          else
            visible.options[#visible.options+1]={action=item.action,selected=item.selected,label=item.label,
              effects=item.effects,icon=icon_signature(item.id,item.icon_hash)}
          end
        end
      end
      rendered.wizard=visible
    end
    if view.open or selected_variant then
      local selected=selected_variant and selected_variant.request or view.selection or {}
      local profile=context.stats_profiles and context.stats_profiles[selected.stats_id]
      local base=type(profile)=='table'and profile.base_only==true and profile.base_values_verified==true
        and type(profile.base_values)=='table'and profile.base_values or {}
      local passive=context.passive_variants and context.passive_variants[selected.passive_variant_id]or {}
      local name=caption_signature('passive_variant_id',selected.passive_variant_id)
      if name==selected.passive_variant_id and type(passive.name)=='string'then name=passive.name end
      local lines={}
      for _,effect in ipairs(passive.effects or {})do
        for _,line in ipairs(wrap(effect,math.max(18,math.floor(layout.review.w*0.49/(7.5*scale))-3)))do lines[#lines+1]=line end
      end
      local visible={rect=layout.review,apply=layout.apply,footer=layout.footer,creating=view.open,
        label=selected_variant and (selected_variant.display_name or selected_variant.label) or view.label,
        look=caption_signature('appearance_id',selected.appearance_id),base=tuple_signature(base),passive_name=name,
        icon=icon_signature(selected.passive_variant_id,passive.icon_hash,not view.open),
        paging=page_signature('review',math.max(1,math.ceil(#lines/7))),lines={}}
      for index=(self.pages.review-1)*7+1,math.min(#lines,self.pages.review*7)do visible.lines[#visible.lines+1]=lines[index]end
      if view.open then visible.notice=view.notice;visible.saving=view.saving;visible.can_create=view.can_create
      else visible.notice=view.apply_notice end
      rendered.review=visible
    end
    if native_apply then
      rendered.native_apply={apply=layout.apply,footer=layout.footer,native_details=native_details,
        enabled=apply_enabled,native_override=native_override,native_override_id=native_override_id,equipped=equipped,
        label=saved_variant and saved_variant.label,can_remove=view.can_remove,
        summary=native_summary,notice=apply_notice,
        look=native_summary and saved_variant and caption_signature('appearance_id',saved_variant.request.appearance_id)or nil}
    end
    local signature=stamp({rendered,proof_stamp,preview_icons})
    metrics.signature_ms=(os.clock()-signature_started)*1000
    metrics.signature_total_ms=metrics.signature_total_ms+metrics.signature_ms
    metrics.signature_bytes=#signature
    if self.signature==signature and self.world==world then return true end
    self:clear();self.world=world
    self.gui=assert(W.create_screen_gui(world,'scale',1,1))
    metrics.rebuild_count=metrics.rebuild_count+1
    local gui,id=self.gui,engine.IdString64.from_hex
    local font,material=id(sample.font),id(sample.material)
    local ink=assert(G.material(gui,material))
    local function parameter(hash)return id(hash..'00000000')end
    for _,hash in ipairs({'8035c266','5e8455fe','309e7783','82b803a8'}) do engine.Material.set_scalar(ink,parameter(hash),0) end
    engine.Material.set_vector2(ink,parameter('e13777ce'),engine.Vector2(1,-1))
    engine.Material.set_vector4(ink,parameter('7701209e'),engine.Color(0,0,0,0))
    engine.Material.set_texture(ink,parameter('88bac99b'),id(sample.atlas))
    local function color(r,g,b,a)return engine.Color(a or 255,r,g,b)end
    local gold,white,muted=color(255,215,60),color(242,244,247),color(168,178,186)
    local function rect(r,c,layer)G.rect(gui,engine.Vector3(r.x,r.y,layer or 980),engine.Vector2(r.w,r.h),c)end
    local function text(value,x,y,size,c,layer)
      G.text(gui,tostring(value or ''),font,size*scale,material,engine.Vector3(x,y,layer or 984),c or white)
    end
    local function capture(r)self.captures[#self.captures+1]=r end
    local function action(r,value,enabled)
      if enabled~=false then self.regions[#self.regions+1]={x=r.x,y=r.y,w=r.w,h=r.h,action=value}end
      local focus=view.controller_mode and view.controller_focus
      if enabled~=false and focus and focus.type==value.type and focus.id==value.id and focus.target==value.target then
        local t=3*scale
        rect({x=r.x,y=r.y,w=r.w,h=t},gold,988);rect({x=r.x,y=r.y+r.h-t,w=r.w,h=t},gold,988)
        rect({x=r.x,y=r.y,w=t,h=r.h},gold,988);rect({x=r.x+r.w-t,y=r.y,w=t,h=r.h},gold,988)
      end
    end
    local function button(r,title,value,enabled)
      rect(r,enabled==false and color(29,34,38) or color(54,58,49),982)
      text(title,r.x+10*scale,r.y+(r.h-16*scale)/2,16,enabled==false and muted or gold)
      action(r,value,enabled)
    end
    local function image(spec,r,thumbnail,bounds)
      if type(spec)~='table' or not check(spec,thumbnail) then return false end
      local layer=thumbnail and 982 or 985
      local uv=spec.uv
      if bounds then
        local visible=intersection(r,bounds)
        if not visible then return true end
        if visible.x~=r.x or visible.y~=r.y or visible.w~=r.w or visible.h~=r.h then
          if uv~=nil and not valid_uv(uv)then return false end
          local source=uv or {0,0,1,1}
          local u,v=source[3]-source[1],source[4]-source[2]
          -- Bitmap UVs use top-left texture coordinates while GUI rectangles
          -- use bottom-left viewport coordinates.
          uv={source[1]+(visible.x-r.x)/r.w*u,source[2]+(r.y+r.h-visible.y-visible.h)/r.h*v,
            source[1]+(visible.x+visible.w-r.x)/r.w*u,source[2]+(r.y+r.h-visible.y)/r.h*v}
          r=visible
        end
      end
      local ok,drawn=pcall(function()
        if spec.material_handle then
          if proof[spec]~=true or not valid_uv(uv) or type(G.bitmap_uv)~='function' then return false end
          G.bitmap_uv(gui,spec.material_handle,engine.Vector2(uv[1],uv[2]),engine.Vector2(uv[3],uv[4]),
            engine.Vector3(r.x,r.y,layer),engine.Vector2(r.w,r.h),white)
        else
          if type(A.can_get)~='function' or not A.can_get('material',id(spec.material)) or type(G.bitmap)~='function' then return false end
          -- Resource thumbnails must be an independently verified ready-to-use
          -- material. Texture rebinding and foreign native atlas pointers are
          -- intentionally outside this renderer's contract.
          if spec.texture~=nil then return false end
          local handle=self.resource_materials[spec.material]
          if not handle then
            handle=G.material(gui,id(spec.material))
            -- HD2's live Gui.material returns engine Material userdata. Pass
            -- that ORIGINAL value to bitmap, never the resource IdString64,
            -- an integer address, cdata pointer, or a fabricated wrapper.
            if type(handle)~='userdata' then return false end
            self.resource_materials[spec.material]=handle
          end
          if uv then
            if not valid_uv(uv) or type(G.bitmap_uv)~='function' then return false end
            G.bitmap_uv(gui,handle,engine.Vector2(uv[1],uv[2]),engine.Vector2(uv[3],uv[4]),
              engine.Vector3(r.x,r.y,layer),engine.Vector2(r.w,r.h),white)
          else G.bitmap(gui,handle,engine.Vector3(r.x,r.y,layer),engine.Vector2(r.w,r.h),white) end
        end
        return true
      end)
      return ok and drawn==true
    end
    local function icon(passive_id,hash,r,resource_only,bounds)
      if icon_art and icon_art:has(hash)then
        local result=icon_art:draw(gui,hash,r,985,{255,221,31,255},bounds)
        if result then
          metrics.original_icon_draws=metrics.original_icon_draws+1
          metrics.original_icon_rectangles=metrics.original_icon_rectangles+result.rectangles
          return true
        end
      end
      local spec=not resource_only and context.passive_icons and context.passive_icons[passive_id]or {material=hash}
      if image(spec,r,false,bounds)then return true end
      if not bounds or contained(r,bounds,width,height)then
        text('?',r.x+r.w/3,r.y+r.h/4,math.min(16,r.h/scale*.7),muted)
      end
      return false
    end
    local function pager(target,r,count)
      self.page_limits[target]=math.max(1,count)
      self.pages[target]=math.min(self.page_limits[target],math.max(1,self.pages[target]))
      if count<=1 then return end
      local page=self.pages[target]
      button({x=r.x,y=r.y,w=34*scale,h=28*scale},'<',{type='panel_page',target=target,delta=-1},page>1)
      text(page..' / '..count,r.x+43*scale,r.y+7*scale,13,muted)
      button({x=r.x+101*scale,y=r.y,w=34*scale,h=28*scale},'>',{type='panel_page',target=target,delta=1},page<count)
    end
    local function caption(field,key)
      local names=context.labels and context.labels[field]
      return key and (names and names[key] or key) or 'Not selected'
    end
    local function review(label,selected,creating)
      capture(layout.review);rect(layout.review,color(12,17,22))
      capture(layout.apply);rect(layout.apply,color(12,17,22))
      capture(layout.footer);rect(layout.footer,color(0,0,0))
      local r=layout.review
      text(creating and 'CUSTOM VARIANT' or 'Saved variant',r.x+16*scale,r.y+r.h-26*scale,13,gold)
      text(clip(label or 'New variant',65),r.x+16*scale,r.y+r.h-55*scale,23,white)
      text('LOOK',r.x+16*scale,r.y+r.h-86*scale,12,muted)
      text(clip(caption('appearance_id',selected.appearance_id),75),r.x+16*scale,r.y+r.h-112*scale,19,white)
      if creating and view.step==1 then
        text(view.controller_mode and 'D-pad / left stick: choose a look. A: select.' or view.stats_follow_look and 'Choose owned armor to use its look and base stats.' or 'Choose an owned armor thumbnail to use its look.',r.x+16*scale,r.y+r.h-151*scale,17,gold)
      end
      local profile=context.stats_profiles and context.stats_profiles[selected.stats_id]
      local base=type(profile)=='table' and profile.base_only==true and profile.base_values_verified==true
        and type(profile.base_values)=='table' and profile.base_values or {}
      text('BASE STATS',r.x+16*scale,r.y+r.h-185*scale,13,gold)
      for index,field in ipairs(STAT_FIELDS)do
        local x=r.x+16*scale+(index-1)*145*scale
        text(STAT_LABELS[index],x,r.y+r.h-208*scale,10,muted)
        text(number(base[field]) and base[field]>=0 and string.format('%g',base[field]) or '--',x,r.y+r.h-236*scale,22,white)
      end
      local passive=context.passive_variants and context.passive_variants[selected.passive_variant_id] or {}
      local right=r.x+r.w*0.51
      text('PASSIVE',right,r.y+r.h-145*scale,13,gold)
      local badge={x=right,y=r.y+r.h-195*scale,w=30*scale,h=30*scale}
      icon(selected.passive_variant_id,passive.icon_hash,badge,not creating)
      local passive_name=caption('passive_variant_id',selected.passive_variant_id)
      if passive_name==selected.passive_variant_id and type(passive.name)=='string' then passive_name=passive.name end
      local names=wrap(passive_name,math.max(16,math.floor(r.w*0.49/(9*scale))-6))
      for index=1,math.min(2,#names)do text(names[index],right+40*scale,r.y+r.h-(176+(index-1)*21)*scale,17,white)end
      local lines={}
      for _,effect in ipairs(passive.effects or {})do
        for _,line in ipairs(wrap(effect,math.max(18,math.floor(r.w*0.49/(7.5*scale))-3)))do lines[#lines+1]=line end
      end
      local pages=math.max(1,math.ceil(#lines/7));self.pages.review=math.min(pages,math.max(1,self.pages.review))
      for index=1,7 do
        local line=lines[(self.pages.review-1)*7+index]
        if line then text(line,right,r.y+r.h-(227+(index-1)*17)*scale,14,white)end
      end
      pager('review',{x=right,y=r.y+78*scale},pages)
      local note=creating and (view.notice or 'Create saves this variant. Your equipped armor stays unchanged.')
        or (type(view.apply_notice)=='string'and view.apply_notice or (sample.kind=='deployment'and 'Choose a saved variant.'or 'Choose another card or + to create a variant.'))
      text(clip(note,90),r.x+16*scale,r.y+24*scale,13,muted)
      if creating then button(layout.apply,view.saving and 'Saving...' or 'Create',{type='create'},view.can_create)end
    end
    self.page_limits={}
    if prefix then
      local saved,add={},nil
      for _,tile in ipairs((view.section or {}).tiles or {})do
        if tile.kind=='variant' then saved[tile.label]=tile elseif tile.kind=='add' then add=tile end
      end
      local function fitted(value,r,size,padding)
        local clean=tostring(value or ''):gsub('%c',' ')
        local available=r.w-padding*scale
        local function fallback()
          local count=math.floor((r.w/scale-padding)/(size*.8))
          return clip(clean,math.max(1,count-3))
        end
        if type(G.text_extents)~='function'then return fallback()end
        local function measure(text)
          local ok,width=pcall(function()
            -- Observed native Lua contract: first two results are min/max
            -- vectors. Measure on this owned GUI with its actual font/size.
            local minimum,maximum=G.text_extents(gui,text,font,size*scale)
            local left,right=minimum.x,maximum.x
            if not number(left)or not number(right)or right<left then return nil end
            local extent=right-left
            return number(extent)and extent or nil
          end)
          return ok and width or nil
        end
        local width=measure(clean)
        if not width then return fallback()end
        if width<=available then return clean end
        local dots=measure('...')
        if not dots then return fallback()end
        if dots>available then return ''end
        local characters=chars(clean)
        local low,high,best=0,#characters-1,'...'
        while low<=high do
          local count=math.floor((low+high)/2)
          local candidate=table.concat(characters,'',1,count)..'...'
          local measured=measure(candidate)
          if not measured then return fallback()end
          if measured<=available then best=candidate;low=count+1 else high=count-1 end
        end
        return best
      end
      if rendered.prefix.category then
        local category=rendered.prefix.category;local r=category.rect
        rect(r,color(12,17,22));text(category.text,r.x+16*scale,r.y+(r.h-20*scale)/2,20,gold)
      end
      for _,cell in ipairs(rendered.prefix.original_badges)do
        local visible=intersection(cell.badge,prefix.clip)
        if visible then rect(visible,color(12,17,22),983);icon(nil,cell.icon,cell.badge,true,prefix.clip)end
      end
      for _,header in ipairs(prefix.headers)do
        local r=type(header)=='table' and header.rect
        if type(header)=='table' and header.text=='Custom Variant'
          and contained(r,prefix.clip,width,height) and r.w>=180*scale and r.h>=24*scale then
          capture(r);rect(r,color(12,17,22))
          local size=math.min(20,r.h/scale-8,(r.w/scale-16)/(14*.8))
          text('Custom Variant',r.x+8*scale,r.y+(r.h-size*scale)/2,size,gold)
        end
      end
      for _,cell in ipairs(prefix.cells)do
        local tile=type(cell)=='table' and (cell.kind=='create' and add or cell.kind=='variant' and saved[cell.label])
        local r,partial,visible
        if tile and type(cell.key)=='string'and #cell.key>0 and #cell.key<=256 then
          r,partial,visible=prefix_cell_rect(cell,prefix.clip,width,height,scale)
        end
        if r then
          capture(visible)
          if partial and cell.kind=='create' then
            -- The native placeholder must never show through while scrolling.
            -- Keep its plus at the original card center while clipping.
            rect(visible,color(12,17,22))
            local plus={x=r.x+r.w/2-12*scale,y=r.y+r.h/2-8*scale,w=36*scale,h=36*scale}
            if visible.w>=52*scale and visible.h>=52*scale and contained(plus,prefix.clip,width,height)then
              text('+',plus.x,plus.y,36,tile.enabled and gold or muted)
            end
          elseif cell.kind=='create' then
            rect(r,color(12,17,22))
            text('+',r.x+r.w/2-12*scale,r.y+r.h/2-8*scale,36,tile.enabled and gold or muted)
            text(fitted('Create variant',r,13,16),r.x+8*scale,r.y+12*scale,13,tile.enabled and white or muted)
            action(r,{type='open'},tile.enabled==true)
          else
            local name={x=r.x,y=r.y,w=r.w,h=math.min(34*scale,r.h*.3)}
            local visible_name=intersection(name,prefix.clip)
            if visible_name then
              rect(visible_name,color(12,17,22))
              if contained(name,prefix.clip,width,height)then
                local caption=tile.display_name or cell.label
                local fit=fitted(caption,name,13,12)
                local look,perk=caption:match('^(.-) %- (.+)$')
                if fit~=caption and look and perk then
                  text(fitted(look,name,13,12),name.x+6*scale,name.y+18*scale,13,tile.enabled and white or muted)
                  text(fitted('- '..perk,name,13,12),name.x+6*scale,name.y+3*scale,13,tile.enabled and white or muted)
                else text(fit,name.x+6*scale,name.y+(name.h-13*scale)/2,13,tile.enabled and white or muted)end
              end
              if cell.selected==true then
                local line=intersection({x=name.x,y=name.y,w=name.w,h=2*scale},prefix.clip)
                if line then rect(line,gold,983)end
              end
            end
            local badge=badge_rect(cell,r,scale)
            local visible_badge=intersection(badge,prefix.clip)
            local passive=type(cell.passive)=='table' and cell.passive or {}
            local hash=resource(passive.icon_hash) and passive.icon_hash or passive.material
            -- Construct a resource-only descriptor. Never pass foreign handle,
            -- pointer, texture, valid(), or preview metadata to the image path.
            if preview_icons and visible_badge then
              rect(visible_badge,color(12,17,22),983)
              icon(nil,hash,badge,true,prefix.clip)
            end
            action(visible,{type='select_variant',label=cell.label},not partial and tile.enabled==true)
          end
        end
      end
      self.policy={native_look_pick=false,block_native_apply=false,block_native_compare=false,
        native_prefix=true,custom_cells_require_interception=true}
    elseif not view.open and section then
      capture(section);rect(section,color(12,17,22))
      text('Custom Variant',section.x+8*scale,section.y+section.h-27*scale,20,gold)
      local tiles=(view.section or {}).tiles or {}
      local columns=math.max(1,math.floor(section.w/(146*scale)))
      local pages=math.max(1,math.ceil(#tiles/columns))
      self.pages.section=math.min(pages,math.max(1,self.pages.section))
      local gap=7*scale
      local card_width=(section.w-gap*(columns-1))/columns
      local card_height=math.max(20*scale,section.h-42*scale)
      for slot=1,columns do
        local tile=tiles[(self.pages.section-1)*columns+slot]
        if tile then
          local r={x=section.x+(slot-1)*(card_width+gap),y=section.y+5*scale,w=card_width,h=card_height}
          rect(r,color(30,36,42));action(r,tile.action,tile.enabled)
          if tile.kind=='add' then
            text('+',r.x+r.w/2-12*scale,r.y+r.h/2,36,tile.enabled and gold or muted)
            text('Create variant',r.x+8*scale,r.y+10*scale,13,tile.enabled and white or muted)
          else
            local ready=image(tile.preview,{x=r.x+4*scale,y=r.y+34*scale,w=r.w-8*scale,h=math.max(1,r.h-38*scale)},true)
            if not ready then text('Saved look',r.x+8*scale,r.y+r.h/2,13,muted)end
            text(clip(tile.display_name or tile.label,math.max(8,math.floor(card_width/(7*scale))-2)),r.x+6*scale,r.y+12*scale,14,tile.enabled and white or muted)
            local badge={x=r.x+r.w-31*scale,y=r.y+r.h-31*scale,w=25*scale,h=25*scale}
            if preview_icons then
              rect(badge,color(12,17,22),983)
              icon(tile.request and tile.request.passive_variant_id,tile.icon_hash,badge)
            end
          end
        end
      end
      pager('section',{x=section.x+section.w-140*scale,y=section.y+section.h-31*scale},pages)
      self.policy={native_look_pick=false,block_native_apply=false,block_native_compare=false}
    elseif view.open then
      capture(layout.header);rect(layout.header,color(12,17,22))
      text('CREATE VARIANT  '..tostring(view.step_number or view.step)..' / '..tostring(view.step_count or 3),layout.header.x+8*scale,layout.header.y+34*scale,12,gold)
      text(view.controller_notice or view.title or 'Create variant',layout.header.x+8*scale,layout.header.y+10*scale,19,white)
      button({x=layout.header.x+layout.header.w-172*scale,y=layout.header.y+10*scale,w=76*scale,h=32*scale},'Back',{type='back'},view.can_back)
      button({x=layout.header.x+layout.header.w-88*scale,y=layout.header.y+10*scale,w=80*scale,h=32*scale},'Cancel',{type='cancel'},view.can_cancel)
      if view.step~=1 or view.controller_mode and not view.controller_native_looks then
        capture(layout.picker);rect(layout.picker,color(12,17,22))
        local options=view.options or {}
        local row_h=(view.step~=3 and 122 or 208)*scale
        local count=math.max(1,math.floor((layout.picker.h-44*scale)/row_h))
        local pages=math.max(1,math.ceil(#options/count))
        self.pages.options=math.min(pages,math.max(1,self.pages.options))
        for row=1,count do
          local item=options[(self.pages.options-1)*count+row]
          if item then
            local r={x=layout.picker.x+5*scale,y=layout.picker.y+layout.picker.h-row*row_h+6*scale,
              w=layout.picker.w-10*scale,h=row_h-12*scale}
            rect(r,item.selected and color(61,60,39) or color(30,36,42));action(r,item.action)
            if item.selected then rect({x=r.x,y=r.y,w=3*scale,h=r.h},gold,983)end
            if view.step==1 then
              image(item.preview,{x=r.x+10*scale,y=r.y+8*scale,w=80*scale,h=r.h-16*scale},true)
              local names=wrap(item.label,math.max(12,math.floor((r.w/scale-116)/9)))
              for i=1,math.min(3,#names)do text(names[i],r.x+104*scale,r.y+r.h-(24+(i-1)*24)*scale,18,gold)end
            elseif view.step==2 then
              text('BASE STATS',r.x+12*scale,r.y+r.h-23*scale,13,gold)
              for index,field in ipairs(STAT_FIELDS) do
                local x=r.x+12*scale+(index-1)*(r.w-24*scale)/3
                local value=item.base_values and item.base_values[field]
                text(STAT_LABELS[index],x,r.y+46*scale,11,muted)
                text(number(value) and string.format('%g',value) or '--',x,r.y+17*scale,24,white)
              end
            else
              icon(item.id,item.icon_hash,{x=r.x+12*scale,y=r.y+r.h-53*scale,w=36*scale,h=36*scale})
              local names=wrap(item.label,math.max(12,math.floor((r.w/scale-78)/9)))
              text(names[1],r.x+62*scale,r.y+r.h-30*scale,18,gold)
              if names[2] then text(names[2],r.x+62*scale,r.y+r.h-50*scale,18,gold)end
              local lines={}
              for _,effect in ipairs(item.effects or {}) do
                for _,line in ipairs(wrap(effect,math.max(14,math.floor((r.w/scale-24)/8)))) do lines[#lines+1]=line end
              end
              for index=1,math.min(6,#lines) do text(lines[index],r.x+12*scale,r.y+r.h-(68+(index-1)*18)*scale,15,white)end
              if #lines>6 then text('Select to review the full passive.',r.x+12*scale,r.y+8*scale,12,muted)end
            end
          end
        end
        if #options==0 then
          local lines=wrap(view.empty_options_notice or 'Waiting for verified owned choices.',52)
          for i=1,math.min(5,#lines)do
            text(lines[i],layout.picker.x+12*scale,layout.picker.y+layout.picker.h-(35+(i-1)*23)*scale,17,muted)
          end
        end
        pager('options',{x=layout.picker.x+layout.picker.w-147*scale,y=layout.picker.y+5*scale},pages)
        if view.controller_mode then
          text('A Select   B Back   Y Cancel',layout.picker.x+12*scale,layout.picker.y+24*scale,12,gold)
          text('D-pad / stick Move    LB / RB Page',layout.picker.x+12*scale,layout.picker.y+8*scale,11,muted)
        end
        if view.step==2 and not view.controller_mode then text('Passive bonuses are excluded.',layout.picker.x+12*scale,layout.picker.y+13*scale,13,muted)end
      end
      review(view.label,view.selection or {},true)
      self.policy={native_look_pick=view.step==1 and (not view.controller_mode or view.controller_native_looks==true),block_native_grid=view.step~=1 or (view.controller_mode==true and not view.controller_native_looks),
        block_native_apply=true,block_native_compare=true,wizard_open=true,native_picker_rect=layout.picker}
    end
    if selected_variant then
      review(selected_variant.display_name or selected_variant.label,selected_variant.request,false)
      self.policy.saved_variant_review=true
      self.policy.native_look_pick=false
      self.policy.block_native_apply=true
      self.policy.block_native_compare=true
    end
    if native_apply then
      capture(layout.apply);capture(layout.footer)
      local apply_action={type='apply_variant',label=not native_override and saved_variant and saved_variant.label or nil,
        id=native_override_id}
      action(layout.apply,apply_action,apply_enabled)
      action(layout.footer,apply_action,apply_enabled)
      if native_summary then
        local r=native_summary
        if apply_notice then
          local lines=wrap(apply_notice,math.max(1,math.floor(r.w/(12*scale*.8))-3))
          local offset=20
          for index=1,math.min(2,#lines)do
            text(lines[index]..(index==2 and #lines>2 and '...'or ''),r.x,r.y+r.h-(offset+(index-1)*14)*scale,12,gold)
          end
        elseif equipped then
          text('Equipped',r.x,r.y+r.h-20*scale,13,gold)

        end
      end
      if saved_variant and view.can_remove and sample.kind~='deployment' then
        local remove={x=layout.apply.x-196*scale,y=layout.apply.y,w=180*scale,h=layout.apply.h}
        if valid_rect(remove,width,height)then
          button(remove,'Remove variant',{type='remove_variant',label=saved_variant.label},view.apply_pending~=true)
        end
      end
      self.policy.native_details=native_details
      self.policy.native_override=native_override
      self.policy.block_native_apply=true
      self.policy.block_native_compare=not native_details or view.apply_pending==true
      self.policy.apply_pending=view.apply_pending==true
    end
    self.signature=signature
    return true
  end
  return self
end
return M
