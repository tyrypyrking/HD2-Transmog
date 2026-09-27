-- The native Armory uses a centered 1920-wide canvas on ultrawide screens.
-- Share its transform between drawing, clipping and input; native thumbnail
-- rectangles already contain this translation and must not be shifted again.
local M={}
function M.resolve(width,height,creating)
 assert(type(width)=='number'and type(height)=='number'and width>=640 and height>=480
  and width<math.huge and height<math.huge,'valid UI viewport required')
 local scale=math.min(width/1920,height/1080)
 local left=(width-1920*scale)/2
 local function rect(x,top,w,h)
  return {x=left+x*scale,y=height-top*scale,w=w*scale,h=h*scale}
 end
 local footer_width=creating and 400 or 250
 return {scale=scale,left=left,
  navigation=rect(0,160,1100,160),
  header=rect(172,238,644,56),picker=rect(172,976,644,738),
  prefix=rect(172,976,644,794),review=rect(860,978,1010,440),
  apply=rect(1534,976,330,58),
  footer={x=left+(1920-footer_width)*scale,y=0,w=footer_width*scale,h=58*scale}}
end
function M.contains(r,x,y)
 return r and type(x)=='number'and type(y)=='number'
  and x>=r.x and x<r.x+r.w and y>=r.y and y<r.y+r.h
end
function M.contains_rect(bounds,r)
 return r and r.x>=bounds.x and r.y>=bounds.y
  and r.x+r.w<=bounds.x+bounds.w and r.y+r.h<=bounds.y+bounds.h
end
return M
