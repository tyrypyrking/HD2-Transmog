"""Provider declarations are data-only and cannot bypass the renderer gate."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zipfile

import pytest
from test_runtime import run_lua

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('appearance_sdk',ROOT/'tools/appearance_sdk.py')
sdk=importlib.util.module_from_spec(spec);spec.loader.exec_module(sdk)
MANIFEST=json.loads((ROOT/'sdk/examples/ceremonial.appearances.json').read_text())


def test_registration_copies_content_is_idempotent_and_never_claims_render_support():
    run_lua("local R=dofile('src/appearance_registry.lua');local m="+sdk.lua(MANIFEST)+'''
local r=R.new();local first=assert(r.register(m))
assert(first.status=='registered_unavailable'and not first.already_registered)
assert(r.register(m).already_registered)
assert(r.capabilities().registration and not r.capabilities().independent_rendering)
local list=r.list('lean');assert(#list==1 and list[1].available==false)
list[1].bodies.lean.package='changed';m.appearances[1].name='changed'
assert(r.list()[1].name=='Ceremonial Armor')
assert(r.list()[1].bodies.lean.package~='changed')
assert(not r.register(m),'changed content reused an existing identity')
assert(#r.list('muscle')==1)
''')


@pytest.mark.parametrize('mutate',[
 lambda m:m.update(api=2),lambda m:m.update(asset_abi=2),lambda m:m.update(armor_id='armor:12345678'),
 lambda m:m.update(id='../other'),lambda m:m.update(version='latest'),
 lambda m:m['appearances'][0].update(passive='Medic'),
 lambda m:m['appearances'][0].update(stats={'armor':150}),
 lambda m:m['appearances'][0].update(bodies={}),
 lambda m:m['appearances'][0]['bodies'].update(heavy=m['appearances'][0]['bodies']['lean']),
 lambda m:m['appearances'][0]['bodies']['lean'].update(package='units/vanilla/body'),
 lambda m:m['appearances'][0]['bodies']['lean'].update(units=[]),
 lambda m:m['appearances'][0]['bodies']['lean'].update(units=['mods/hd2transmog/appearances/other/pack/body']),
 lambda m:m['appearances'][0]['bodies']['lean'].update(units=['mods/hd2transmog/appearances/example/ceremonial/../body']),
 lambda m:m['appearances'][0]['bodies']['lean'].update(address=123456789),
 lambda m:m['appearances'].append(copy.deepcopy(m['appearances'][0])),
])
def test_invalid_or_gameplay_coupled_manifest_rejected(mutate):
    manifest=copy.deepcopy(MANIFEST);mutate(manifest)
    with pytest.raises(ValueError):sdk.validate(manifest)


def test_lua_metatables_and_sparse_arrays_are_rejected():
    run_lua("local R=dofile('src/appearance_registry.lua');local m="+sdk.lua(MANIFEST)+'''
setmetatable(m,{__index=function()error('foreign code')end});assert(not R.validate(m))
setmetatable(m,nil);m.appearances[3]=m.appearances[1];assert(not R.validate(m))
m.appearances[3]=nil;m.appearances[1].bodies.lean.units={function()end};assert(not R.validate(m))
''')


def test_registration_preview_is_deterministic_and_supports_dependency_loading(tmp_path):
    manifest=tmp_path/'appearance.json';manifest.write_text(json.dumps(MANIFEST))
    output=tmp_path/'provider.zip';result=sdk.build(manifest,output)
    first=output.read_bytes();sdk.build(manifest,output);assert(output.read_bytes()==first)
    assert not result['renderable']
    with zipfile.ZipFile(output) as z:
        assert json.loads(z.read('manifest.json'))['Description'].startswith('Experimental registration only')
        assert 'transmog.appearances.json' in z.namelist()
        data=z.read('Addon/9ba626afa44a3aa3.patch_0')
        resources=sdk.archive_entries(data,0,0);assert(len(resources)==1 and resources[0]['type']=='lua')
    script=sdk.entry(MANIFEST)
    run_lua('''
local calls=0
stingray={Application={can_get=function(kind,name)
 assert(kind=='lua'and name=='mods/hd2transmog/foundation');return true end}}
package.preload['mods/hd2transmog/foundation']=function()
 calls=calls+1;HD2Transmog={appearances=dofile('src/appearance_registry.lua').new()};return HD2Transmog end
local result=(function()
'''+script+'''
end)()
assert(calls==1 and result.status=='registered_unavailable')
assert(#HD2Transmog.appearances.list()==1)
''')


def test_unavailable_dependency_never_calls_require():
    run_lua('''
stingray={Application={can_get=function()return false end}}
require=function()error('unavailable module was required')end
local ok,why=pcall(function()
'''+sdk.entry(MANIFEST)+'''
end)
assert(not ok and why:find('requires HD2 Transmog',1,true))
''')


def test_invalid_manifest_does_not_overwrite_existing_output(tmp_path):
    manifest=tmp_path/'invalid.json';manifest.write_text('{}')
    out=tmp_path/'keep.zip';out.write_bytes(b'keep')
    with pytest.raises(ValueError):sdk.build(manifest,out)
    assert out.read_bytes()==b'keep'


def test_provider_names_with_hyphens_cannot_collide_with_underscore_names(tmp_path):
    identifiers=[]
    for provider in ('example/a-b','example/a_b'):
        m=copy.deepcopy(MANIFEST);old=m['id'];m['id']=provider
        for body in m['appearances'][0]['bodies'].values():
            body['package']=body['package'].replace(old,provider)
            body['units']=[p.replace(old,provider)for p in body['units']]
        path=tmp_path/'m.json';path.write_text(json.dumps(m));out=tmp_path/'m.zip';sdk.build(path,out)
        with zipfile.ZipFile(out) as z:identifiers.append(sdk.archive_entries(z.read('Addon/9ba626afa44a3aa3.patch_0'),0,0)[0]['name'])
    assert identifiers[0]!=identifiers[1]


def test_archive_inspection_rejects_truncation_resource_overlap_and_sidecar_overrun():
    from archive import make_archive,resource_hash
    raw=make_archive({resource_hash('mods/test/entry'):b'payload'})
    assert sdk.archive_entries(raw,0,0)
    with pytest.raises(ValueError):sdk.archive_entries(raw[:100],0,0)
    bad=bytearray(raw);struct.pack_into('<Q',bad,104+16,0)
    with pytest.raises(ValueError):sdk.archive_entries(bad,0,0)
    bad=bytearray(raw);struct.pack_into('<I',bad,104+64,1)
    with pytest.raises(ValueError):sdk.archive_entries(bad,0,0)
