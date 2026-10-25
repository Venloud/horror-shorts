"""Inbox-scoped media first; promote only cleared assets into the existing library."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

from common import CONFIG, ROOT, log


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_id(story):
    match = re.fullmatch(r'inbox/([A-Za-z0-9_-]+)\.txt', str(story.get('source', '')))
    return match.group(1) if match else None


def directory(identifier):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier or ''):
        raise ValueError('Invalid inbox project identifier')
    path = ROOT / 'assets/projects' / identifier
    if not path.resolve().is_relative_to(ROOT.resolve()) or any(p.is_symlink() for p in [ROOT/'assets', ROOT/'assets/projects', path]):
        raise ValueError('Project assets must remain inside the repository')
    return path


def asset_path(base, rel):
    parts = PurePosixPath(rel)
    if parts.is_absolute() or '..' in parts.parts or '\\' in rel:
        raise ValueError('Unsafe project asset path')
    p = base / rel
    if not p.resolve().is_relative_to(base.resolve()) or p.is_symlink() or not p.is_file():
        raise ValueError('Missing or unsafe project asset')
    return p


def load(identifier):
    base = directory(identifier)
    manifest = json.loads((base/'manifest.json').read_text())
    if manifest.get('schema') != 1 or manifest.get('project_id') != identifier:
        raise ValueError('Project manifest does not match its inbox script')
    ids = set()
    for item in manifest['assets']:
        if item['id'] in ids:
            raise ValueError('Duplicate project asset identifier')
        ids.add(item['id'])
        extensions={'image':{'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'},
                    'video':{'.mp4','.mov','.mkv','.webm','.m4v'},
                    'sfx':{'.mp3','.wav','.m4a','.ogg','.flac'}}
        if Path(item['file']).suffix.lower() not in extensions.get(item['kind'],set()):
            raise ValueError('Unsupported project media container; remote playlists are not accepted')
        try:
            file = asset_path(base, item['file'])
            if digest(file) != item['sha256']:raise ValueError('Supplied asset checksum changed')
        except ValueError:
            if item['kind']=='sfx':continue  # Optional audio is checked again before use, never a visual-build blocker.
            raise
    return base, manifest


def exact_opening(source):
    identifier=project_id({'source':source})
    if not identifier or not (directory(identifier)/'manifest.json').is_file():return False
    return load(identifier)[1].get('preserve_exact_opening') is True


def sound_effect(story,cue):
    """Project-authorized optional SFX, after the renderer's existing approved sound library."""
    identifier=project_id(story)
    if not identifier or not re.fullmatch(r'[a-z0-9_]{1,60}',cue):return None
    try:
        base,manifest=load(identifier)
        for item in manifest['assets']:
            if (item['kind']!='sfx' or item.get('cue',item['id'])!=cue
                or not item.get('project_use_authorized') or item.get('license_status')=='unknown'):continue
            path=asset_path(base,item['file'])
            if digest(path)!=item['sha256']:continue
            result=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-select_streams','a:0',
                                   '-show_entries','stream=codec_type','-of','json',str(path)],check=True,capture_output=True,text=True)
            if json.loads(result.stdout).get('streams'):
                story.setdefault('_project_sfx_used',[]).append({'id':item['id'],'sha256':item['sha256'],'provenance':item.get('provenance',{})})
                return path
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        log('Optional project sound unavailable; visual generation continues')
    return None


def fill_scene_assets(story,outdir,history,*,offline=False,reuse_general=True):
    """Shared production/preview order: project -> existing library -> licensed sources -> AI gaps."""
    import images,library,media
    fill_shots(story,outdir)
    if reuse_general:
        previous=story.get('_prefer_existing_assets')
        story['_prefer_existing_assets']=True
        try:library.fill_shots(story,outdir,history)
        finally:
            if previous is None:story.pop('_prefer_existing_assets',None)
            else:story['_prefer_existing_assets']=previous
    if not offline:media.fill_shots(story,outdir,history)
    return images.generate_images(story,outdir,offline=True) if offline else images.generate_images(story,outdir)


def media_info(path, kind):
    if kind == 'image':
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            return {'width': im.width, 'height': im.height, 'format': im.format}
    result = subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries','stream=width,height,codec_type:format=duration',
                             '-of','json',str(path)], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s.get('codec_type') == 'video')
    return {'width':video['width'],'height':video['height'],'duration':float(info['format']['duration'])}


def poster(path, target):
    subprocess.run(['ffmpeg','-y','-v','error','-protocol_whitelist','file,pipe','-i',str(path),'-frames:v','1',str(target)],
                   check=True, capture_output=True)


