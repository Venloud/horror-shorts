"""Isolated source priority, original-byte promotion, failure safety and actual FFmpeg frames."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pipeline'))
import project_assets as pa
import images,library,render,sources,get_sfx


class TrackingStore(library.DirStore):
    def __init__(self,path,fail=None):
        super().__init__(path);self.uploads=[];self.fail=fail
    def put(self,name,src):
        self.uploads.append(name)
        if self.fail=='upload' or (self.fail=='metadata' and name=='index.json'):
            raise OSError('injected storage failure')
        super().put(name,src)
    def get(self,name,dest):
        result=super().get(name,dest)
        if result and self.fail=='readback' and name!='index.json':dest.write_bytes(b'corrupt readback')
        return result


class ProjectAssetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.base=self.root/'assets/projects/case';(self.base/'images').mkdir(parents=True)
        im=Image.new('RGB',(600,900),'#19324b');ImageDraw.Draw(im).rectangle((50,100,450,640),fill='#c5a879')
        file=self.base/'images/farmhouse.png';im.save(file)
        self.entry={'id':'farmhouse','file':'images/farmhouse.png','sha256':pa.digest(file),'kind':'image',
                    'description':'snowy farmhouse','project_use_authorized':True,'license_status':'cleared',
                    'general_reuse_approved':True,'case_specific':False,'rights':'Synthetic fixture; no real clearance claim',
                    'provenance':{'original_source':'test-only archived fixture','kind':'historical_photo'}}
        self.manifest={'schema':1,'project_id':'case','assets':[self.entry]};self.write_manifest()
        self.story={'source':'inbox/case.txt','story_id':'fixture','scenes':[{'narration':'An isolated farmhouse stood in snow.','image_prompt':'snowy farmhouse','sfx':'missing_optional_sound'}]}
        self.out=self.root/'work';self.out.mkdir()
        self.video=self.root/'render.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=24:d=0.2','-c:v','libx264','-pix_fmt','yuv420p',str(self.video)],check=True)
        self.store=TrackingStore(self.root/'existing-library')
        self.state=library._STATE.copy()
        library._STATE.update(index=None,store=self.store,readonly=False,reused=0)
        self.addCleanup(lambda: (library._STATE.clear(),library._STATE.update(self.state)))
        for target,value in [('ROOT',self.root)]:
            ctx=patch.object(pa,target,value);ctx.start();self.addCleanup(ctx.stop)
        ctx=patch.object(library,'LOCAL',self.root/'library-cache');ctx.start();self.addCleanup(ctx.stop)
        ctx=patch.object(library,'rank_images',side_effect=lambda text,paths,source=None:[{'path':str(p),'score':.8} for p in paths]);ctx.start();self.addCleanup(ctx.stop)
        ctx=patch.object(library,'embed_image',return_value=[1.,0.]);ctx.start();self.addCleanup(ctx.stop)

    def write_manifest(self):
        (self.base/'manifest.json').write_text(json.dumps(self.manifest))

    def test_project_assets_are_placed_before_general_search_or_generation(self):
        calls=[]
        def general(*args):
            self.assertTrue((self.out/'scene_00a.json').exists());calls.append('general')
        def media(*args):calls.append('licensed-media')
        with patch.object(library,'fill_shots',side_effect=general),patch('media.fill_shots',side_effect=media),patch.object(images,'_cloudflare',side_effect=AssertionError('AI called')):
            result=pa.fill_scene_assets(self.story,self.out,[])
        self.assertTrue(result[0][0].exists());self.assertEqual(calls,['general','licensed-media'])
        self.assertEqual(json.loads((self.out/'scene_00a.json').read_text())['project_asset'],'farmhouse')

    def test_irrelevant_asset_is_rejected(self):
        with patch.object(library,'rank_images',return_value=[{'path':str(self.base/self.entry['file']),'score':.01}]):
            self.assertEqual(pa.fill_shots(self.story,self.out),0)
        self.assertFalse((self.out/'scene_00a.png').exists())

    def test_general_library_precedes_ai_and_offline_rejects_unfilled_shots(self):
        self.story['source']='inbox/no-project.txt';calls=[]
        def general(*args):
            shutil.copy2(self.base/self.entry['file'],self.out/'scene_00a.png');calls.append('library')
        with patch.object(library,'fill_shots',side_effect=general),patch.object(images,'_cloudflare',side_effect=AssertionError('AI called')):
            self.assertTrue(pa.fill_scene_assets(self.story,self.out,[],offline=True)[0][0].exists())
        self.assertEqual(calls,['library'])
        (self.out/'scene_00a.png').unlink()
        with self.assertRaisesRegex(RuntimeError,'no approved matching asset'):
            images.generate_images(self.story,self.out,offline=True)

    def test_source_checksum_mismatch_rejected(self):
        (self.base/self.entry['file']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):
            pa.fill_shots(self.story,self.out)

    def test_owner_hook_is_not_prefixed_and_video_assets_are_supported(self):
        import story as writer
        self.manifest['preserve_exact_opening']=True;self.write_manifest()
        text='Someone walked out of the frozen woods. '+('A farmer reported strange sounds. '*10)
        item={'key':'inbox/case.txt','kind':'script','true':True,'text':text}
        with patch('sources.next_inbox',return_value=item),patch.object(writer,'env',return_value='unused-fixture-key'),patch.object(writer,'_final_problem',return_value=None),patch.object(writer,'plan_scenes',return_value={'title':'Test','scenes':[{'narration':text}]}) as planner:
            result=writer.write_story([])
        self.assertEqual(result['scenes'][0]['narration'],text)
        self.assertEqual(planner.call_args.args[0],text)
        video=self.base/'images/farmhouse.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=s=400x640:r=24:d=0.25','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
        self.entry.update(file='images/farmhouse.mp4',kind='video',sha256=pa.digest(video));self.write_manifest()
        self.assertEqual(pa.fill_shots(self.story,self.out),1)
        self.assertEqual(pa.digest(self.out/'scene_00a.mp4'),self.entry['sha256'])

    def test_low_quality_unused_asset_blocks_promotion_without_deletion(self):
        file=self.base/self.entry['file'];Image.new('RGB',(64,64),'blue').save(file)
        self.entry['sha256']=pa.digest(file);self.write_manifest()
        with self.assertRaisesRegex(ValueError,'quality minimum'):
            pa.finalize(self.story,self.video,video_verified=True)
        self.assertTrue(file.exists());self.assertEqual(self.store.uploads,[])

    def test_optional_project_sound_is_local_and_missing_sound_does_not_block(self):
        import wave
        file=self.base/'images/door.wav'
        with wave.open(str(file),'wb') as sound:
            sound.setparams((1,2,8000,0,'NONE','not compressed'));sound.writeframes(b'\0\0'*800)
        effect={'id':'door','kind':'sfx','file':'images/door.wav','sha256':pa.digest(file),
                'project_use_authorized':True,'license_status':'cleared'}
        self.manifest['assets'].append(effect);self.write_manifest()
        self.assertEqual(pa.sound_effect(self.story,'door'),file)
        file.unlink()
        self.assertIsNone(pa.sound_effect(self.story,'door'))
        self.assertEqual(pa.fill_shots(self.story,self.out),1)

    def test_duplicate_hash_uploads_original_once_and_cleanup_is_repeatable(self):
        second=dict(self.entry,id='same-bytes',file='images/copy.png')
        shutil.copy2(self.base/self.entry['file'],self.base/second['file']);self.manifest['assets'].append(second);self.write_manifest()
        result=pa.finalize(self.story,self.video,video_verified=True)
        self.assertTrue(result['cleanup']);self.assertFalse(self.base.exists())
        originals=[x for x in self.store.uploads if x.endswith('.png')]
        self.assertEqual(len(originals),1)
        self.assertEqual(pa.digest(self.store.path/originals[0]),self.entry['sha256'])
        self.assertTrue(pa.finalize(self.story,self.video,video_verified=True)['repeated'])

    def test_failed_upload_never_cleans_originals(self):
        self.store.fail='upload'
        with self.assertRaises(OSError):pa.finalize(self.story,self.video,video_verified=True)
        self.assertEqual(pa.digest(self.base/self.entry['file']),self.entry['sha256'])

    def test_failed_metadata_upload_never_cleans_originals(self):
        self.store.fail='metadata'
        with self.assertRaises(OSError):pa.finalize(self.story,self.video,video_verified=True)
        self.assertTrue(self.base.exists())

    def test_corrupt_readback_never_cleans_originals(self):
        self.store.fail='readback'
        with self.assertRaisesRegex(RuntimeError,'readback'):pa.finalize(self.story,self.video,video_verified=True)
        self.assertTrue(self.base.exists())

    def test_failed_generation_retains_project_and_never_uploads(self):
        self.assertEqual(pa.finalize(self.story,self.video,video_verified=False)['status'],'render-unverified')
        self.assertTrue(self.base.exists());self.assertEqual(self.store.uploads,[])

    def test_unknown_rights_are_restricted_not_promoted_or_deleted(self):
        self.entry['license_status']='unknown';self.write_manifest()
        self.assertEqual(pa.fill_shots(self.story,self.out),0)
        result=pa.finalize(self.story,self.video,video_verified=True)
        self.assertFalse(result['cleanup']);self.assertEqual(self.store.uploads,[])

    def test_historical_provenance_survives_verified_promotion(self):
        result=pa.finalize(self.story,self.video,video_verified=True,cleanup=False)
        index=json.loads((self.store.path/'index.json').read_text())
        self.assertEqual(index['assets'][0]['provenance'],self.entry['provenance'])
        self.assertEqual(index['assets'][0]['sha256'],self.entry['sha256'])
        self.assertEqual(result['source_manifest']['assets'][0]['provenance'],self.entry['provenance'])

    def test_extra_unlisted_file_prevents_cleanup(self):
        (self.base/'unlisted-original.txt').write_text('preserve me')
        self.assertFalse(pa.finalize(self.story,self.video,video_verified=True)['cleanup'])
        self.assertTrue((self.base/'unlisted-original.txt').exists())

    def test_existing_flat_inbox_format_still_works(self):
        inbox=self.root/'inbox';inbox.mkdir();(inbox/'case.txt').write_text('SCRIPT TRUE\n'+'A farmhouse stands alone in the winter snow. '*10)
        with patch.object(sources,'INBOX',inbox),patch('repeat_guard.repeat_of',return_value=''),patch.dict(os.environ,{'INBOX_FILE':'case.txt'}):
            item=sources.next_inbox([])
        self.assertEqual(item['key'],'inbox/case.txt');self.assertEqual(item['kind'],'script');self.assertTrue(item['true'])

    def test_image_and_video_really_render_inside_existing_ffmpeg_frame(self):
        image=self.base/self.entry['file']
        for video in [False,True]:
            if video:shutil.copy2(self.video,image.with_suffix('.mp4'))
            target=self.out/('video-frame.mp4' if video else 'image-frame.mp4')
            render._framed_asset_clip(image,.2,target)
            info=pa.media_info(target,'video')
            self.assertEqual((info['width'],info['height']),(1080,1920))
            self.assertGreater(info['duration'],0)

    def test_elevenlabs_probe_never_generates_or_returns_credentials(self):
        response=type('Response',(),{'status_code':200,'json':lambda self:{'character_limit':100,'character_count':0,'xi_api_key':'DO NOT RETURN'}})()
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'fixture'}),patch.object(get_sfx.requests,'get',return_value=response),patch.object(get_sfx.requests,'post') as post:
            result=get_sfx.check_elevenlabs()
        self.assertTrue(result['authenticated']);self.assertFalse(result['generation_tested'])
        self.assertNotIn('DO NOT RETURN',json.dumps(result));post.assert_not_called()


if __name__=='__main__':unittest.main()
