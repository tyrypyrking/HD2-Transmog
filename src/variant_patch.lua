-- Reversible independent look / base-weight / exact-native-passive composition.
-- All addresses come from fresh observations or retained private data buffers.
-- No native function calls, code patches, file I/O or ownership changes.
-- bridge.verify(result, request, source_id, target_id, phase) MUST check fresh
-- ownership for plan/apply/readback, and session/identity for rollback/reset.
-- Successful apply proves memory readback only, never rendered appearance.
local M = {}
local layout=VariantLayout or require('src.variant_layout')

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
local function packed32(n)
    assert(integer(n),'invalid uint32')
    local out={};for i=1,4 do out[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(out)
end
local function packed_pointer(n)
    assert(type(n)=='number'and n%1==0 and n>=65536 and n<140737488355328,'invalid private pointer')
    return packed32(n%4294967296)..packed32(math.floor(n/4294967296))
end
local function weights(record,body_type)
    local out,seen={},0
    for _,body in ipairs(record.bodies)do
        if body.type==3 or body.type==body_type then
            for _,piece in ipairs(body.pieces)do
                assert(seen<20,'native stats donor exceeds the verified collection capacity');seen=seen+1
                if piece.kind==0 and piece.weight~=3 then out[#out+1]=piece.weight end
            end
        end
    end
    return out
end
local function weight_bytes(piece,weight)
    assert(weight>=0 and weight<=3 and weight%1==0,'unsupported native weight')
    return piece.bytes:sub(1,16)..packed32(weight)..piece.bytes:sub(21)
end
-- The average getters collect matching-body/Any pieces (first 20), while the
-- class getter additionally selects the contributing Torso slot. Preserve both.
local function composition(source,target,allocate,capabilities)
    -- Uniform donor profiles have the same mathematical mean and torso class
    -- regardless of piece count (float32 summation may differ in low bits).
    -- Keep the look's original body/slot topology intact and use
    -- the donor's weight on every Armor piece. This avoids artificial pieces
    -- and the unproved fourth UI coefficient when the two looks differ.
    local uniform;local donor_counts={}
    for _,body_type in ipairs({0,1})do
        local donor=weights(target,body_type)
        assert(#donor>0,'native stats donor has no armor weights')
        donor_counts[body_type]=#donor
        local torso=false
        for _,body in ipairs(target.bodies)do if body.type==3 or body.type==body_type then
            for _,piece in ipairs(body.pieces)do if piece.kind==0 then
                -- None is not a proved UI coefficient, even though the
                -- gameplay average excludes it. Do not promote it here.
                if piece.weight>2 then uniform=false end
                if piece.slot==2 and piece.weight<=2 then torso=true end
            end end
        end end
        assert(torso,'native stats donor has no contributing torso')
        if uniform==false then break end
        for _,value in ipairs(donor)do
            if uniform==nil then uniform=value elseif uniform~=value then uniform=false;break end
        end
        if uniform==false then break end
    end
    if uniform~=false and uniform~=nil then
        local spans,descriptors={},{};local sequence_preserved=true
        for _,body_type in ipairs({0,1})do
            local count,armor_count,torso=0,0,false
            for _,body in ipairs(source.bodies)do if body.type==3 or body.type==body_type then
                for _,piece in ipairs(body.pieces)do
                    count=count+1
                    if piece.kind==0 then armor_count=armor_count+1 end
                    if piece.kind==0 and piece.slot==2 then torso=true end
                end
            end end
            assert(count<=20 and torso,'uniform look exceeds native collector or has no torso')
            if armor_count~=donor_counts[body_type]then sequence_preserved=false end
        end
        for _,body in ipairs(source.bodies)do
            local pieces={}
            for _,piece in ipairs(body.pieces)do
                pieces[#pieces+1]=piece.kind==0 and weight_bytes(piece,uniform)or piece.bytes
            end
            local raw=table.concat(pieces);local allocation,why=allocate(raw);assert(allocation,why)
            spans[#spans+1]=span(allocation.address,raw,#raw)
            descriptors[#descriptors+1]=body.bytes:sub(1,8)..packed_pointer(allocation.address)..packed32(#pieces)..packed32(0)
        end
        local raw=table.concat(descriptors);local allocation,why=allocate(raw);assert(allocation,why)
        spans[#spans+1]=span(allocation.address,raw,#raw)
        return packed_pointer(allocation.address)..packed32(#descriptors)..packed32(0),spans,
            {uniform_weight=uniform,appearance_topology_preserved=true,
             base_weight_sequence_preserved=sequence_preserved,weight_none=false,stat_only_pieces=false}
    end
    local by={};for _,body in ipairs(source.bodies)do by[body.type]=body end
    assert(by[3]and by[0]and by[1],'complete native body variants required')
    local wanted={[0]=weights(target,0),[1]=weights(target,1)}
    assert(#wanted[0]>0 and #wanted[1]>0,'native stats donor has no armor weights')
    local common_count=0
    for _,p in ipairs(by[3].pieces)do if p.kind==0 then common_count=common_count+1 end end
    local shared=0
    for i=1,math.min(common_count,#wanted[0],#wanted[1])do
        if wanted[0][i]~=wanted[1][i]then break end;shared=i
    end
    local common,moved={},{};local used=0
    for _,p in ipairs(by[3].pieces)do
        if p.kind==0 then
            used=used+1
            if used<=shared then common[#common+1]=weight_bytes(p,wanted[0][used])
            else moved[#moved+1]=p end
        else common[#common+1]=p.bytes end
    end
    local built={[3]=common};local needs_none,needs_null=false,false
    for _,body_type in ipairs({0,1})do
        local pieces={};local next_weight=shared+1
        local source_pieces={};for _,p in ipairs(moved)do source_pieces[#source_pieces+1]=p end
        for _,p in ipairs(by[body_type].pieces)do source_pieces[#source_pieces+1]=p end
        for _,p in ipairs(source_pieces)do
            if p.kind==0 then
                local weight=wanted[body_type][next_weight]
                if weight==nil then weight=3;needs_none=true else next_weight=next_weight+1 end
                pieces[#pieces+1]=weight_bytes(p,weight)
            else pieces[#pieces+1]=p.bytes end
        end
        while next_weight<=#wanted[body_type]do
            needs_null=true
            pieces[#pieces+1]=string.rep('\0',8)..packed32(2)..packed32(0)..packed32(wanted[body_type][next_weight])..string.rep('\0',76)
            next_weight=next_weight+1
        end
        assert(#common+#pieces<=20,'composed body exceeds the verified native collection capacity')
        built[body_type]=pieces
    end
    assert(not needs_none or capabilities.weight_none_render_verified==true,
        'This composition needs a native weight-None rendering check before activation')
    assert(not needs_null or capabilities.null_visual_pieces_verified==true,
        'This composition needs a native stat-only piece rendering check before activation')
    for _,body_type in ipairs({0,1})do
        local expected,actual={},{}
        for _,body in ipairs(target.bodies)do if body.type==3 or body.type==body_type then
            for _,piece in ipairs(body.pieces)do if piece.kind==0 and piece.weight~=3 then
                expected[#expected+1]=piece.slot..':'..piece.weight
            end end
        end end
        for _,kind in ipairs({3,body_type})do for _,raw in ipairs(built[kind])do
            if u32(raw,12)==0 and u32(raw,16)~=3 then actual[#actual+1]=u32(raw,8)..':'..u32(raw,16)end
        end end
        table.sort(expected);table.sort(actual)
        assert(table.concat(expected,',')==table.concat(actual,','),
            'This composition needs the exact slot-preserving rendering trial before activation')
    end
    local spans,body_records={},{}
    for _,body_type in ipairs({3,0,1})do
        local list=built[body_type];local descriptor
        if #list>0 then
            local raw=table.concat(list);local allocation,why=allocate(raw);assert(allocation,why)
            spans[#spans+1]=span(allocation.address,raw,#raw)
            descriptor=packed_pointer(allocation.address)..packed32(#list)..packed32(0)
        else descriptor=string.rep('\0',16)end
        body_records[#body_records+1]=by[body_type].bytes:sub(1,8)..descriptor
    end
    local body_bytes=table.concat(body_records);local body,why=allocate(body_bytes);assert(body,why)
    spans[#spans+1]=span(body.address,body_bytes,#body_bytes)
    return packed_pointer(body.address)..packed32(3)..packed32(0),spans,
        {ordered_weights=wanted,weight_none=needs_none,stat_only_pieces=needs_null}
end
local function exact_composition(source,target,allocate,capabilities,trial)
    local composed=layout.compose(source,target)
    assert(trial or capabilities.explicit_body_render_verified==true,'Explicit body rendering not yet verified')
    assert(trial or not composed.needs_none or capabilities.weight_none_render_verified==true,'Weight-None rendering not yet verified')
    assert(trial or not composed.needs_null or capabilities.null_visual_pieces_verified==true,'Stat-only piece rendering not yet verified')
    local spans,bodies={},{}
    for _,body in ipairs(composed.bodies)do
        local raw=table.concat(body.pieces);local allocation,why=allocate(raw);assert(allocation,why)
        spans[#spans+1]=span(allocation.address,raw,#raw)
        bodies[#bodies+1]=packed32(body.type)..packed32(0)..packed_pointer(allocation.address)..packed32(#body.pieces)..packed32(0)
    end
    local raw=table.concat(bodies);local allocation,why=allocate(raw);assert(allocation,why)
    spans[#spans+1]=span(allocation.address,raw,#raw)
    return packed_pointer(allocation.address)..packed32(#bodies)..packed32(0),spans,
        {ordered_weights=composed.ordered_weights,weight_none=composed.needs_none,
         stat_only_pieces=composed.needs_null,slot_weights_preserved=true,render_trial=trial==true}
end
local function unaffected_kit(raw)
    -- Identity/DLC/set, rarity and category stay native to the carrier.
    -- The three localization hashes belong to the selected appearance.
    return raw:sub(1,12)..raw:sub(25,28)..raw:sub(41,48)
end
local function appearance_labels(record)
    local reference=record.reference
    assert(type(reference)=='table','verified appearance localization reference required')
    for _,field in ipairs({{'name_upper',12},{'name_cased',16},{'description_loc',20}})do
        assert(integer(reference[field[1]])and u32(record.bytes,field[2])==reference[field[1]],
            'appearance localization fields differ from verified kit reference')
    end
    return record.bytes:sub(13,24)
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
        assert(bridge.verify(plan.result,plan.request,plan.source_id,plan.target_id,phase,plan.donors)==true,
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
            passive_source_id=plan.passive_source_id,passive_variant_id=plan.request.passive_variant_id,
            appearance_verified=false,numeric_stats_verified=false,
            base_weight_sequence_preserved=plan.weight_evidence.base_weight_sequence_preserved~=false,
            uniform_weight=plan.weight_evidence.uniform_weight,
            appearance_topology_preserved=plan.weight_evidence.appearance_topology_preserved==true,
            appearance_labels_preserved=true,
            passive_bytes_unchanged=plan.passive_unchanged,render_trial=plan.weight_evidence.render_trial==true,
            weight_none=plan.weight_evidence.weight_none,stat_only_pieces=plan.weight_evidence.stat_only_pieces}
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
            local source_id,target_id,passive_id
            local ids={};for id in pairs(result.catalog)do ids[#ids+1]=id end;table.sort(ids)
            for _,id in ipairs(ids)do
                local kit=result.catalog[id]
                if result.owned[id]==true then
                    if kit.appearance_id==wanted.appearance_id then
                        assert(not source_id,'ambiguous appearance donor');source_id=id
                    end
                    if kit.stats_id==wanted.stats_id then
                        assert(not target_id,'ambiguous native stats donor');target_id=id
                    end
                    if kit.passive_variant_id==wanted.passive_variant_id and not passive_id then passive_id=id end
                end
            end
            assert(source_id,'appearance donor is not currently owned')
            assert(target_id,'base stats donor is not currently owned')
            assert(passive_id,'exact passive donor is not currently owned')
            local source,target=result.records[source_id],result.records[target_id]
            local passive=assert(result.records[passive_id],'passive record unavailable')
            local source_spans=record_spans(source)
            local target_spans=record_spans(target)
            local passive_spans=record_spans(passive)
            local labels=appearance_labels(source)
            assert(wanted.stats_id=='native-stats:'..string.format('%08x',target.item_id),
                'only an identified native stats donor is supported')
            for id,record in pairs(result.records) do
                assert(id==target_id or record.address~=target.address,'target record has an identity alias')
            end
            local spans={}
            for _,list in ipairs({source_spans,target_spans,passive_spans}) do
                for _,observed in ipairs(list) do spans[#spans+1]=observed end
            end
            local donors={source_id,target_id,passive_id}
            assert(bridge.verify(result,wanted,source_id,target_id,'plan',donors)==true,'fresh donor evidence unavailable')
            assert(type(bridge.allocate)=='function','private variant data allocator unavailable')
            local descriptor,private_spans,weight_evidence
            if result.render_trial==true or result.capabilities.explicit_body_render_verified==true then
                descriptor,private_spans,weight_evidence=exact_composition(source,target,bridge.allocate,result.capabilities,result.render_trial==true)
            else
                descriptor,private_spans,weight_evidence=composition(source,target,bridge.allocate,result.capabilities)
            end
            for _,s in ipairs(private_spans)do spans[#spans+1]=s end
            local passive_bytes=passive.bytes:sub(29,32)
            local plan={result=result,request=wanted,source_id=source_id,target_id=target_id,donors=donors,
                passive_source_id=passive_id,passive_unchanged=passive_bytes==target.bytes:sub(29,32),
                weight_evidence=weight_evidence,
                target_address=target.address,spans=spans,
                applied_bytes=target.bytes:sub(1,12)..labels..target.bytes:sub(25,28)..passive_bytes
                    ..source.bytes:sub(33,40)..target.bytes:sub(41,48)..descriptor,ranges={
                    {address=target.address+28,original=target.bytes:sub(29,32),intended=passive_bytes},
                    {address=target.address+32,original=target.bytes:sub(33,40),intended=source.bytes:sub(33,40)},
                    {address=target.address+48,original=target.bytes:sub(49,64),intended=descriptor},
                    {address=target.address+12,original=target.bytes:sub(13,20),intended=labels:sub(1,8)},
                    {address=target.address+20,original=target.bytes:sub(21,24),intended=labels:sub(9,12)},
                }}
            local changed={};for _,r in ipairs(plan.ranges)do if r.original~=r.intended then changed[#changed+1]=r end end;plan.ranges=changed
            for _,range in ipairs(plan.ranges) do
                for _,observed in ipairs(spans) do
                    if observed.address~=target.address then
                        assert(range.address+#range.original<=observed.address or observed.address+observed.size<=range.address,
                            'write range aliases observed data')
                    end
                end
            end
            check(plan,'plan','original')
            return {source_id=source_id,target_id=target_id,passive_source_id=passive_id,request=request_copy(wanted),
                base_weight_sequence_preserved=weight_evidence.base_weight_sequence_preserved~=false,
                uniform_weight=weight_evidence.uniform_weight,
                appearance_topology_preserved=weight_evidence.appearance_topology_preserved==true,
                appearance_labels_preserved=true,
                requires_re_equip=true,render_trial=weight_evidence.render_trial==true,
                weight_none=weight_evidence.weight_none,stat_only_pieces=weight_evidence.stat_only_pieces},plan
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
