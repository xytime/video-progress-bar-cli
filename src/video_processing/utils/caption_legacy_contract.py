"""已审查前代翻译完成合同的精确适配；processor/checkpoints → 本模块 → 质量纯工具。

只收纳 28696dd 基线，以及同 HEAD 的词汇元数据改动版本的源码摘要；
生产未提交实现未复制进来。未知方法/模块/设置合同一律不适配。
离线完整质检不调用修复模型，旧案例保留，新合同需要独立不可变案例。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.6 | 2026-10-31 | Codex | 登记绑定词注确定性清理目标，字幕正文与全部质量模块不变。 |
| 1.0.5 | 2026-10-31 | Codex | 登记有界校准及续跑期限修复，前代合同与质量阈值保持不变。 |
| 1.0.4 | 2026-10-30 | Codex | 接续地域分类的当前目标摘要，旧合同不变且仍完整离线复核。 |
| 1.0.3 | 2026-10-30 | Codex | 精确审查 AGY 空成功地域错误与状态码分类修复，保留前代摘要及完整质量门。 |
| 1.0.0 | 2026-10-29 | Codex | 两个精确已审查前代合同，完整质量复核后原子升级完成快照。 |
| 1.0.2 | 2026-10-30 | Codex | 审查 HTTP 错误分类修复后更新当前目标摘要，原质量合同与前代摘要不变。 |
| 1.0.1 | 2026-10-29 | Codex | 审查未准入故障归因与 Google 挑战即停差异后更新精确目标；质量模块与全片复核不变。 |
"""
from copy import deepcopy

from .subtitle_failure_receipt import fingerprint, require_quality_warning_envelope, validate_quality_warning
from .subtitle_translation_provider import SubtitleTranslationCandidate
from .subtitle_quality_recovery import prepare_subtitle_candidate

