-- Reversible, narrow visual experiment. All addresses are supplied by a fresh
-- CatalogProbe observation and retained only in this instance's private state.
-- No native functions, scanning, file I/O, unlocks, or independent perk writes.
-- bridge.verify(result, request, source_id, target_id, phase) MUST check fresh
-- ownership for plan/apply/readback, and session/identity for rollback/reset.
-- Successful apply proves memory readback only, never rendered appearance.
local M = {}

local function u32(s, offset)
    if type(s) ~= 'string' or #s < offset+4 then return nil end
    local a,b,c,d=s:byte(offset+1,offset+4)
    return a+b*256+c*65536+d*16777216
end
local function pointer(s, offset)
    local lo,hi=u32(s,offset),u32(s,offset+4)
    if not hi or hi>=32768 then return nil end
    local value=lo+hi*4294967296
    return value>=65536 and value or nil
end
local function integer(value)
    return type(value)=='number' and value>=0 and value<=4294967295 and value%1==0
end
local function request_copy(request)
    assert(type(request)=='table','variant request required')
    local copy={}
    for _,field in ipairs({'appearance_id','stats_id','passive_variant_id'}) do
        local value=request[field]
        assert(type(value)=='string' and #value>0 and #value<=128 and not value:find('[%c%s]'),'invalid variant identity')
        copy[field]=value
    end
    return copy
end
local function span(address, bytes, size)
    assert(type(address)=='number' and address%1==0 and address>=65536 and address+size<140737488355328,'invalid observation address')
    assert(type(bytes)=='string' and #bytes==size,'incomplete observation bytes')
    return {address=address,bytes=bytes,size=size}
end
local function record_spans(record)
    assert(type(record)=='table' and record.category==0,'armor record required')
    local spans={span(record.address,record.bytes,64)}
    local raw=record.bytes
    assert(integer(record.item_id) and u32(raw,0)==record.item_id and u32(raw,40)==0,'kit identity/category mismatch')
    local bodies=record.bodies
    assert(type(bodies)=='table' and #bodies>=1 and #bodies<=8,'invalid body profile')
    assert(u32(raw,56)==#bodies and u32(raw,60)==0,'body array count mismatch')
    local bodies_at=assert(pointer(raw,48),'body array unavailable')
    local profile,seen_bodies={},{}
    for i,body in ipairs(bodies) do
        assert(type(body)=='table' and integer(body.type) and not seen_bodies[body.type],'duplicate or invalid body type')
        seen_bodies[body.type]=true
        spans[#spans+1]=span(body.address,body.bytes,24)
        assert(body.address==bodies_at+(i-1)*24 and u32(body.bytes,0)==body.type,'body observation mismatch')
        local pieces=body.pieces
        assert(type(pieces)=='table' and #pieces>=1 and #pieces<=64,'invalid piece profile')
        assert(u32(body.bytes,16)==#pieces and u32(body.bytes,20)==0,'piece array count mismatch')
        local pieces_at=assert(pointer(body.bytes,8),'piece array unavailable')
        local seen_pieces={}
        for j,piece in ipairs(pieces) do
            assert(type(piece)=='table' and integer(piece.slot) and integer(piece.kind) and integer(piece.weight),'invalid piece fields')
            local key=body.type..':'..piece.slot..':'..piece.kind
            assert(not seen_pieces[key],'duplicate body/slot/kind profile')
            seen_pieces[key]=true
            spans[#spans+1]=span(piece.address,piece.bytes,96)
            assert(piece.address==pieces_at+(j-1)*96,'piece observation address mismatch')
            assert(u32(piece.bytes,8)==piece.slot and u32(piece.bytes,12)==piece.kind and u32(piece.bytes,16)==piece.weight,'piece observation fields mismatch')
            profile[#profile+1]=key..':'..piece.weight
        end
    end
    table.sort(profile)
    return spans,table.concat(profile,'|')
end
local function mutated_kit(original, source)
    return original:sub(1,32)..source:sub(33,40)..original:sub(41,48)..source:sub(49,64)
end
local function unaffected_kit(raw)
    return raw:sub(1,32)..raw:sub(41,48)
end
local function attributable(current, original, intended)
    if type(current)~='string' or #current~=#original then return false end
    for i=1,#current do
        local byte=current:byte(i)
        if byte~=original:byte(i) and byte~=intended:byte(i) then return false end
    end
    return true
end

function M.new(bridge)
    assert(type(bridge)=='table' and type(bridge.read)=='function' and type(bridge.write)=='function'
        and type(bridge.verify)=='function','read/write/fresh verification bridge required')
    local self={}
    local plans=setmetatable({}, {__mode='k'})
    local active
    local function read(address,size)
        local value=bridge.read(address,size)
        assert(type(value)=='string' and #value==size,'patch evidence unreadable')
        return value
    end
    local function verify(plan,phase)
        assert(bridge.verify(plan.result,plan.request,plan.source_id,plan.target_id,phase)==true,
            'fresh ownership or compatibility verification failed: '..phase)
    end
    local function check(plan,phase,mode)
        verify(plan,phase)
        for _,observed in ipairs(plan.spans) do
            local value=read(observed.address,observed.size)
            if observed.address==plan.target_address and observed.size==64 then
                if mode=='recover' then
                    assert(unaffected_kit(value)==unaffected_kit(observed.bytes),'target identity changed during recovery')
                else
                    assert(value==(mode=='applied' and plan.applied_bytes or observed.bytes),'target kit evidence changed')
                end
            else assert(value==observed.bytes,'source or body/piece evidence changed') end
        end
    end
    local function evidence(plan,status)
        return {status=status,source_id=plan.source_id,target_id=plan.target_id,
            appearance_verified=false,numeric_stats_verified=false,passive_bytes_unchanged=true}
    end
    local function recover(plan,phase)
        local safe,reason=pcall(check,plan,phase,'recover')
        if not safe then return nil,tostring(reason) end
        local errors={}
        for i=#plan.ranges,1,-1 do
            local range=plan.ranges[i]
            if range.attempted then
                local ok,why=pcall(function()
                    local current=read(range.address,#range.original)
                    if current==range.original then return end
                    verify(plan,phase)
                    assert((range.observed==nil or current==range.observed) and attributable(current,range.original,range.intended),
                        'changed range conflicts with retained evidence')
                    -- Conditional restoration must not overwrite an unrelated
                    -- write that arrived after the failed application.
                    assert(read(range.address,#range.original)==current,'range changed before restoration')
                    local wrote,write_result=pcall(bridge.write,range.address,range.original)
                    local readable,after=pcall(read,range.address,#range.original)
                    if readable and attributable(after,range.original,range.intended) then range.observed=after end
                    assert(wrote and write_result==true and readable and after==range.original,'restoration write/readback failed')
                end)
                if not ok then errors[#errors+1]=tostring(why) end
            end
        end
        local complete,why=pcall(check,plan,phase,'original')
        if not complete then errors[#errors+1]=tostring(why) end
        if #errors>0 then return nil,table.concat(errors,'; ') end
        return true,evidence(plan,'original_memory_restored')
    end
    function self:plan(result,request)
        if active then return nil,'an active patch must be reset before planning another' end
        local ok,handle,plan=pcall(function()
            local wanted=request_copy(request)
            assert(type(result)=='table' and type(result.catalog)=='table' and type(result.owned)=='table'
                and type(result.records)=='table','fresh catalog result required')
            assert(result.capabilities and result.capabilities.kit_records_verified==true
                and result.capabilities.ownership_verified==true,'verified kit records and ownership required')
            local source_id,target_id
            for id,kit in pairs(result.catalog) do
                if result.owned[id]==true then
                    if kit.appearance_id==wanted.appearance_id then
                        assert(not source_id,'ambiguous appearance donor');source_id=id
                    end
                    if kit.stats_id==wanted.stats_id and kit.passive_variant_id==wanted.passive_variant_id then
                        assert(not target_id,'ambiguous native stats donor');target_id=id
                    end
                end
            end
            assert(source_id,'appearance donor is not currently owned')
            assert(target_id,'native stats and exact passive must come from one owned donor')
            assert(source_id~=target_id,'requested appearance is already native; no patch needed')
            local source,target=result.records[source_id],result.records[target_id]
            local source_spans,source_profile=record_spans(source)
            local target_spans,target_profile=record_spans(target)
            assert(wanted.stats_id=='native-stats:'..string.format('%08x',target.item_id),
                'only an identified native stats donor is supported')
            assert(source_profile==target_profile,'body/slot/kind/weight profiles differ')
            assert(source.address~=target.address,'source and target alias the same record')
            for id,record in pairs(result.records) do
                assert(id==target_id or record.address~=target.address,'target record has an identity alias')
            end
            local spans={}
            for _,list in ipairs({source_spans,target_spans}) do
                for _,observed in ipairs(list) do spans[#spans+1]=observed end
            end
            local plan={result=result,request=wanted,source_id=source_id,target_id=target_id,
                target_address=target.address,spans=spans,
                applied_bytes=mutated_kit(target.bytes,source.bytes),ranges={
                    {address=target.address+32,original=target.bytes:sub(33,40),intended=source.bytes:sub(33,40)},
                    {address=target.address+48,original=target.bytes:sub(49,64),intended=source.bytes:sub(49,64)},
                }}
            assert(plan.applied_bytes~=target.bytes,'source visual fields already match the target')
            for _,range in ipairs(plan.ranges) do
                for _,observed in ipairs(spans) do
                    if observed.address~=target.address then
                        assert(range.address+#range.original<=observed.address or observed.address+observed.size<=range.address,
                            'write range aliases observed data')
                    end
                end
            end
            check(plan,'plan','original')
            return {source_id=source_id,target_id=target_id,request=request_copy(wanted)},plan
        end)
        if not ok then return nil,tostring(handle) end
        plans[handle]=plan
        return handle
    end
    function self:apply(handle)
        if active then return nil,'an active patch must be reset first' end
        local plan=plans[handle]
        if not plan then return nil,'unknown or consumed patch plan' end
        plans[handle]=nil -- Evidence is single-use, even after a failed attempt.
        local ok,reason=pcall(function()
            check(plan,'apply','original')
            for _,range in ipairs(plan.ranges) do
                verify(plan,'apply')
                assert(read(range.address,#range.original)==range.original,'target changed before write')
                range.attempted=true
                local wrote,write_result=pcall(bridge.write,range.address,range.intended)
                local observed,after=pcall(read,range.address,#range.original)
                if observed then range.observed=after end
                assert(wrote and write_result==true and observed and after==range.intended,'visual write/readback failed')
            end
            check(plan,'readback','applied')
        end)
        if not ok then
            local attempted=false
            for _,range in ipairs(plan.ranges) do if range.attempted then attempted=true end end
            if not attempted then return nil,tostring(reason) end
            active=plan
            local restored,why=recover(plan,'rollback')
            if restored then active=nil;return nil,tostring(reason)..'; rollback verified' end
            return nil,tostring(reason)..'; recovery required: '..tostring(why)
        end
        active=plan
        return true,evidence(plan,'memory_readback_verified')
    end
    function self:reset()
        if not active then return true,{status='no_active_patch'} end
        local restored,why=recover(active,'reset')
        if restored then active=nil end
        return restored,why
    end
    function self:is_active()
        if not active then return false end
        local ok,reason=pcall(check,active,'readback','applied')
        if not ok then return nil,'retained patch requires attention: '..tostring(reason) end
        return true,evidence(active,'memory_readback_verified')
    end
    return self
end
return M
