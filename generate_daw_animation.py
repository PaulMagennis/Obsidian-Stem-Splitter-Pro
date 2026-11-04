"""
Generate high-fidelity animated GIF of a DAW audio track that slowly separates
into different spectrum stems and loops seamlessly.
"""

import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

def create_daw_spectrum_gif(output_path: str, width=360, height=86, num_frames=72):
    frames = []

    # 7 distinct spectral stem colors (matching the app's 9-stem colors)
    stem_colors = [
        (255, 75, 75),    # Vocals (Red)
        (255, 165, 0),    # Drums (Orange)
        (255, 215, 0),    # Guitar (Gold)
        (0, 255, 102),    # Bass (Neon Green)
        (0, 229, 255),    # Synth/Key (Cyan)
        (153, 51, 255),   # Brass (Purple)
        (255, 51, 153),   # Strings (Magenta)
    ]
    num_stems = len(stem_colors)

    # Generate synthetic music waveform
    np.random.seed(42)
    x_points = np.linspace(0, 4 * np.pi, width)
    # Master waveform combining bass thump, mid harmonic, high chatter
    base_wave = (
        0.55 * np.sin(x_points * 2.5) * np.cos(x_points * 0.7) +
        0.25 * np.sin(x_points * 6.0 + 1.2) +
        0.15 * np.sin(x_points * 14.0) +
        0.10 * np.cos(x_points * 28.0)
    )
    # Normalize base_wave
    base_wave = base_wave / np.max(np.abs(base_wave))

    # Individual stem variations (each frequency band has distinct rhythmic character)
    stem_waves = []
    for i in range(num_stems):
        freq_mult = 1.0 + i * 1.6
        phase = i * 0.9
        w = (
            0.6 * np.sin(x_points * freq_mult + phase) +
            0.3 * np.cos(x_points * (freq_mult * 2.1) + phase * 1.5) +
            0.15 * np.sin(x_points * 12.0)
        )
        w = w / np.max(np.abs(w))
        stem_waves.append(w)

    for f in range(num_frames):
        # Time progression t in [0, 1)
        t = f / float(num_frames)

        # Separation curve:
        # 0.0 -> 0.18: Single master waveform
        # 0.18 -> 0.52: Waveform fans out into colorful spectral layers
        # 0.52 -> 0.78: Fully separated spectral tracks / glowing spectrum bands
        # 0.78 -> 1.00: Smoothly converges back into single master waveform
        if t < 0.18:
            sep = 0.0
        elif t < 0.52:
            # Smooth ease-in-out
            p = (t - 0.18) / (0.52 - 0.18)
            sep = 0.5 - 0.5 * math.cos(math.pi * p)
        elif t < 0.78:
            sep = 1.0
        else:
            # Smooth ease-in-out return
            p = (t - 0.78) / (1.00 - 0.78)
            sep = 0.5 + 0.5 * math.cos(math.pi * p)

        # Create dark DAW background
        img = Image.new("RGBA", (width, height), (14, 17, 23, 255))
        draw = ImageDraw.Draw(img)

        # Draw DAW UI Header & Grid
        # Subtle horizontal track grid lines
        for y_grid in [16, 33, 50, 67]:
            draw.line([(0, y_grid), (width, y_grid)], fill=(24, 28, 38, 180), width=1)

        # Vertical time bar markers (every 45 pixels)
        for x_bar in range(0, width, 45):
            draw.line([(x_bar, 0), (x_bar, height)], fill=(22, 26, 36, 160), width=1)
            # Small tick at top
            draw.line([(x_bar, 0), (x_bar, 6)], fill=(55, 65, 85, 200), width=1)

        # DAW top banner bar
        draw.rectangle([(0, 0), (width, 16)], fill=(18, 22, 30, 240))
        # Status text
        if sep < 0.15:
            banner_text = "DAW TRACK 01: MASTER AUDIO IN"
            status_color = (0, 255, 102, 230)
        elif sep > 0.85:
            banner_text = "AI SEPARATED SPECTRUM [9 STEMS]"
            status_color = (255, 102, 0, 230)
        else:
            banner_text = "SPECTRAL DECOMPOSITION..."
            status_color = (0, 229, 255, 230)

        draw.text((6, 2), banner_text, fill=status_color)

        # Animated Playhead sweeping across the DAW track
        playhead_x = int((t * 2.0 % 1.0) * width)
        draw.line([(playhead_x, 0), (playhead_x, height)], fill=(255, 255, 255, 140), width=1)
        # Small playhead triangle at top
        draw.polygon([(playhead_x - 3, 0), (playhead_x + 3, 0), (playhead_x, 5)], fill=(255, 255, 255, 220))

        # Center Y for waveform
        cy = 50

        # Draw the waveforms:
        if sep < 0.02:
            # PURE MASTER WAVEFORM (Glowing Neon Green)
            pts = []
            for x in range(width):
                amp = 26.0 * (0.85 + 0.15 * math.sin(x * 0.08 + t * 12.0))
                y = cy + base_wave[x] * amp
                pts.append((x, y))

            # Draw glow
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i+1]], fill=(0, 255, 102, 230), width=2)
                # Upper mirror line
                mirror_pt1 = (pts[i][0], 2 * cy - pts[i][1])
                mirror_pt2 = (pts[i+1][0], 2 * cy - pts[i+1][1])
                draw.line([mirror_pt1, mirror_pt2], fill=(0, 200, 80, 80), width=1)
        else:
            # SPECTRAL SEPARATION FAN-OUT
            # Each stem fans out from center cy to its dedicated vertical lane
            max_spread = 28.0 * sep  # vertical spread
            lane_offsets = np.linspace(-max_spread, max_spread, num_stems)

            for s_idx, (r, g, b) in enumerate(stem_colors):
                target_lane_y = cy + lane_offsets[s_idx]
                # Wave height dampens as it separates to fit within lanes
                stem_amp = (26.0 * (1.0 - sep * 0.72)) * (0.8 + 0.2 * math.sin(t * 8.0 + s_idx))
                s_wave = stem_waves[s_idx]

                pts = []
                for x in range(width):
                    # Blend base_wave and individual stem wave
                    cur_w = (1.0 - sep) * base_wave[x] + sep * s_wave[x]
                    # Y position interpolates from center to target lane
                    cur_center_y = cy + sep * lane_offsets[s_idx]
                    y = cur_center_y + cur_w * stem_amp
                    pts.append((x, y))

                # Draw stem waveform with alpha
                alpha = int(140 + 115 * sep)
                color = (r, g, b, alpha)
                for i in range(len(pts) - 1):
                    draw.line([pts[i], pts[i+1]], fill=color, width=2 if sep > 0.4 else 1)

                # If fully separated, draw small stem indicator dot on left
                if sep > 0.6:
                    dot_y = int(target_lane_y)
                    draw.ellipse([(6, dot_y - 2), (10, dot_y + 2)], fill=(r, g, b, 240))

        # Bottom subtle border
        draw.line([(0, height - 1), (width, height - 1)], fill=(40, 46, 60, 200), width=1)

        frames.append(img.convert("P", palette=Image.ADAPTIVE))

    # Save as animated GIF
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=45,  # 45ms per frame = ~22 fps
        loop=0
    )
    print(f"Generated animated DAW GIF: {output_path} ({len(frames)} frames)")

if __name__ == "__main__":
    out = Path(r"c:\TCNS\Gemini projects\StemSplitterPro\assets\daw_spectrum.gif")
    out.parent.mkdir(parents=True, exist_ok=True)
    create_daw_spectrum_gif(str(out))