# 静态生成：ast + inspect.getblock 读取源码；没有导入旧 settings 或运行旧代码。
# dirty 相对基线仅参与合同的两个方法和两个模块增加词汇 phonetics/POS/levels。
MANIFEST = {
    "base_revision": "28696ddd4d7c30c075f03a463013cd6c019a1e62",
    "legacy_config_keys": [
        "subtitle_translation_provider_order",
        "enable_deepseek_vocab_fallback",
        "enable_translation_quality_fail_open",
        "enable_translation_numeric_guard",
        "agy_subtitle_model",
        "deepseek_model",
        "codex_text_model",
        "codex_text_effort",
        "codex_subtitle_batch_size"
    ],
    "profiles": [
        {
            "name": "baseline-28696dd",
            "methods": "d15b1160c77963e2e575b71dd210bd5fc7f23f3a8aefe0184f0b23ab1485dc24",
            "modules": {
                "subtitle_translation_provider": "b664893df8f1db61fe1e0f7c7bcc19aa32f136dd25b049d6c5f7a97692b53184",
                "subtitle_translation_quality": "db36ba5f3be0fe50e29911abc25e9b1ce0a850db5c8b3a4e138829a70e196a6f",
                "subtitle_content_contract": "9dbc3f32ed77c66e804138c4f1633b286a41fa10f18fb1b6fbe48de6e790d650",
                "translation_quality_guard": "2d8eb01f8ba24f30ee44dd631a67269b81817b73c0ab24c74fa7fd13bce737cf",
                "translation_context": "1b14035b1890e3516ecf1289210783bc5da1fff5e30b89e8e74b4b85a78cf59c",
                "translation_candidate_arbitration": "bee812fbee6692e5d4f438cc271179fc44f2e659db5c4bf3c009d65b899a4145",
                "translation_quality_evaluator": "73364b1221e5f4036141e3d46c83454e3ce085cbd367c7cabb23fd7a9aacf7b6",
                "translation_consistency_guard": "242803e50e8e9ea16e7109117f51cc1d7ce15b7f45f59985a978911d0fd47344",
                "translation_fluency_guard": "6798c1f0c644e83334d441e48d32c2dd570577084e36f605cb07d3238c88ac1a",
                "translation_entity_guard": "99080c6074620a8b2ae23e617aafcc368268522bb4f23cf9263ab121f1d4a6ff",
                "translation_prompt_constraints": "90401ceafbf8a184520b9c5ee9008e0f753d5e5acdcf8c71a88ba0bbda765c97",
                "vocab_helper": "ed821d5db1648cf75eb0d4b41843792a59f62fec8b5bf9f6b10d74b6d015ae6d",
                "translation_helper": "aeaa318bc945030bc69b63774b968a11f18072ff6e2a4bf165e06e9315e7f167",
                "deepseek_translation": "1742632acc123f87dca773aa934db84db8695ee32b4baf734e359eea6388ed38",
                "translation_model_pool": "a60ca0dc373d2c63ffa54def5acfa2d07e4e1b74b36ba7092342121039a4ac73",
                "agy_provider": "2fbe28d6cea7ab67f5bc8a9cd56ee2f068d134027436be89d0c08d8d715cb404",
                "codex_subtitle_provider": "e2651433cc03ccde5ec54c916b2847ee59982fa0bf90517f391ae07417828759",
                "codex_text_provider": "129baa32fb32ef88f7f64e30b1257f3eb0697c1e66916e4ed57b5dce6672b57d",
                "subtitle_recovery_state": "a1a27bef4be471764144fb03c4698e1d88356ab4abcf08e0398d05de1115d201",
                "subtitle_failure_receipt": "f18542c3028495636bf0c1ff134c2d5ec213e94e9601b57a32cbbfda03e36ee1",
                "subtitle_audio_review": "1153d5d49cce7f07d753880bd0e4e628eecb479490426ee7ce875cc5b8148ddf",
                "subtitle_audio_review_worker": "c2c88f92e4cb5ecb1ed48438f9f6bcb4448ec2bfd0dbaf01444c78636dde64fb",
                "subtitle_sparse_policy": "1151e1dc22600f8f73418df4df5337ca8ee79caf879801b4b1e5dadff652a184",
                "subtitle_quality_recovery": "ba780fb04edcf7d1067a3cf7e6878e4de9506f546dffcda80c497b96a264883d",
                "subtitle_bad_cases": "d8869449ec21a17a822990d46e2f6b429e5097833c9823e61d7917a1d8cc5fa4"
            },
            "source_files": {
                "src/video_processing/processors/caption_processor.py": "ceeabf0cfce0756efb1afd38c0ff7d932c04ca0c384505ccb1d1c718697ec254"
            }
        },
        {
            "name": "production-vocab-metadata-2026-10-29",
            "methods": "28b79be69479f9de47685303c44d1d49095b7fa75eba245e3f96471b4a098b1a",
            "modules": {
                "subtitle_translation_provider": "8b48e0e5645c15a291915306253f0c11e1be3eef76bf8ab1d813cfc10b1e94ad",
                "subtitle_translation_quality": "db36ba5f3be0fe50e29911abc25e9b1ce0a850db5c8b3a4e138829a70e196a6f",
                "subtitle_content_contract": "9dbc3f32ed77c66e804138c4f1633b286a41fa10f18fb1b6fbe48de6e790d650",
                "translation_quality_guard": "2d8eb01f8ba24f30ee44dd631a67269b81817b73c0ab24c74fa7fd13bce737cf",
                "translation_context": "1b14035b1890e3516ecf1289210783bc5da1fff5e30b89e8e74b4b85a78cf59c",
                "translation_candidate_arbitration": "bee812fbee6692e5d4f438cc271179fc44f2e659db5c4bf3c009d65b899a4145",
                "translation_quality_evaluator": "73364b1221e5f4036141e3d46c83454e3ce085cbd367c7cabb23fd7a9aacf7b6",
                "translation_consistency_guard": "242803e50e8e9ea16e7109117f51cc1d7ce15b7f45f59985a978911d0fd47344",
                "translation_fluency_guard": "6798c1f0c644e83334d441e48d32c2dd570577084e36f605cb07d3238c88ac1a",
                "translation_entity_guard": "99080c6074620a8b2ae23e617aafcc368268522bb4f23cf9263ab121f1d4a6ff",
                "translation_prompt_constraints": "90401ceafbf8a184520b9c5ee9008e0f753d5e5acdcf8c71a88ba0bbda765c97",
                "vocab_helper": "64566fab74d76d4bec8eca5c718e2e0a5826968dd996b21252a0e7191333edc2",
                "translation_helper": "aeaa318bc945030bc69b63774b968a11f18072ff6e2a4bf165e06e9315e7f167",
                "deepseek_translation": "1742632acc123f87dca773aa934db84db8695ee32b4baf734e359eea6388ed38",
                "translation_model_pool": "a60ca0dc373d2c63ffa54def5acfa2d07e4e1b74b36ba7092342121039a4ac73",
                "agy_provider": "2fbe28d6cea7ab67f5bc8a9cd56ee2f068d134027436be89d0c08d8d715cb404",
                "codex_subtitle_provider": "e2651433cc03ccde5ec54c916b2847ee59982fa0bf90517f391ae07417828759",
                "codex_text_provider": "129baa32fb32ef88f7f64e30b1257f3eb0697c1e66916e4ed57b5dce6672b57d",
                "subtitle_recovery_state": "a1a27bef4be471764144fb03c4698e1d88356ab4abcf08e0398d05de1115d201",
                "subtitle_failure_receipt": "f18542c3028495636bf0c1ff134c2d5ec213e94e9601b57a32cbbfda03e36ee1",
                "subtitle_audio_review": "1153d5d49cce7f07d753880bd0e4e628eecb479490426ee7ce875cc5b8148ddf",
                "subtitle_audio_review_worker": "c2c88f92e4cb5ecb1ed48438f9f6bcb4448ec2bfd0dbaf01444c78636dde64fb",
                "subtitle_sparse_policy": "1151e1dc22600f8f73418df4df5337ca8ee79caf879801b4b1e5dadff652a184",
                "subtitle_quality_recovery": "ba780fb04edcf7d1067a3cf7e6878e4de9506f546dffcda80c497b96a264883d",
                "subtitle_bad_cases": "d8869449ec21a17a822990d46e2f6b429e5097833c9823e61d7917a1d8cc5fa4"
            },
            "source_files": {
                "src/video_processing/processors/caption_processor.py": "a174b3a03121ff47e1f6c9c03c32cc9af00ca239e1950ec14e658300422cdb4f",
                "src/video_processing/utils/vocab_helper.py": "64566fab74d76d4bec8eca5c718e2e0a5826968dd996b21252a0e7191333edc2",
                "src/video_processing/utils/subtitle_translation_provider.py": "8b48e0e5645c15a291915306253f0c11e1be3eef76bf8ab1d813cfc10b1e94ad"
            }
        }
    ],
    "target_methods": "40f8decece6ad22a741190b6ae2e997056bb51329975ff2e60386a1d6489d67a",
    "target_modules": {
        "subtitle_translation_provider": "b664893df8f1db61fe1e0f7c7bcc19aa32f136dd25b049d6c5f7a97692b53184",
        "subtitle_translation_quality": "db36ba5f3be0fe50e29911abc25e9b1ce0a850db5c8b3a4e138829a70e196a6f",
        "subtitle_content_contract": "9dbc3f32ed77c66e804138c4f1633b286a41fa10f18fb1b6fbe48de6e790d650",
        "translation_quality_guard": "2d8eb01f8ba24f30ee44dd631a67269b81817b73c0ab24c74fa7fd13bce737cf",
        "translation_context": "1b14035b1890e3516ecf1289210783bc5da1fff5e30b89e8e74b4b85a78cf59c",
        "translation_candidate_arbitration": "bee812fbee6692e5d4f438cc271179fc44f2e659db5c4bf3c009d65b899a4145",
        "translation_quality_evaluator": "73364b1221e5f4036141e3d46c83454e3ce085cbd367c7cabb23fd7a9aacf7b6",
        "translation_consistency_guard": "242803e50e8e9ea16e7109117f51cc1d7ce15b7f45f59985a978911d0fd47344",
        "translation_fluency_guard": "6798c1f0c644e83334d441e48d32c2dd570577084e36f605cb07d3238c88ac1a",
        "translation_entity_guard": "99080c6074620a8b2ae23e617aafcc368268522bb4f23cf9263ab121f1d4a6ff",
        "translation_prompt_constraints": "90401ceafbf8a184520b9c5ee9008e0f753d5e5acdcf8c71a88ba0bbda765c97",
        "vocab_helper": "84fe7d2c303f20f12fcd3a7563449644d4d64c89ef02d8a121ed07c023bdedfb",
        "translation_helper": "bb965eaa8cdccd1e556cea3e6e2b07311902a3e542ea4ede5f5a2327e4be9507",
        "deepseek_translation": "113ec14031b3ca7dfd4ac17afc177ffbed90bd5d216b0cc0e529e7b29cba1e54",
        "translation_model_pool": "7c25f7cd799f837efc174d6e3c35bcf66cc1a4a3cad1a82538b274f13576c270",
        "agy_provider": "7bcdab9bddd7a04c8c0662a50cbc3b084fa7a0a0e0c44940fa7e7d4b15a522cd",
        "codex_subtitle_provider": "9e405b01c87a83ee81335b46bcc6ed7348c8c160dc9362f9c4b7cb5abeeb5be6",
        "codex_text_provider": "11cf850aaa6d41df6cb2c559af2823d8ff2f2b2cab6cd73fff46f8870fb7baf4",
        "subtitle_recovery_state": "a1a27bef4be471764144fb03c4698e1d88356ab4abcf08e0398d05de1115d201",
        "subtitle_failure_receipt": "f18542c3028495636bf0c1ff134c2d5ec213e94e9601b57a32cbbfda03e36ee1",
        "subtitle_audio_review": "1153d5d49cce7f07d753880bd0e4e628eecb479490426ee7ce875cc5b8148ddf",
        "subtitle_audio_review_worker": "c2c88f92e4cb5ecb1ed48438f9f6bcb4448ec2bfd0dbaf01444c78636dde64fb",
        "subtitle_sparse_policy": "1151e1dc22600f8f73418df4df5337ca8ee79caf879801b4b1e5dadff652a184",
        "subtitle_quality_recovery": "ba780fb04edcf7d1067a3cf7e6878e4de9506f546dffcda80c497b96a264883d",
        "subtitle_bad_cases": "d8869449ec21a17a822990d46e2f6b429e5097833c9823e61d7917a1d8cc5fa4",
        "subtitle_translation_budget": "75b256bb55acfe9d9c479c2e1b1d5e3d8f54f76fadab2e0a7390ac486c640579",
        "subtitle_batch_cache": "820299ff78e3e1424afdfdc0e1766a1f851ff87d37ee401e6fbd1a567f2e81a9",
        "subtitle_provider_inventory": "1369cba1a30c7cec37027e8b39f21263e3afe0a4575904251a7717a3af58241f"
    },
    "additional_targets": [
        {
            "methods": "931bce77a74ed140cf57aaabbd1d515f2bf96eeb147b9a2801e679c21564c86c",
            "modules": {
                "subtitle_translation_provider": "8b48e0e5645c15a291915306253f0c11e1be3eef76bf8ab1d813cfc10b1e94ad",
                "subtitle_translation_quality": "db36ba5f3be0fe50e29911abc25e9b1ce0a850db5c8b3a4e138829a70e196a6f",
                "subtitle_content_contract": "9dbc3f32ed77c66e804138c4f1633b286a41fa10f18fb1b6fbe48de6e790d650",
                "translation_quality_guard": "2d8eb01f8ba24f30ee44dd631a67269b81817b73c0ab24c74fa7fd13bce737cf",
                "translation_context": "1b14035b1890e3516ecf1289210783bc5da1fff5e30b89e8e74b4b85a78cf59c",
                "translation_candidate_arbitration": "bee812fbee6692e5d4f438cc271179fc44f2e659db5c4bf3c009d65b899a4145",
                "translation_quality_evaluator": "73364b1221e5f4036141e3d46c83454e3ce085cbd367c7cabb23fd7a9aacf7b6",
                "translation_consistency_guard": "242803e50e8e9ea16e7109117f51cc1d7ce15b7f45f59985a978911d0fd47344",
                "translation_fluency_guard": "6798c1f0c644e83334d441e48d32c2dd570577084e36f605cb07d3238c88ac1a",
                "translation_entity_guard": "99080c6074620a8b2ae23e617aafcc368268522bb4f23cf9263ab121f1d4a6ff",
                "translation_prompt_constraints": "90401ceafbf8a184520b9c5ee9008e0f753d5e5acdcf8c71a88ba0bbda765c97",
                "vocab_helper": "e4c7a8ed2f1fef3ad1893c2c2754455483a50bea13a0e9fa6cee86d8cb122a2a",
                "translation_helper": "f705fe99b8a389758e8621592b04db1b22155e197ea5009c7d37caa96cccf8bb",
                "deepseek_translation": "113ec14031b3ca7dfd4ac17afc177ffbed90bd5d216b0cc0e529e7b29cba1e54",
                "translation_model_pool": "a60ca0dc373d2c63ffa54def5acfa2d07e4e1b74b36ba7092342121039a4ac73",
                "agy_provider": "2fbe28d6cea7ab67f5bc8a9cd56ee2f068d134027436be89d0c08d8d715cb404",
                "codex_subtitle_provider": "9e405b01c87a83ee81335b46bcc6ed7348c8c160dc9362f9c4b7cb5abeeb5be6",
                "codex_text_provider": "129baa32fb32ef88f7f64e30b1257f3eb0697c1e66916e4ed57b5dce6672b57d",
                "subtitle_recovery_state": "a1a27bef4be471764144fb03c4698e1d88356ab4abcf08e0398d05de1115d201",
                "subtitle_failure_receipt": "f18542c3028495636bf0c1ff134c2d5ec213e94e9601b57a32cbbfda03e36ee1",
                "subtitle_audio_review": "1153d5d49cce7f07d753880bd0e4e628eecb479490426ee7ce875cc5b8148ddf",
                "subtitle_audio_review_worker": "c2c88f92e4cb5ecb1ed48438f9f6bcb4448ec2bfd0dbaf01444c78636dde64fb",
                "subtitle_sparse_policy": "1151e1dc22600f8f73418df4df5337ca8ee79caf879801b4b1e5dadff652a184",
                "subtitle_quality_recovery": "ba780fb04edcf7d1067a3cf7e6878e4de9506f546dffcda80c497b96a264883d",
                "subtitle_bad_cases": "d8869449ec21a17a822990d46e2f6b429e5097833c9823e61d7917a1d8cc5fa4",
                "subtitle_translation_budget": "75b256bb55acfe9d9c479c2e1b1d5e3d8f54f76fadab2e0a7390ac486c640579",
                "subtitle_batch_cache": "820299ff78e3e1424afdfdc0e1766a1f851ff87d37ee401e6fbd1a567f2e81a9",
                "subtitle_provider_inventory": "1369cba1a30c7cec37027e8b39f21263e3afe0a4575904251a7717a3af58241f"
            }
        },
        {
            "methods": "72d80fd1c41687c16f5ffb8d65ce88884318fe59fc4211816dc80bd034529437",
            "modules": {
                "subtitle_translation_provider": "b664893df8f1db61fe1e0f7c7bcc19aa32f136dd25b049d6c5f7a97692b53184",
                "subtitle_translation_quality": "db36ba5f3be0fe50e29911abc25e9b1ce0a850db5c8b3a4e138829a70e196a6f",
                "subtitle_content_contract": "9dbc3f32ed77c66e804138c4f1633b286a41fa10f18fb1b6fbe48de6e790d650",
                "translation_quality_guard": "2d8eb01f8ba24f30ee44dd631a67269b81817b73c0ab24c74fa7fd13bce737cf",
                "translation_context": "1b14035b1890e3516ecf1289210783bc5da1fff5e30b89e8e74b4b85a78cf59c",
                "translation_candidate_arbitration": "bee812fbee6692e5d4f438cc271179fc44f2e659db5c4bf3c009d65b899a4145",
                "translation_quality_evaluator": "73364b1221e5f4036141e3d46c83454e3ce085cbd367c7cabb23fd7a9aacf7b6",
                "translation_consistency_guard": "242803e50e8e9ea16e7109117f51cc1d7ce15b7f45f59985a978911d0fd47344",
                "translation_fluency_guard": "6798c1f0c644e83334d441e48d32c2dd570577084e36f605cb07d3238c88ac1a",
                "translation_entity_guard": "99080c6074620a8b2ae23e617aafcc368268522bb4f23cf9263ab121f1d4a6ff",
                "translation_prompt_constraints": "90401ceafbf8a184520b9c5ee9008e0f753d5e5acdcf8c71a88ba0bbda765c97",
                "vocab_helper": "84fe7d2c303f20f12fcd3a7563449644d4d64c89ef02d8a121ed07c023bdedfb",
                "translation_helper": "bb965eaa8cdccd1e556cea3e6e2b07311902a3e542ea4ede5f5a2327e4be9507",
                "deepseek_translation": "113ec14031b3ca7dfd4ac17afc177ffbed90bd5d216b0cc0e529e7b29cba1e54",
                "translation_model_pool": "7c25f7cd799f837efc174d6e3c35bcf66cc1a4a3cad1a82538b274f13576c270",
                "agy_provider": "7bcdab9bddd7a04c8c0662a50cbc3b084fa7a0a0e0c44940fa7e7d4b15a522cd",
                "codex_subtitle_provider": "6cdb378853c93aef03097c3fda6b16e5e105ff0fe7b9b5743c1580b29d9c4f39",
                "codex_text_provider": "e671230f081830ecf23e7804c001e86b87339bc61500be540e1c371cba5f2c54",
                "subtitle_recovery_state": "21e302e7de42a4788dc160b65dc7342ac8b7f4099eebb3782bbbae15efa94c66",
                "subtitle_failure_receipt": "f18542c3028495636bf0c1ff134c2d5ec213e94e9601b57a32cbbfda03e36ee1",
                "subtitle_audio_review": "1153d5d49cce7f07d753880bd0e4e628eecb479490426ee7ce875cc5b8148ddf",
                "subtitle_audio_review_worker": "c2c88f92e4cb5ecb1ed48438f9f6bcb4448ec2bfd0dbaf01444c78636dde64fb",
                "subtitle_sparse_policy": "1151e1dc22600f8f73418df4df5337ca8ee79caf879801b4b1e5dadff652a184",
                "subtitle_quality_recovery": "ba780fb04edcf7d1067a3cf7e6878e4de9506f546dffcda80c497b96a264883d",
                "subtitle_bad_cases": "d8869449ec21a17a822990d46e2f6b429e5097833c9823e61d7917a1d8cc5fa4",
                "subtitle_translation_budget": "ad8b4d8f4a7de8f50e1a140ecc07b3970f0fdae1d5b219785c5755636286193d",
                "subtitle_batch_cache": "820299ff78e3e1424afdfdc0e1766a1f851ff87d37ee401e6fbd1a567f2e81a9",
                "subtitle_provider_inventory": "a1ce3c8f24b894bec91c59cdd41909140a36bfbc82012f30ec5fe30c827fa887"
            }
        },
        {
            "methods": "72d80fd1c41687c16f5ffb8d65ce88884318fe59fc4211816dc80bd034529437",
            "modules": {
                "subtitle_translation_provider": "b664893df8f1db61fe1e0f7c7bcc19aa32f136dd25b049d6c5f7a97692b53184",
                "subtitle_translation_quality": "db36ba5f3be0fe50e29911abc25e9b1ce0a850db5c8b3a4e138829a70e196a6f",
                "subtitle_content_contract": "9dbc3f32ed77c66e804138c4f1633b286a41fa10f18fb1b6fbe48de6e790d650",
                "translation_quality_guard": "2d8eb01f8ba24f30ee44dd631a67269b81817b73c0ab24c74fa7fd13bce737cf",
                "translation_context": "1b14035b1890e3516ecf1289210783bc5da1fff5e30b89e8e74b4b85a78cf59c",
                "translation_candidate_arbitration": "bee812fbee6692e5d4f438cc271179fc44f2e659db5c4bf3c009d65b899a4145",
                "translation_quality_evaluator": "73364b1221e5f4036141e3d46c83454e3ce085cbd367c7cabb23fd7a9aacf7b6",
                "translation_consistency_guard": "242803e50e8e9ea16e7109117f51cc1d7ce15b7f45f59985a978911d0fd47344",
                "translation_fluency_guard": "6798c1f0c644e83334d441e48d32c2dd570577084e36f605cb07d3238c88ac1a",
                "translation_entity_guard": "99080c6074620a8b2ae23e617aafcc368268522bb4f23cf9263ab121f1d4a6ff",
                "translation_prompt_constraints": "90401ceafbf8a184520b9c5ee9008e0f753d5e5acdcf8c71a88ba0bbda765c97",
                "vocab_helper": "84fe7d2c303f20f12fcd3a7563449644d4d64c89ef02d8a121ed07c023bdedfb",
                "translation_helper": "bb965eaa8cdccd1e556cea3e6e2b07311902a3e542ea4ede5f5a2327e4be9507",
                "deepseek_translation": "113ec14031b3ca7dfd4ac17afc177ffbed90bd5d216b0cc0e529e7b29cba1e54",
                "translation_model_pool": "7c25f7cd799f837efc174d6e3c35bcf66cc1a4a3cad1a82538b274f13576c270",
                "agy_provider": "7bcdab9bddd7a04c8c0662a50cbc3b084fa7a0a0e0c44940fa7e7d4b15a522cd",
                "codex_subtitle_provider": "83d712b59f4168e1929e9a31e2d19d4d705acf1c4575bd2e25a4f325c6e235a7",
                "codex_text_provider": "e671230f081830ecf23e7804c001e86b87339bc61500be540e1c371cba5f2c54",
                "subtitle_recovery_state": "21e302e7de42a4788dc160b65dc7342ac8b7f4099eebb3782bbbae15efa94c66",
                "subtitle_failure_receipt": "f18542c3028495636bf0c1ff134c2d5ec213e94e9601b57a32cbbfda03e36ee1",
                "subtitle_audio_review": "1153d5d49cce7f07d753880bd0e4e628eecb479490426ee7ce875cc5b8148ddf",
                "subtitle_audio_review_worker": "c2c88f92e4cb5ecb1ed48438f9f6bcb4448ec2bfd0dbaf01444c78636dde64fb",
                "subtitle_sparse_policy": "1151e1dc22600f8f73418df4df5337ca8ee79caf879801b4b1e5dadff652a184",
                "subtitle_quality_recovery": "ba780fb04edcf7d1067a3cf7e6878e4de9506f546dffcda80c497b96a264883d",
                "subtitle_bad_cases": "d8869449ec21a17a822990d46e2f6b429e5097833c9823e61d7917a1d8cc5fa4",
                "subtitle_translation_budget": "ad8b4d8f4a7de8f50e1a140ecc07b3970f0fdae1d5b219785c5755636286193d",
                "subtitle_batch_cache": "820299ff78e3e1424afdfdc0e1766a1f851ff87d37ee401e6fbd1a567f2e81a9",
                "subtitle_provider_inventory": "67afbc48eecb3dac56d55654320d67534622101c2f631113c4830e368fcc74bb"
            }
        }
    ]
}

