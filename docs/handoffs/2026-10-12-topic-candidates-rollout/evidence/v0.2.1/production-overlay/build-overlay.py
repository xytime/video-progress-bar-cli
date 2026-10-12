from pathlib import Path
import importlib.util
import hashlib
import re
import ast
import json
import subprocess
import tempfile
source=Path('/Users/ryusei/.codex/worktrees/2d17/Video-precessing')
production=Path('/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing')
spec=importlib.util.spec_from_file_location('isolated_runner',source/'scripts/run_isolated_tests.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
dest=Path(tempfile.mkdtemp(prefix='topic-integration-overlay-'))
manifest=module.snapshot(source,dest)
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=production,text=True).strip()
paths=['src/video_processing/db/database.py','src/video_processing/processors/caption_processor.py','src/video_processing/utils/subtitle_translation_provider.py','src/video_processing/utils/vocab_helper.py','scripts/submit_generic_douyin.py','config/wechat_products.json']
receipts={}
for relative in paths:
 ours=dest/relative; theirs=(production/relative).read_bytes()
 base=subprocess.check_output(['git','show',head+':'+relative],cwd=production)
 if ours.read_bytes()==base:
  ours.write_bytes(theirs)
 else:
  with tempfile.TemporaryDirectory(prefix='topic-overlay-merge-') as temp:
   root=Path(temp);basefile=root/'base';theirfile=root/'theirs'
   basefile.write_bytes(base);theirfile.write_bytes(theirs)
   merged=subprocess.run(['git','merge-file','-p',str(ours),str(basefile),str(theirfile)],capture_output=True)
   output=merged.stdout
   if merged.returncode:
    text=output.decode();matches=list(re.finditer(r'^<<<<<<< .*?\n(.*?)^=======\n(.*?)^>>>>>>> .*?\n',text,re.M|re.S))
    if relative not in {'src/video_processing/db/database.py','scripts/submit_generic_douyin.py'} or len(matches)!=1 or matches[0].start()>2000:
     (dest/'merge-conflict.txt').write_bytes(output)
     raise RuntimeError(f'Overlay conflict: {relative}; {dest}')
    match=matches[0];left,right=match.groups()
    assert all(not line.strip() or line.startswith('|') for line in (left+right).splitlines())
    text=text[:match.start()]+left+right+text[match.end():]
    ast.parse(text);output=text.encode()
   ours.write_bytes(output)
 receipts[relative]={'production_working_sha256':hashlib.sha256(theirs).hexdigest(),'integrated_sha256':hashlib.sha256(ours.read_bytes()).hexdigest()}
for relative in ['src/video_processing/topic_clues/__init__.py','src/video_processing/topic_clues/hub.py','tests/unit/test_topic_clues_hub.py','tests/unit/test_vocabulary_export.py']:
 origin=production/relative
 assert origin.is_file() and not origin.is_symlink()
 target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(origin.read_bytes())
 receipts[relative]={'production_working_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'integrated_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
subprocess.run(['git','init','-q'],cwd=dest,check=True)
receipt={'production_head':head,'source':str(source),'snapshot':str(dest),'base_source_manifest_sha256':hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),'overlays':receipts}
(dest/'overlay-receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps({'snapshot':str(dest),'production_head':head,'files':len(receipts)}))
