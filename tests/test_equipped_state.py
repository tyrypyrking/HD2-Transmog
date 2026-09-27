"""Startup intent is mod-private, bounded, and never inferred from selection."""
from test_runtime import run_lua

FIX=r'''
local S=dofile('src/state.lua');local E=dofile('src/equipped_state.lua')
local request={appearance_id='armor:00000001',stats_id='native-stats:00000002',passive_variant_id='perk-a'}
local files={};local writes=0;local fail=false
local fs={read=function(name)return files[name],files[name]and nil or 'missing'end,
 write_atomic=function(name,value)writes=writes+1;if fail then return nil,'disk unavailable'end;files[name]=value;return true end}
'''


def test_roundtrip_pins_definition_and_normal_carrier_without_ownership_or_addresses():
    run_lua(FIX+r'''
local raw=assert(E.encode(S,'Saved',request));local record=assert(E.decode(S,raw))
local domain=S.new();domain.presets.Saved=request
assert(E.matches(record,domain,'armor:00000001'))
assert(not E.matches(record,domain,'armor:00000002'))
domain.presets.Saved=nil;assert(not E.matches(record,domain,record.target_id))
domain.presets.Saved={appearance_id=request.appearance_id,stats_id=request.stats_id,passive_variant_id='changed'}
assert(not E.matches(record,domain,record.target_id))
assert(not raw:find('0x')and not raw:find('address'))
assert(not E.encode(S,'Saved',{appearance_id='custom:1',stats_id='s',passive_variant_id='p'}))
''')


def test_clear_is_durable_before_new_equipment_and_failed_write_retains_previous_record():
    run_lua(FIX+r'''
local e=E.new(fs,S);assert(e:record()==nil and writes==0)
assert(e:remember('Saved',request));local previous=files['equipped.state']
fail=true;assert(not e:clear()and files['equipped.state']==previous and e:record().label=='Saved')
fail=false;assert(e:clear());assert(E.decode(S,files['equipped.state'])==false)
assert(E.new(fs,S):record()==nil)
''')


def test_corrupt_or_unreadable_record_never_restores_or_gets_silently_overwritten():
    run_lua(FIX+r'''
for _,raw in ipairs({'bad',string.rep('X',4097),'HD2TM_EQUIPPED 9\nnone\n'})do
 files['equipped.state']=raw;local e=E.new(fs,S)
 assert(not e:record()and e:clear()and not e:remember('Saved',request))
 assert(files['equipped.state']==raw)
end
fs.read=function()return nil,'unreadable'end
local e=E.new(fs,S);assert(not e:record()and e:clear()and not e:remember('Saved',request))
''')