def reviewed_target_contracts():
    """目标也逐个精确审查；联合生产词汇元数据版本不能通配跳过模块。"""
    return [dict(methods=MANIFEST['target_methods'], modules=MANIFEST['target_modules']),
            *MANIFEST.get('additional_targets', [])]


def _profile(old, target):
    previous, current = old.get('translation', {}), target.get('translation', {})
    outer = {'asr_sha256', 'src_lang', 'detected_lang', 'target_lang', 'translation'}
    if set(old) != outer or set(target) != outer:
        return None
    if any(old[key] != target[key] for key in outer - {'translation'}):
        return None
    if set(previous) != {'version', 'methods', 'modules', 'config'} or previous['version'] != 1:
        return None
    if current.get('version') != 1:
        return None
    # 本适配器自身摘要可进入完成合同，但不能把未知目标模块偷偷排除掉。
    current_modules = dict(current.get('modules') or {})
    current_modules.pop('caption_legacy_contract', None)
    if not any(current.get('methods') == reviewed['methods'] and current_modules == reviewed['modules']
               for reviewed in reviewed_target_contracts()):
        return None
    keys = MANIFEST['legacy_config_keys']
    if set(previous.get('config') or {}) != set(keys):
        return None
    if previous['config'] != {key: (current.get('config') or {}).get(key) for key in keys}:
        return None
    return next((profile for profile in MANIFEST['profiles']
                 if previous['methods'] == profile['methods'] and previous['modules'] == profile['modules']), None)


