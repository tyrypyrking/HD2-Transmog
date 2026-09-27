-- Explicit, one-shot passive-icon binding diagnostic. Never used by normal UI.
-- No FFI, addresses, casts, resource loading, gameplay calls, or shared materials.
--
-- local probe=IconProbe.new(engine)
-- probe:draw(sample, '7c818b04a594d8e5') -> true|nil, reason
-- probe:report() -> bounded semantic text; API acceptance is NOT visual proof.
-- probe:metrics() -> counters only
-- probe:clear() -> discard all owned GUIs; does not rearm this probe instance.
-- Construct a new instance for another explicitly requested diagnostic.
-- sample: {kind='armory', font=<hash>,material=<font hash>,atlas=<hash>}

local M={}
local GENERIC='57fcf14ad069020b' -- Installed content/ui/shared/material/gui_diffuse_map.
local BRANCHES={
 {key='direct_hash',label='1  Resource ID'},
 {key='icon_userdata',label='2  Icon material'},
 {key='generic_texture',label='3  Texture binding'},
 {key='configured_icon',label='4  Configured icon'},
}
local function hash(value)return type(value)=='string'and #value==16 and not value:find('[^%x]')end
local function safe(value)
 return tostring(value):gsub('0[xX][%x]+','<address>'):gsub('[\r\n%z]',' '):sub(1,200)
