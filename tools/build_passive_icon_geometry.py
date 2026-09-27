#!/usr/bin/env python3
"""Compile original installed passive DDS art into material-free Gui rectangles.

Resource identity is catalog icon hash -> material diffuse_map -> same texture
hash. No perk-label/template guessing, executable access or game mutation.
"""
from __future__ import annotations
import argparse
import bisect
import functools
import hashlib
import io
import json
from pathlib import Path
import struct

import lz4.block
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
TEXTURE_TYPE=0xcd4238c6a0c69e32
MATERIAL_TYPE=0xeac0b497876adedf
TEXTURE_ARCHIVE='8bb19e255ed514d5'


def sha(value):return hashlib.sha256(value).hexdigest()


class Bundles:
    """Bounded reader for the existing decompressed bundle index and chunks."""
    def __init__(self,index_path,data_path):
        self.index=Path(index_path).read_bytes();self.root=Path(data_path)
        _,_,_,files,archives=struct.unpack_from('<4sIIII4x',self.index)
        if not(0<files<=100000 and 0<archives<=100000):raise ValueError('bundle index counts')
        self.names=[self.string(struct.unpack_from('<I',self.index,24+archives*24+i*4)[0])for i in range(files)]
        self.archives={}
        for i in range(archives):
            size,name,count,entries=struct.unpack_from('<QIIQ',self.index,24+i*24)
            name=self.string(name)
            if name in (TEXTURE_ARCHIVE,TEXTURE_ARCHIVE+'.gpu_resources',TEXTURE_ARCHIVE+'.stream'):
                rows=[struct.unpack_from('<I4xI3xB',self.index,entries+j*16)for j in range(count)]
                self.archives[name]=(size,rows,[r[0]for r in rows])
    def string(self,offset):return self.index[offset:self.index.index(b'\0',offset)].decode()
    @functools.lru_cache(32)
    def bundle(self,index):
        path=(self.root/self.names[index]).resolve()
        if not path.is_relative_to(self.root.resolve()):raise ValueError('bundle path leaves game data')
        stream=path.open('rb');header=stream.read(32);count=struct.unpack_from('<I',header,8)[0]
        if not 0<count<=100000:raise ValueError('chunk count')
        rows=[struct.unpack('<QQIIBB6x',stream.read(32))for _ in range(count)]
        return stream,rows,[r[0]for r in rows]
    @functools.lru_cache(256)
    def chunk(self,index,number):
        stream,rows,_=self.bundle(index);_,offset,size,packed,kind,_=rows[number]
        if not(0<size<=16777216 and 0<packed<=16777216 and kind in (0,3)):raise ValueError('chunk bounds/type')
        stream.seek(offset);raw=stream.read(packed)
        value=raw if kind==0 else lz4.block.decompress(raw,uncompressed_size=size)
        if len(value)!=size:raise ValueError('short decompressed chunk')
        return value
    def read(self,name,offset,size):
        total,rows,offsets=self.archives[name]
        if offset<0 or size<0 or offset+size>total or size>16777216:raise ValueError('archive read bounds')
        out=[]
        while size:
            index=bisect.bisect_right(offsets,offset)-1
            if index<0:raise ValueError('unmapped archive span')
            archive_offset,bundle_offset,bundle_index=rows[index]
            end=offsets[index+1]if index+1<len(rows)else total
            take=min(size,end-offset);skip=offset-archive_offset
            _,chunks,starts=self.bundle(bundle_index);number=bisect.bisect_left(starts,bundle_offset)
            if number>=len(starts)or starts[number]!=bundle_offset:raise ValueError('chunk mapping')
            while skip>=chunks[number][2]:skip-=chunks[number][2];number+=1
            left=take
            while left:
                raw=self.chunk(bundle_index,number);n=min(left,len(raw)-skip)
                if n<=0:raise ValueError('empty chunk span')
                out.append(raw[skip:skip+n]);left-=n;skip=0;number+=1
            offset+=take;size-=take
        return b''.join(out)


def merged_rectangles(pixels,width,height):
    """Exact non-overlapping cover: merge identical horizontal runs vertically."""
    active={};result=[]
    for y in range(height):
        row=[];x=0
        while x<width:
            color=pixels[y*width+x];end=x+1
            while end<width and pixels[y*width+end]==color:end+=1
            row.append((x,end-x,color));x=end
        following={}
        for key in row:
            rect=active.pop(key,None)
            if rect is None:rect=[key[0],y,key[1],1,key[2]+1]
            else:rect[3]+=1
            following[key]=rect
        result.extend(active.values());active=following
    result.extend(active.values())
    return sorted(result,key=lambda r:(r[1],r[0],r[4]))


def compile_dds(dds,sample=32,colors=8):
    if sample not in (32,48)or not 2<=colors<=16:raise ValueError('bounded icon sampling required')
    if not dds.startswith(b'DDS '):raise ValueError('texture payload is not DDS')
    image=Image.open(io.BytesIO(dds));image.load()
    if image.width!=image.height or image.width<sample or image.width>2048:raise ValueError('icon texture dimensions')
    source=image.convert('RGBA')
    sampled=source.resize((sample,sample),Image.Resampling.LANCZOS)
    indexed=sampled.quantize(colors=colors,method=Image.Quantize.FASTOCTREE,dither=Image.Dither.NONE)
    palette=indexed.getpalette('RGBA');flat=list(indexed.tobytes());used=sorted(set(flat))
    remap={value:i for i,value in enumerate(used)}
    rgba=[palette[i*4:i*4+4]for i in used]
    pixels=[remap[value]for value in flat]
    rectangles=merged_rectangles(pixels,sample,sample)
    if len(rectangles)>1024:raise ValueError('icon rectangle budget exceeded')
    decoded=bytes(source.tobytes())
    approx=indexed.convert('RGBA');error=sum(abs(a-b)for a,b in zip(sampled.tobytes(),approx.tobytes()))/(sample*sample*4)
    return {'source_width':source.width,'source_height':source.height,'sample':sample,
            'palette':rgba,'rectangles':rectangles,'dds_sha256':sha(dds),'decoded_rgba_sha256':sha(decoded),
            'sample_mae':round(error,6)}