def _visual_hash(path):
    from PIL import Image
    with Image.open(path) as im:
        small=im.convert('L').resize((9,8))
        values=[small.getpixel((x,y)) for y in range(8) for x in range(9)]
    return sum(int(values[y*9+x] > values[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))


def fill_shots(story, outdir):
    """Fail closed on provenance/CLIP, fill before the general library, never call generation."""
    import images
    import library
    identifier = project_id(story)
    if not identifier or not (directory(identifier)/'manifest.json').is_file():
        return 0
    base, manifest = load(identifier)
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    candidates = []
    for item in manifest['assets']:
        # Owner supplied these for this episode; that is not a general reuse license.
        if not item.get('project_use_authorized') or item.get('license_status') == 'unknown':
            continue
        if item['kind'] not in ('image','video'):
            continue
        src = asset_path(base,item['file']); info=media_info(src,item['kind'])
        if min(info['width'],info['height']) < int(CONFIG.get('project_asset_min_dimension',400)):
            continue
        preview = src
        if item['kind'] == 'video':
            preview = outdir/('project-poster-'+item['id']+'.png')
            poster(src,preview)
        candidates.append((item,src,preview,_visual_hash(preview)))
    used, visual, placed = set(), [], 0
    for i, scene in enumerate(story.get('scenes',[])):
        for letter in images._letters():
            prompt = (scene.get(library.PROMPT_KEYS[letter]) or '').strip()
            target = outdir/f'scene_{i:02d}{letter}.png'
            if not prompt or target.exists():
                continue  # Preserve a validated checkpoint; project priority applies to unfilled shots.
            allow_repeat = bool(scene.get('allow_asset_repeat'))
            allowed = scene.get('project_asset_ids_'+letter,scene.get('project_asset_ids'))
            pool = [(a,s,p,h) for a,s,p,h in candidates if (not allowed or a['id'] in allowed)
                    and (allow_repeat or (a['sha256'] not in used and all((h^prior).bit_count()>2 for prior in visual)))]
            intent=(prompt+'. '+scene.get('narration',''))[:280]
            scores = library.rank_images(intent,[row[2] for row in pool],source='project_asset')
            if not scores:
                continue  # Missing CLIP never silently approves a vaguely matching picture.
            by_path = {str(row[2]):row for row in pool}
            for rank in scores:
                if rank['score'] < float(CONFIG.get('project_asset_min_similarity',0.27)):
                    break
                item,src,preview,vhash = by_path[rank['path']]
                if item['kind']=='video':
                    shutil.copy2(src,target.with_suffix('.mp4')); shutil.copy2(preview,target)
                else:
                    from PIL import Image
                    if src.suffix.lower()=='.png':shutil.copy2(src,target)
                    else:
                        with Image.open(src) as im:im.convert('RGB').save(target,'PNG')
                if not images._is_image(target):
                    target.unlink(missing_ok=True);target.with_suffix('.mp4').unlink(missing_ok=True)
                    continue
                meta = {'source':'owner_project','project_asset':item['id'],'project_id':identifier,
                        'source_sha256':item['sha256'],'original_file':item['file'],
                        'kind':item['kind'],'type':'project_video' if item['kind']=='video' else 'project_image',
                        'scene':i,'shot':letter,'license':item.get('rights','not specified'),
                        'license_status':item['license_status'],'reuse_scope':'project',
                        'provenance':item.get('provenance',{}),'visual_kind':item.get('visual_kind','illustration'),
                        'qa':'PASS','qa_method':'existing local image checks + CLIP; no historical-authenticity claim',
                        'clip_similarity':round(rank['score'],6),'frame_style':scene.get('asset_frame','none')}
                target.with_suffix('.json').write_text(json.dumps(meta,indent=2))
                story.setdefault('media_assets',[]).append(meta)
                used.add(item['sha256']);visual.append(vhash);placed+=1
                log(f'Project {identifier}: {item["id"]} -> scene {i:02d}{letter}, CLIP {rank["score"]:.3f}')
                break
    story['_project_asset_placements']=placed
    return placed


def verify_render(video):
    info=media_info(Path(video),'video')
    if info['duration'] <= 0:
        raise ValueError('Rendered video has no duration')
    subprocess.run(['ffmpeg','-v','error','-protocol_whitelist','file,pipe','-i',str(video),'-map','0:v:0','-f','null','-'],
                   check=True,capture_output=True)
    return info


def finalize(story, video, *, video_verified=False, cleanup=True):
    """Promote through library.py's store/index; verified readback precedes any deletion."""
    import library
    identifier=project_id(story)
    if not identifier:
        return {'status':'not-applicable','cleanup':False}
    base=directory(identifier)
    receipts=ROOT/'data/project_asset_promotions';receipt=receipts/(identifier+'.json')
    if not base.exists():
        if receipt.is_file():return {**json.loads(receipt.read_text()),'repeated':True}
        return {'status':'missing','cleanup':False}
    if not video_verified:
        return {'status':'render-unverified','cleanup':False}
    verify_render(video)
    base,manifest=load(identifier)
    eligible=[a for a in manifest['assets'] if a.get('general_reuse_approved') is True
              and a.get('license_status')=='cleared' and not a.get('case_specific') and a['kind'] in ('image','video')]
    restricted=[a['id'] for a in manifest['assets'] if a not in eligible]
    if not eligible:
        return {'status':'retained-restricted','restricted':restricted,'cleanup':False}
    for item in eligible:
        info=media_info(asset_path(base,item['file']),item['kind'])
        if min(info['width'],info['height'])<400:
            raise ValueError('Reusable original is below the project quality minimum; originals retained')
    index=library.load_index()
    if library._STATE['readonly']:
        raise RuntimeError('Existing asset library is unavailable; project assets retained')
    store=library._store();promoted=[]
    scratch=Path(tempfile.mkdtemp(prefix='.promotion-verify-',dir=base))
    try:
        for item in eligible:
            src=asset_path(base,item['file']);sha=item['sha256']
            known=next((a for a in index['assets'] if a.get('sha256')==sha or a['id']==hashlib.sha1(src.read_bytes()).hexdigest()[:16]),None)
            if known:
                if known.get('license_status')=='unknown' or known.get('reuse_scope')=='project' or known.get('case_specific'):
                    raise RuntimeError('Duplicate library asset needs its existing rights metadata reviewed; originals retained')
                dest=scratch/('existing-'+known['id']+Path(known['file']).suffix)
                if not store.get(known['file'],dest) or digest(dest)!=sha:
                    raise RuntimeError('Existing duplicate failed source-hash readback')
                promoted.append({'project_asset':item['id'],'library_asset':known['id'],'sha256':sha,'file':known['file']})
                continue
            aid=hashlib.sha1(src.read_bytes()).hexdigest()[:16];name=aid+src.suffix.lower()
            check=scratch/('readback-'+name)
            if not store.get(name,check) or digest(check)!=sha:
                store.put(name,src)
            if not store.get(name,check) or digest(check)!=sha:
                raise RuntimeError('Promoted original failed full-hash readback')
            preview=src
            poster_name=None
            if item['kind']=='video':
                preview=scratch/(aid+'.png');poster(src,preview);poster_name=aid+'.png';store.put(poster_name,preview)
                poster_check=scratch/('readback-'+poster_name)
                if not store.get(poster_name,poster_check) or digest(poster_check)!=digest(preview):
                    raise RuntimeError('Video poster readback failed')
            row={'id':aid,'file':name,'poster':poster_name,'kind':item['kind'],'sha256':sha,
                 'description':item['description'],'tags':item.get('tags',[]),'scene_relevance':item.get('scene_relevance',[]),
                 'style':item.get('style','painted'),'era':item.get('era','any'),'setting':item.get('setting','exterior'),
                 'subjects':item.get('subjects',[]),'source':item.get('source','owner_project'),
                 'license':item.get('rights',''),'license_status':'cleared','reuse_scope':'general',
                 'url':item.get('source_url',''),'provenance':item.get('provenance',{}),
                 'original_project':identifier,'original_filename':src.name,'media':media_info(src,item['kind']),
                 'character_specific':False,'embedding':library._pack(library.embed_image(preview)),
                 'retain_original':True,'visual_kind':item.get('visual_kind','illustration'),
                 'times_used':0,'last_used_seq':-999,'uses':[]}
            index['assets'].append(row)
            promoted.append({'project_asset':item['id'],'library_asset':aid,'sha256':sha,'file':name})
        library.save_index()
        verified=scratch/'index-readback.json'
        if not store.get('index.json',verified):raise RuntimeError('Library index readback failed')
        persisted=json.loads(verified.read_text())
        if any(not any(a.get('id')==p['library_asset'] and a.get('sha256',p['sha256'])==p['sha256'] for a in persisted['assets']) for p in promoted):
            raise RuntimeError('Promoted metadata was not durably stored')
        result={'schema':1,'project_id':identifier,'status':'promoted','promoted':promoted,
                'restricted':restricted,'source_manifest':manifest,'video_sha256':digest(video),'cleanup':False}
        receipts.mkdir(parents=True,exist_ok=True)
        temp=receipt.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2));temp.replace(receipt)
        if json.loads(receipt.read_text())['promoted']!=promoted:raise RuntimeError('Promotion receipt verification failed')
    finally:
        shutil.rmtree(scratch,ignore_errors=True)
    declared={'manifest.json'}|{a['file'] for a in manifest['assets']}
    extra=[p for p in base.rglob('*') if p.is_symlink() or (p.is_file() and p.relative_to(base).as_posix() not in declared)]
    if cleanup and not restricted and not extra:
        # Originals are now in the existing library and metadata in the durable receipt.
        shutil.rmtree(base)
        result['cleanup']=True
        temp=receipt.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2));temp.replace(receipt)
    return result
