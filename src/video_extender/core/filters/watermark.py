"""Watermark filter — overlay PNG/JPG image on video."""
from __future__ import annotations

from typing import Any

from video_extender.core.filters.base import Filter, FilterFragment


class WatermarkFilter(Filter):
    name = "watermark"
    label = "Logo / Filigran"

    # Position presets → ffmpeg overlay x:y expressions
    POSITIONS = {
        "top-left":      ("10", "10"),
        "top-right":     ("W-w-10", "10"),
        "bottom-left":   ("10", "H-h-10"),
        "bottom-right":  ("W-w-10", "H-h-10"),
        "center":        ("(W-w)/2", "(H-h)/2"),
    }

    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        opts = options or {}
        image = opts.get("image")
        if not image:
            return FilterFragment()  # disabled

        position = opts.get("position", "bottom-right")
        opacity = float(opts.get("opacity", 0.8))
        scale_pct = float(opts.get("scale", 0.15))  # 15% of MAIN video width
        main_width = int(opts.get("_main_width", 0))
        # _main_width is injected by the pipeline from job.media.video.width.
        # Computing target px against the main video makes the watermark
        # visually consistent regardless of logo image dimensions.
        if main_width <= 0:
            target_w_expr = "iw"
        else:
            target_w_expr = str(max(1, int(main_width * scale_pct)))

        x_expr, y_expr = self.POSITIONS.get(position, self.POSITIONS["bottom-right"])
        in_idx = next_input_index
        out_v = f"[vw{in_idx}]"

        # -loop 1 ensures the still image is repeated for the whole video duration;
        # without it, overlay shows the logo on the first frame only.
        seg = (
            f"[{in_idx}:v]format=rgba,colorchannelmixer=aa={opacity:.3f},"
            f"scale={target_w_expr}:-1[wm{in_idx}];"
            f"{in_video}[wm{in_idx}]overlay={x_expr}:{y_expr}:shortest=0{out_v}"
        )
        return FilterFragment(
            prefix_input_args=("-loop", "1"),
            extra_inputs=(str(image),),
            filter_segment=seg,
            new_video_label=out_v,
        )

    def build_hw(
        self,
        namespace: str,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment | None:
        """CUDA variant: watermark is scaled on CPU (small image, fast),
        uploaded to GPU, then composited via overlay_cuda. Main stream is
        expected to be already in CUDA memory.

        Verified on RTX 3070 + ffmpeg n8.1.1: 50% CPU usage vs 172% on
        equivalent CPU chain, ~10% wall-time reduction on 1080p — much
        bigger gains expected on 4K and on multi-job batches where CPU
        contention matters.
        """
        if namespace != "cuda":
            return None
        opts = options or {}
        image = opts.get("image")
        if not image:
            return FilterFragment()

        position = opts.get("position", "bottom-right")
        opacity = float(opts.get("opacity", 0.8))
        scale_pct = float(opts.get("scale", 0.15))
        main_width = int(opts.get("_main_width", 0))
        if main_width <= 0:
            target_w_expr = "iw"
        else:
            target_w_expr = str(max(1, int(main_width * scale_pct)))

        x_expr, y_expr = self.POSITIONS.get(position, self.POSITIONS["bottom-right"])
        in_idx = next_input_index
        out_v = f"[vw{in_idx}]"
        # Stream pipeline:
        #   logo (CPU) → format=rgba → opacity adjust → scale (CPU) →
        #     hwupload_cuda → CUDA frame [wm{idx}]
        #   main (CUDA) [wm{idx}] → overlay_cuda → out
        seg = (
            f"[{in_idx}:v]format=rgba,colorchannelmixer=aa={opacity:.3f},"
            f"scale={target_w_expr}:-1,format=yuv420p,hwupload_cuda[wm{in_idx}];"
            f"{in_video}[wm{in_idx}]overlay_cuda=x={x_expr}:y={y_expr}{out_v}"
        )
        return FilterFragment(
            prefix_input_args=("-loop", "1"),
            extra_inputs=(str(image),),
            filter_segment=seg,
            new_video_label=out_v,
        )
