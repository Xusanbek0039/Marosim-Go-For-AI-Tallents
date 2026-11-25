"""System checks for the studio app (``manage.py check`` / runserver / deploy)."""

import shutil

from django.core.checks import Warning, register


@register()
def check_video_tools(app_configs, **kwargs):
    """Reel uploads are fully validated only with ffprobe (orientation, 3-60 s duration, real video).

    Without it ``reels.prepare`` falls back to extension, size, container signature and the poster's
    orientation. Shared hosting often has no ffmpeg, so say it instead of degrading silently.
    """
    if shutil.which("ffprobe"):
        return []
    return [
        Warning(
            "ffprobe not found: studio reel uploads are only checked by extension, size, container "
            "signature and poster orientation (not duration or the video's own orientation).",
            hint="Install ffmpeg (it includes ffprobe) on the server, e.g. `apt install ffmpeg`.",
            id="studios.W001",
        )
    ]
