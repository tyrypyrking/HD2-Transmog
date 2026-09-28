-- Retained Stingray GUI. Coordinates are bottom-left, in viewport pixels.
-- Engine resource/parameter identifiers are observations from DiverKit; no art is bundled.
local M = {}

-- Keep localized names/effect clauses inside the dock without cutting a UTF-8
-- code point. Wide glyphs use two cells; the native font remains authoritative.
local function characters(value)
    local chars = {}
    for char in tostring(value or ''):gmatch('[%z\1-\127\194-\244][\128-\191]*') do
        chars[#chars+1] = char
    end
    return chars
end
local function clip(value, limit)
    local chars, out, used = characters(value), {}, 0
    for index, char in ipairs(chars) do
        local size = char:byte() >= 0xE3 and 2 or 1
        if used+size > limit then return table.concat(out)..'...' end
        out[#out+1], used = char, used+size
    end
    return table.concat(out)
end
local function wrap(value, limit)
    local lines, line, used, last_space = {}, {}, 0, nil
    local function flush()
        lines[#lines+1] = table.concat(line):gsub('%s+$', '')
        line, used, last_space = {}, 0, nil
    end
    for _, char in ipairs(characters(value)) do
        local size = char:byte() >= 0xE3 and 2 or 1
        if char == '\n' then flush()
        else
            if used+size > limit then
                if last_space then
                    local rest = {}
                    for i=last_space+1,#line do rest[#rest+1] = line[i] end
                    for i=#line,last_space,-1 do line[i] = nil end
                    flush(); line = rest
                    for _, retained in ipairs(line) do used=used+(retained:byte() >= 0xE3 and 2 or 1) end
                else flush() end
            end
            if char ~= ' ' or #line > 0 then
                line[#line+1], used = char, used+size
                if char == ' ' then last_space = #line end
            end
        end
    end
    if #line > 0 then flush() end
    return lines
end

local function stamp(value,depth)
    depth=depth or 0
    if type(value)~='table'then
        local text=type(value)=='string' and value or type(value)=='number' and tostring(value) or type(value)=='boolean' and tostring(value) or type(value)
        return #text..':'..text
    end
    if depth>8 then return 'bounded' end
    local keys,out={},{}
    for key in pairs(value)do if type(key)=='string'or type(key)=='number'then keys[#keys+1]=key end end
    table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
    for _,key in ipairs(keys)do out[#out+1]=stamp(key,depth+1)..stamp(value[key],depth+1)end
    return '{'..table.concat(out)..'}'
end
local function resource(value)
    return type(value)=='string' and #value==16 and not value:find('[^%x]')
end
local function native_preview_valid(spec)
    if type(spec)~='table'or spec.native_handle_verified~=true or type(spec.valid)~='function'then return false end
    -- A raw void* cdata is not established as HD2's Material binding ABI.
    -- Require an actual engine-provided handle; never fabricate it here.
    local kind=type(spec.material_handle)
    if (kind~='userdata'and kind~='cdata')or spec.handle_source~='engine_material' then return false end
    local ok,value=pcall(spec.valid)
    return ok and value==true
end
local function valid_uv(uv)
    if type(uv)~='table'or #uv~=4 then return false end
    for i=1,4 do if type(uv[i])~='number'or uv[i]~=uv[i]or uv[i]<0 or uv[i]>1 then return false end end
    return uv[3]>uv[1]and uv[4]>uv[2]
end

function M.new(engine,trace)
    local self = {regions = {}, capture_regions={}, image_guis={}, card_layout={},trace=trace,
        native_handle_ids=setmetatable({}, {__mode='k'}),next_native_handle_id=0}
    local A, W, G = engine.Application, engine.World, engine.Gui
    local function stage(name)
        if type(self.trace)=='function'then pcall(self.trace,name)end
    end
    function self:set_trace(callback)self.trace=callback end
    local function alive(world)
        for _, value in ipairs(A.worlds() or {}) do if value == world then return true end end
        return false
    end
    function self:clear()
        if alive(self.world)then
            if self.gui then W.destroy_gui(self.world, self.gui) end
            for _,gui in ipairs(self.image_guis)do W.destroy_gui(self.world,gui)end
        end
        self.gui, self.world, self.signature, self.material_handle = nil, nil, nil, nil
        self.regions,self.capture_regions,self.image_guis,self.card_layout = {},{},{},{}
        self.active_title_bounds=nil
    end
    function self:variant_cards()return self.card_layout end
    function self:material_diagnostic()
        local result={gui_present=self.gui~=nil and alive(self.world),material_type=type(self.material_handle),
            ffi_available=false,void_pointer_cast=false}
        if not result.gui_present or self.material_handle==nil then return result end
        local loaded,ffi=pcall(require,'ffi')
        if not loaded then return result end
        result.ffi_available=true
        result.void_pointer_cast=pcall(function()ffi.cast('void *',self.material_handle)end)
        return result -- Never stringify or return a native address/handle.
    end
    function self:test_pointer_binding(report)
        local function trace_test(name)if type(report)=='function'then pcall(report,name)end end
        trace_test('begin')
        if not self.gui or not alive(self.world)or self.material_handle==nil then
            return {accepted=false,error='No live owned GUI material is available'}
        end
        local kind=type(self.material_handle)
        if kind~='userdata'and kind~='cdata'then return {accepted=false,error='Owned material is not an engine handle'}end
        if type(G.bitmap)~='function'then return {accepted=false,error='GUI bitmap binding unavailable'}end
        local bitmap_id
        local ok,reason=pcall(function()
            trace_test('before_handle_prepare')
            local handle=self.material_handle
            -- Explicit debug only: test the original engine-provided Material
            -- handle. A successful result does NOT authorize casting numbers
            -- or void* cdata into the same binding.
            trace_test('before_bitmap')
            bitmap_id=G.bitmap(self.gui,handle,engine.Vector3(0,0,969),engine.Vector2(8,8),engine.Color(255,255,255,255))
            trace_test('after_bitmap')
        end)
        if ok then
            trace_test('before_cleanup')
            if type(G.destroy_bitmap)=='function'and bitmap_id~=nil then
                local cleaned=pcall(G.destroy_bitmap,self.gui,bitmap_id)
                if not cleaned then self:clear()end
            else self:clear()end -- Guarantee the tiny test primitive is removed.
            trace_test('after_cleanup')
            return {accepted=true}
        end
        local message=tostring(reason):gsub('0[xX][%x]+','<pointer>'):gsub('[\r\n]',' '):sub(1,240)
        trace_test('error')
        return {accepted=false,error=message}
    end
    function self:capture(px,py)
        for _,r in ipairs(self.capture_regions)do
            if px>=r.x and px<r.x+r.w and py>=r.y and py<r.y+r.h then return true end
        end
        return false
    end
    function self:hit(x, y)
        for _, r in ipairs(self.regions) do
            if x >= r.x and x < r.x+r.w and y >= r.y and y < r.y+r.h then return r.key end
        end
        if self:capture(x,y)then return 'panel_background' end
    end
    function self:draw(sample, view)
        if view.suspended then self:clear();return false end
        local width, height = G.resolution()
        if width < 640 or height < 480 then self:clear(); return false end
        local world
        for _, candidate in ipairs(A.worlds() or {}) do
            if candidate ~= A.main_world() then world = candidate; break end
        end
        if not world then self:clear(); return false end
        -- Armory editor dock: above the character preview, away from the armor
        -- grid and the native Apply/Back controls. Deployment layout is retained
        -- solely as an offline regression fixture.
        local scale = math.min(width/1920, height/1080)
        local pw, ph = 430*scale, (view.open and 460 or 42)*scale
        local x = math.min(width-pw-12*scale, sample.anchor.x)
        local y = sample.anchor.y + sample.anchor.h + 10*scale
        if sample.kind=='armory' then
            x=width-pw-20*scale
            y=height-94*scale-ph
        end
        if x < 0 or y < 0 or y+ph > height-8*scale then self:clear(); return false end
        -- The adapter may reserve a real row at the top of the native left
        -- grid. Until it does, a compact strip fits in the gap below its tabs.
        local section=sample.variant_section
        if sample.kind=='armory' and not section and view.saved_section_enabled then
            section={x=204*scale,y=height-189*scale,w=582*scale,h=34*scale}
        end
        if section then
            for _,key in ipairs({'x','y','w','h'})do
                if type(section[key])~='number'or section[key]~=section[key]then self:clear();return false end
            end
            if section.x<0 or section.y<0 or section.w<260*scale or section.h<28*scale
                or section.x+section.w>width or section.y+section.h>height then self:clear();return false end
        end
        local editor = view.editor or {
            label='No variant selected', choice='No verified choices', count=0,
            details={'Waiting for a current owned armor catalog.'},
            ownership='Ownership unavailable - saved choices are preserved.',
            detail_page=1, saved_count=0,
        }
        -- Main supplies this only after the active variant's carrier matches
        -- the independently verified native selected kit. No identity guess
        -- or ownership inference is performed by the renderer.
        local active_title=sample.kind=='armory'and view.active_variant or nil
        if type(active_title)=='table'then
            for _,key in ipairs({'label','appearance_label','stats_label','passive_label'})do
                if type(active_title[key])~='string'or #active_title[key]>512 or active_title[key]==''then active_title=nil;break end
            end
        else active_title=nil end
        local title_box=active_title and (sample.variant_title or
            {x=885*scale,y=height-624*scale,w=970*scale,h=70*scale})or nil
        if title_box then
            for _,key in ipairs({'x','y','w','h'})do
                if type(title_box[key])~='number'or title_box[key]~=title_box[key]then title_box=nil;break end
            end
            if title_box and (title_box.x<0 or title_box.y<0 or title_box.w<320*scale or title_box.h<60*scale
                or title_box.x+title_box.w>width or title_box.y+title_box.h>height)then title_box=nil end
        end
        -- Borrowed native materials have a shorter lifetime than our retained
        -- GUI. Fresh validation MUST precede the unchanged-signature shortcut.
        local native_checks,native_validity,native_handle_tokens={},{},{}
        for _,card in ipairs((editor.saved_section or {}).cards or {})do
            for _,field in ipairs({'preview','passive_icon'})do
                local descriptor=card[field]
                if type(descriptor)=='table'and (descriptor.material_pointer~=nil or descriptor.material_handle~=nil)then
                    local valid=native_preview_valid(descriptor)
                    native_checks[descriptor]=valid;native_validity[#native_validity+1]=valid
                    local handle=descriptor.material_handle
                    if type(handle)=='userdata'or type(handle)=='cdata'then
                        if not self.native_handle_ids[handle]then
                            self.next_native_handle_id=self.next_native_handle_id+1
                            self.native_handle_ids[handle]=self.next_native_handle_id
                        end
                        native_handle_tokens[#native_handle_tokens+1]=self.native_handle_ids[handle]
                    else native_handle_tokens[#native_handle_tokens+1]=0 end
                end
            end
        end
        local detail_lines = {}
        for _, value in ipairs(editor.details or {}) do
            for _, line in ipairs(wrap(value, 49)) do detail_lines[#detail_lines+1] = line end
        end
        local pages = math.max(1, math.ceil(#detail_lines/4))
        local page = math.min(pages, math.max(1, editor.detail_page or 1))
        local signature = tostring(world)..stamp({width,height,x,y,view.open,view.tab or '',view.notice or '',view.saved,
            sample.font,sample.material,sample.atlas,view.title,view.apply_label,editor,section or false,native_validity,native_handle_tokens,
            active_title or false,title_box or false})
        if self.signature == signature then return true end
        self:clear()
        stage('draw.before_create_gui')
        self.world = world
        self.gui = assert(W.create_screen_gui(world, 'scale', 1, 1), 'screen GUI unavailable')
        stage('draw.after_create_gui')
        local gui, id = self.gui, engine.IdString64.from_hex
        local font, material = id(sample.font), id(sample.material)
        local ink = assert(G.material(gui, material), 'font material unavailable')
        self.material_handle=ink
        stage('draw.after_font_material')
        local function parameter(hash) return id(hash..'00000000') end
        for _, hash in ipairs({'8035c266','5e8455fe','309e7783','82b803a8'}) do
            engine.Material.set_scalar(ink, parameter(hash), 0)
        end
        engine.Material.set_vector2(ink, parameter('e13777ce'), engine.Vector2(1,-1))
        engine.Material.set_vector4(ink, parameter('7701209e'), engine.Color(0,0,0,0))
        engine.Material.set_texture(ink, parameter('88bac99b'), id(sample.atlas))
        stage('draw.after_font_setup')
        local function color(r,g,b,a) return engine.Color(a or 255,r,g,b) end
        local gold, white, muted = color(255,215,60), color(240,242,245), color(163,175,187)
        local function rect_at(rx,ry,rw,rh,c,layer)
            G.rect(gui,engine.Vector3(rx,ry,layer or 970),engine.Vector2(rw,rh),c)
        end
        local function text_at(value,tx,ty,size,c,layer)
            G.text(gui,value,font,size*scale,material,engine.Vector3(tx,ty,layer or 973),c or white)
        end
        local function rect(rx,ry,rw,rh,c)
            G.rect(gui,engine.Vector3(x+rx*scale,y+ry*scale,970),engine.Vector2(rw*scale,rh*scale),c)
        end
        local function text(s,tx,ty,size,c)
            G.text(gui,s,font,size*scale,material,engine.Vector3(x+tx*scale,y+ty*scale,973),c or white)
        end
        local function button(key,label,bx,by,bw,enabled,active)
            rect(bx,by,bw,30,enabled == false and color(28,34,40) or color(46,54,61))
            if active then rect(bx,by,bw,2,gold) end
            text(label,bx+8,by+8,15,enabled == false and muted or gold)
            if enabled ~= false then
                self.regions[#self.regions+1]={key=key,x=x+bx*scale,y=y+by*scale,w=bw*scale,h=30*scale}
            end
        end
        local function region(key,bx,by,bw,bh,enabled)
            if enabled~=false then self.regions[#self.regions+1]={key=key,x=bx,y=by,w=bw,h=bh}end
        end
        local function bitmap(spec,bx,by,bw,bh,tint,layer)
            if type(spec)~='table'then return false end
            if spec.material_pointer~=nil or spec.material_handle~=nil then
                if native_checks[spec]~=true or type(G.bitmap_uv)~='function'or not valid_uv(spec.uv)then return false end
                local ok,value=pcall(function()
                    if not native_preview_valid(spec)then return false end
                    local handle=spec.material_handle
                    local uv=spec.uv
                    -- Call only the documented Lua GUI binding. This is not
                    -- an arbitrary native function-pointer invocation.
                    stage('draw.before_native_bitmap')
                    G.bitmap_uv(gui,handle,engine.Vector2(uv[1],uv[2]),engine.Vector2(uv[3],uv[4]),
                        engine.Vector3(bx,by,layer or 971),engine.Vector2(bw,bh),tint or white)
                    stage('draw.after_native_bitmap')
                    return true
                end)
                return ok and value==true
            end
            if spec.native==true then return true end -- Native widget owns its thumbnail.
            if not resource(spec.material)or type(G.bitmap)~='function'or type(A.can_get)~='function'then return false end
            local ok,value=pcall(function()
                local mat=id(spec.material)
                if not A.can_get('material',mat)then return false end
                local target=gui
                if spec.texture then
                    if not resource(spec.texture)or not resource(spec.texture_parameter)or not A.can_get('texture',id(spec.texture))then return false end
                    -- Separate GUI instances prevent one retained image's
                    -- texture binding from changing another card's material.
                    target=assert(W.create_screen_gui(world,'scale',1,1))
                    self.image_guis[#self.image_guis+1]=target
                    local instance=assert(G.material(target,mat))
                    engine.Material.set_texture(instance,id(spec.texture_parameter),id(spec.texture))
                end
                local position,size=engine.Vector3(bx,by,layer or 971),engine.Vector2(bw,bh)
                stage('draw.before_resource_bitmap')
                if spec.uv then
                    if type(G.bitmap_uv)~='function'or not valid_uv(spec.uv)then return false end
                    local uv=spec.uv
                    G.bitmap_uv(target,mat,engine.Vector2(uv[1],uv[2]),engine.Vector2(uv[3],uv[4]),position,size,tint or white)
                else G.bitmap(target,mat,position,size,tint or white)end
                stage('draw.after_resource_bitmap')
                return true
            end)
            return ok and value==true
        end
        local function badge(icon,bx,by,size)
            rect_at(bx-2*scale,by-2*scale,size+4*scale,size+4*scale,color(12,17,22,245),975)
            if not bitmap(icon,bx,by,size,size,gold,977)then text_at('?',bx+size/3,by+size/5,14,muted,977)end
        end
        if section then
            stage('draw.saved_section')
            local sx,sy,sw,sh=section.x,section.y,section.w,section.h
            local saved=editor.saved_section or {cards={},page=1,pages=1,count=0}
            local full=sh>=110*scale
            self.capture_regions[#self.capture_regions+1]={x=sx,y=sy,w=sw,h=sh}
            if not section.native_cards then rect_at(sx,sy,sw,sh,color(12,17,22,245))end
            if section.native_cards then rect_at(sx,sy+sh-31*scale,sw,31*scale,color(12,17,22,245))end
            rect_at(sx,sy+sh-2*scale,sw,2*scale,gold)
            local title_width=full and 158*scale or 64*scale
            text_at(full and 'SAVED VARIANTS' or 'SAVED',sx+7*scale,sy+sh-23*scale,full and 17 or 12,gold)
            region('toggle',sx,sy+sh-30*scale,title_width,30*scale)
            local newx=sx+sw-54*scale
            text_at('+ New',newx+4*scale,sy+sh-22*scale,13,editor.can_new and gold or muted)
            region('new_variant',newx,sy+sh-30*scale,54*scale,30*scale,editor.can_new==true)
            local start=full and sx or sx+title_width
            local top=full and sy+sh-32*scale or sy+3*scale
            local card_h=full and math.min(sh-36*scale,240*scale)or sh-6*scale
            local available_w=full and sw or sw-title_width-92*scale
            local gap=7*scale
            local card_w=(available_w-2*gap)/3
            for index,card in ipairs(saved.cards or {})do
                local cx=start+(index-1)*(card_w+gap)
                local cy=full and top-card_h or top
                self.card_layout[#self.card_layout+1]={label=card.label,request=card.request,x=cx,y=cy,w=card_w,h=card_h,
                    image={x=cx+3*scale,y=cy+34*scale,w=card_w-6*scale,h=math.max(0,card_h-38*scale)},
                    badge={x=cx+card_w-31*scale,y=cy+card_h-31*scale,w=25*scale,h=25*scale}}
                local native_image=full and type(card.preview)=='table'and card.preview.native==true
                rect_at(cx,cy,card_w,native_image and 34*scale or card_h,card.selected and color(66,63,34)or color(29,35,40))
                if card.selected then rect_at(cx,cy,card_w,2*scale,gold)end
                if full then
                    local image_y,image_h=cy+34*scale,card_h-38*scale
                    local image_x,image_w=cx+3*scale,card_w-6*scale
                    if type(card.preview)=='table'and type(card.preview.width)=='number'and type(card.preview.height)=='number'
                        and card.preview.width>0 and card.preview.height>0 and card.preview.width<=32768 and card.preview.height<=32768 then
                        local ratio=card.preview.width/card.preview.height
                        local fitted_w,fitted_h=math.min(image_w,image_h*ratio),math.min(image_h,image_w/ratio)
                        image_x,image_y=image_x+(image_w-fitted_w)/2,image_y+(image_h-fitted_h)/2
                        image_w,image_h=fitted_w,fitted_h
                    end
                    self.card_layout[#self.card_layout].image={x=image_x,y=image_y,w=image_w,h=image_h}
                    local shown=image_h>0 and bitmap(card.preview,image_x,image_y,image_w,image_h,white)
                    self.card_layout[#self.card_layout].thumbnail_ready=shown==true
                    if not shown then
                        text_at(clip(card.appearance,math.max(8,math.floor(card_w/(8*scale))-2)),cx+7*scale,cy+card_h/2,14,card.available and white or muted)
                        if card_h>100*scale then text_at(card.available and 'Owned appearance' or 'Unavailable donor',cx+7*scale,cy+card_h/2-18*scale,11,muted)end
                    end
                    text_at(clip(card.label,math.max(8,math.floor(card_w/(7*scale))-3)),cx+6*scale,cy+18*scale,13,card.available and white or muted)
                    text_at(card.dirty and 'UNSAVED' or card.available and 'SELECT' or 'UNAVAILABLE',cx+6*scale,cy+5*scale,10,card.dirty and gold or muted)
                    badge(card.passive_icon,cx+card_w-31*scale,cy+card_h-31*scale,25*scale)
                    if card.selected then
                        text_at('Edit',cx+card_w-31*scale,cy+5*scale,11,gold)
                        region(card.edit_action,cx+card_w-38*scale,cy,38*scale,30*scale)
                    end
                else
                    text_at(clip(card.label,math.max(6,math.floor((card_w-26*scale)/(7*scale)))),cx+4*scale,cy+7*scale,12,card.available and white or muted)
                    badge(card.passive_icon,cx+card_w-23*scale,cy+4*scale,18*scale)
                end
                region(card.action,cx,cy,card_w,card_h,card.can_select~=false)
            end
            if #(saved.cards or {})==0 then
                text_at(full and 'Create your first owned armor variant.'or 'No saved variants',start+7*scale,
                    full and sy+sh/2-7*scale or sy+11*scale,full and 15 or 12,muted)
            end
            local pagerx=full and sx+sw-128*scale or sx+sw-90*scale
            local pagery=sy+sh-27*scale
            if full then text_at(tostring(saved.page or 1)..'/'..tostring(saved.pages or 1),pagerx-40*scale,pagery+6*scale,12,muted)end
            text_at('<',pagerx+3*scale,pagery+5*scale,15,saved.can_previous and gold or muted)
            text_at('>',pagerx+27*scale,pagery+5*scale,15,saved.can_next and gold or muted)
            region('previous_variants',pagerx,pagery,22*scale,27*scale,saved.can_previous==true)
            region('next_variants',pagerx+24*scale,pagery,22*scale,27*scale,saved.can_next==true)
        end
        if view.open or not section then
            self.capture_regions[#self.capture_regions+1]={x=x,y=y,w=pw,h=ph}
            rect(0,0,430,view.open and 460 or 42,color(12,17,22,245))
            rect(0,0,3,view.open and 460 or 42,gold)
        end
        if not view.open and not section then
            button('toggle',(view.title or 'ARMOR VARIANTS')..'  /  Transmog',10,6,410)
        elseif view.open then
            text(view.title or 'ARMOR VARIANTS',16,427,24,gold)
            button('toggle','Close',344,420,72)
            text(clip(editor.label,39),16,395,18)
            text(editor.dirty and 'UNSAVED DRAFT' or 'SAVED '..tostring(editor.saved_count or 0),16,376,12,muted)
            button('new_variant','New',16,338,100,editor.can_new == true)
            button('duplicate_variant','Duplicate',126,338,138,editor.can_duplicate == true)
            button('discard_variant','Discard',274,338,140,editor.can_discard == true)
            button('appearance','Look',16,296,118,true,view.tab=='appearance')
            button('stats','Base stats',144,296,134,true,view.tab=='stats')
            button('passive','Perk',288,296,126,true,view.tab=='passive')
            local titles = {appearance='OWNED APPEARANCE',stats='BASE STAT DONOR',
                passive='OWNED EXACT PERK',presets='SAVED VARIANT'}
            text(titles[view.tab] or titles.appearance,16,270,16,gold)
            if view.title=='HELMET VARIANTS'then button('presets','Saved',316,262,98,true,view.tab=='presets')end
            button('previous_option','<',16,226,32,editor.can_previous == true)
            button('next_option','>',382,226,32,editor.can_next == true)
            text(clip(editor.choice,34),60,237,16)
            text((editor.index and tostring(editor.index)..' / ' or '')..tostring(editor.count or 0)..
                (view.tab == 'presets' and ' saved' or ' owned choices'),60,218,12,muted)
            if view.tab=='stats'then
                text('BASE',207,195,11,muted);text('PERK',269,195,11,muted);text('TOTAL',344,195,11,gold)
                for index,row in ipairs((editor.stats_summary or {}).rows or {})do
                    local ry=173-(index-1)*21
                    local function number(v)return v~=nil and string.format('%g',v)or '--'end
                    text(row.label,16,ry,14)
                    text(number(row.base),207,ry,14,muted)
                    text(row.bonus and string.format('%+g',row.bonus)or '--',269,ry,14,muted)
                    text(number(row.effective),344,ry,15,row.verified and gold or muted)
                end
                text(clip((editor.stats_summary or {}).note or 'Numeric values not yet verified.',62),16,111,12,muted)
            else
                for row=1,4 do
                    local line=detail_lines[(page-1)*4+row]
                    if line then text(line,16,197-(row-1)*18,14) end
                end
            end
            if pages > 1 and view.tab~='stats'then
                text(page..' / '..pages,296,270,12,muted)
                button('previous_details','<',346,262,30,page>1)
                button('next_details','>',382,262,32,page<pages)
            end
            text(clip(editor.ownership,62),16,99,12,muted)
            button('save_variant','Save variant',16,60,138,editor.can_save == true)
            button('reload','Reload',166,60,102)
            if editor.patch_active then
                button('reset_variant','Reset',280,60,134,true)
            else
                button('apply_variant',view.apply_label or 'Apply variant',280,60,134,editor.can_apply == true)
            end
            text(clip(editor.apply_note or 'Apply unavailable - armor remains unchanged.',62),16,42,12,muted)
            text(clip(view.notice or '',55),16,17,13,view.saved and gold or muted)
        end
        if active_title and title_box then
            stage('draw.active_variant_title')
            local function line(value,limit)return clip(value:gsub('[%c]',' '),limit)end
            local tx,ty,tw,th=title_box.x,title_box.y,title_box.w,title_box.h
            self.active_title_bounds={x=tx,y=ty,w=tw,h=th}
            rect_at(tx,ty,tw,th,color(12,17,22,250))
            rect_at(tx,ty,3*scale,th,gold)
            text_at('MY VARIANT',tx+12*scale,ty+th-17*scale,11,gold)
            text_at(line(active_title.label,math.floor((tw/scale-24)/11)),tx+12*scale,ty+27*scale,21,white)
            local summary='LOOK: '..line(active_title.appearance_label,32)..'   |   BASE: '..line(active_title.stats_label,32)
                ..'   |   PERK: '..line(active_title.passive_label,32)
            text_at(clip(summary,math.floor((tw/scale-24)/6.5)),tx+12*scale,ty+8*scale,12,muted)
            -- Informational only. Native stat/perk panels and Apply remain
            -- outside these bounds and receive no new input capture region.
        end
        self.signature = signature
        stage('draw.complete')
        return true
    end
    return self
end
return M
