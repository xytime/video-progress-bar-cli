"""整改合同回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 主机结构、绕过与字幕/路径边界 |
"""
import copy
import pytest
from video_processing.compliance_remix.manifest_contract import validate_manifest, validate_model_manifest, safe_card_path
from video_processing.compliance_remix.censor_guard import ComplianceCensorGuard
from video_processing.compliance_remix.subtitle_generator import TopEdgeSubtitleGenerator

VALID_MANIFEST = dict(id='synthetic_demo', title='市场观察', description='合成测试内容', cover_title='市场成本长期观察', cover_subtitle='观察', cover_label='研究', category='财经', badge_text='观察', keywords=['市场'], content_hints=['研究'], chapters=[dict(index=1,text='市场关注长期成本。',clauses=[['市场关注长期成本。',3.0]])],cards=[],raw_shots=[[0,3]],comparison_table=[dict(timestamp_range='00:00 - 00:03',source_english_gist='Synthetic source evidence.',remix_chinese_commentary='市场关注长期成本。',reframing_rationale='解释商业成本。')])

def test_valid_and_trusted_extension():
    value=copy.deepcopy(VALID_MANIFEST); value['source_evidence']={'text':'source'}
    assert validate_manifest(value) is value
    with pytest.raises(ValueError): validate_model_manifest(value)

@pytest.mark.parametrize('change', [lambda m:m.clear(),lambda m:m.update(chapters=[]),lambda m:m['chapters'][0].update(index=0),lambda m:m['chapters'][0].update(text='different'),lambda m:m['chapters'][0]['clauses'][0].__setitem__(1,float('nan')),lambda m:m.update(raw_shots=[[0,-1]]),lambda m:m['comparison_table'][0].update(timestamp_range='unknown')])
def test_invalid_structure(change):
    value=copy.deepcopy(VALID_MANIFEST);change(value)
    with pytest.raises(ValueError): validate_manifest(value)
    assert not ComplianceCensorGuard().validate_script_manifest(value).passed

@pytest.mark.parametrize('text',['港\u2062独','港\x00独','港\ufe0f独','港!独','Hong Kong independence'])
def test_unicode_and_english_bypass(text):
    assert ComplianceCensorGuard().check_sentence(text)

@pytest.mark.parametrize('field',['cover_title','cover_subtitle','cover_label','category','badge_text','description','title'])
def test_all_metadata_checked(field):
    value=copy.deepcopy(VALID_MANIFEST);value[field]='港!独'
    assert not ComplianceCensorGuard().validate_script_manifest(value).passed

def test_source_evidence_not_output():
    value=copy.deepcopy(VALID_MANIFEST);value['comparison_table'][0]['source_english_gist']='Hong Kong independence'
    assert ComplianceCensorGuard().validate_script_manifest(value).passed

@pytest.mark.parametrize('name',['../x.png','/tmp/x.png','x/../y.png','x.ass','..png'])
def test_card_paths(tmp_path,name):
    with pytest.raises(ValueError):safe_card_path(tmp_path,name)

def test_ass_injection(tmp_path):
    output=tmp_path/'safe.ass'
    TopEdgeSubtitleGenerator().generate_subtitles([(0,3,r'{\p1}m 0 0\Ninjected')],output,title='x\n[Events]\nDialogue: attack')
    text=output.read_text()
    assert r'{\p1}' not in text and '\nDialogue: attack' not in text
    assert text.count('\nDialogue:') == 1

def test_restricted_codex_signature_and_host_validator(monkeypatch):
    from types import SimpleNamespace
    from video_processing.compliance_remix import commentary_generator as module
    calls=[]
    def provider(**kwargs):
        calls.append(kwargs)
        assert 'system_prompt' not in kwargs
        assert kwargs['state_dir'].is_dir() and kwargs['command']
        return SimpleNamespace(payload=kwargs['validate'](copy.deepcopy(VALID_MANIFEST)))
    monkeypatch.setattr(module,'run_codex_structured',provider)
    value,report,provider_name=module.CommentaryGenerator().generate_proposal('Synthetic','00:00 Synthetic source', 'demo')
    assert report.passed and provider_name == 'codex' and len(calls)==1

def test_invalid_provider_payload_refused(monkeypatch):
    from types import SimpleNamespace
    from video_processing.compliance_remix import commentary_generator as module
    monkeypatch.setattr(module,'run_codex_structured',lambda **kwargs:SimpleNamespace(payload={}))
    with pytest.raises(RuntimeError):module.CommentaryGenerator().generate_proposal('Synthetic','00:00 source','demo')

@pytest.mark.parametrize('text',['港\u034f独','港\u115f独','港\u1160独','港\u3164独','港\uffa0独','Hong.Kong independence','Hong-Kong independence'])
def test_more_ignorable_and_english_separators(text):
    assert ComplianceCensorGuard().check_sentence(text)

@pytest.mark.parametrize('change',[lambda m:m.update(chapters=m['chapters']*17),lambda m:m.update(title='x'*4001),lambda m:m['chapters'][0]['clauses'][0].__setitem__(1,1801),lambda m:m['comparison_table'][0].update(remix_chinese_commentary='遗漏'),lambda m:m.update(raw_shots=[[0,1801]])])
def test_resource_and_complete_comparison_limits(change):
    value=copy.deepcopy(VALID_MANIFEST);change(value)
    with pytest.raises(ValueError):validate_manifest(value)

@pytest.mark.parametrize('title',['短标题','x'*17])
def test_cover_short_title_contract(title):
    value=copy.deepcopy(VALID_MANIFEST);value['cover_title']=title
    with pytest.raises(ValueError):validate_manifest(value)


def test_prompt_requires_exact_evidence_without_fabricated_numbers():
    from video_processing.compliance_remix.commentary_generator import SYSTEM_PROMPT_COMPLIANCE_REMIX, build_user_prompt
    source="WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nSynthetic source evidence."
    prompt=SYSTEM_PROMPT_COMPLIANCE_REMIX + build_user_prompt('Synthetic', source, 'synthetic_demo')
    assert source in prompt
    for requirement in ('逐字连续原文摘录', '真实 cue 时间范围', 'cards=[]', '[[start, duration]', '人工待审', '高亮词只放 keywords', '不得补造'):
        assert requirement in prompt
    assert '13O' not in prompt and '2000万' not in prompt and '3~5' not in prompt
