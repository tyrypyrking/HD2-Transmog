#!/usr/bin/env python3
"""Inspect legacy replacers and package data-only Transmog provider declarations.

Never installs assets or rewrites opaque unit/texture payloads. Rendering is a
separate runtime capability; a valid provider is not proof of render support.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/BingusSharedLoader/scripts'))
from archive import resource_hash
from build_addon import build_addon

TYPES={resource_hash(name):name for name in ('unit','bones','material','texture','package','lua','physics','mesh')}
MAX_MAIN=64*1024*1024

def path_ok(name):
    p=PurePosixPath(name)
    return bool(name) and '\\' not in name and not p.is_absolute() and '..' not in p.parts and '\0' not in name

def lua(value):
    if isinstance(value,str):return '"'+''.join(f'\\{byte:03d}' for byte in value.encode())+'"'
    if value is True:return 'true'
    if value is False:return 'false'
    if value is None:return 'nil'
    if isinstance(value,int):return str(value)
    if isinstance(value,list):return '{'+','.join(map(lua,value))+'}'
    if isinstance(value,dict):return '{'+','.join('['+lua(k)+']='+lua(v)for k,v in sorted(value.items()))+'}'
    raise ValueError('Manifest contains unsupported JSON data')

def validate(manifest):
    script="local R=dofile('src/appearance_registry.lua');local v,e=R.validate("+lua(manifest)+");if not v then io.stderr:write(e);os.exit(1)end"
    result=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=10)
    if result.returncode:raise ValueError(result.stderr.strip()or 'Manifest validation failed')

def archive_entries(raw,stream_size,gpu_size):
    if len(raw)<72:raise ValueError('Truncated archive header')
    magic,types,count=struct.unpack_from('<III',raw)
    if magic!=0xf0000011 or not 1<=types<=256 or not 1<=count<=16384:raise ValueError('Unsupported archive header')
    table=72+32*types;end=table+80*count
    if end>len(raw):raise ValueError('Truncated resource table')
    declared={}
    for i in range(types):
        row=struct.unpack_from('<IIQIIII',raw,72+32*i)
        if row[2] in declared:raise ValueError('Duplicate resource type')
        declared[row[2]]=row[3]
    seen=set();actual={};out=[]
    for i in range(count):
        row=struct.unpack_from('<7Q6I',raw,table+i*80)
        name,kind=row[:2]
        if (name,kind) in seen or kind not in declared:raise ValueError('Duplicate or undeclared resource')
        seen.add((name,kind));actual[kind]=actual.get(kind,0)+1
        for offset,size,bound in zip(row[2:5],row[7:10],(len(raw),stream_size,gpu_size)):
            if size and(offset+size>bound or offset<0):raise ValueError('Resource exceeds archive/sidecar bounds')
        if row[7] and row[2]<end:raise ValueError('Resource overlaps archive directory')
        out.append({'name':f'{name:016x}','type':TYPES.get(kind,f'{kind:016x}'),
                    'type_hash':f'{kind:016x}','main_bytes':row[7],'stream_bytes':row[8],'gpu_bytes':row[9]})
    if actual!=declared:raise ValueError('Resource type counts differ')
    return out

def inspect(path):
    reference=json.loads((ROOT/'reference/current_catalog.json').read_text())
    owners={}
    for kit in reference['kits'].values():
        for body in kit['bodies']:
            for piece in body['pieces']:
                owners.setdefault(piece['path'],set()).add(kit['id'])
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names))or any(not path_ok(n) for n in names):raise ValueError('Ambiguous or unsafe ZIP paths')
        if len(names)>10000:raise ValueError('ZIP entry limit exceeded')
        metadata={}
        if 'manifest.json' in names:
            if z.getinfo('manifest.json').file_size>1024*1024:raise ValueError('Manifest too large')
            metadata=json.loads(z.read('manifest.json'))
        archives=[];identities=set();types={};overrides={}
        for name in names:
            if '.patch_' not in name or not name.rsplit('.patch_',1)[1].isdigit():continue
            info=z.getinfo(name)
            if info.file_size>MAX_MAIN:raise ValueError('Archive inspection bound exceeded')
            sizes=[z.getinfo(name+suffix).file_size if name+suffix in names else 0 for suffix in ('.stream','.gpu_resources')]
            entries=archive_entries(z.read(name),*sizes)
            for entry in entries:
                identities.add((entry['name'],entry['type_hash']));types[entry['type']]=types.get(entry['type'],0)+1
                if entry['type']=='unit'and entry['name']in owners:overrides[entry['name']]=sorted(owners[entry['name']])
            archives.append({'path':name,'resources':entries})
        options=[{'name':o.get('Name'),'choices':len(o.get('SubOptions',[])),'include':o.get('Include',[])}for o in metadata.get('Options',[])]
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return {'source':path.name,'sha256':digest.hexdigest(),
            'name':metadata.get('Name'),'guid':metadata.get('Guid'),'archive_count':len(archives),
            'distinct_resources':len(identities),'resource_types':types,'options':options,
            'stock_unit_overrides':overrides,'archives':archives,'converted':False,
            'migration':'Re-export namespaced visual resources and dependency references; registration alone cannot detach a replacement archive from vanilla armor.'}

def entry(manifest):
    return '''local engine=rawget(_G,'stingray')
local host=rawget(_G,'HD2Transmog')
if not host then
 assert(engine and engine.Application and engine.Application.can_get('lua','mods/hd2transmog/foundation'),
  'This appearance provider requires HD2 Transmog')
 host=require('mods/hd2transmog/foundation')
end
assert(host and host.appearances and host.appearances.api==1,'Transmog appearance API 1 is required')
local result,reason=host.appearances.register('''+lua(manifest)+''')
assert(result,reason)
return result
'''

def build(manifest_path,output):
    manifest=json.loads(manifest_path.read_text());validate(manifest)
    if output.resolve()==manifest_path.resolve():raise ValueError('Output must not overwrite manifest')
    name='mods/hd2transmog/providers/p_'+manifest['id'].encode().hex()
    guid=str(uuid.uuid5(uuid.NAMESPACE_URL,'hd2-transmog-provider:'+manifest['id']))
    # This command intentionally packages registration only. Asset compilation
    # and the native rendering backend remain explicit, separate prerequisites.
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.transmog-provider-',dir=output.parent) as folder:
        temporary=Path(folder)/'provider.zip'
        build_addon(name,entry(manifest).encode(),guid,temporary,manifest['name']+' — Transmog provider preview')
        with zipfile.ZipFile(temporary) as z:files={n:z.read(n)for n in z.namelist()}
        m=json.loads(files['manifest.json']);m['Description']='Experimental registration only; requires HD2 Transmog appearance API 1. Independent rendering is not available yet.'
        files['manifest.json']=(json.dumps(m,indent=2)+'\n').encode()
        files['transmog.appearances.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        files['README.txt']=b'This preview registers cosmetic metadata only. It does not replace vanilla assets and cannot yet render independent armor. Do not publish it as a working appearance mod.\n'
        with zipfile.ZipFile(temporary,'w') as z:
            for name,data in sorted(files.items()):
                info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,data)
        temporary.replace(output)
    return {'output':str(output),'provider':manifest['id'],'kind':'registration_preview','renderable':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    i=commands.add_parser('inspect');i.add_argument('zip',type=Path);i.add_argument('--output',required=True,type=Path)
    v=commands.add_parser('validate');v.add_argument('manifest',type=Path)
    b=commands.add_parser('build-registration');b.add_argument('manifest',type=Path);b.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    try:
        if args.command=='inspect':
            if args.output.resolve()==args.zip.resolve():raise ValueError('Output must not overwrite input ZIP')
            result=inspect(args.zip);args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({k:v for k,v in result.items()if k not in ('archives','stock_unit_overrides','options')},indent=2))
        elif args.command=='validate':validate(json.loads(args.manifest.read_text()));print('Valid API 1 declaration; independent rendering remains unavailable.')
        else:print(json.dumps(build(args.manifest,args.output),indent=2))
    except (ValueError,OSError,zipfile.BadZipFile,KeyError,subprocess.SubprocessError) as e:p.exit(2,str(e)+'\n')
if __name__=='__main__':main()
