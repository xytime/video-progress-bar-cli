"""Photorealistic pen sprite rendering and natural handwriting motion dynamics.

Implements:
1. High-fidelity pen asset handling with exact mathematical tip rotation.
2. Physically accurate dual-shadow system:
   - Contact shadow (ambient occlusion) anchored directly at nib with zero offset at z=0.
   - Directional progressive cast shadow whose displacement and blur increase along the pen barrel.
3. Natural handwriting motion dynamics:
   - Continuous velocity and acceleration across phrases via monotonic Hermite splines (PCHIP).
   - Physiological micro-tremor with paper friction damping.
   - Elegant hover arcs during breath pauses and curved carriage returns between stanzas.
   - Natural wrist angle pivot (~-2° to -5°).
   - Collision-free tip tracking directly beneath active English words.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of pen physics and dual-shadow system |
| 1.1.0 | 2026-10-08 | Antigravity | Physically anchored dual-shadows, PCHIP trajectory smoothing, zero-clipping padding |
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .contracts import HandwrittenPagerConfig, LyricLine, LyricWord, PenState


def _pchip_interpolate(x: np.ndarray, y: np.ndarray, x_new: np.ndarray) -> np.ndarray:
    """Monotone cubic Hermite interpolation (Fritsch-Carlson). Guaranteed C1 continuity and zero overshoot."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n == 1:
        return np.full_like(x_new, y[0], dtype=float)

    dx = np.diff(x)
    dy = np.diff(y)
    dx = np.where(dx == 0, 1e-6, dx)
    m = dy / dx

    d = np.zeros(n, dtype=float)
    d[0] = m[0]
    d[-1] = m[-1]
    for i in range(1, n - 1):
        if m[i - 1] * m[i] <= 0:
            d[i] = 0.0
        else:
            w1 = 2.0 * dx[i] + dx[i - 1]
            w2 = dx[i] + 2.0 * dx[i - 1]
            d[i] = (w1 + w2) / (w1 / m[i - 1] + w2 / m[i])

    idx = np.searchsorted(x, x_new) - 1
    idx = np.clip(idx, 0, n - 2)
    h = dx[idx]
    t = (x_new - x[idx]) / h
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    return h00 * y[idx] + h10 * h * d[idx] + h01 * y[idx + 1] + h11 * h * d[idx + 1]


