#!/usr/bin/env python3
"""Fail-closed verifier for a completed Shorts MP4 master."""
import argparse, hashlib, json, os, re, subprocess, sys
from fractions import Fraction
p=argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--expect-width',type=int,default=1440)
p.add_argument('--expect-height',type=int,default=2560)
p.add_argument('--expect-fps',type=Fraction,default=Fraction(60,1))
p.add_argument('--expect-duration',type=float,required=True)
p.add_argument('--duration-tolerance',type=float,default=.10)
p.add_argument('--expect-title',required=True)
p.add_argument('--expect-description',required=True)
p.add_argument('--expect-artist',default='@IshaniFact')
p.add_argument('--expect-copyright',required=True)
p.add_argument('--expect-lufs',type=float,default=-14.0)
p.add_argument('--lufs-tolerance',type=float,default=.6)
p.add_argument('--expected-sha256')
p.add_argument('--expected-size',type=int)
p.add_argument('--encoder-command',required=True)
p.add_argument('--expect-cq',default='22',help='NVENC CQ used: 22 default, 18 for the higher-quality variant')
p.add_argument('--report')
a=p.parse_args(); checks=[]
def check(name,ok,detail): checks.append({'check':name,'pass':bool(ok),'detail':str(detail)})
def run(args):
    r = subprocess.run(args, capture_output=True)
    r.stdout = r.stdout.decode('utf-8', 'replace') if isinstance(r.stdout, bytes) else r.stdout
    r.stderr = r.stderr.decode('utf-8', 'replace') if isinstance(r.stderr, bytes) else r.stderr
    return r
exists=os.path.isfile(a.video) and os.path.getsize(a.video)>0
size=os.path.getsize(a.video) if os.path.exists(a.video) else 0
check('nonempty',exists,f'{size} bytes')
meta={}
if exists:
 r=run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',a.video])
 try: meta=json.loads(r.stdout) if r.returncode==0 else {}; check('ffprobe',r.returncode==0,r.stderr[-500:])
 except Exception as e: check('ffprobe',False,repr(e))
else: check('ffprobe',False,'file absent')
streams=meta.get('streams',[]); vids=[x for x in streams if x.get('codec_type')=='video']; auds=[x for x in streams if x.get('codec_type')=='audio']
v=vids[0] if vids else {}; au=auds[0] if auds else {}; fmt=meta.get('format',{})
check('required_streams',len(vids)==1 and len(auds)==1,f'video={len(vids)} audio={len(auds)}')
check('dimensions',(v.get('width'),v.get('height'))==(a.expect_width,a.expect_height),f"{v.get('width')}x{v.get('height')} expected {a.expect_width}x{a.expect_height}")
try: fps=Fraction(v.get('avg_frame_rate') or v.get('r_frame_rate') or '0/1')
except Exception: fps=Fraction(0,1)
check('frame_rate',fps==a.expect_fps,f'{fps} expected {a.expect_fps}')
check('video_codec_pix_fmt',v.get('codec_name')=='h264' and v.get('pix_fmt')=='yuv420p',f"{v.get('codec_name')} / {v.get('pix_fmt')}")
check('color_tags',all(v.get(k)=='bt709' for k in ['color_space','color_transfer','color_primaries']),f"{v.get('color_space')}/{v.get('color_transfer')}/{v.get('color_primaries')}")
check('audio_stream',au.get('codec_name')=='aac' and int(au.get('sample_rate') or 0)==48000 and int(au.get('channels') or 0)==2,f"{au.get('codec_name')} {au.get('sample_rate')}Hz {au.get('channels')}ch")
# Read MP4 tags from format and stream scopes; normalize tag-key case.
tags={}
for scope in [fmt.get('tags',{})]+[x.get('tags',{}) for x in streams]:
 for key,value in scope.items(): tags[str(key).lower()]=str(value)
for key,expected in [('title',a.expect_title),('description',a.expect_description),('artist',a.expect_artist),('copyright',a.expect_copyright)]:
 check('metadata_'+key,tags.get(key)==expected, 'matches' if tags.get(key)==expected else 'actual='+repr(tags.get(key))+'; expected='+repr(expected))
for forbidden in ('genre','comment'):
 present=forbidden in tags
 check('no_'+forbidden, not present, 'present' if present else 'absent')
try: dur=float(fmt.get('duration',0))
except Exception: dur=0
check('duration',abs(dur-a.expect_duration)<=a.duration_tolerance,f'{dur:.3f}s expected {a.expect_duration:.3f}s ±{a.duration_tolerance:.3f}s')
try: audur=float(au.get('duration') or dur)
except Exception: audur=0
check('audio_duration',abs(audur-a.expect_duration)<=a.duration_tolerance,f'{audur:.3f}s expected {a.expect_duration:.3f}s ±{a.duration_tolerance:.3f}s')
if exists:
 dec=run(['ffmpeg','-v','error','-xerror','-i',a.video,'-f','null','-'])
 check('full_decode',dec.returncode==0,dec.stderr[-1000:] or f'exit={dec.returncode}')
 loud=run(['ffmpeg','-hide_banner','-nostats','-i',a.video,'-af',f'loudnorm=I={a.expect_lufs}:TP=-1.5:LRA=7:print_format=json','-f','null','-'])
 blocks=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',loud.stderr,re.S); measured=None
 if loud.returncode==0 and blocks:
  try: measured=float(json.loads(blocks[-1])['input_i'])
  except Exception: pass
 check('integrated_loudness',measured is not None and abs(measured-a.expect_lufs)<=a.lufs_tolerance,f'{measured} LUFS; target {a.expect_lufs}±{a.lufs_tolerance}')
 h=hashlib.sha256()
 with open(a.video,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 digest=h.hexdigest()
else: digest=None
check('sha256',digest is not None and (not a.expected_sha256 or digest==a.expected_sha256),f'{digest}; expected {a.expected_sha256 or "(not supplied)"}')
check('size_match',exists and (a.expected_size is None or size==a.expected_size),f'{size}; expected {a.expected_size if a.expected_size is not None else "(not supplied)"}')
required=['h264_nvenc','-preset p4',f'-cq {a.expect_cq}','-b:v 0','-pix_fmt yuv420p']
missing=[x for x in required if x not in a.encoder_command]
check('encoder_command',not missing,'ok' if not missing else f'missing {missing}')
result={'file':os.path.abspath(a.video),'size':size,'sha256':digest,'checks':checks,'pass':all(x['pass'] for x in checks)}
out=json.dumps(result,indent=2); print(out)
if a.report: open(a.report,'w').write(out+'\n')
sys.exit(0 if result['pass'] else 1)
