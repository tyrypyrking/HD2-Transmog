-- Original DDS-derived art drawn with retained Gui.rect primitives only.
-- Caller owns GUI creation/destruction and redraw caching. Coordinates use
-- Gui's bottom-left convention; stored art uses top-left sampled pixels.
-- Tint is an optional plain RGBA array, e.g. native gold {255,221,31,255}.
-- Optional clip bounds crop primitives without moving or scaling the artwork.
-- No materials, textures, game memory, FFI, resource loading, or invented art.
local M={}
local function number(value)return type(value)=='number'and value==value and math.abs(value)<10000000 end
local function byte(value)return number(value)and value%1==0 and value>=0 and value<=255 end
local function factory(value)
 local kind=type(value)
 -- Stingray Vector2/Vector3 are callable tables in the captured live API.
 return kind=='function'or kind=='table'or kind=='cdata'
end
local function valid_icon(icon)
 assert(type(icon)=='table'and(icon.sample==32 or icon.sample==48),'invalid sampled icon size')
 assert(type(icon.palette)=='table'and #icon.palette>=1 and #icon.palette<=16,'icon palette bounds rejected')
 for _,color in ipairs(icon.palette)do
  assert(type(color)=='table'and #color==4,'RGBA palette required')
  for _,v in ipairs(color)do assert(byte(v),'invalid icon color')end
 end
 assert(type(icon.rectangles)=='table'and #icon.rectangles>=1 and #icon.rectangles<=1024,'icon rectangle bounds rejected')
 for _,r in ipairs(icon.rectangles)do
  assert(type(r)=='table'and #r==5,'icon rectangle shape rejected')
  for _,v in ipairs(r)do assert(number(v)and v%1==0,'integer sampled rectangle required')end
  assert(r[1]>=0 and r[2]>=0 and r[3]>0 and r[4]>0 and r[1]+r[3]<=icon.sample and r[2]+r[4]<=icon.sample
   and r[5]>=1 and r[5]<=#icon.palette,'sampled rectangle outside icon bounds')
 end
end
function M.new(engine,data)
 assert(type(engine)=='table'and engine.Gui and type(engine.Gui.rect)=='function'
  and factory(engine.Vector2)and factory(engine.Vector3)and factory(engine.Color),'Gui rectangle/vector/color API required')
 assert(type(data)=='table'and data.schema_version==1 and type(data.icons)=='table','original icon geometry required')
 local count=0
 for hash,icon in pairs(data.icons)do
  assert(type(hash)=='string'and hash:match('^%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x$'),'native icon hash required')
  valid_icon(icon);count=count+1
 end
 assert(count>=1 and count<=64,'icon dictionary bounds rejected')
 local self={}
 function self:has(hash)return type(hash)=='string'and data.icons[hash:lower()]~=nil end
 function self:draw(gui,hash,rect,layer,tint,clip)
  local icon=type(hash)=='string'and data.icons[hash:lower()]
  if not icon then return nil,'Original native icon art unavailable'end
  local ok,result=pcall(function()
   assert(type(rect)=='table'and number(rect.x)and number(rect.y)and number(rect.w)and number(rect.h)
    and rect.w>0 and rect.h>0 and rect.w<=4096 and rect.h<=4096,'icon draw bounds rejected')
   assert(number(layer),'explicit icon draw layer required')
   if clip~=nil then
    assert(type(clip)=='table'and number(clip.x)and number(clip.y)and number(clip.w)and number(clip.h)
     and clip.w>0 and clip.h>0,'icon clip bounds rejected')
   end
   tint=tint or {255,255,255,255}
   assert(type(tint)=='table'and #tint==4,'RGBA icon tint required')
   for _,v in ipairs(tint)do assert(byte(v),'invalid icon tint')end
   local colors={}
   for index,pixel in ipairs(icon.palette)do
    local rgba={};for i=1,4 do rgba[i]=math.floor(pixel[i]*tint[i]/255+0.5)end
    if rgba[4]>0 then colors[index]=engine.Color(rgba[4],rgba[1],rgba[2],rgba[3])end
   end
   local sx,sy=rect.w/icon.sample,rect.h/icon.sample;local drawn=0
   for _,r in ipairs(icon.rectangles)do
    local color=colors[r[5]]
    if color then
     local x,y,w,h=rect.x+r[1]*sx,rect.y+rect.h-(r[2]+r[4])*sy,r[3]*sx,r[4]*sy
     if clip then
      local right,top=math.min(x+w,clip.x+clip.w),math.min(y+h,clip.y+clip.h)
      x,y=math.max(x,clip.x),math.max(y,clip.y);w,h=right-x,top-y
     end
     if w>0 and h>0 then
      engine.Gui.rect(gui,engine.Vector3(x,y,layer),engine.Vector2(w,h),color)
      drawn=drawn+1
     end
    end
   end
   return {rectangles=drawn,icon_hash=hash:lower(),source='original_native_dds',sample=icon.sample}
  end)
  if not ok then return nil,tostring(result)end
  return result
 end
 return self
end
return M
