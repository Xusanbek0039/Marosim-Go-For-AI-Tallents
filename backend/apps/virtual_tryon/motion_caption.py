"""Describe what the user does in their 4-second clip, so the fast video follows their real motion.

The fast pipeline animates one dressed photo; on its own the video model invents the movement
(user report 2026-11-26: "I raised my hand, the video did not"). A small vision model looks at a few
frames of the clip (~3-5 s, < $0.001) and writes the movement down; that sentence goes into the
video prompt. Without an OpenAI key, or on any error, a neutral "turns left and right" is used.
"""

import base64
import io
import logging
import subprocess
from pathlib import Path

import requests
from PIL import Image

from . import openai_tryon, video_tryon

logger = logging.getLogger("apps.virtual_tryon.motion")

DEFAULT_MOTION = "slowly turns a little to the left, then a little to the right, then faces the camera again"
MODEL = "gpt-4o-mini"
FRAMES = 6

INSTRUCTION = (
    "These are frames, in time order, from a 4-second phone video of one person trying on clothes. "
    "Describe ONLY the person's body movements in order, as one short English sentence starting with a "
    "verb, e.g. 'raises the right hand above the head, lowers it, then turns to the left'. Mention hands, "
    "arms, turning, walking and head movements; be specific about left/right as seen from the person. "
    "Do not describe clothes, the face, the person or the room. If they barely move, answer "
    "'stands still and looks at the camera'."
)


def _frames(src: Path, work: Path) -> list[bytes]:
    pattern = work / "cap_%02d.jpg"
    subprocess.run(
        [video_tryon._ffmpeg_bin(), "-y", "-i", str(src), "-vf", f"fps={FRAMES / 4},scale=384:-2", "-frames:v",
         str(FRAMES), "-q:v", "4", str(pattern)],
        capture_output=True,
        timeout=20,
        check=False,
    )
    out = []
    for p in sorted(work.glob("cap_*.jpg")):
        img = Image.open(p).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        out.append(buf.getvalue())
    return out


def describe(src: Path, work: Path) -> str:
    """One sentence about the user's movements in the clip, or ``DEFAULT_MOTION``."""
    if not openai_tryon.is_configured():
        return DEFAULT_MOTION
    try:
        frames = _frames(src, work)
        if len(frames) < 2:
            return DEFAULT_MOTION
        content = [{"type": "text", "text": INSTRUCTION}] + [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(f).decode()}", "detail": "low"},
            }
            for f in frames
        ]
        res = requests.post(
            f"{openai_tryon._base_url()}/chat/completions",
            headers={"Authorization": f"Bearer {openai_tryon._api_key()}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": 80,
                  "temperature": 0},
            timeout=20,
        )
        if res.status_code != 200:
            logger.warning("motion caption HTTP %s", res.status_code)
            return DEFAULT_MOTION
        text = (res.json()["choices"][0]["message"]["content"] or "").strip().strip('"').rstrip(".")
        return text[:300] or DEFAULT_MOTION
    except Exception as exc:  # noqa: BLE001 — a caption must never block the try-on
        logger.warning("motion caption failed: %s", type(exc).__name__)
        return DEFAULT_MOTION
