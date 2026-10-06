"""本地双语跟读 DAG 编排；不会触及发现队列或任何发布平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 以 Timeline 输入连接证据、独立阶段缓存、母带和成片 QA |
"""
from copy import deepcopy
import json
from pathlib import Path
import time

from video_processing.follow_along.audio import MediaTools
from video_processing.follow_along.alignment import accept_supplied_alignment, apply_word_results
from video_processing.follow_along.cache import StageCache
from video_processing.follow_along.contracts import PipelineError, digest, validate, verify_ref
from video_processing.follow_along.layout import LayoutCompiler
from video_processing.follow_along.qa import preflight, final_media
from video_processing.follow_along.renderer import Renderer


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    temporary.replace(path)


class FollowAlongPipeline:
    """生产入口仅消费本地哈希资产；模型执行端口独立于本地制作入口。"""
    def __init__(self, root: Path, tools: MediaTools, aligner=None):
        self.root = root.resolve()
        self.tools = tools
        self.aligner = aligner
        domain = Path(__file__).parent / "follow_along"
        modules = {"prepare": ["audio.py"], "separate": ["audio.py"], "align": ["alignment.py", "contracts.py", "whisperx_adapter.py"],
                   "resolve": ["layout.py", "font_coverage.py", "timing.py", "chunking.py"], "mix": ["audio.py"],
                   "preflight": ["qa.py", "contracts.py", "timing.py"], "render": ["renderer.py", "timing.py"],
                   "package": ["qa.py", "audio.py"]}
        revisions = {stage: {name: digest(domain / name) for name in names} for stage, names in modules.items()}
        import PIL
        revisions["resolve"]["pillow"] = PIL.__version__
        self.cache = StageCache(self.root / ".follow-along/cache", revisions=revisions)

    def run(self, job_spec: dict, target_stage="package", resume=True):
        if target_stage not in {"align", "resolve", "render", "package"}:
            raise ValueError("target_stage 必须为 align/resolve/render/package")
        stages = []
        receipt = {"state": "RUNNING", "target_stage": target_stage, "stages": stages}
        receipt_path = self.root / ".follow-along" / f"receipt-{time.time_ns()}.json"
        def stage(name, inputs, callback):
            stages.append({"stage": name, "key": self.cache.key(name, inputs), "state": "RUNNING"})
            write_json(receipt_path, receipt)
            try:
                path, record = self.cache.run(name, inputs, callback, resume)
            except BaseException:
                stages[-1]["state"] = "FAILED"
                raise
            stages[-1] = record
            write_json(receipt_path, receipt)
            return path
        try:
            validate(job_spec, self.root)
            assets = {a["id"]: a for a in job_spec["assets"]}
            tracks = {t["role"]: t for t in job_spec["tracks"]}
            clock = job_spec["clock"]
            ticks = clock["ticks_per_second"]
            for role in ("performer", "source_master", "render_master"):
                if role not in tracks or len(tracks[role]["clips"]) != 1:
                    raise PipelineError("INPUT_INVALID", f"首版要求唯一单 clip {role}")
                clip = tracks[role]["clips"][0]
                if clip["timeline_interval"] != {"start_tick": 0, "end_tick": job_spec["metadata"]["duration_tick"]}:
                    raise PipelineError("SOURCE_MAPPING_AMBIGUOUS", f"{role} 必须覆盖全程")
                media_asset = assets[clip["asset_id"]]
                if media_asset.get("pts_origin_tick", 0) != 0:
                    raise PipelineError("SOURCE_MAPPING_AMBIGUOUS", "首版非零 PTS 起点需先规范化并保存来源映射")
                probe = self.tools.probe(verify_ref(self.root, media_asset))
                kind = "video" if role == "performer" else "audio"
                streams = [s for s in probe["streams"] if s["codec_type"] == kind]
                if len(streams) != 1 or streams[0]["index"] != media_asset.get("stream_index", streams[0]["index"]):
                    raise PipelineError("SOURCE_MAPPING_AMBIGUOUS", "媒体流选择不明确")
                if float(probe["format"]["duration"]) + 0.002 < clip["source_interval"]["end_tick"] / ticks:
                    raise PipelineError("INPUT_INVALID", f"{role} 素材实际时长不足")
            import subprocess
            version = subprocess.check_output([self.tools.ffmpeg, "-version"], text=True, timeout=30).splitlines()[0]
            source_clip = tracks["source_master"]["clips"][0]
            source_asset = assets[source_clip["asset_id"]]
            source_path = verify_ref(self.root, source_asset)
            def prepare(directory):
                probe = self.tools.prepare(source_path, source_clip["source_interval"]["start_tick"], source_clip["source_interval"]["end_tick"], ticks, directory)
                write_json(directory / "probe.json", probe)
            prepared = stage("prepare", {"asset": source_asset, "clip": source_clip, "ticks": ticks, "ffmpeg": version}, prepare)
            analysis = prepared / "alignment.wav"
            if self.aligner is not None:
                if "alignment_vocals" not in tracks or len(tracks["alignment_vocals"]["clips"]) != 1:
                    raise PipelineError("STEM_INVALID", "模型对齐要求明确提供人声轨；不能把原混音冒充 clean vocals")
                vocal_clip = tracks["alignment_vocals"]["clips"][0]
                if vocal_clip["timeline_interval"] != source_clip["timeline_interval"]:
                    raise PipelineError("STEM_INVALID", "人声时间映射须覆盖同一输出区间")
                vocal_asset = assets[vocal_clip["asset_id"]]
                def separate(directory):
                    probe = self.tools.prepare(verify_ref(self.root, vocal_asset), vocal_clip["source_interval"]["start_tick"],
                                               vocal_clip["source_interval"]["end_tick"], ticks, directory)
                    if abs(float(probe["format"]["duration"]) - job_spec["metadata"]["duration_tick"] / ticks) > 1/48000:
                        raise PipelineError("STEM_INVALID", "人声轨实际长度不一致")
                    write_json(directory / "report.json", {"separator":"provided-stem", "inference_executed":False, "probe":probe})
                separated = stage("separate", {"asset":vocal_asset,"clip":vocal_clip,"ffmpeg":version}, separate)
                analysis = separated / "alignment.wav"
            alignment_inputs = {"cues": [{k: c[k] for k in ("id", "english_text", "source_asset_id", "source_span", "interval", "words")} for c in job_spec["cues"]],
                                "english_assets": [assets[c["source_asset_id"]] for c in job_spec["cues"]],
                                "clock": clock, "policy": job_spec["policy"]["alignment"],
                                "provider": self.aligner.identity if self.aligner else "supplied-evidence",
                                "analysis_sha256": digest(analysis) if self.aligner else None}
            def align(directory):
                if self.aligner is None:
                    accepted = accept_supplied_alignment(job_spec, self.root)
                    report = {"provider": "supplied-evidence", "inference_executed": False,
                              "analysis_copy_role": "original_mix_16k_not_separated_vocals"}
                else:
                    windows=[]
                    for cue in job_spec["cues"]:
                        if not cue["interval"]:
                            raise PipelineError("ALIGNMENT_AMBIGUOUS", "模型对齐需要粗窗口；请提供每个原句的区间", [cue["id"]])
                        windows.append({**cue["interval"], "word_ids":[w["id"] for w in cue["words"]]})
                    response=self.aligner.align(analysis, [w for c in job_spec["cues"] for w in c["words"]], windows, directory, ticks)
                    response_path=directory / "response.json"
                    final=self.cache.root / "align" / self.cache.key("align", alignment_inputs)
                    evidence={"uri":str((final / "response.json").relative_to(self.root)), "sha256":digest(response_path)}
                    accepted=apply_word_results(job_spec,response,evidence)
                    report={"provider":self.aligner.identity,"inference_executed":True,"actual_device":response["actual_device"]}
                write_json(directory / "alignment.json", [{"id": c["id"], "interval": c["interval"], "words": c["words"]} for c in accepted["cues"]])
                write_json(directory / "report.json", report)
            aligned = stage("align", alignment_inputs, align)
            plan = deepcopy(job_spec)
            for cue, result in zip(plan["cues"], json.loads((aligned / "alignment.json").read_text())):
                cue["interval"], cue["words"] = result["interval"], result["words"]
            plan["phase"] = "aligned"
            report = json.loads((aligned / "report.json").read_text())
            plan["provenance"].append({"component":"follow-along-alignment", "version":"1",
                                       "actual_device":report.get("actual_device", "not_applicable"),
                                       "input_hashes":[{"id":c["source_asset_id"], "sha256":assets[c["source_asset_id"]]["sha256"]} for c in plan["cues"]],
                                       "evidence_ref":{"uri":str((aligned / "report.json").relative_to(self.root)), "sha256":digest(aligned / "report.json")}})
            if self.aligner:
                identity = self.aligner.identity
                plan["policy"]["alignment"].update(adapter=identity["adapter"], model_id=self.aligner.model_directory.name,
                                                     model_revision=identity["package_version"], weights_sha256=identity["weights_sha256"], requested_device="cpu")
            validate(plan, self.root)
            if target_stage == "align":
                receipt.update(state="ALIGNED", alignment=str(aligned / "alignment.json"), report=str(aligned / "report.json"))
                return receipt
            layout_inputs = {"cues": [{k: v for k, v in c.items() if k != "layout"} for c in plan["cues"]],
                             "styles": plan["styles"], "layers": plan["layers"], "canvas": plan["canvas"],
                             "fonts": [a for a in plan["assets"] if a["kind"] == "font"],
                             "policy": {k: plan["policy"][k] for k in ("chunking", "scroll")},
                             "motions": plan["motions"]}
            def resolve(directory):
                output = LayoutCompiler(self.root).compile(plan, directory / "atlases")
                # 图集路径在同卷目录提交后解析，缓存不留下临时目录引用。
                key = self.cache.key("resolve", layout_inputs)
                final = self.cache.root / "resolve" / key
                for cue in output["cues"]:
                    relative = Path(cue["layout"]["atlas_ref"]["uri"]).relative_to(directory.relative_to(self.root))
                    cue["layout"]["atlas_ref"]["uri"] = str((final / relative).relative_to(self.root))
                write_json(directory / "layout.json", {"cues": output["cues"], "layers": output["layers"], "motions": output["motions"]})
            resolved = stage("resolve", layout_inputs, resolve)
            layout = json.loads((resolved / "layout.json").read_text())
            plan.update(layout)
            plan["phase"] = "resolved"
            validate(plan, self.root, resolved=True)
            if target_stage == "resolve":
                receipt.update(state="RESOLVED", layout=str(resolved / "layout.json"))
                return receipt
            def mix(directory):
                vocals, instrumental = None, None
                if plan["policy"]["audio"]["mix_mode"] != "original":
                    for role, name in (("alignment_vocals", "vocals"), ("instrumental", "instrumental")):
                        if role not in tracks or len(tracks[role]["clips"]) != 1:
                            raise PipelineError("STEM_INVALID", "分轨混音缺少单轨 stems")
                        clip = tracks[role]["clips"][0]
                        self.tools.prepare(verify_ref(self.root, assets[clip["asset_id"]]), clip["source_interval"]["start_tick"],
                                           clip["source_interval"]["end_tick"], ticks, directory / name)
                    vocals, instrumental = directory / "vocals/original.wav", directory / "instrumental/original.wav"
                if vocals is not None:
                    for stem in (vocals, instrumental):
                        probe = self.tools.probe(stem)
                        if abs(float(probe["format"]["duration"]) - plan["metadata"]["duration_tick"] / ticks) > 1/48000:
                            raise PipelineError("STEM_INVALID", "分轨解码后长度不一致；需要延迟补偿和完整样本")
                self.tools.master(prepared / "original.wav", plan["policy"]["audio"], directory, vocals=vocals, instrumental=instrumental)
            mix_inputs = {"source": digest(prepared / "original.wav"), "policy": plan["policy"]["audio"], "ffmpeg": version,
                          "stems": [t for t in plan["tracks"] if t["role"] in {"alignment_vocals", "instrumental"}] if plan["policy"]["audio"]["mix_mode"] != "original" else [],
                          "stem_assets": [assets[c["asset_id"]] for t in plan["tracks"] if t["role"] in {"alignment_vocals", "instrumental"} for c in t["clips"]] if plan["policy"]["audio"]["mix_mode"] != "original" else []}
            mixed = stage("mix", mix_inputs, mix)
            master = mixed / "master.wav"
            native = self.tools.probe(master)
            audio = next(s for s in native["streams"] if s["codec_type"] == "audio")
            from fractions import Fraction
            duration_tick = round(Fraction(audio["duration_ts"]) * Fraction(audio["time_base"]) * ticks)
            asset_id = "follow-along-render-master"
            if asset_id in assets:
                raise PipelineError("INPUT_INVALID", "保留的母带 asset ID 与输入冲突")
            plan["assets"].append({"id": asset_id, "kind": "audio", "uri": str(master.relative_to(self.root)), "sha256": digest(master),
                                   "byte_length": master.stat().st_size, "duration_tick": duration_tick,
                                   "sample_rate": 48000, "sample_count": round(Fraction(audio["duration_ts"]) * Fraction(audio["time_base"]) * 48000), "channels": 2,
                                   "native_time_base": {"numerator": 1, "denominator": 48000}, "pts_origin_tick": 0, "stream_index": 0,
                                   "source_asset_id": source_asset["id"], "source_time_map": {"parent_interval": source_clip["source_interval"],
                                       "asset_interval": {"start_tick": 0, "end_tick": plan["metadata"]["duration_tick"]},
                                       "playback_rate": {"numerator": 1, "denominator": 1}, "compensated_delay_tick": 0}})
            master_track = next(t for t in plan["tracks"] if t["role"] == "render_master")
            master_track["clips"][0].update(asset_id=asset_id, source_interval={"start_tick": 0, "end_tick": plan["metadata"]["duration_tick"]})
            validate(plan, self.root, resolved=True)
            def check(directory):
                write_json(directory / "qa.json", preflight(plan))
                write_json(directory / "timeline.json", plan)
            checked = stage("preflight", {"plan": plan, "master": digest(master)}, check)
            def render(directory):
                Renderer(self.tools).render(plan, self.root, master, directory)
            rendered = stage("render", {"timeline": digest(checked / "timeline.json"), "ffmpeg": version}, render)
            if target_stage == "render":
                receipt.update(state="RENDERED_NOT_PACKAGED", video=str(rendered / "video.mp4"))
                return receipt
            def package(directory):
                write_json(directory / "qa.json", final_media(plan, rendered / "video.mp4", self.tools, directory))
            packaged = stage("package", {"video": digest(rendered / "video.mp4"), "plan": plan, "ffmpeg": version}, package)
            receipt.update(state="LOCAL_PACKAGE_READY", video=str(rendered / "video.mp4"), timeline=str(checked / "timeline.json"), qa=str(packaged / "qa.json"))
        except KeyboardInterrupt:
            receipt.update(state="CANCELLED", error={"code":"CANCELLED", "message":"用户中断本地制作"})
        except PipelineError as exc:
            receipt.update(state="NEEDS_REVIEW" if exc.code in {"ALIGNMENT_INCOMPLETE", "ALIGNMENT_AMBIGUOUS", "TRANSLATION_MAPPING_MISSING", "SOURCE_MAPPING_AMBIGUOUS"} else "FAILED", error=exc.report())
        except (OSError, ValueError, KeyError) as exc:
            receipt.update(state="FAILED", error={"code": "INPUT_INVALID", "message": str(exc)})
        finally:
            write_json(receipt_path, receipt)
        return receipt
