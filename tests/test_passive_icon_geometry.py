"""Original archive identity, exact sampled-pixel cover and material-free draw."""
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import subprocess

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('icon_generator',ROOT/'tools/build_passive_icon_geometry.py')
generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)


def reconstruct(rectangles,width,height):
    pixels=[None]*(width*height)
    for x,y,w,h,color in rectangles:
        assert 0<=x<x+w<=width and 0<=y<y+h<=height
        for yy in range(y,y+h):
            for xx in range(x,x+w):
                at=yy*width+xx;assert pixels[at]is None,'overlapping sampled art'
                pixels[at]=color-1
    assert None not in pixels,'sampled art has gaps'
    return pixels


def test_run_merging_is_exact_and_does_not_fill_holes_or_cross_colors():
    rows=[[0,0,1,1,0,0],[0,0,1,1,0,0],[0,1,0,0,1,0],[0,1,0,0,1,0]]
    pixels=sum(rows,[]);rects=generator.merged_rectangles(pixels,6,4)
    assert reconstruct(rects,6,4)==pixels
    assert len(rects)==8
    random.seed(12)
    for _ in range(30):
        pixels=[random.randrange(8)for _ in range(32*32)]
        assert reconstruct(generator.merged_rectangles(pixels,32,32),32,32)==pixels


def test_every_current_native_icon_has_bounded_original_art_and_provenance():
    catalog=json.loads((ROOT/'reference/current_catalog.json').read_text())
    manifest=json.loads((ROOT/'reference/passive_icon_geometry_manifest.json').read_text())
    wanted={p['icon']for p in catalog['passives'].values()}
    assert len(wanted)==29 and set(manifest['icons'])==wanted
    assert manifest['catalog_sha256']==hashlib.sha256((ROOT/'reference/current_catalog.json').read_bytes()).hexdigest()
    assert manifest['sample']==32 and manifest['colors']==8
    for icon in manifest['icons'].values():
        assert 0<icon['rectangle_count']<=330 and icon['sample_mae']<5
        for key in ('material_sha256','texture_header_sha256','dds_sha256','decoded_rgba_sha256'):
            assert len(icon[key])==64
    assert sum(i['selected_payload']=='stream'for i in manifest['icons'].values())==3


def test_available_dds_samples_match_generated_source_hashes_and_art():
    manifest=json.loads((ROOT/'reference/passive_icon_geometry_manifest.json').read_text())
    for key in ('3642b3057d12359e','7c818b04a594d8e5','e5ad658ba8221acf'):
        path=ROOT/'.cache/lua-api-reference'/f'actual-icon-{key}.dds'
        if not path.exists():continue
        icon=generator.compile_dds(path.read_bytes())
        assert icon['dds_sha256']==manifest['icons'][key]['dds_sha256']
        assert icon['decoded_rgba_sha256']==manifest['icons'][key]['decoded_rgba_sha256']
        assert len(icon['rectangles'])==manifest['icons'][key]['rectangle_count']


def run(script):
    value=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=10)
    assert value.returncode==0,value.stdout+value.stderr


def test_lua_geometry_covers_each_sample_exactly():
    run(r'''
local data=dofile('src/passive_icon_geometry.lua');local count=0
for hash,icon in pairs(data.icons)do
 count=count+1;local pixels={};assert(#hash==16 and #icon.palette<=8 and #icon.rectangles<=330)
 for _,r in ipairs(icon.rectangles)do
  assert(icon.palette[r[5]])
  for y=r[2],r[2]+r[4]-1 do for x=r[1],r[1]+r[3]-1 do
   local index=y*icon.sample+x;assert(not pixels[index],'overlap');pixels[index]=true
  end end
 end
 for index=0,icon.sample^2-1 do assert(pixels[index],'gap')end
end
assert(count==29)
''')