def upgrade_legacy_result(payload, target, source_segments, input_sha256):
    """返回全片复核后的新结果；不识别/不合格返回 None，不触发供应商。"""
    old = payload.get('contract') or {}
    profile = _profile(old, target)
    if profile is None or not source_segments or old['asr_sha256'] != fingerprint(source_segments):
        return None
    result = deepcopy(payload['result'])
    warning = require_quality_warning_envelope(result)
    if warning:
        validate_quality_warning(warning, segments=result['segments'], input_sha256=input_sha256,
            asr_sha256=old['asr_sha256'], contract_sha256=fingerprint(old))
    translations = [segment['zh_text'] for segment in result['segments']]
    vocabs = [segment.get('vocab') or {} for segment in result['segments']]
    history = warning['report'].get('repair_history') or [] if warning else []
    candidate = SubtitleTranslationCandidate(provider='legacy', translations=translations, vocabs=vocabs,
                                              supports_vocab=True, repair_history=history)
    if candidate.contract_error_for(len(source_segments)):
        return None
    candidate = prepare_subtitle_candidate(candidate, source_segments,
        context_text='\n'.join(segment['text'].strip() for segment in source_segments))
    report = candidate.quality_report
    if candidate.vocabs != vocabs:
        return None
    if warning is None:
        if report['status'] != 'clean':
            return None
    else:
        if (report['status'] != 'accepted_with_warnings'
                or report['summary_sha256'] != warning['summary_sha256']):
            return None
        from pathlib import Path
        from .subtitle_bad_cases import load_bad_case, save_bad_case
        reference = warning['bad_case']
        case = load_bad_case(Path(reference['path']), reference['sha256'])['payload']
        upgraded = deepcopy(case)
        upgraded.update(contract_sha256=fingerprint(target),
                        legacy_contract_sha256=fingerprint(old), legacy_case_sha256=reference['sha256'])
        warning['bad_case'] = save_bad_case(Path(reference['path']).parents[2], upgraded)
        validate_quality_warning(warning, segments=result['segments'], input_sha256=input_sha256,
            asr_sha256=target['asr_sha256'], contract_sha256=fingerprint(target))
    result['quality_audit'] = [*(result.get('quality_audit') or []),
        dict(event='legacy_checkpoint_revalidated', profile=profile['name'], status=report['status'],
             previous_contract_sha256=fingerprint(old))]
    return result