class PenPhysicsEngine:
    """Calculates realistic pen trajectories and renders photorealistic pen sprites with dual shadows."""

    def __init__(self, config: Optional[HandwrittenPagerConfig] = None):
        self.config = config or HandwrittenPagerConfig()
        self.config.validate()

        # Load pen sprite asset
        asset_dir = Path(__file__).parent / "assets"
        sprite_path = (
            Path(self.config.pen_sprite_path)
            if self.config.pen_sprite_path
            else (asset_dir / "pen_ballpoint_photorealistic.png")
        )
        if not sprite_path.exists():
            raise FileNotFoundError(f"Pen sprite asset not found at {sprite_path}")

        meta_path = asset_dir / "pen_metadata.json"
        metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

        raw_sprite = Image.open(sprite_path).convert("RGBA")
        target_w = self.config.pen_width
        self.scale = target_w / raw_sprite.width
        target_h = int(raw_sprite.height * self.scale)
        self.pen_base = raw_sprite.resize((target_w, target_h), Image.Resampling.LANCZOS)

        # Base tip coordinates
        if "tip_x" in metadata and "tip_y" in metadata:
            self.tip_x = int(metadata["tip_x"] * self.scale)
            self.tip_y = int(metadata["tip_y"] * self.scale)
        else:
            arr = np.array(self.pen_base)
            y_idx, x_idx = np.where(arr[:, :, 3] > 100)
            min_idx = np.argmin(x_idx + y_idx)
            self.tip_x = int(x_idx[min_idx])
            self.tip_y = int(y_idx[min_idx])

        self.base_angle = metadata.get("base_angle_deg", -3.0)

        # Precompute base shadow mask templates
        p_alpha = np.array(self.pen_base.getchannel("A"), dtype=np.float32) / 255.0
        h, w = p_alpha.shape
        yy, xx = np.mgrid[:h, :w]
        dist_from_tip = np.maximum(0.0, ((xx - self.tip_x) + (yy - self.tip_y)) / np.sqrt(2.0))

        # Contact mask: tightly concentrated at the nib
        self.contact_mask_base = p_alpha * np.exp(-dist_from_tip / 28.0)
        # Body mask: progressive along the barrel
        self.body_mask_base = p_alpha * (1.0 - np.exp(-dist_from_tip / 22.0))

        # Cache for rotated sprites, tip coordinates, and matching masks
        self._rotation_cache: Dict[float, Tuple[Image.Image, int, int, np.ndarray, np.ndarray]] = {}

    def _get_rotated_bundle(self, angle_deg: float) -> Tuple[Image.Image, int, int, np.ndarray, np.ndarray]:
        """Returns rotated pen sprite, exact transformed tip coordinate, and matching shadow masks."""
        angle_key = round(angle_deg * 5.0) / 5.0  # 0.2 degree quantization
        if angle_key in self._rotation_cache:
            return self._rotation_cache[angle_key]

        if abs(angle_key) < 0.05:
            rot = self.pen_base
            cur_tip_x, cur_tip_y = self.tip_x, self.tip_y
        else:
            rot = self.pen_base.rotate(angle_key, resample=Image.Resampling.BICUBIC, expand=True)
            w, h = self.pen_base.size
            cx_orig, cy_orig = (w - 1) / 2.0, (h - 1) / 2.0
            rad = np.radians(angle_key)
            cos_a, sin_a = np.cos(rad), np.sin(rad)
            rx = cos_a * (self.tip_x - cx_orig) + sin_a * (self.tip_y - cy_orig)
            ry = -sin_a * (self.tip_x - cx_orig) + cos_a * (self.tip_y - cy_orig)
            new_w, new_h = rot.size
            cur_tip_x = int(round(rx + (new_w - 1) / 2.0))
            cur_tip_y = int(round(ry + (new_h - 1) / 2.0))

        p_alpha = np.array(rot.getchannel("A"), dtype=np.float32) / 255.0
        ph, pw = p_alpha.shape
        yy, xx = np.mgrid[:ph, :pw]
        dist = np.maximum(0.0, ((xx - cur_tip_x) + (yy - cur_tip_y)) / np.sqrt(2.0))
        contact_mask = p_alpha * np.exp(-dist / 28.0)
        body_mask = p_alpha * (1.0 - np.exp(-dist / 22.0))

        res = (rot, cur_tip_x, cur_tip_y, contact_mask, body_mask)
        self._rotation_cache[angle_key] = res
        return res

    def compute_trajectory(
        self,
        lines: List[LyricLine],
        total_duration: float,
        fps: Optional[int] = None,
    ) -> List[PenState]:
        """Calculates smooth C1 continuous pen trajectory for every frame in the video."""
        fps = fps or self.config.fps
        total_frames = int(math.ceil(total_duration * fps))

        if not lines:
            return [
                PenState(
                    frame_idx=i,
                    t=i / fps,
                    x=540.0,
                    y=960.0,
                    z=20.0,
                    angle_deg=self.base_angle,
                    is_active=False,
                )
                for i in range(total_frames)
            ]

        # 1. Build smooth keyframe sequence for PCHIP interpolation
        keyframes: List[Tuple[float, float, float, float]] = []  # (t, x, y, z)
        first_w = lines[0].words[0]
        first_y = lines[0].y_en + self.config.tip_y_offset

        # Intro approach
        keyframes.append((0.0, first_w.x_start - 60.0, first_y, 14.0))
        t_app = max(0.05, first_w.start_time - 0.25)
        keyframes.append((t_app, first_w.x_start - 20.0, first_y, 5.0))

        for line_idx, line in enumerate(lines):
            ly = line.y_en + self.config.tip_y_offset
            for w_idx, w in enumerate(line.words):
                t_s = max(keyframes[-1][0] + 0.005, w.start_time)
                t_e = max(t_s + 0.01, w.end_time)

                # If this is the last word in the line and next line begins soon:
                if w_idx == len(line.words) - 1 and line_idx < len(lines) - 1:
                    next_start = lines[line_idx + 1].words[0].start_time
                    if next_start - t_e < 0.25:
                        t_e = max(t_s + 0.10, next_start - 0.28)

                keyframes.append((t_s, w.x_start, ly, 0.0))
                keyframes.append((t_e, w.x_end, ly, 0.0))

                # Intra-line word gap
                if w_idx < len(line.words) - 1:
                    next_w = line.words[w_idx + 1]
                    gap = next_w.start_time - t_e
                    if gap > 0.10:
                        t_mid = (t_e + next_w.start_time) / 2.0
                        x_mid = (w.x_end + next_w.x_start) / 2.0
                        keyframes.append((t_mid, x_mid, ly, 3.5))

            # Inter-line carriage return
            if line_idx < len(lines) - 1:
                next_line = lines[line_idx + 1]
                next_first_w = next_line.words[0]
                next_ly = next_line.y_en + self.config.tip_y_offset

                t_ret_start = keyframes[-1][0]
                t_ret_end = next_first_w.start_time
                t_mid = (t_ret_start + t_ret_end) / 2.0
                x_mid = (keyframes[-1][1] + next_first_w.x_start) / 2.0
                y_mid = (ly + next_ly) / 2.0
                keyframes.append((t_mid, x_mid, y_mid, 14.0))

        # Outro lift
        last_w = lines[-1].words[-1]
        last_y = lines[-1].y_en + self.config.tip_y_offset
        t_last = keyframes[-1][0]
        keyframes.append((t_last + 0.35, last_w.x_end + 30.0, last_y - 10.0, 10.0))
        keyframes.append((total_duration + 0.1, last_w.x_end + 50.0, last_y - 15.0, 18.0))

        # Sort and deduplicate keyframes
        k_t, k_x, k_y, k_z = [], [], [], []
        for pt in sorted(keyframes, key=lambda p: p[0]):
            if not k_t or pt[0] > k_t[-1] + 1e-4:
                k_t.append(pt[0])
                k_x.append(pt[1])
                k_y.append(pt[2])
                k_z.append(pt[3])

        t_eval = np.linspace(0.0, total_duration, total_frames)
        x_eval = _pchip_interpolate(np.array(k_t), np.array(k_x), t_eval)
        y_eval = _pchip_interpolate(np.array(k_t), np.array(k_y), t_eval)
        z_eval = np.maximum(0.0, _pchip_interpolate(np.array(k_t), np.array(k_z), t_eval))

        # Flatten word list for active word tagging
        all_words_list: List[LyricWord] = []
        for line in lines:
            all_words_list.extend(line.words)

        states: List[PenState] = []
        for f_idx in range(total_frames):
            t = float(t_eval[f_idx])
            raw_x = float(x_eval[f_idx])
            raw_y = float(y_eval[f_idx])
            raw_z = float(z_eval[f_idx])

            # Physiological human micro-tremor
            jitter_x = 0.40 * math.sin(2 * math.pi * 9.1 * t + 1.2) + 0.25 * math.cos(2 * math.pi * 13.5 * t + 2.5)
            jitter_y = 0.35 * math.cos(2 * math.pi * 8.7 * t + 0.8) + 0.20 * math.sin(2 * math.pi * 14.1 * t + 3.1)
            damping = 0.35 if raw_z < 0.5 else 0.80

            final_x = max(0.0, min(float(self.config.width), raw_x + jitter_x * damping))
            final_y = max(0.0, min(float(self.config.height), raw_y + jitter_y * damping))
            final_z = max(0.0, raw_z)

            # Wrist angle pivot across canvas
            wrist_pivot = ((final_x - 540.0) / 540.0) * 2.5
            angle_deg = max(-6.0, min(1.0, self.base_angle + wrist_pivot))

            # Determine active word
            active_word_name = None
            is_active = False
            if final_z < 1.0:
                for w in all_words_list:
                    if w.start_time <= t <= w.end_time:
                        active_word_name = w.word
                        is_active = True
                        break

            states.append(
                PenState(
                    frame_idx=f_idx,
                    t=t,
                    x=final_x,
                    y=final_y,
                    z=final_z,
                    angle_deg=angle_deg,
                    is_active=is_active,
                    active_word=active_word_name,
                )
            )

        return states

    def render_pen_frame(self, canvas: Image.Image, state: PenState) -> Image.Image:
        """Composites pen and photorealistic dual shadows onto canvas."""
        frame = canvas.copy()

        # Dynamic rotation with exact tip mathematics and cached matching masks
        cur_pen, cur_tip_x, cur_tip_y, contact_mask, body_mask = self._get_rotated_bundle(state.angle_deg)
        w, h = cur_pen.size

        pen_left = int(round(state.x - cur_tip_x))
        pen_top = int(round(state.y - state.z - cur_tip_y))

        # --- PHYSICALLY ACCURATE DUAL SHADOW SYSTEM ---
        pad = 60  # generous padding to completely prevent bounding-box shadow clipping

        # 1. Proximal Contact Shadow (Ambient Occlusion)
        # Directly anchored at the nib contact point. When z=0, offset is (0, 0)!
        c_fade = max(0.0, 1.0 - state.z / 6.0)
        c_off_x = int(round(state.z * 0.5))
        c_off_y = int(round(state.z * 0.7))

        # 2. Directional Progressive Body Shadow (Cast Shadow)
        # Displacement and blur increase along the barrel
        b_off_x = int(round(state.z * 0.7 + 9.0))
        b_off_y = int(round(state.z * 0.9 + 13.0))

        shadow_layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))

        # Composite diffuse body shadow
        b_img = Image.fromarray((body_mask * 105.0).astype(np.uint8))
        b_rgba = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        b_col = Image.new("RGBA", (w, h), (30, 24, 18, 255))
        b_col.putalpha(b_img)
        b_rgba.paste(b_col, (pad, pad))
        b_blurred = b_rgba.filter(ImageFilter.GaussianBlur(6.5 + state.z * 0.6))
        shadow_layer.alpha_composite(
            b_blurred,
            (pen_left + b_off_x - pad, pen_top + b_off_y + int(round(state.z)) - pad),
        )

        # Composite proximal contact shadow if close to paper
        if c_fade > 0.05:
            c_img = Image.fromarray((contact_mask * (175.0 * c_fade)).astype(np.uint8))
            c_rgba = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
            c_col = Image.new("RGBA", (w, h), (25, 20, 15, 255))
            c_col.putalpha(c_img)
            c_rgba.paste(c_col, (pad, pad))
            c_blurred = c_rgba.filter(ImageFilter.GaussianBlur(1.8 + state.z * 0.3))
            shadow_layer.alpha_composite(
                c_blurred,
                (pen_left + c_off_x - pad, pen_top + c_off_y + int(round(state.z)) - pad),
            )

        # Composite shadows then pen sprite
        frame.alpha_composite(shadow_layer)
        frame.alpha_composite(cur_pen, (pen_left, pen_top))

        return frame
