"""金额一致性只比较同一原文金额，人员/岗位和不同金额不得串配。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 复现真实人数误报，保留同额漂移、相邻单位及逐段事实门。 |
"""
import pytest
from video_processing.utils.translation_consistency_guard import evaluate_translation_consistency
from video_processing.utils.translation_quality_guard import extract_fact_signal, evaluate_translation_pair


def amount_warnings(source, translated):
    return [i for i in evaluate_translation_consistency(source, translated)
            if i.code == 'AMOUNT_CONSISTENCY_UNIT_DRIFT']


def test_employee_and_job_counts_do_not_drift_unrelated_capex():
    source = ['Microsoft planned to spend $175 billion on data centers.',
              'A company can spend $175 billion in one year.',
              'Microsoft had 223,000 full-time employees.',
              'August was cut from 162,000', 'to 133,000 jobs.']
    translated = ['微软计划投入1750亿美元建设数据中心。', '一家公司一年能花掉1750亿美元。',
                  '微软有22.3万名全职员工。', '八月份的数据从16.2万', '下调至13.3万。']
    assert amount_warnings(source, translated) == []


def test_different_real_money_amounts_are_not_the_same_fact():
    assert amount_warnings(['A fund raised $175 billion.', 'A separate fund raised $1 million.'],
                           ['一只基金募集1750亿美元。', '另一只基金募集100万美元。']) == []


def test_multiple_real_amounts_in_same_row_do_not_drift_each_other():
    assert amount_warnings(['The assets total $175 billion and the fee is $1 million.',
                            'The assets still total $175 billion.'],
                           ['资产总计1750亿美元，费用为100万美元。', '资产仍总计1750亿美元。']) == []


def test_employee_count_in_money_row_is_not_a_second_dollar_fact():
    assert amount_warnings(['It spent $175 billion and employed 223,000 people.',
                            'It spent $175 billion again.'],
                           ['它投入1750亿美元，并雇佣22.3万名员工。', '它再次投入1750亿美元。']) == []


def test_repeated_source_money_still_detects_tenfold_drift():
    assert amount_warnings(['The fund raised $49 billion.', 'The same fund raised $49 billion.'],
                           ['基金募集490亿美元。', '同一基金募集49亿美元。'])


def test_adjacent_split_money_unit_keeps_original_identity():
    issues = amount_warnings(['The cost is $175', 'billion for data centers.',
                             'The same cost is $175 billion.'],
                            ['成本为1750亿美元', '用于数据中心。', '相同成本为175亿美元。'])
    assert issues and issues[0].source_signal == '$175B'


@pytest.mark.parametrize('text', ['22.3万名员工', '6万名参与者'])
def test_named_people_are_not_dollar_amounts(text):
    assert extract_fact_signal(text, lang='zh').amounts_usd == []


def test_actual_dollars_and_per_segment_missing_fact_guard_remain():
    assert extract_fact_signal('6万美元的名义本金', lang='zh').amounts_usd == [60000.]
    assert extract_fact_signal('6万名义本金', lang='zh').amounts_usd == [60000.]
    result = evaluate_translation_pair('The fund raised $60,000.', '共有6万名员工。',
                                       require_amount_coverage=True)
    assert any(i.severity == 'P0' for i in result.issues)