end
function M.new(engine)
 local A,W,G=engine.Application,engine.World,engine.Gui
 local self={guis={},attempted=false,visible=false,branches={},status='not_requested'}
 local counts={draw_requests=0,attempts=0,guis_created=0,guis_destroyed=0,
  material_userdata=0,bitmap_accepted=0}
 local function alive(world)
  for _,candidate in ipairs(A.worlds()or {})do if candidate==world then return true end end
  return false
 end
 function self:clear()
  if alive(self.world)then
   for index=#self.guis,1,-1 do
    if pcall(W.destroy_gui,self.world,self.guis[index])then counts.guis_destroyed=counts.guis_destroyed+1 end
   end
  end
  self.guis={};self.world=nil;self.visible=false
 end
 function self:metrics()
  local out={};for key,value in pairs(counts)do out[key]=value end
  out.visible=self.visible;out.active_guis=#self.guis;return out
 end
 function self:report()
  local lines={'HD2TM_ICON_PROBE 1','status='..self.status,'visual_verified=false',
   'visible='..tostring(self.visible),'raw_pointer_conversions=false',
   'icon_hash='..tostring(self.icon_hash or ''),'configured_uniforms_verified_for=font_material_only'}
  if self.error then lines[#lines+1]='error='..safe(self.error)end
  for _,definition in ipairs(BRANCHES)do
   local branch=self.branches[definition.key]
   if branch then
    lines[#lines+1]='branch='..definition.key..' accepted='..tostring(branch.accepted==true)
      ..' material_available='..tostring(branch.material_available==true)
      ..' texture_available='..tostring(branch.texture_available==true)
      ..' material_type='..tostring(branch.material_type or 'resource_id')
    if branch.error then lines[#lines+1]='branch_error='..definition.key..' '..safe(branch.error)end
   end
  end
  return table.concat(lines,'\n')..'\n'
 end
 function self:draw(sample,icon_hash)
  counts.draw_requests=counts.draw_requests+1
  if self.attempted then return nil,'This icon probe already ran; clear it and create a new probe for another test.'end
  self.attempted=true;counts.attempts=counts.attempts+1
  self.icon_hash=hash(icon_hash)and icon_hash or nil
  local ok,reason=pcall(function()
   assert(type(sample)=='table'and sample.kind=='armory','Open the native Armory before the icon probe.')
   assert(hash(icon_hash)and hash(sample.font)and hash(sample.material)and hash(sample.atlas),'Observed icon/font resource hashes are required.')
   assert(type(G.bitmap)=='function'and type(G.material)=='function','Required engine GUI bindings are unavailable.')
   local width,height=G.resolution();assert(width>=640 and height>=480,'Viewport is too small for the icon probe.')
   for _,world in ipairs(A.worlds()or {})do if world~=A.main_world()then self.world=world;break end end
   assert(self.world,'No current UI world is available.')
   local scale=math.min(width/1920,height/1080)
   local id=engine.IdString64.from_hex
   local function color(r,g,b,a)return engine.Color(a or 255,r,g,b)end
   local function gui()
    local value=assert(W.create_screen_gui(self.world,'scale',1,1),'Screen GUI creation failed.')
    self.guis[#self.guis+1]=value;counts.guis_created=counts.guis_created+1;return value
   end
   local function material(target,resource)
    local value=G.material(target,id(resource))
    assert(type(value)=='userdata','Gui.material did not return original engine userdata.')
    counts.material_userdata=counts.material_userdata+1;return value
   end
   local function available(kind,resource)
    if type(A.can_get)~='function'then return false end
    local checked,value=pcall(A.can_get,kind,id(resource));return checked and value==true
   end
   local function configure(value)
    local function parameter(value)return id(value..'00000000')end
    for _,key in ipairs({'8035c266','5e8455fe','309e7783','82b803a8'})do
     engine.Material.set_scalar(value,parameter(key),0)
    end
    engine.Material.set_vector2(value,parameter('e13777ce'),engine.Vector2(1,-1))
    engine.Material.set_vector4(value,parameter('7701209e'),engine.Color(0,0,0,0))
   end
   local text_gui=gui()
   local ink=material(text_gui,sample.material);configure(ink)
   engine.Material.set_texture(ink,id('88bac99b00000000'),id(sample.atlas))
   local font,font_material=id(sample.font),id(sample.material)
   local x,y,w,h=width-1040*scale,height-395*scale,1010*scale,200*scale
   G.rect(text_gui,engine.Vector3(x,y,990),engine.Vector2(w,h),color(12,17,22))
   local function text(value,tx,ty,size,tint)
    G.text(text_gui,value,font,size*scale,font_material,engine.Vector3(tx,ty,997),tint or color(240,242,245))
   end
   text('PASSIVE ICON PROBE / '..icon_hash,x+12*scale,y+h-24*scale,17,color(255,215,60))
   local column=(w-24*scale)/4
   for index,definition in ipairs(BRANCHES)do
    local cx=x+12*scale+(index-1)*column
    local branch={accepted=false,material_available=false,texture_available=false}
    self.branches[definition.key]=branch
    text(definition.label,cx,y+h-49*scale,14)
    local bx,by,size=cx+column/2-42*scale,y+45*scale,84*scale
    G.rect(text_gui,engine.Vector3(bx,by,991),engine.Vector2(size,size),color(86,86,86))
    local passed,problem=pcall(function()
     local own_gui=gui()
     local resource=definition.key=='generic_texture'and GENERIC or icon_hash
     branch.material_available=available('material',resource)
     branch.texture_available=available('texture',icon_hash)
     assert(branch.material_available,'Material resource is unavailable.')
     local binding
     if definition.key=='direct_hash'then binding=id(icon_hash)
     else
      binding=material(own_gui,resource);branch.material_type=type(binding)
      if definition.key=='generic_texture'then
       assert(branch.texture_available,'Texture resource is unavailable.')
       engine.Material.set_texture(binding,'diffuse_map',id(icon_hash))
      elseif definition.key=='configured_icon'then configure(binding)end
     end
     G.bitmap(own_gui,binding,engine.Vector3(bx,by,995),engine.Vector2(size,size),color(255,255,255))
     branch.accepted=true;counts.bitmap_accepted=counts.bitmap_accepted+1
    end)
    if not passed then branch.error=safe(problem)end
    text(branch.accepted and 'API accepted; inspect image' or 'Unavailable / rejected',cx,y+18*scale,12,
      branch.accepted and color(166,190,169)or color(220,158,120))
   end
   self.status='drawn';self.visible=true
  end)
  if not ok then self.error=safe(reason);self.status='failed';self:clear();return nil,self.error end
  return true
 end
 return self
end
return M
