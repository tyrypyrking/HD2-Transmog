-- Bundled after State, Platform, Adapter and Panel by tools/build.py.
local MODULE = 'mods/hd2transmog/foundation'
local STATS_FOLLOW_LOOK = false -- Arsenal build option; default keeps independent stats.
local UiLayout=UiLayout or require('src.ui_layout')
local EquippedState=EquippedState or require('src.equipped_state')
if rawget(_G, 'HD2Transmog') then return rawget(_G, 'HD2Transmog') end
local runtime = {version='0.1.2-debug',build='source', status='starting', armor_writes=false,native_hitbox_source='root',automatic_custom_ui=true,profile={frames=0,tick=0,guard=0,draw=0}}
rawset(_G, 'HD2Transmog', runtime)
local loader = rawget(_G, 'CowboyBingusModLoader')
local log
local function report(key, value)
    if log then log:report(key,value)end
end
local ok, failure = pcall(function()
    log=(Diagnostics or require('src.diagnostics')).open(loader)
    report('creator.stats_follow_look',STATS_FOLLOW_LOOK)
    report('startup.begin',true);report('version',runtime.version);report('build',runtime.build)
    report('loader.present',type(loader)=='table')
    report('loader.version',type(loader)=='table'and loader.version or 'unknown')
    report('loader.api',type(loader)=='table'and loader.api or 'unavailable')
    assert(type(loader)=='table' and tonumber(loader.api) and tonumber(loader.api)>=1,
        'Bingus Shared Loader API 1 is required')
    report('loader.compatible',true);report('armor_writes',false)
    if type(loader.modules)=='table'then
        local modules={};for name,value in pairs(loader.modules)do
            if #modules>=64 then break end
            modules[#modules+1]=tostring(name)..':'..tostring(value)
        end
        table.sort(modules);report('loader.modules_at_init',table.concat(modules,','))
    end
    report('runtime.luajit',jit and jit.version or 'unavailable')
    local engine=assert(rawget(_G,'stingray'),'Stingray UI unavailable')
    report('startup.engine',type(engine.Gui)=='table'and 'GUI available'or 'GUI unavailable')
    if AppearanceRegistry then runtime.appearances=AppearanceRegistry.new(report)end
    local fs=Platform.new(loader, engine)
    local debug_bridge=DebugBridge and DebugBridge.new(fs,engine,report)
    local surface=Panel.new(engine)
    local domain=State.new()
    local equipped_state=EquippedState.new(fs,State,report)
    local startup={record=equipped_state:record(),next_sample=0}
    report('restore.intent_present',startup.record~=nil)
    local startup_guard
    local editor=State.editor_new()
    local catalog_result, catalog_adapter, catalog_probe, catalog_failed
    local catalog_resolved,catalog_resolver_frame=false,nil
    local catalog_requested=false
    local ownership_next,ownership_running,ownership_changed=0,false,false
    local armory_probe,armory_probe_written
    local armor_probe,armor_probe_written
    local grid_ui={next_sample=0,thumbnail_verified=false,thumbnail_tested=false}
    local creation,variant_session
    local section=ArmorySection and ArmorySection.new()
    local armory_open,armory_open_pending,armory_open_waiting,armory_open_deadline,armory_open_visible_since
    local patch,patch_plan,patch_key,patch_active,patch_note
    local view={suspended=true,open=false,tab='appearance',notice='Open the Armory to read your owned armor',saved=false}
    local tabs={appearance=true,stats=true,passive=true,presets=true}
    local locked=false
    local function status(message)
        runtime.status=message
        report('status',message)
        local wrote, why=fs.write_atomic('STATUS.txt',message..'\nVersion: '..runtime.version..
            '\nVariant transaction: '..(patch_active and 'active; native rendering requires observation' or 'inactive')..
            '\nStats: donor base weights; selected passive applied by the game\nOwnership source: '..(catalog_result and 'native progression observed' or 'waiting for native catalog')..'\n')
        if not wrote then report('status.write_error',why) end
    end
    local function decode(bytes)
        local tab, payload=bytes:match('^HD2TRANSMOG_UI\t1\n([a-z]+)\n(.*)$')
        if not tab or not tabs[tab] then return nil,'Unsupported or corrupt saved state' end
        local restored,why=State.decode(payload)
        if not restored then return nil,why end
        return {tab=tab,domain=restored}
    end
    local function restore()
        local bytes,why=fs.read('transmog.state')
        if not bytes then
            report('state.load',why or 'unavailable')
            if why~='missing' then locked=true; view.notice='State unreadable - saving is disabled'; report('state.read_error',why) end
            return
        end
        local restored,reason=decode(bytes)
        if not restored then
            locked=true;view.notice='State needs recovery - saving is disabled';report('state.decode_error',reason)
            return
        end
        domain=restored.domain;view.tab=restored.tab;view.saved=true;locked=false
        editor=State.editor_new()
        if catalog_result then State.reconcile_owned(domain,catalog_result.catalog,catalog_result.owned) end
        view.notice='Saved state restored';report('state.restored',true)
    end
    restore()
    local function save(candidate)
        if locked then view.notice='Preserved unreadable state - saving disabled';return end
        local encoded,payload,why=pcall(State.encode,candidate or domain)
        if not encoded or not payload then view.notice='State validation failed'; report('state.encode_error',why or payload);return end
        local bytes='HD2TRANSMOG_UI\t1\n'..view.tab..'\n'..payload
        local wrote,reason=fs.write_atomic('transmog.state',bytes)
        view.saved=wrote==true
        if wrote and candidate then domain=candidate;State.editor_saved(editor) end
        view.notice=wrote and (candidate and 'Variant saved in My variants' or 'State saved') or 'Save failed - previous state retained'
        report('state.saved',wrote or reason)
        return wrote==true
    end
    local adapter, stopped, frame, retries = nil,false,0,0
    local started, next_attempt = fs.now(),0
    local token, previous_down, armed
    local function reset()
        previous_down,armed=nil,nil
    end
    local function update_catalog(resolver_only)
        if not CatalogProbe or catalog_result or catalog_failed then return end
        if not catalog_adapter then
            catalog_adapter=Adapter.new(engine,function(k,v)report('catalog_resolver.'..k,v)end,nil,CatalogCompat,'catalog')
        end
        if not catalog_resolved then
            if catalog_resolver_frame==frame then return end
            catalog_resolver_frame=frame
            catalog_resolved=catalog_adapter:step()=='ready'
            if not catalog_resolved then return end
        end
        -- Signature discovery reads only the game image. Warm it while the
        -- player is elsewhere; live catalog/ownership still requires entry
        -- or the explicit read-only debug request.
        if resolver_only then return end
        if not catalog_probe then
            local bridge=catalog_adapter:data_bridge()
            if Localization then
                local reason;bridge.localize,reason=Localization.bind(bridge)
                if reason then report('localization.unavailable',reason) end
            end
            if CatalogLabels then
                local native_localize=bridge.localize
                bridge.localize=function(key)
                    return (native_localize and native_localize(key))or CatalogLabels.strings[key]
                end
            end
            catalog_probe=CatalogProbe.new(bridge,CatalogData,report)
        end
        local phase,result=catalog_probe:step()
        if phase=='failed' then
            catalog_failed=result;catalog_requested=false;view.notice='Armor catalog unavailable - saved variants retained';report('catalog.failure',result)
        elseif phase=='ready' then
            catalog_result=result
            if CatalogLabels and CatalogData then
                local names={appearance_id={},passive_variant_id={}}
                for _,kit in pairs(CatalogData.kits or {})do
                    if kit.category==0 then
                        names.appearance_id[kit.id]=CatalogLabels.strings[kit.name_cased]
                        local passive=CatalogData.passives[kit.passive_enum]
                        if passive then names.passive_variant_id[passive.variant_id]=CatalogLabels.strings[passive.name_loc]end
                    end
                end
                result.context.variant_labels=names
            end

            result.context.options_revision=0
            ownership_next=fs.now()+2000;ownership_running=false;ownership_changed=false
            catalog_requested=false
            State.reconcile_owned(domain,result.catalog,result.owned)
            local reserve=0;for _ in pairs(result.catalog)do reserve=reserve+1 end
            result.context.variant_capacity=(VariantCards or require('src.variant_cards')).capacity(reserve,true)
            local rows={'HD2TRANSMOG_CATALOG 1','source_commit '..result.source_commit,
                'pe_timestamp '..tostring(catalog_adapter.pe_timestamp),
                'kits '..result.counts.kits,'owned_armors '..result.counts.owned_armors}
            local ids={};for id in pairs(result.catalog)do ids[#ids+1]=id end;table.sort(ids)
            for _,id in ipairs(ids)do
                local v=result.catalog[id]
                local function label(field,value)return (((result.context.labels[field]or{})[value]or value):gsub('[\t\r\n]',' '))end
                rows[#rows+1]=table.concat({'armor',id,result.owned[id] and 'owned' or 'unowned',v.stats_id,v.passive_variant_id,label('appearance_id',id),label('passive_variant_id',v.passive_variant_id)},'\t')
            end
            report('catalog.health','kits='..tostring(result.counts.kits)..',owned_armors='..tostring(result.counts.owned_armors)..',capacity='..tostring(result.context.variant_capacity))
            fs.write_atomic('catalog-observed.txt',table.concat(rows,'\n')..'\n')
            view.notice=tostring(result.counts.owned_armors)..' owned armors ready - create a variant'
            status('CATALOG READY - native armor and ownership verified')
        end
    end
    local stat_ui={}
    local function update_ownership(now)
        if not(catalog_result and type(catalog_result.refresh_ownership)=='function')
            or variant_session and type(variant_session.busy)=='function'and variant_session:busy() then return end
        if not ownership_running and now<ownership_next then return end
        local called,phase,value=pcall(catalog_result.refresh_ownership)
        ownership_running=called and phase=='resolving'
        if ownership_running then return end
        ownership_next=now+2000
        if called and phase=='ready' then
            if value then
                State.reconcile_owned(domain,catalog_result.catalog,catalog_result.owned)
                stat_ui.catalog=nil;stat_ui.next_sample=0;patch_key=nil;patch_plan=nil
                ownership_changed=true
                report('catalog.ownership_refreshed',catalog_result.counts.owned_armors)
            end
        else
            State.reconcile_owned(domain,domain.catalog,nil)
            stat_ui.catalog=nil;patch_key=nil;patch_plan=nil
            view.notice='Ownership could not be refreshed; waiting for fresh evidence.'
            report('catalog.ownership_wait',called and value or phase)
        end
    end
    local function update_base_stats(now)
        if not(catalog_result and ArmorStatResolver and ArmorBaseStats and PlayerCustomizationProbe)
            or domain.ownership_verified~=true
            or catalog_result.capabilities and catalog_result.capabilities.ownership_verified==false then return end
        if not stat_ui.resolver then stat_ui.resolver=ArmorStatResolver.new(catalog_adapter:data_bridge(),report)end
        local phase,evidence=stat_ui.resolver:step()
        if phase~='ready' then
            catalog_result.context.stats_status=phase=='failed'and 'unavailable'or 'loading'
            if phase=='failed'and not stat_ui.reported then stat_ui.reported=true;report('stats.unavailable',evidence)end
            return
        end
        if now<(stat_ui.next_sample or 0)then return end
        stat_ui.next_sample=now+1000
        stat_ui.player=stat_ui.player or PlayerCustomizationProbe.new(catalog_adapter:data_bridge(),CatalogData)
        local player,why=stat_ui.player:sample_body_type()
        local body=player and player.body_type
        if body~=0 and body~=1 then
            catalog_result.context.stats_status='player_unavailable'
            if stat_ui.body_wait~=why then stat_ui.body_wait=why;report('stats.body_wait',why)end
            return
        end
        stat_ui.body_wait=nil
        catalog_result.context.stats_status='ready'
        if stat_ui.body==body and stat_ui.catalog==catalog_result then return end
        assert(evidence.verify(),'Native stat formula changed')
        local groups,reason=ArmorBaseStats.choices(catalog_result,body,evidence.contract);assert(groups,reason)
        for _,group in ipairs(groups)do
            for _,id in ipairs(group.stats_ids)do
                local profile=catalog_result.context.stats_profiles[id]or {}
                profile.base_only=true;profile.base_values_verified=group.verified==true;profile.base_values=group.base_values
                catalog_result.context.stats_profiles[id]=profile
            end
        end
        catalog_result.context.options_revision=(catalog_result.context.options_revision or 0)+1
        stat_ui.body=body;stat_ui.catalog=catalog_result
        report('stats.base_choices',#groups)
    end
    local function refresh_plan()
        if not AppearancePatch or not RuntimeWriter or not catalog_result or patch_active
            or variant_session and variant_session:is_active()then return end
        local request=editor.draft
        local key=request and table.concat({request.appearance_id,request.stats_id,request.passive_variant_id},'|')
        if key==patch_key then return end
        patch_key,patch_plan=key,nil
        if not request then return end
        if not patch then patch=AppearancePatch.new(RuntimeWriter.new(catalog_adapter:data_bridge(),catalog_result))end
        patch_plan,patch_note=patch:plan(catalog_result,request)
        if patch_plan then patch_note='Apply variant, then equip the armor selected under Stats.'
        else report('variant.plan_rejected',patch_note);patch_note='This variant could not be prepared; see diagnostics.' end
    end
    local function queue_native_preview(target)
        if not (target and grid_ui.bridge and grid_ui.bridge.select_kit and catalog_result)then return false end
        local snapshot=grid_ui.bridge:snapshot(catalog_result)
        if not snapshot or not snapshot.identity_mapping_verified then return false end
        local first=target
        if snapshot.selected_kit_id==target then
            local choices={}
            for id,owned in pairs(catalog_result.owned)do if owned and id~=target then choices[#choices+1]=id end end
            table.sort(choices);first=choices[1]or target
        end
        grid_ui.preview={target=target,first=first,phase='queued',deadline=fs.now()+15000}
        return true
    end
    local presentation={revision=0}
    function presentation.restore()
        if not grid_ui.presentation then return true end
        if grid_ui.bridge and grid_ui.bridge.custom_headers then grid_ui.bridge:custom_headers(0,false)end
        grid_ui.snapshot=nil;grid_ui.next_sample=0
        if catalog_result then catalog_result.context.appearance_previews={}end
        if creation then creation:clear()end
        local result=grid_ui.presentation:restore()
        report('presentation.restore',result.phase..':'..tostring(result.error or ''))
        if result.phase=='restored' or result.phase=='retired' then
            grid_ui.presentation=nil;grid_ui.custom_cards=nil;grid_ui.navigation_group=nil;grid_ui.navigation_pending=nil;grid_ui.navigation_cleared=nil;grid_ui.next_sample=0
            return true
        end
        return nil,result.error or result.phase
    end
    function presentation.build()
        assert(NativeGridPresentation and catalog_result and grid_ui.bridge,'Custom presentation is not ready')
        assert(not grid_ui.presentation,'Custom presentation already active')
        local model,why=grid_ui.bridge:inspect_model(catalog_result);assert(model,why)
        local by_kit={};for _,offer in ipairs(model.offers)do if offer.owned then by_kit[offer.kit_id]=offer end end
        local allow_create=grid_ui.screen_kind~='deployment'
        local donor=model.offers[1]
        local card_api=VariantCards or require('src.variant_cards')
        local cards,reason=card_api.build(domain.presets,by_kit,allow_create,donor and donor.kit_id)
        assert(cards,reason)
        -- Reserve space for every currently known Armor unlock, not just the
        -- owned subset, so unlocking armor cannot crowd saved cards out later.
        local reserve=math.max(model.item_count,catalog_result.counts.verified_armors or model.item_count)
        catalog_result.context.variant_capacity=card_api.capacity(reserve,true)
        if #cards==0 then return nil,'No saved variants available',{phase='blocked',error='No saved variants available'}end
        presentation.revision=presentation.revision+1
        local native=grid_ui.bridge:presentation_bridge(catalog_result,tostring(token)..':'..presentation.revision)
        local coordinator=NativeGridPresentation.new(native,{allow_create=allow_create})
        local started=fs.now()
        report('presentation.build.begin',tostring(grid_ui.screen_kind)..':revision='..presentation.revision..':native='..model.item_count..':custom='..#cards..':create='..tostring(allow_create))
        -- Clear releases native thumbnail leases and reconstructs the widgets.
        -- Neither a successful rebuild nor rollback preserves the old sample.
        grid_ui.snapshot=nil;grid_ui.next_sample=0
        catalog_result.context.appearance_previews={}
        if creation then creation:clear()end
        local result=coordinator:attempt(cards)
        report('presentation.build.returned','revision='..presentation.revision..':elapsed_ms='..(fs.now()-started)..':phase='..tostring(result.phase))
        report('presentation.attempt',result.phase..':'..tostring(result.error or ''))
        if result.phase~='active'then return nil,result.error or result.phase,result end
        grid_ui.navigation_group=nil;grid_ui.navigation_pending=nil;grid_ui.navigation_cleared=nil
        grid_ui.presentation=coordinator;grid_ui.custom_cards=cards;grid_ui.custom_expected_count=model.item_count+#cards;grid_ui.next_sample=0
        if creation then
            local label=grid_ui.last_created_label or grid_ui.resume_label
            if not(label and domain.presets[label])then label=cards[1].kind=='variant'and cards[1].label or nil end
            grid_ui.last_created_label=nil
            if label then
            report('presentation.auto_preview',label)
            local shown,why=creation:action{type='select_variant',label=label}
            if not shown then report('creator.preview_unavailable',why)end
            end
        end
        return true
    end
    local function saved_session()
        if variant_session then return variant_session end
        assert(VariantSession and ArmorRefreshBridge and ArmorRefresh,'Variant equipment modules are unavailable')
        assert(not patch_active,'Reset the development preview before selecting a saved variant')
        local player=PlayerCustomizationProbe.new(catalog_adapter:data_bridge(),CatalogData)
        local function preview_saved(request,requires_apply,label,index,widgets_only)
                report('preview.request',table.concat({tostring(grid_ui.screen_kind),tostring(label),tostring(request.appearance_id),tostring(request.stats_id),tostring(request.passive_variant_id),'widgets_only='..tostring(widgets_only)},'|'))
                local observed,why=player:sample()
                report('preview.player',observed and PlayerCustomizationProbe.format(observed)or why)
                for i,card in ipairs(grid_ui.custom_cards or {})do
                    if label and card.label==label then index=i-1;break end
                end
                return grid_ui.bridge:preview_variant_details(request.appearance_id,request.stats_id,request.passive_variant_id,
                    catalog_result,{requires_apply=requires_apply,focus_index=index,widgets_only=widgets_only,verify_appearance=function(id)
                        return variant_session and variant_session:verify_appearance(id)==true
                    end,verify_composition=function(id)
                        return variant_session and variant_session:verify_composition(id)==true
                    end})
        end
        variant_session=VariantSession.new{
            catalog=function()return catalog_result end,
            before_apply=function(background)
                if not background then startup.finished=true end
                return equipped_state:clear()
            end,
            persist_equipped=function(label,request)return equipped_state:remember(label,request)end,
            validate_composition=function(request)return AppearancePatch.compatible(catalog_result,request)end,
            new_patch=function()return AppearancePatch.new(RuntimeWriter.new(catalog_adapter:data_bridge(),catalog_result))end,
            detail_state=function()return grid_ui.bridge:detail_state()end,
            preview=function(id,requires_apply)
                return grid_ui.bridge:preview_details(id,catalog_result,{requires_apply=requires_apply})
            end,
            preview_variant=preview_saved,
            refresh_widgets=function(request,label,index)return preview_saved(request,false,label,index,true)end,
            equipped_feedback=function(request)
                return grid_ui.bridge:equipment_feedback(request.appearance_id,catalog_result)
            end,
            restore_focus=function(id,index)
                if type(index)~='number'or not grid_ui.custom_cards or index<#grid_ui.custom_cards then
                    return nil,'The original armor card changed during Apply.'
                end
                local focused,why=grid_ui.bridge:focus_index(index,id,catalog_result)
                if focused then report('variant.original_focus',id..':'..index)end
                return focused~=nil,why
            end,
            player=function()return player:sample()end,
            new_refresh=function(background)
                local bridge,why
                if background then
                    bridge,why=grid_ui.bridge:player_refresh_bridge(player,catalog_result,catalog_adapter:data_bridge(),startup_guard)
                else bridge,why=ArmorRefreshBridge.new(grid_ui.bridge,player,catalog_result)end
                if not bridge then return nil,why end
                return ArmorRefresh.new(bridge,report)
            end,
            report=report,
        }
        return variant_session
    end
    function presentation.sample(sample,observed)
        if not(grid_ui.presentation and grid_ui.presentation.phase=='active'and observed and grid_ui.custom_cards)then return end
        local w,h=engine.Gui.resolution()
        local prefix={verified=true,clip=UiLayout.resolve(w,h).prefix,headers={},cells={},original_badges={}}
        if grid_ui.bridge.custom_headers then
            local ok,why=grid_ui.bridge:custom_headers(#grid_ui.custom_cards,grid_ui.selected_label~=nil)
            if not ok and grid_ui.header_error~=why then report('presentation.header',why);grid_ui.header_error=why end
        end
        for _,widget in ipairs(observed.widgets or {})do
            local card=widget.logical_index and grid_ui.custom_cards[widget.logical_index+1]
            if card and widget.root_viewport_rect and widget.bound_owned_kit_id==card.kit_id then
                local request=card.request
                local passive=request and catalog_result.context.passive_variants[request.passive_variant_id]
                prefix.cells[#prefix.cells+1]={rect=widget.root_viewport_rect,image_rect=widget.image_viewport_rect,key=card.key,kind=card.kind,label=card.label,
                    passive=passive,selected=grid_ui.selected_label==card.label}
            elseif widget.root_viewport_rect and widget.bound_owned_kit_id then
                local kit=catalog_result.catalog[widget.bound_owned_kit_id]
                local passive=kit and catalog_result.context.passive_variants[kit.passive_variant_id]
                if passive then prefix.original_badges[#prefix.original_badges+1]={rect=widget.root_viewport_rect,
                    image_rect=widget.image_viewport_rect,passive=passive}end
            end
        end
        sample.native_prefix=prefix
    end
    local function creation_flow()
        if creation then return creation end
        assert(VariantWizard and WizardPanel and UiWorkflow,'Creator modules are unavailable')
        creation=UiWorkflow.new(State,VariantWizard,WizardPanel.new(engine),{
            native_picker=true,
            stats_follow_look=STATS_FOLLOW_LOOK,
            now=fs.now,
            report=report,
            allow_create=grid_ui.screen_kind~='deployment',
            current=function()return domain,catalog_result and catalog_result.context or {}end,
            input_scope=function()
                if not(grid_ui.bridge and grid_ui.bridge.phase=='ready')then return false end
                local active,why=grid_ui.bridge:input_scope()
                assert(active~=nil,why)
                return active
            end,
            consume_select=function()
                if not(grid_ui.bridge and grid_ui.bridge.phase=='ready')then return nil,'Native grid is not ready'end
                return grid_ui.bridge:consume_select()
            end,
            begin_creation=function()
                if variant_session then local ok,why=variant_session:browse();if not ok then return nil,why end end
                grid_ui.selected_label=nil
                grid_ui.rebuild_after_creator=grid_ui.presentation~=nil
                return presentation.restore()
            end,
            end_creation=function()
                if grid_ui.rebuild_after_creator then grid_ui.rebuild_after_creator=false;grid_ui.custom_rows_dirty=true end
            end,
            native_navigation_at=function(x,y)
                if variant_session and variant_session:busy()then return false end
                local w,h=engine.Gui.resolution()
                return UiLayout.contains(UiLayout.resolve(w,h).navigation,x,y)
            end,
            should_capture=function(input)
                if grid_ui.rebuild_pending or grid_ui.custom_rows_dirty or grid_ui.navigation_pending then return true end
                if variant_session and variant_session:view().native_override then return true end
                if not(grid_ui.presentation and grid_ui.custom_cards and grid_ui.bridge)then return false end
                if grid_ui.selected_label then return true end
                local w,h=engine.Gui.resolution()
                if input and input.down and UiLayout.contains(UiLayout.resolve(w,h).picker,input.x,input.y)then return true end
                local index=grid_ui.bridge:selection_index()
                if grid_ui.native_browse_index~=nil and index==grid_ui.native_browse_index then return false end
                grid_ui.native_browse_index=nil
                return index==nil or index<#grid_ui.custom_cards
            end,
            browse_look_at=function(x,y)
                if not(grid_ui.presentation and grid_ui.custom_cards)then return nil end
                local snapshot=grid_ui.bridge:snapshot(catalog_result)
                if not(snapshot and snapshot.kind==4 and snapshot.identity_mapping_verified)then return nil end
                local w,h=engine.Gui.resolution()
                if not UiLayout.contains(UiLayout.resolve(w,h).picker,x,y)then return nil end
                for _,widget in ipairs(snapshot.widgets)do
                    local r=widget.root_viewport_rect
                    if widget.logical_index and widget.logical_index>=#grid_ui.custom_cards
                        and widget.bound_owned_kit_id and r and x>=r.x and y>=r.y and x<r.x+r.w and y<r.y+r.h then
                        return widget.bound_owned_kit_id,widget.logical_index
                    end
                end
            end,
            preview_native_look=function(id,index)
                if type(index)~='number'or index%1~=0 or not grid_ui.custom_cards
                    or index<#grid_ui.custom_cards then return nil,'The original armor card changed.'end
                -- Capture Apply for every original card while duplicate offers
                -- exist. The game's ordinary Apply handler highlights the first
                -- matching offer, which can be a custom prefix card.
                local ok,why=saved_session():browse(id,fs.now(),index);if not ok then return nil,why end
                grid_ui.selected_label=nil;grid_ui.resume_label=nil;grid_ui.native_browse_index=index;grid_ui.next_sample=0
                return true
            end,
            preview_look=function(id)
                if not(grid_ui.bridge and catalog_result)then return nil,'Owned look preview is not ready'end
                local kit=catalog_result.catalog[id]
                if not kit then for _,entry in pairs(catalog_result.catalog)do
                    if entry.appearance_id==id then kit=entry;break end
                end end
                if not kit then return nil,'Owned look preview is not ready'end
                local result,reason=grid_ui.bridge:preview_variant_details(id,kit.stats_id,kit.passive_variant_id,catalog_result,{
                    verify_appearance=function(look)return variant_session and variant_session:verify_appearance(look)==true end,
                    verify_composition=function(look)return variant_session and variant_session:verify_composition(look)==true end})
                return result~=nil,reason
            end,
            look_at=function(x,y)
                if runtime.native_hitbox_source~='root' and runtime.native_hitbox_source~='image'then return nil end
                local snapshot=grid_ui.bridge and grid_ui.bridge:snapshot(catalog_result)
                if not(snapshot and snapshot.identity_mapping_verified)then return nil end
                for _,widget in ipairs(snapshot.widgets)do
                    local r=widget[runtime.native_hitbox_source..'_viewport_rect']
                    if widget.bound_owned_kit_id and r and x>=r.x and y>=r.y and x<r.x+r.w and y<r.y+r.h then
                        return widget.bound_owned_kit_id
                    end
                end
            end,
            verify_create=function(tx)
                if not catalog_result then return nil,'Current ownership is unavailable'end
                local capacity=catalog_result.context.variant_capacity
                if type(capacity)~='number'then return nil,'Native variant capacity is unavailable'end
                local count=0;for _ in pairs(tx.candidate.presets)do count=count+1 end
                if count>capacity then return nil,'The saved variant limit is reached.'end
                local request=tx.candidate.presets[tx.label];local donors={}
                if AppearancePatch and AppearancePatch.compatible then
                    local valid,why=AppearancePatch.compatible(catalog_result,request)
                    if not valid then return nil,why end
                end
                for _,field in ipairs({'appearance_id','stats_id','passive_variant_id'})do
                    local selected
                    for id,kit in pairs(catalog_result.catalog)do
                        if catalog_result.owned[id]and kit[field]==request[field]then selected=id;break end
                    end
                    if not selected then return nil,'A chosen component is no longer owned'end
                    donors[#donors+1]=selected
                end
                return catalog_result.verify_owned(donors)==true,'Current ownership changed'
            end,
            persist=function(tx)
                if locked then return nil,'Saved state needs recovery'end
                local bytes='HD2TRANSMOG_UI\t1\n'..view.tab..'\n'..tx.encoded
                local written,why=fs.write_atomic('transmog.state',bytes)
                if not written then return nil,why end
                domain=tx.candidate;report('creator.saved',tx.label)
                return true,domain
            end,
            created=function(label)
                report('creator.created',label);grid_ui.last_created_label=label;grid_ui.custom_rows_dirty=true;grid_ui.rebuild_after_creator=false
            end,
            remove_variant=function(label)
                if grid_ui.screen_kind=='deployment' then return nil,'Remove variants in the ship Armory.'end
                if locked then return nil,'Saved state needs recovery'end
                if label~=grid_ui.selected_label or not domain.presets[label] then return nil,'The selected variant changed.'end
                if variant_session and variant_session:busy()then return nil,'Wait for the armor change to finish.'end
                -- Clone through the state codec; removal never edits equipment or composition.
                local candidate,why=State.decode(State.encode(domain));if not candidate then return nil,why end
                candidate.presets[label]=nil
                local encoded,reason=State.encode(candidate);if not encoded then return nil,reason end
                local written,error=fs.write_atomic('transmog.state','HD2TRANSMOG_UI\t1\n'..view.tab..'\n'..encoded)
                if not written then return nil,error end
                domain.presets=candidate.presets
                local remembered=equipped_state:record()
                if remembered and remembered.label==label then
                    local cleared,why=equipped_state:clear();if not cleared then report('variant.persistence_failed',why)end
                end
                if variant_session then variant_session:browse()end
                grid_ui.selected_label=nil;grid_ui.resume_label=nil;grid_ui.last_created_label=nil
                local restored,why=presentation.restore()
                grid_ui.custom_rows_dirty=restored==true;grid_ui.next_sample=0
                if not restored then
                    report('presentation.remove_restore_failed',why)
                    if section then section:pause('Reopen Armor after removing a variant')end
                end
                report('creator.removed',label)
                return true
            end,
            intent=function(tx)
                if tx.kind~='select_variant'then return false,'Unknown saved variant action'end
                local selected,reason=saved_session():select(tx.label,tx.request,fs.now())
                if not selected then return nil,reason end
                grid_ui.selected_label=tx.label;grid_ui.resume_label=tx.label;grid_ui.native_browse_index=nil;grid_ui.next_sample=0
                return true
            end,
            variant_view=function()
                local state=variant_session and variant_session:view()or {}
                if domain.ownership_verified~=true then state.can_apply=false end
                return state
            end,
            validate_confirm=function(action)
                local native=grid_ui.bridge and grid_ui.bridge:snapshot(catalog_result)
                if not(native and native.kind==4 and native.native_view_mode==0
                    and native.identity_mapping_verified and grid_ui.custom_cards)then return false end
                local index=native.logical_selected_index
                if type(index)~='number'then return false end
                local card=grid_ui.custom_cards[index+1]
                if action.label then return card and card.kind=='variant'and card.label==action.label or false end
                if index<#grid_ui.custom_cards or index~=grid_ui.native_browse_index then return false end
                for _,widget in ipairs(native.widgets or {})do
                    if widget.logical_index==index and widget.bound_owned_kit_id==action.id then return true end
                end
                return false
            end,
            apply_variant=function()return saved_session():apply(fs.now())end,
            controller_confirmed=function(source)report('variant.controller_confirm',source)end,
            notice=function(reason)report('creator.notice',reason)end,
        })
        return creation
    end
    local function apply_variant()
        assert(patch and patch_plan and not patch_active,'No verified variant transaction is ready')
        local done,evidence=patch:apply(patch_plan);patch_plan=nil;patch_key=nil
        patch_active=patch:is_active()~=false
        runtime.armor_writes=patch_active
        assert(done,evidence)
        runtime.armor_writes=true
        report('preview.readback',evidence.status);report('preview.source',evidence.source_id);report('preview.target',evidence.target_id)
        report('variant.passive',editor.draft and editor.draft.passive_variant_id)
        patch_note='Equip another armor, exit, then equip the Stats armor.'
        if queue_native_preview(evidence.target_id)then patch_note='Selecting the variant in the native preview...'end
        view.notice=patch_note
        status('VARIANT PREPARED - equip another owned armor, exit Armory, reopen and equip the Stats armor')
        return 'Variant data readback verified; native preview still requires observation'
    end
    local function reset_variant()
        assert(patch,'No appearance preview exists')
        grid_ui.preview=nil
        local done,evidence=patch:reset();patch_active=patch:is_active()~=false;patch_key=nil
        assert(done,evidence)
        if evidence.target_id then queue_native_preview(evidence.target_id)end
        runtime.armor_writes=false;patch_note='Original armor restored - refresh the native preview'
        view.notice=patch_note;report('preview.reset',evidence.status)
        status('VARIANT RESET - original armor data restored')
        return patch_note
    end
    -- Test controls share the editor's domain/save/transaction paths. Requests
    -- contain identities and names only; no caller-supplied addresses or code.
    local function require_editor(mutable)
        assert(adapter and adapter.phase=='ready' and adapter:sample(),'Open the native Armory Equipment screen first')
        assert(catalog_result and domain.ownership_verified,'Current owned armor catalog is not ready')
        if mutable then assert(not patch_active,'Reset the current variant before editing') end
        return catalog_result.context or {}
    end
    local function variant_status()
        local lines={'HD2TM_VARIANT_STATUS 1','version '..runtime.version,
            'catalog_ready '..tostring(catalog_result~=nil),
            'active '..tostring(patch_active==true),'label '..tostring(editor.label or ''),
            'dirty '..tostring(editor.dirty==true),'can_apply '..tostring(patch_plan~=nil and not patch_active)}
        lines[#lines+1]='native_thumbnail_binding '..tostring(grid_ui.thumbnail_verified)
        lines[#lines+1]='native_selected_kit '..tostring(grid_ui.snapshot and grid_ui.snapshot.selected_kit_id or '')
        for _,field in ipairs({'appearance_id','stats_id','passive_variant_id'})do
            lines[#lines+1]=field..' '..tostring(editor.draft and editor.draft[field] or '')
        end
        local labels={};for label in pairs(domain.presets)do labels[#labels+1]=label end;table.sort(labels)
        for _,label in ipairs(labels)do lines[#lines+1]='saved '..label end
        lines[#lines+1]='note '..tostring(patch_note or view.notice or ''):gsub('[\r\n]',' ')
        assert(fs.write_atomic('debug-variant-status.txt',table.concat(lines,'\n')..'\n'))
        return 'Current variant and saved-section state recorded'
    end
    local function draft_variant(args)
        require_editor(true)
        assert(not editor.dirty,'Save or discard the current draft first')
        local appearance,stats,passive,label=args:match('^(%S+) (%S+) (%S+)\n([^\r\n]+)$')
        assert(appearance and label,'Expected three stable identities followed by a variant name')
        local candidate=State.new{catalog=domain.catalog,owned=domain.owned}
        local selected,why=State.select(candidate,appearance,stats,passive);assert(selected,why)
        local draft=State.editor_new();draft.draft=candidate.requested
        local named,reason=State.editor_rename(domain,draft,label);assert(named,reason)
        editor=draft;view.open=true;patch_key=nil;refresh_plan()
        variant_status()
        return 'Owned independent choices loaded into the editable draft'
    end
    local function select_variant(args)
        require_editor(true)
        assert(not editor.dirty,'Save or discard the current draft first')
        local chosen=assert(domain.presets[args],'Saved variant was not found')
        editor=State.editor_new()
        editor.draft={appearance_id=chosen.appearance_id,stats_id=chosen.stats_id,passive_variant_id=chosen.passive_variant_id}
        editor.label,editor.source_label,editor.dirty=args,args,false
        view.open=true;patch_key=nil;refresh_plan();variant_status()
        return 'Saved variant selected'
    end
    local function ship_scene()
        local world=engine.Application.main_world()
        if not world then return false end
        local present=false
        for _,candidate in ipairs(engine.Application.worlds()or{})do if candidate==world then present=true end end
        if not present then return false end
        for _,hash in ipairs({'be0be6b1875a4a66','ce2566805c9e893a','3b9bcf29e38da0a6'})do
            local units=engine.World.units_by_resource(world,engine.IdString64.from_hex(hash))
            if type(units)~='table' or #units<1 or #units>16 then return false end
            for _,unit in ipairs(units)do if not engine.Unit.alive(unit)then return false end end
        end
        return true
    end
    startup_guard=function()
        local ok,ready=pcall(ship_scene);return ok and ready==true
    end
    local function restore_on_startup(now)
        if startup.active then
            variant_session:step(now)
            runtime.armor_writes=variant_session:is_active()
            if not variant_session:restoring()then
                startup.active=false;startup.finished=true
                if variant_session.restore_status=='complete'then grid_ui.resume_label=startup.record.label end
                report('restore.result',variant_session.restore_status or 'failed')
            end
            return
        end
        if startup.finished or not startup.record or locked or now<startup.next_sample then return end
        startup.next_sample=now+500
        if not EquippedState.matches(startup.record,domain,startup.record.target_id)then
            startup.finished=true;report('restore.skipped','saved variant removed or changed');return
        end
        if not(catalog_resolved and grid_ui.bridge and grid_ui.bridge.phase=='ready')then return end
        if not startup_guard()or grid_ui.bridge:idle_menu()~=true then return end
        startup.deadline=startup.deadline or now+30000
        if now>startup.deadline then startup.finished=true;report('restore.skipped','startup evidence timed out');return end
        startup.player=startup.player or PlayerCustomizationProbe.new(catalog_adapter:data_bridge(),CatalogData)
        local actor,why=startup.player:sample()
        if not actor or not actor.settled then
            if startup.wait~=why then startup.wait=why;report('restore.wait',why or 'armor is transitioning')end
            return
        end
        if not EquippedState.matches(startup.record,domain,actor.request_armor_id)then
            startup.finished=true;report('restore.skipped','a different ordinary armor is equipped');return
        end
        if not catalog_result then
            if catalog_failed then startup.finished=true;report('restore.skipped',catalog_failed);return end
            update_catalog()
            if not catalog_result then startup.next_sample=now;return end
        end
        local allowed,error=AppearancePatch.compatible(catalog_result,startup.record.request)
        if not allowed then startup.finished=true;report('restore.skipped',error);return end
        local session=saved_session()
        local restored,reason=session:restore(startup.record.label,startup.record.request,now)
        if not restored then startup.finished=true;report('restore.skipped',reason);return end
        startup.active=true;report('restore.started',startup.record.label)
    end
    local function armory_open_status(kind,message)
        report('debug.open_armory.'..kind,message)
        fs.write_atomic('debug-armory-open.txt','HD2TM_ARMORY_OPEN 1\n'..
            debug_bridge.session..'\n'..kind..'\n'..tostring(message):gsub('[\r\n]',' ')..'\n')
    end
    local function poll_debug()
    if debug_bridge then debug_bridge:poll({
            sound_reference=function(args)
                assert(args=='on'or args=='off','Expected on or off')
                assert(not(variant_session and variant_session:busy()),'Wait for the armor change to finish')
                if args=='on'then
                    assert(presentation.restore())
                    if creation then creation:leave();creation=nil end
                    if variant_session then assert(variant_session:cancel_preview())end
                    surface:clear();reset();grid_ui.preview=nil;grid_ui.selected_label=nil
                    grid_ui.custom_rows_dirty=false;grid_ui.rebuild_pending=nil;grid_ui.rebuild_after_creator=false
                    runtime.sound_reference=true
                else
                    runtime.sound_reference=false;grid_ui.initial_attempted=false
                    if section then section:request(fs.now())end
                end
                return args=='on'and 'Native equipment reference: custom UI and capture disabled'
                    or 'Custom UI resumed'
            end,
            variant_status=variant_status,
            icon_probe=function(args)
                if grid_ui.icon_probe then grid_ui.icon_probe:clear();grid_ui.icon_probe=nil end
                if args=='off'then return 'Icon probe cleared'end
                assert(type(args)=='string'and args:match('^%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x$'),'Expected icon resource hash or off')
                local sample,why=adapter and adapter:sample();assert(sample,why or 'Open the Armory first')
                grid_ui.icon_probe=IconProbe.new(engine)
                local shown,reason=grid_ui.icon_probe:draw(sample,args)
                fs.write_atomic('debug-icon-probe.txt',grid_ui.icon_probe:report())
                assert(shown,reason)
                return 'Four owned-material icon tests drawn once; awaiting visual comparison'
            end,
            ui_status=function(args)
                local rows={'HD2TM_UI_STATUS 1'}
                for key,value in pairs(runtime.profile)do rows[#rows+1]=key..'='..tostring(value)end
                if creation and creation.metrics then for key,value in pairs(creation:metrics())do rows[#rows+1]='panel.'..key..'='..tostring(value)end end
                if creation and creation.automation_snapshot then
                    local state=creation:automation_snapshot();local current=state.view
                    local w,h=engine.Gui.resolution();rows[#rows+1]='viewport='..w..','..h
                    rows[#rows+1]='step='..tostring(current.step);rows[#rows+1]='open='..tostring(current.open)
                    rows[#rows+1]='can_create='..tostring(current.can_create);rows[#rows+1]='label='..tostring(current.label or '')
                    rows[#rows+1]='stats_tuple_id='..tostring(current.stats_tuple_id or '')
                    for _,key in ipairs({'native_details','can_apply','apply_pending','variant_phase','apply_notice'})do
                        rows[#rows+1]=key..'='..tostring(current[key]or ''):gsub('[\r\n]',' ')
                    end
                    rows[#rows+1]='selected_variant='..tostring(current.selected_variant and current.selected_variant.label or '')
                    for key,value in pairs(current.selection or {})do rows[#rows+1]='selection.'..key..'='..tostring(value)end
                    local function region(action,r)
                        if not(action and r and type(r.x)=='number'and type(r.y)=='number')then return end
                        local value=tostring(action.id or action.label or ''):gsub('[\t\r\n]',' ')
                        rows[#rows+1]=table.concat({'region',action.type,value,r.x,r.y,r.w,r.h,action.target or '',action.delta or ''},'\t')
                    end
                    for _,r in ipairs(state.regions)do region(r.action,r)end
                    if current.open and current.step==1 and grid_ui.bridge then
                        local native=grid_ui.bridge:snapshot(catalog_result);local picker=UiLayout.resolve(w,h).picker
                        for _,widget in ipairs(native and native.widgets or {})do
                            local r=widget.root_viewport_rect
                            if widget.bound_owned_kit_id and r and UiLayout.contains_rect(picker,r)then
                                region({type='select_look',id=widget.bound_owned_kit_id},r)
                            end
                        end
                    end
                end
                assert(fs.write_atomic('debug-ui-status.txt',table.concat(rows,'\n')..'\n'))
                if args=='reset'then runtime.profile={frames=0,tick=0,guard=0,draw=0}end
                return 'UI timing and retained drawing counters recorded'
            end,
            presentation_trial=function(args)
                require_editor(true)
                if args=='off'then assert(presentation.restore());return 'Native armor list restored'end
                assert(args=='on','Expected on or off')
                assert(presentation.build());creation_flow()
                return 'Custom section constructed once; awaiting visual verification'
            end,
            open_creator=function()
                require_editor(true)
                local snapshot,why=grid_ui.bridge and grid_ui.bridge:snapshot(catalog_result)
                assert(snapshot and snapshot.kind==4 and snapshot.identity_mapping_verified,why or 'Open the native Armor list first')
                local done,reason=creation_flow():action{type='open'};assert(done,reason)
                return 'Creation UI opened; equipped armor is unchanged'
            end,
        draft_variant=draft_variant,
        select_variant=select_variant,
        save_variant=function()
            local context=require_editor(true)
            local handled,notice,candidate=State.editor_action(domain,editor,'save_variant',view.tab,context)
            assert(handled and candidate,notice or 'No editable variant to save')
            assert(save(candidate),'Variant save failed; previous file retained')
            variant_status();return 'Variant saved through the editor persistence path'
        end,
        apply_variant=function()require_editor(false);refresh_plan();local result=apply_variant();variant_status();return result end,
        reset_variant=function()require_editor(false);local result=reset_variant();variant_status();return result end,
        probe_armor=function()
            assert(NativeArmorProbe and catalog_adapter and catalog_adapter.phase=='ready','Native armor evidence not ready')
            armor_probe=NativeArmorProbe.new(catalog_adapter:data_bridge(),report);armor_probe_written=false
            return 'Read-only native armor-consumer inspection scheduled'
        end,
        inspect_player_armor=function()
            assert(PlayerCustomizationProbe and catalog_adapter and catalog_adapter.phase=='ready','Native armor catalog is not ready')
            local probe=PlayerCustomizationProbe.new(catalog_adapter:data_bridge(),CatalogData)
            local result,reason=probe:sample();assert(result,reason)
            assert(fs.write_atomic('debug-player-armor.txt',PlayerCustomizationProbe.format(result)))
            return 'Current local-player armor request and cache recorded without addresses'
        end,
        layout_trial=function(args)
            require_editor(true)
            assert(args=='on' or args=='off','Expected on or off')
            catalog_result.render_trial=args=='on';patch=nil;patch_key=nil;refresh_plan()
            report('variant.unverified_render_trial',catalog_result.render_trial)
            return args=='on' and 'Explicit development trial enabled; rendering is not yet verified' or 'Development trial disabled'
        end,
            inspect_armory_grid=function()
            assert(NativeGrid and adapter and adapter.phase=='ready','Armory UI evidence not ready')
            grid_ui.bridge=grid_ui.bridge or NativeGrid.new(adapter:debug_bridge(),report)
            local result,why=grid_ui.bridge:snapshot(catalog_result);assert(result,why)
            assert(fs.write_atomic('debug-armory-grid.txt',NativeGrid.format(result)))
                return 'Read-only native armor-grid observations recorded'
            end,
            inspect_armory_model=function()
                assert(NativeGridModel and NativeGrid and adapter and adapter.phase=='ready','Armory UI evidence not ready')
                grid_ui.bridge=grid_ui.bridge or NativeGrid.new(adapter:debug_bridge(),report)
                local result,reason=grid_ui.bridge:inspect_model(catalog_result);assert(result,reason)
                assert(fs.write_atomic('debug-armory-model.txt',NativeGridModel.format(result)))
                return 'Read-only native logical rows and group boundaries recorded'
            end,
            inspect_armory_producers=function()
                assert(grid_ui.bridge and grid_ui.bridge.phase=='ready','Native grid evidence is not ready')
                local started,reason=grid_ui.bridge:start_producer_scan();assert(started,reason)
                grid_ui.producer_written=false
                return 'Bounded read-only native list-builder inspection scheduled'
            end,
        inspect_render_types=function()
            assert(surface.material_diagnostic,'Render diagnostics unavailable')
            local values=surface:material_diagnostic()
            local lines={'HD2TM_RENDER_TYPES 1'}
            for _,key in ipairs({'gui_present','material_type','ffi_available','void_pointer_cast'})do
                lines[#lines+1]=key..'='..tostring(values[key])
            end
            assert(fs.write_atomic('debug-render-types.txt',table.concat(lines,'\n')..'\n'))
            if RenderProbe and adapter and adapter.phase=='ready' and surface.material_handle then
                local result,reason=RenderProbe.inspect(engine,surface.material_handle,adapter:debug_bridge())
                fs.write_atomic('debug-material-box.txt',result and RenderProbe.format(result)or tostring(reason)..'\n')
            end
            return 'Existing GUI material types recorded without addresses'
        end,
        inspect_api=function()return debug_bridge:inspect()end,
        inspect_world=function()return debug_bridge:inspect_world()end,
        open_armory=function()
            assert(DebugOpenArmory and adapter and adapter.phase=='ready','Armory UI evidence not ready')
            assert(not armory_open_pending and not armory_open_waiting,'An Armory request is already in progress')
            if not armory_open then armory_open=DebugOpenArmory.new(adapter:debug_bridge(),ship_scene,report)end
            armory_open_pending=true
            armory_open_visible_since=nil
            armory_open_status('pending','Resolving and checking the native Armory transition')
            return 'Native Armory request queued; verify the resulting Equipment screen'
        end,
        read_catalog=function()
            if catalog_result and type(catalog_result.refresh_ownership)=='function'
                and(patch_active or variant_session and variant_session:is_active())then
                ownership_next=0
                return 'Ownership-only refresh scheduled for the visible armor picker'
            end
            assert(not patch_active,'Reset the preview before refreshing ownership')
            catalog_result,catalog_probe,catalog_failed=nil,nil,nil
            patch,patch_key,patch_plan=nil,nil,nil
            State.reconcile_owned(domain,domain.catalog,nil)
            catalog_requested=true
            return 'Read-only catalog observation scheduled'
        end,
        probe_armory=function()
            assert(DebugArmory and adapter and adapter.phase=='ready','Armory UI evidence not ready')
            armory_probe=DebugArmory.new(adapter:debug_bridge(),report);armory_probe_written=false
            return 'Read-only native menu inspection scheduled; no menu call made'
        end,
        inspect_controller=function()
            assert(DebugController and adapter and adapter.phase=='ready','Armory UI evidence not ready')
            local bridge=adapter:debug_bridge();bridge.decode=DebugArmory.decode
            local result,why=DebugController.inspect(bridge);assert(result,why)
            fs.write_atomic('debug-controller.txt',DebugController.format(result))
            return 'Read-only Armory controller metadata recorded'
        end,
        inspect_native_code=function(args)
            assert(DebugArmory and adapter and adapter.phase=='ready','Armory UI evidence not ready')
            local rva,count=args:match('^%s*(%x+)%s+(%d+)%s*$')
            assert(rva,'Expected hexadecimal relative location and decimal byte count')
            local text,why=DebugArmory.inspect_code(adapter:debug_bridge(),tonumber(rva,16),tonumber(count))
            assert(text,why);fs.write_atomic('debug-native-code.txt',text)
            return 'Bounded native instruction semantics recorded; no call made'
        end,
            inspect_native_switch=function(args)
            assert(DebugArmory and adapter and adapter.phase=='ready','Armory UI evidence not ready')
            local rva,count=args:match('^%s*(%x+)%s+(%d+)%s*$')
            assert(rva,'Expected hexadecimal switch table location and decimal count')
            local text,why=DebugArmory.inspect_switch(adapter:debug_bridge(),tonumber(rva,16),tonumber(count))
            assert(text,why);fs.write_atomic('debug-native-switch.txt',text)
                return 'Validated native switch selectors recorded; no call made'
            end,
            inspect_native_callee=function(args)
                assert(DebugArmory and adapter and adapter.phase=='ready','Native UI evidence not ready')
                local site,count=args:match('^%s*(%x+)%s+(%d+)%s*$');assert(site,'Expected callsite RVA and byte count')
                local result,reason=DebugArmory.inspect_callee(adapter:debug_bridge(),tonumber(site,16),tonumber(count))
                assert(result,reason);assert(fs.write_atomic('debug-native-callee.txt',result))
                return 'Verified direct-call target inspected read-only; no native call made'
            end,
    }) end
    end
    local function tick()
        frame=frame+1
        local now=fs.now()
        if now-started<15000 or now<next_attempt then return end
        if grid_ui.capture_latched and grid_ui.bridge and grid_ui.bridge.phase=='ready' then
            -- Keep ownership through release, including leaving the menu or
            -- moving outside the overlay. This path never dereferences its grid.
            local held=fs.sample_input()
            local consumed,reason=grid_ui.bridge:consume_select()
            if held and not held.down then grid_ui.capture_latched=false end
            if not consumed then report('grid.consume_error',reason);surface:clear();reset();return end
        end
        local catalog_stepped=false
        poll_debug()
        if runtime.sound_reference then return end
        if armory_open_pending then
            local passed,phase,reason=pcall(function()return armory_open:step()end)
            if not passed or phase=='failed' then
                armory_open_pending=false;armory_open_status('error',reason or phase)
            elseif phase=='ready' then
                armory_open_pending=false
                local called,done,why=pcall(function()return armory_open:open()end)
                if called and done then
                    armory_open_waiting=true;armory_open_deadline=now+45000
                    armory_open_status('pending','Native transition sent; awaiting the visible Armory Equipment view')
                else armory_open_status('error',why or done)end
            end
        end
        if armory_probe and not armory_probe_written then
            local phase=armory_probe:step()
            if phase~='resolving' then
                fs.write_atomic('debug-armory.txt',armory_probe:summary());armory_probe_written=true
            end
        end
        if armor_probe and not armor_probe_written then
            local phase=armor_probe:step()
            if phase~='resolving' then
                fs.write_atomic('debug-native-armor.txt',armor_probe:summary());armor_probe_written=true
            end
        end
        if catalog_requested then
            catalog_stepped=true
            local passed,why=pcall(update_catalog)
            if not passed then catalog_failed=tostring(why);catalog_requested=false;report('catalog.failure',why)end
        end
        if not adapter then
            adapter=Adapter.new(engine,report)
            status('RESOLVING - checking current game UI layout')
        end
        if not catalog_stepped then
            local passed,reason=pcall(update_catalog,true)
            if not passed then catalog_failed=tostring(reason);report('catalog.failure',reason)end
        end
        local sample,why=adapter:sample()
        if armory_open_waiting then
            if sample and sample.kind=='armory' then
                armory_open_visible_since=armory_open_visible_since or now
                if now-armory_open_visible_since>=500 then
                    armory_open_waiting=false;armory_open_status('ok','Native Armory Equipment view stably observed')
                end
            else armory_open_visible_since=nil end
            if armory_open_waiting and now>armory_open_deadline then
                armory_open_waiting=false;armory_open_status('error','Native request was sent, but Equipment visibility was not confirmed')
            end
        end
        if adapter.phase=='ready' and not runtime.compat_ready then
            runtime.compat_ready=true;status('READY - open ship Armory Equipment')
        end
        if NativeGrid and adapter.phase=='ready' then
            grid_ui.bridge=grid_ui.bridge or NativeGrid.new(adapter:debug_bridge(),report)
            if grid_ui.bridge.phase=='resolving'or(grid_ui.bridge.producer_status and grid_ui.bridge:producer_status()=='scanning')then
                grid_ui.bridge:step()
            end
            if grid_ui.producer_written==false and grid_ui.bridge.producer_status then
                local phase=grid_ui.bridge:producer_status()
                if phase=='complete'or phase=='failed'then
                    fs.write_atomic('debug-armory-producers.txt',grid_ui.bridge:producer_report());grid_ui.producer_written=true
                end
            end
        end
        local restored,restore_error=pcall(restore_on_startup,now)
        if not restored then
            startup.finished=true;startup.active=false
            if variant_session then variant_session:abandon_restore(restore_error)end
            report('restore.skipped',restore_error)
        end
        if not sample then
            if why and runtime.wait_reason~=why then runtime.wait_reason=why;report('screen.wait',why) end
            surface:clear();reset();grid_ui.preview=nil
            local departed=why=='not ship Armory'or why=='Equipment Armor picker inactive'
            if section then
                if departed then section:observe(now,{armor=false})else section:observe(now,{})end
            end
            if departed and token~=nil then
                if grid_ui.icon_probe then grid_ui.icon_probe:clear();grid_ui.icon_probe=nil end
                token=nil
                if creation then creation:leave()end
                if variant_session then
                    local left,reason=variant_session:leave();if not left then report('variant.leave_failed',reason)end
                end
                grid_ui.presentation=nil;grid_ui.custom_cards=nil;grid_ui.navigation_group=nil;grid_ui.navigation_pending=nil;grid_ui.navigation_cleared=nil;grid_ui.initial_attempted=false;grid_ui.creator_failed=false
                grid_ui.selected_label=nil;grid_ui.native_browse_index=nil
                grid_ui.custom_rows_dirty=false;grid_ui.rebuild_pending=nil;grid_ui.rebuild_after_creator=false
                grid_ui.preview=nil
                if grid_ui.bridge and grid_ui.bridge.release_view then grid_ui.bridge:release_view()end
            elseif creation then creation:clear()end
            grid_ui.snapshot=nil;grid_ui.next_sample=0
            return
        end
        if token~=sample.token then
            ownership_next=0
            if token~=nil then
                if creation then creation:leave()end
                if variant_session then variant_session:leave()end
                grid_ui.presentation=nil;grid_ui.custom_cards=nil;grid_ui.navigation_group=nil;grid_ui.navigation_pending=nil;grid_ui.navigation_cleared=nil;grid_ui.custom_expected_count=nil
                grid_ui.selected_label=nil;grid_ui.native_browse_index=nil
                grid_ui.rebuild_pending=nil;grid_ui.custom_rows_dirty=false;grid_ui.creator_failed=false
            end
            if grid_ui.screen_kind~=sample.kind and creation then creation:leave();creation=nil end
            grid_ui.screen_kind=sample.kind
            surface:clear();reset();token=sample.token;report('screen.detected',sample.kind)
            if sample.anchor then
                report('screen.anchor',table.concat({sample.anchor.x,sample.anchor.y,sample.anchor.w,sample.anchor.h},','))
            end
            if not patch_active and not(variant_session and variant_session:is_active())then
                catalog_result,catalog_probe,catalog_failed=nil,nil,nil
                patch,patch_key,patch_plan=nil,nil,nil
                variant_session=nil
                State.reconcile_owned(domain,domain.catalog,nil)
            end
        end
        local catalog_ok,catalog_why=true,nil
        if not catalog_stepped then catalog_ok,catalog_why=pcall(update_catalog)end
        if not catalog_ok and not catalog_failed then catalog_failed=tostring(catalog_why);report('catalog.failure',catalog_failed) end
        update_ownership(now)
        if catalog_result and grid_ui.bridge and grid_ui.bridge.phase=='ready' then
            if grid_ui.presentation or now>=grid_ui.next_sample then
                grid_ui.next_sample=now+100
                local observed,reason=grid_ui.bridge:snapshot(catalog_result)
                grid_ui.snapshot=observed
                local lifecycle=grid_ui.presentation and observed and grid_ui.presentation.status and grid_ui.presentation:status()
                if grid_ui.presentation and observed and(observed.kind~=4 or observed.native_view_mode~=0
                    or observed.item_count~=grid_ui.custom_expected_count or lifecycle and lifecycle.phase=='retired')then
                    local retirement=observed.kind~=4 and 'category changed'
                        or observed.native_view_mode~=0 and 'view mode changed'
                        or observed.item_count~=grid_ui.custom_expected_count and 'item count changed'
                        or lifecycle and lifecycle.error or 'native model changed'
                    report('presentation.retired',retirement..':screen='..tostring(grid_ui.screen_kind)
                        ..':kind='..tostring(observed.kind)..':mode='..tostring(observed.native_view_mode)
                        ..':items='..tostring(observed.item_count)..':expected='..tostring(grid_ui.custom_expected_count)
                        ..':revision='..presentation.revision)
                    grid_ui.presentation=nil;grid_ui.custom_cards=nil;grid_ui.navigation_group=nil;grid_ui.navigation_pending=nil;grid_ui.navigation_cleared=nil;grid_ui.custom_expected_count=nil
                    grid_ui.selected_label=nil;grid_ui.native_browse_index=nil
                    if creation then creation:leave()end
                    if variant_session then
                        local left,reason=variant_session:leave();if not left then report('variant.leave_failed',reason)end
                    end
                    if section then section:invalidate(now,'Native Armor list rebuilt')end
                end
                if observed then
                    local armor=observed.kind==4 and observed.native_view_mode==0
                    if grid_ui.was_armor and not armor and variant_session then variant_session:leave()end
                    grid_ui.was_armor=armor
                end
                local context=catalog_result.context
                context.current_kit_id=observed and observed.identity_mapping_verified and observed.selected_kit_id or nil
                context.appearance_previews=observed and observed.appearance_previews or {}
                for _,preview in pairs(context.appearance_previews)do preview.native_handle_verified=grid_ui.thumbnail_verified end
                if not observed and runtime.grid_wait~=reason then runtime.grid_wait=reason;report('grid.wait',reason)end
                if observed and runtime.grid_wait then
                    report('grid.recovered',runtime.grid_wait);runtime.grid_wait=nil
                end
            end
            -- The previous native-resize experiment is intentionally removed.
            -- New custom rows must use the verified list model, never a repeated
            -- move/restore cycle when a transformed child becomes clipped.
            local pending=grid_ui.preview
            if pending then
                if now>pending.deadline then
                    grid_ui.preview=nil;report('variant.native_preview_error','native selection was not observed before deadline')
                    view.notice='Select the Stats armor to inspect this variant.'
                elseif pending.phase=='queued' then
                    local selected,reason=grid_ui.bridge:select_kit(pending.first,catalog_result)
                    if selected then pending.phase='waiting';grid_ui.next_sample=0
                    else grid_ui.preview=nil;report('variant.native_preview_error',reason);view.notice='Select the Stats armor to inspect this variant.'end
                elseif grid_ui.snapshot and grid_ui.snapshot.selected_kit_id==pending.first then
                    if pending.first~=pending.target then pending.first=pending.target;pending.phase='queued'
                    else
                        grid_ui.preview=nil;patch_note=patch_active and 'Use the native Apply button to equip this variant.'or 'Original armor selected in the native preview.'
                        view.notice=patch_note;report('variant.native_preview',pending.target)
                    end
                end
            end
        end
        view.editor=State.editor_view(domain,editor,view.tab,catalog_result and catalog_result.context or {})
        view.active_variant=nil
        if patch_active and editor.draft and grid_ui.snapshot and grid_ui.snapshot.identity_mapping_verified
            and grid_ui.snapshot.selected_kit_id=='armor:'..editor.draft.stats_id:gsub('^native%-stats:','') then
            view.active_variant={label=editor.label,appearance_label=view.editor.appearance_label,
                stats_label=view.editor.stats_label,passive_label=view.editor.passive_label}
        end
        refresh_plan()
        view.editor.can_apply=patch_plan~=nil and not patch_active
        view.editor.patch_active=patch_active==true
        view.editor.apply_note=patch_note
        if patch_active then
            for _,key in ipairs({'can_new','can_duplicate','can_discard','can_previous','can_next','can_save'})do
                view.editor[key]=false
            end
        end
        if not stat_ui.disabled then
            local verified,reason=pcall(update_base_stats,now)
            if not verified then
                if catalog_result then catalog_result.context.stats_status='unavailable'end
                if stat_ui.last_error~=reason then report('stats.unavailable',reason);stat_ui.last_error=reason end
            end
        end
        -- C/Z category changes are native navigation, independent of mouse clicks.
        -- Adopt the new row before stepping a queued preview of the old variant.
        local observed=grid_ui.snapshot
        if creation and grid_ui.presentation and grid_ui.custom_cards and observed
            and observed.identity_mapping_verified and not creation:is_open()
            and type(observed.logical_selected_group)=='number' then
            local group=observed.logical_selected_group
            if grid_ui.navigation_group~=nil and group~=grid_ui.navigation_group then grid_ui.navigation_pending=true;grid_ui.navigation_cleared=nil end
            grid_ui.navigation_group=group
            if grid_ui.navigation_pending and not(variant_session and variant_session:busy())then
                local index=observed.logical_selected_index
                local card=index and grid_ui.custom_cards[index+1]
                local id
                if index and index>=#grid_ui.custom_cards then
                    for _,widget in ipairs(observed.widgets or {})do
                        if widget.logical_index==index and widget.bound_owned_kit_id then id=widget.bound_owned_kit_id;break end
                    end
                end
                if not grid_ui.navigation_cleared then
                    local ready=not variant_session or variant_session:cancel_preview()
                    if ready then
                        creation:clear_selected_variant()
                        grid_ui.selected_label=nil;grid_ui.resume_label=nil;grid_ui.native_browse_index=nil
                        grid_ui.navigation_cleared=true
                    end
                end
                if grid_ui.navigation_cleared and (card or id)then
                    local ok,why=true,nil
                    if card and card.kind=='variant' then ok,why=creation:action{type='select_variant',label=card.label}
                    elseif id then ok,why=creation:action{type='select_native_look',id=id,index=index}end
                    grid_ui.navigation_pending=nil;grid_ui.navigation_cleared=nil
                    if not ok then report('variant.navigation_unavailable',why)end
                end
            end
        end
        if variant_session and grid_ui.snapshot and grid_ui.snapshot.kind==4 and grid_ui.snapshot.identity_mapping_verified then
            variant_session:step(now)
            runtime.armor_writes=variant_session:is_active()or patch_active==true
        end
        local input=fs.sample_input()
        if not input then surface:clear();reset();return end
        local armor_visible=grid_ui.snapshot and grid_ui.snapshot.kind==4 and grid_ui.snapshot.native_view_mode==0
            and grid_ui.snapshot.identity_mapping_verified
        -- D-pad/stick navigation can change cards without changing category.
        -- Adopt that native focus before A is allowed to confirm a variant.
        if input.controller_source and creation and armor_visible and grid_ui.presentation
            and grid_ui.custom_cards and not creation:is_open()
            and not(variant_session and (variant_session:busy()or variant_session:view().apply_pending))then
            local index=grid_ui.snapshot.logical_selected_index
            local card=type(index)=='number'and grid_ui.custom_cards[index+1]
            local action
            if card and card.kind=='variant'and grid_ui.selected_label~=card.label then
                action={type='select_variant',label=card.label}
            elseif type(index)=='number'and index>=#grid_ui.custom_cards and grid_ui.native_browse_index~=index then
                for _,widget in ipairs(grid_ui.snapshot.widgets or {})do
                    if widget.logical_index==index and widget.bound_owned_kit_id then
                        action={type='select_native_look',id=widget.bound_owned_kit_id,index=index};break
                    end
                end
            end
            if action then
                local ready,why=true,nil
                if variant_session then ready,why=variant_session:cancel_preview()end
                if ready then
                    creation:clear_selected_variant()
                    ready,why=creation:action(action)
                end
                if not ready then report('variant.controller_selection',why)end
            elseif card and card.kind~='variant'and (grid_ui.selected_label
                or variant_session and variant_session:view().native_override)then
                if not variant_session or variant_session:cancel_preview()then
                    creation:clear_selected_variant();grid_ui.selected_label=nil;grid_ui.native_browse_index=nil
                end
            end
        end
        if section then
            local observed=grid_ui.snapshot
            local armor
            if observed then armor=observed.kind==4 and observed.native_view_mode==0 end
            section:observe(now,{token=token,armor=armor,ready=armor_visible and catalog_result~=nil})
        end
        if grid_ui.snapshot and(grid_ui.snapshot.kind~=4 or grid_ui.snapshot.native_view_mode~=0)then
            grid_ui.initial_attempted=false;grid_ui.creator_failed=false
        end
        if runtime.automatic_custom_ui and armor_visible and catalog_result
            and(section and section:due(now)or not section and not grid_ui.initial_attempted)
            and not grid_ui.creator_failed and not grid_ui.presentation then
            if section then section:begin(now)end
            grid_ui.initial_attempted=true;creation_flow();grid_ui.custom_rows_dirty=true
        end
        if creation then
            if ownership_changed and not creation:is_open()
                and not(variant_session and type(variant_session.busy)=='function'and variant_session:busy()) then
                local restored,reason=presentation.restore()
                ownership_changed=false
                if restored then
                    grid_ui.custom_rows_dirty=true
                    if section then section:request(now)end
                else
                    report('ownership.presentation_wait',reason)
                    if section then section:pause('Reopen Armor after ownership changed')end
                end
            end
            if grid_ui.custom_rows_dirty and not creation:is_open() then
                grid_ui.custom_rows_dirty=false
                local model,why=grid_ui.bridge:inspect_model(catalog_result)
                if model and model.offers[1]then
                    local selected,reason=grid_ui.bridge:select_kit(model.offers[1].kit_id,catalog_result)
                    if selected then grid_ui.rebuild_pending={deadline=now+2000}
                    elseif section then section:defer(now,reason)
                    else report('presentation.rebuild_failed',reason)end
                elseif section then section:defer(now,why or 'Native list is not ready')end
            elseif grid_ui.rebuild_pending then
                local pending=grid_ui.rebuild_pending
                local observed=grid_ui.bridge:snapshot(catalog_result)
                if observed and observed.scroll==0 and observed.logical_selected_index and observed.logical_selected_index<3 then
                    grid_ui.rebuild_pending=nil
                    local called,rebuilt,reason,result=pcall(presentation.build)
                    if section then section:complete(now,called and(result or {phase=rebuilt and 'active'or 'waiting',error=reason})
                        or {phase='waiting',error=rebuilt,retryable=true})end
                    if not called or not rebuilt then report('presentation.rebuild_failed',called and reason or rebuilt)end
                elseif now>pending.deadline then
                    grid_ui.rebuild_pending=nil
                    if section then section:defer(now,'Native first-row selection is not ready')
                    else report('presentation.rebuild_failed','top selection was not observed')end
                end
            end
            if not(grid_ui.snapshot and grid_ui.snapshot.kind==4 and grid_ui.snapshot.identity_mapping_verified)then
                if grid_ui.snapshot and(grid_ui.snapshot.kind~=4 or grid_ui.snapshot.native_view_mode~=0)then creation:leave()
                else creation:clear()end
                return
            end
            presentation.sample(sample,grid_ui.snapshot)
            local started_draw=os.clock()
            creation:draw(sample,input)
            runtime.profile.draw=runtime.profile.draw+os.clock()-started_draw
            return
        end
        if not runtime.draw_started then runtime.draw_started=true;report('panel.stage','drawing first surface')end
        local shown=surface:draw(sample,view)
        if not shown then reset();return end
        if not runtime.draw_finished then runtime.draw_finished=true;report('panel.stage','first surface completed')end
        if input.down and surface.capture and surface:capture(input.x,input.y)
            and grid_ui.bridge and grid_ui.bridge.phase=='ready' then
            local consumed,reason=grid_ui.bridge:consume_select()
            if not consumed then report('grid.consume_error',reason);reset();return end
            grid_ui.capture_latched=true
        end
        if not runtime.panel_seen then runtime.panel_seen=true;status('UI DRAWN - verify placement and interaction in game') end
        local target=surface:hit(input.x,input.y)
        if previous_down==nil then previous_down=input.down;armed=nil;return end
        if input.down and not previous_down then armed=target end
        if not input.down and previous_down then
            if armed and target==armed then
                if target=='toggle' then view.open=not view.open
                elseif tabs[target] then view.tab=target;view.saved=false;editor.detail_page=1
                elseif target=='save' then save()
                elseif target=='reload' then restore()
                elseif target=='apply_variant' then
                    local done,why=pcall(apply_variant);if not done then view.notice='Preview rejected - see diagnostics';report('preview.error',why)end
                elseif target=='reset_variant' then
                    local done,why=pcall(reset_variant);if not done then view.notice='Reset needs attention - see diagnostics';report('preview.reset_error',why)end
                else
                    local handled,notice,candidate,event=State.editor_action(domain,editor,target,view.tab,catalog_result and catalog_result.context or {})
                    if handled then
                        view.notice=notice or view.notice;view.saved=false
                        if candidate then save(candidate) end
                        if (target=='new_variant' or target=='duplicate_variant') and editor.dirty then view.open=true end
                        if event then
                            local acted,reason=pcall(function()
                                if patch_active then reset_variant() end
                                patch_key=nil;refresh_plan()
                                if event.open_editor then view.open=true
                                else apply_variant();view.open=false end
                            end)
                            if not acted then view.notice='Variant could not be selected - see diagnostics';report('variant.select_error',reason)end
                        end
                    end
                end
                report('ui.action',target)
            end
            armed=nil
        end
        previous_down=input.down
    end
    local previous_update, previous_shutdown=rawget(_G,'update'),rawget(_G,'shutdown')
    local function after(...)
        if not stopped then
            local started_tick=os.clock()
            local passed,reason=pcall(tick)
            runtime.profile.tick=runtime.profile.tick+os.clock()-started_tick;runtime.profile.frames=runtime.profile.frames+1
            if not passed then
                retries=retries+1
                pcall(function() surface:clear() end);reset()
                report('runtime.error',reason);report('frame',frame)
                next_attempt=fs.now()+5000*retries
                if retries>=3 then stopped=true; status('STOPPED - see HD2Transmog.log for compatibility error') end
            end
        end
        return ...
    end
    rawset(_G,'update',function(...)
        if creation then
            local started_guard=os.clock()
            local guarded,ready,reason=pcall(function()return creation:before(fs.sample_input)end)
            runtime.profile.guard=runtime.profile.guard+os.clock()-started_guard
            if not guarded or not ready then
                report('creator.input_error',guarded and reason or ready)
                local failed=creation;creation=nil
                pcall(function()failed:leave()end)
                pcall(presentation.restore)
                grid_ui.custom_rows_dirty=false;grid_ui.rebuild_pending=nil;grid_ui.rebuild_after_creator=false
                grid_ui.creator_failed=true
                if section then section:pause('Native input capture unavailable')end
                status('CREATOR PAUSED - reopen the Armory after input capture recovers')
                return -- Cancel this press once; never repeat a failing guard every frame.
            end
        end
        if previous_update then return after(previous_update(...)) end
        return after()
    end)
    report('startup.hooks_installed',true)
    rawset(_G,'shutdown',function(...)
        stopped=true;pcall(function() surface:clear() end)
        if creation then pcall(function()creation:leave()end)end
        if variant_session then pcall(function()variant_session:shutdown()end)end
        if grid_ui.icon_probe then pcall(function()grid_ui.icon_probe:clear()end)end
        if grid_ui.bridge and grid_ui.bridge.release_view then pcall(function()grid_ui.bridge:release_view()end)end
        if patch_active then
            local restored,reason=pcall(reset_variant);report('shutdown.preview_reset',restored and reason or 'session no longer available')
        end
        report('shutdown',true)
        if log then pcall(function() log:close() end); log=nil end
        if previous_shutdown then return previous_shutdown(...) end
    end)
    status('LOADED - UI initialization scheduled')
end)
if not ok then
    runtime.status='startup_failed';report('startup.error',failure)
    print('[HD2Transmog] '..tostring(failure))
end
return runtime