def lua(value):
    if isinstance(value,str):return json.dumps(value,ensure_ascii=True)
    if isinstance(value,bool):return 'true'if value else'false'
    if value is None:return'nil'
    if isinstance(value,(int,float)):return repr(value)
    if isinstance(value,list):return'{'+','.join(lua(v)for v in value)+'}'
    return'{'+','.join('['+lua(k)+']='+lua(v)for k,v in value.items())+'}'


def build(args):
    catalog_bytes=args.catalog.read_bytes();catalog=json.loads(catalog_bytes)
    wanted={p['icon']for p in catalog['passives'].values()}
    if not 0<len(wanted)<=64:raise ValueError('passive icon bounds')
    bundle=Bundles(args.index,args.game_data)
    header=bundle.read(TEXTURE_ARCHIVE,0,72);magic,types,count=struct.unpack_from('<III',header)
    if magic!=0xf0000011 or count>100000:raise ValueError('texture archive format')
    rows=bundle.read(TEXTURE_ARCHIVE,72+types*32,count*80);entries={}
    for i in range(count):
        values=struct.unpack_from('<7Q6I',rows,i*80);key=f'{values[0]:016x}'
        if key in wanted and values[1]==TEXTURE_TYPE:
            if key in entries:raise ValueError('duplicate passive texture')
            entries[key]=values
    if set(entries)!=wanted:raise ValueError('not all catalog icon hashes have texture entries')
    icons={};provenance={}
    for key in sorted(wanted):
        material_path=args.material_cache/f'icon-{key}.{MATERIAL_TYPE:016x}.bin'
        material=material_path.read_bytes()
        if len(material)!=160 or struct.unpack_from('<I',material,136)[0]!=0x3aa8b87e or struct.unpack_from('<Q',material,140)[0]!=int(key,16):
            raise ValueError('material diffuse_map does not identify its texture: '+key)
        row=entries[key];main=bundle.read(TEXTURE_ARCHIVE,row[2],row[7])
        if main[192:196]!=b'DDS ':raise ValueError('native DDS header offset changed')
        gpu=bundle.read(TEXTURE_ARCHIVE+'.gpu_resources',row[4],row[9])
        stream=bundle.read(TEXTURE_ARCHIVE+'.stream',row[3],row[8])if row[8]else b''
        # Streamed icons store the complete full-resolution mip chain in the
        # stream resource; GPU data is a separate resident low-resolution chain.
        payload=stream or gpu
        icon=compile_dds(main[192:]+payload,args.sample,args.colors)
        provenance[key]={'material_sha256':sha(material),'texture_header_sha256':sha(main),
                         'gpu_payload_sha256':sha(gpu),'dds_sha256':icon['dds_sha256'],
                         'stream_payload_sha256':sha(stream)if stream else None,
                         'selected_payload':'stream'if stream else'gpu_resources',
                         'decoded_rgba_sha256':icon['decoded_rgba_sha256'],
                         'archive':TEXTURE_ARCHIVE,'main_offset':row[2],'stream_offset':row[3],'gpu_offset':row[4],
                         'main_size':row[7],'stream_size':row[8],'gpu_size':row[9],
                         'source_dimensions':[icon['source_width'],icon['source_height']],
                         'rectangle_count':len(icon['rectangles']),'sample_mae':icon['sample_mae']}
        icons[key]={k:icon[k]for k in ('sample','palette','rectangles','dds_sha256')}
    manifest={'schema_version':1,'mapping':'catalog icon hash -> material diffuse_map -> same texture hash -> original DDS',
              'sample':args.sample,'colors':args.colors,'catalog_sha256':sha(catalog_bytes),
              'bundle_index_sha256':sha(bundle.index),'icons':provenance,'rendering_verified':False}
    args.output.write_text('-- Original native DDS art, sampled into retained rectangles. No material residency.\nreturn '+lua({
        'schema_version':1,'sample':args.sample,'icons':icons,'source':{'catalog_sha256':manifest['catalog_sha256'],
        'bundle_index_sha256':manifest['bundle_index_sha256'],'mapping':manifest['mapping']}})+'\n')
    args.manifest.write_text(json.dumps(manifest,indent=2)+'\n')
    counts=[len(i['rectangles'])for i in icons.values()]
    print(f'Compiled {len(icons)} original icons: {sum(counts)} rectangles, max {max(counts)}, {args.output.stat().st_size} Lua bytes')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,default=ROOT/'reference/current_catalog.json')
    p.add_argument('--index',type=Path,default=ROOT/'.cache/lua-api-reference/bundles-index.bin')
    p.add_argument('--game-data',type=Path,required=True)
    p.add_argument('--material-cache',type=Path,default=ROOT/'.cache/lua-api-reference')
    p.add_argument('--sample',type=int,choices=(32,48),default=32)
    p.add_argument('--colors',type=int,default=8)
    p.add_argument('--output',type=Path,default=ROOT/'src/passive_icon_geometry.lua')
    p.add_argument('--manifest',type=Path,default=ROOT/'reference/passive_icon_geometry_manifest.json')
    build(p.parse_args())


if __name__=='__main__':main()
