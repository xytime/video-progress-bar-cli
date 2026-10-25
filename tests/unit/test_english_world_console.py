"""管理台真实 SQLite/文件边界；无平台副作用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 分页去重、早期失败、状态保护、身份绑定和本机权限。 |
"""
import hashlib
import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from video_processing.db.database import PipelineDB
from video_processing.english_world.console import EnglishConsole
from web.english_world_console import create_english_console_router

ORIGIN = 'http://127.0.0.1:9100'


@pytest.fixture
def console_data(tmp_path):
    db = PipelineDB(str(tmp_path/'pipeline.db'))
    db.topic_initialize()
    output = tmp_path/'output';output.mkdir()
    package = output/'package';package.mkdir();(package/'qa').mkdir()
    video = package/'english_world.mp4';video.write_bytes(b'synthetic-video-identity')
    timeline = package/'timeline.json';timeline.write_text('{}')
    manifest = package/'english_world.manifest.json';manifest.write_text(json.dumps({'timeline':str(timeline)}))
    digest = lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    with db.get_connection() as conn:
        for index in range(25):
            conn.execute('''INSERT INTO english_world_review_items
                (id,title,artifact_sha256,manifest_sha256,mp4_path,manifest_path,title_path,copy_path,cover_path,cover_provenance_path,
                 state,source_publisher,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (f'r{index}',f'Ocean 科学 {index}',digest(video) if index==0 else str(index)*64,digest(manifest),
                 str(video),str(manifest),str(package/'title.txt'),str(package/'copy.txt'),str(package/'cover.png'),str(package/'cover.json'),
                 'UNCERTAIN' if index==0 else 'READY_FOR_REVIEW','Science Desk','2026-10-24 18:30:00','2026-10-24 18:30:00'))
        conn.execute("INSERT INTO english_world_jobs (id,review_id,state,requested_by) VALUES ('job1','r0','PRODUCTION_REQUESTED','manual')")
        conn.commit()
    runs=output/'english_world_daily';runs.mkdir()
    name='run_2026-10-25_043005_263918';(runs/(name+'.log')).write_text('not exposed')
    (runs/(name+'.delivery-request.json')).write_text(json.dumps({'title':'今日英语世界短视频','failure':'agy returned no structured_output','kind':'failure'}))
    (runs/(name+'.delivery.json')).write_text(json.dumps({'status':'ACCEPTED','kind':'failure_notice'}))
    return db,output,package


@pytest.fixture
def console_api(console_data):
    db,output,_=console_data
    app=FastAPI();app.include_router(create_english_console_router(db,port=9100,output=output))
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[2]/'src/web/static'),name='static')
    client=TestClient(app,base_url=ORIGIN,client=('127.0.0.1',50000))
    assert client.get('/english-world').status_code==200
    return client,db


def test_real_union_filter_date_page_and_no_mutation(console_data):
    db,output,_=console_data;service=EnglishConsole(db,output)
    before=db.english_console_snapshot()
    result=service.view()
    assert result['counts']['all']==26  # linked manual/review item is one task
    assert result['total']==26 and len(result['items'])==20
    assert len(service.view(page=2)['items'])==6
    result=service.view(q='  oCeAn ',trigger='manual',date='2026-10-25')
    assert len(result['items'])==1  # UTC source creation date is Beijing next day
    assert result['items'][0]['state']=='UNCERTAIN'
    assert result['items'][0]['wechat']['state']=='UNCERTAIN'
    assert service.view(q='no match')['total']==0
    assert service.view(page=999)['page']==2
    assert db.english_console_snapshot()==before


def test_failure_notice_acceptance_is_not_video_publication(console_data):
    db,output,_=console_data
    rows=EnglishConsole(db,output).view(trigger='scheduled')['items']
    assert len(rows)==1 and rows[0]['state']=='FAILED'
    assert rows[0]['wechat']['state']=='UNKNOWN'
    assert 'structured_output' in rows[0]['error']


def test_bound_report_changes_and_missing_paths_fail_closed(console_data,tmp_path):
    db,output,package=console_data;service=EnglishConsole(db,output)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    audio=package/'qa/final_audio_qa.json'
    audio.write_text(json.dumps({'state':'PASS','mp4_sha256':sha(package/'english_world.mp4'),
                                'manifest_sha256':sha(package/'english_world.manifest.json')}))
    assert service.report('job:job1','audio')['status']=='身份一致 · 历史报告 PASS'
    (package/'english_world.mp4').write_bytes(b'changed')
    assert service.report('job:job1','audio')['status']=='关联未核实'
    audio.unlink()
    assert '缺失' in service.report('job:job1','audio')['status']
    secret=tmp_path/'private.json';secret.write_text('{"secret":"never expose"}')
    audio.symlink_to(secret)
    assert '缺失' in service.report('job:job1','audio')['status']
    assert 'never expose' not in str(service.report('job:job1','audio'))



def test_visual_and_safety_reports_use_own_files_and_all_fingerprints(console_data):
    db,output,package=console_data;service=EnglishConsole(db,output)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    video=package/'english_world.mp4';manifest=package/'english_world.manifest.json'
    timeline=package/'timeline.json';sheet=package/'qa/contact_sheet.png';sheet.write_bytes(b'contact')
    evidence=package/'qa/source_evidence.json';evidence.write_text('{}')
    visual={'state':'PASS','mp4_sha256':sha(video),'contact_sheet':str(sheet),'contact_sheet_sha256':sha(sheet)}
    (package/'qa/visual_safety.json').write_text(json.dumps(visual))
    safety={'state':'PASS','mp4_sha256':sha(video),'manifest_sha256':sha(manifest),
            'timeline_sha256':sha(timeline),'source_evidence_sha256':sha(evidence)}
    (package/'qa/safety_gate.json').write_text(json.dumps(safety))
    assert '历史报告 PASS' in service.report('job:job1','visual')['status']
    assert '历史报告 PASS' in service.report('job:job1','safety')['status']
    sheet.write_bytes(b'changed')
    assert service.report('job:job1','visual')['status']=='关联未核实'
    timeline.write_text('{"changed":true}')
    assert service.report('job:job1','safety')['status']=='关联未核实'

def test_http_session_peer_origin_bounds_and_fixed_report_types(console_api):
    client,_=console_api
    result=client.get('/api/english-world/console')
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    assert client.get('/api/english-world/console?date=invalid').status_code==422
    assert client.get('/api/english-world/console?category=missing').status_code==422
    assert client.get('/api/english-world/console/report?task=job:job1&kind=../../private').status_code==422
    assert client.get('/api/english-world/console/report?task=missing&kind=audio').status_code==404
    assert client.get('/api/english-world/console',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/english-world/console').status_code==405
    client.cookies.clear()
    assert client.get('/api/english-world/console').status_code==403


def test_old_inflight_record_is_not_live_progress(console_data):
    db,output,_=console_data
    with db.get_connection() as conn:
        conn.execute("UPDATE english_world_review_items SET state='UNDER_REVIEW',updated_at='2020-01-01 00:00:00' WHERE id='r0'")
        conn.commit()
    row=EnglishConsole(db,output).find('job:job1')
    assert row['stale'] and row['attention'] and not row['active']
    assert '当前待确认' in row['label']