def test_draw_uses_only_rects_flips_y_preserves_rgba_and_handles_unknown_hash():
    run(r'''
local M=dofile('src/passive_icon_draw.lua');local draws={}
local engine={Vector2=function(...)return {...}end,Vector3=function(...)return {...}end,Color=function(...)return {...}end,
 Gui={rect=function(gui,position,size,color)draws[#draws+1]={position=position,size=size,color=color}end}}
local data={schema_version=1,icons={['0123456789abcdef']={sample=32,palette={{255,255,255,255},{0,0,0,128},{255,0,0,0}},
 rectangles={{0,0,32,8,1},{0,8,16,24,2},{16,8,16,24,3}}}}}
local d=M.new(engine,data)
assert(d:has('0123456789ABCDEF')and not d:has('ffffffffffffffff'))
local result=assert(d:draw({},'0123456789abcdef',{x=10,y=20,w=64,h=96},7,{255,221,31,128}))
assert(result.rectangles==2 and #draws==2)
assert(draws[1].position[1]==10 and draws[1].position[2]==92 and draws[1].position[3]==7)
assert(draws[1].size[1]==64 and draws[1].size[2]==24)
assert(draws[1].color[1]==128 and draws[1].color[2]==255 and draws[1].color[3]==221 and draws[1].color[4]==31)
assert(draws[2].position[2]==20 and draws[2].size[1]==32 and draws[2].size[2]==72 and draws[2].color[1]==64)
local before=#draws;assert(not d:draw({},'ffffffffffffffff',{x=0,y=0,w=32,h=32},0));assert(#draws==before)
assert(not d:draw({},'0123456789abcdef',{x=0,y=0,w=-1,h=32},0));assert(#draws==before)
''')


def test_live_vector_factory_tables_are_supported_without_material_api():
    run(r'''
local M=dofile('src/passive_icon_draw.lua');local data=dofile('src/passive_icon_geometry.lua')
local function vector()return setmetatable({},{__call=function(_,...)return {...}end})end
local n=0
local engine={Vector2=vector(),Vector3=vector(),Color=function(...)return {...}end,
 Gui={rect=function()n=n+1 end}}
local art=M.new(engine,data)
local result=assert(art:draw({},'7c818b04a594d8e5',{x=0,y=0,w=32,h=32},10))
assert(n==129 and result.rectangles==129)
assert(engine.Gui.bitmap==nil and engine.Material==nil and engine.IdString64==nil)
''')


def test_clip_crops_original_art_without_rescaling_and_rejects_invalid_bounds():
    run(r'''
local M=dofile('src/passive_icon_draw.lua');local draws={}
local engine={Vector2=function(...)return {...}end,Vector3=function(...)return {...}end,Color=function(...)return {...}end,
 Gui={rect=function(_,position,size,color)draws[#draws+1]={position=position,size=size,color=color}end}}
local data={schema_version=1,icons={['0123456789abcdef']={sample=32,palette={{255,255,255,255},{0,0,0,255}},
 rectangles={{0,0,32,8,1},{0,8,32,24,2}}}}}
local art=M.new(engine,data)
local result=assert(art:draw({},'0123456789abcdef',{x=10,y=20,w=64,h=96},7,nil,{x=25,y=30,w=40,h=70}))
assert(result.rectangles==2 and #draws==2)
assert(draws[1].position[1]==25 and draws[1].position[2]==92 and draws[1].size[1]==40 and draws[1].size[2]==8)
assert(draws[2].position[1]==25 and draws[2].position[2]==30 and draws[2].size[1]==40 and draws[2].size[2]==62)
assert(draws[1].color[2]==255 and draws[2].color[2]==0)
result=assert(art:draw({},'0123456789abcdef',{x=10,y=20,w=64,h=96},7,nil,{x=100,y=100,w=10,h=10}))
assert(result.rectangles==0 and #draws==2)
assert(not art:draw({},'0123456789abcdef',{x=10,y=20,w=64,h=96},7,nil,{x=0/0,y=0,w=10,h=10}))
assert(not art:draw({},'0123456789abcdef',{x=10,y=20,w=64,h=96},7,nil,{x=0,y=0,w=-1,h=10}))
assert(#draws==2)
''')
