"use client";

import {
  Loader2Icon,
  Maximize2Icon,
  PauseIcon,
  PlayIcon,
  RotateCcwIcon,
  SparklesIcon,
  Volume2Icon,
  VolumeXIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

function formatSec(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "0:00";
  const s = Math.floor(sec);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem < 10 ? "0" : ""}${rem}`;
}

export interface MarosimVideoPlayerProps {
  src: string;
  poster?: string;
  title?: string;
  autoPlay?: boolean;
  loop?: boolean;
  className?: string;
}

/**
 * MarosimGo branded video player for Admin & Super Admin virtual try-on gallery.
 * Supports smooth seeking, slow-motion inspection (0.5x / 1x), mute toggle, and fullscreen.
 */
export function MarosimVideoPlayer({
  src,
  poster,
  title,
  autoPlay = true,
  loop = true,
  className,
}: MarosimVideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [muted, setMuted] = useState(true);
  const [speed, setSpeed] = useState<1 | 0.5>(1);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    setError(false);
    setLoading(true);
    setCurrentTime(0);
    setDuration(0);
    const el = videoRef.current;
    if (!el) return;
    el.playbackRate = speed;
    if (autoPlay) {
      void el.play().catch(() => {
        setPlaying(false);
      });
    }
  }, [src, autoPlay, speed]);

  const togglePlay = useCallback(() => {
    const el = videoRef.current;
    if (!el) return;
    if (el.paused) {
      void el.play().catch(() => setPlaying(false));
    } else {
      el.pause();
    }
  }, []);

  const replay = useCallback(() => {
    const el = videoRef.current;
    if (!el) return;
    el.currentTime = 0;
    void el.play().catch(() => undefined);
  }, []);

  const toggleMute = useCallback(() => {
    const el = videoRef.current;
    if (!el) return;
    el.muted = !el.muted;
    setMuted(el.muted);
  }, []);

  const toggleSpeed = useCallback(() => {
    setSpeed((prev) => {
      const next = prev === 1 ? 0.5 : 1;
      if (videoRef.current) videoRef.current.playbackRate = next;
      return next;
    });
  }, []);

  const toggleFullscreen = useCallback(() => {
    const host = containerRef.current;
    const vid = videoRef.current as (HTMLVideoElement & { webkitEnterFullscreen?: () => void }) | null;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else if (host?.requestFullscreen) {
      void host.requestFullscreen();
    } else if (vid?.webkitEnterFullscreen) {
      vid.webkitEnterFullscreen();
    }
  }, []);

  const onSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const el = videoRef.current;
    const val = Number(e.target.value);
    if (!el || !Number.isFinite(val)) return;
    el.currentTime = val;
    setCurrentTime(val);
  };

  const progress = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;

  return (
    <div
      ref={containerRef}
      className={cn(
        "group relative flex items-center justify-center overflow-hidden bg-black select-none",
        className,
      )}
    >
      <video
        ref={videoRef}
        src={src}
        poster={poster}
        muted={muted}
        loop={loop}
        playsInline
        preload="metadata"
        onClick={togglePlay}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onWaiting={() => setLoading(true)}
        onCanPlay={() => setLoading(false)}
        onLoadedMetadata={(e) => {
          setDuration(e.currentTarget.duration || 0);
          setLoading(false);
        }}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onError={() => {
          setLoading(false);
          setError(true);
        }}
        className="h-full max-h-[72dvh] w-full cursor-pointer object-contain"
      />

      {/* Top brand badge */}
      <div className="pointer-events-none absolute top-3 left-3 flex items-center gap-2">
        <span className="brand-gradient inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold text-white shadow-md">
          <SparklesIcon className="size-3" />
          MarosimGo Player
        </span>
        {title && (
          <span className="hidden max-w-52 truncate rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-medium text-white/90 backdrop-blur-md sm:inline-block">
            {title}
          </span>
        )}
      </div>

      {/* Loading indicator */}
      {loading && !error && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/25">
          <span className="flex size-12 items-center justify-center rounded-full bg-black/60 text-white backdrop-blur-md">
            <Loader2Icon className="size-6 animate-spin" />
          </span>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/75 p-4 text-center text-white">
          <p className="text-sm font-semibold">Videoni yuklab bo&apos;lmadi</p>
          <button
            type="button"
            onClick={() => {
              setError(false);
              setLoading(true);
              videoRef.current?.load();
            }}
            className="brand-gradient inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-xs font-semibold text-white"
          >
            <RotateCcwIcon className="size-3.5" /> Qayta urinish
          </button>
        </div>
      )}

      {/* Center play button when paused */}
      {!playing && !loading && !error && (
        <button
          type="button"
          onClick={togglePlay}
          aria-label="Videoni ijro etish"
          className="brand-gradient absolute flex size-16 items-center justify-center rounded-full text-white shadow-xl ring-4 ring-white/25 transition hover:scale-105 active:scale-95"
        >
          <PlayIcon className="ml-1 size-7 fill-current" />
        </button>
      )}

      {/* Bottom glass control bar */}
      <div className="absolute inset-x-0 bottom-0 flex flex-col gap-2 bg-gradient-to-t from-black/90 via-black/60 to-transparent px-3 pt-8 pb-3">
        {/* Progress bar */}
        <div className="relative flex h-4 items-center">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/25">
            <div
              className="brand-gradient h-full rounded-full transition-[width] duration-75"
              style={{ width: `${progress}%` }}
            />
          </div>
          <input
            type="range"
            min={0}
            max={duration || 0.1}
            step={0.05}
            value={currentTime}
            onChange={onSeek}
            aria-label="Video vaqti"
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          />
        </div>

        {/* Controls row */}
        <div className="flex items-center justify-between gap-2 text-white">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={togglePlay}
              aria-label={playing ? "To'xtatish" : "Ijro etish"}
              className="brand-gradient flex size-8 items-center justify-center rounded-full text-white shadow transition hover:brightness-110"
            >
              {playing ? <PauseIcon className="size-4 fill-current" /> : <PlayIcon className="ml-0.5 size-4 fill-current" />}
            </button>
            <button
              type="button"
              onClick={replay}
              aria-label="Boshidan"
              className="flex size-8 items-center justify-center rounded-full bg-white/15 text-white transition hover:bg-white/25"
            >
              <RotateCcwIcon className="size-3.5" />
            </button>
            <span className="ml-1 font-mono text-[11px] font-medium text-white/85 tabular-nums">
              {formatSec(currentTime)} / {formatSec(duration)}
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={toggleSpeed}
              title="Sekinlashtirish (0.5x / 1x)"
              className={cn(
                "rounded-full px-2.5 py-1 text-[11px] font-bold transition",
                speed === 0.5 ? "brand-gradient text-white" : "bg-white/15 text-white hover:bg-white/25",
              )}
            >
              {speed}x
            </button>
            <button
              type="button"
              onClick={toggleMute}
              aria-label={muted ? "Ovozni yoqish" : "Ovozni o'chirish"}
              className="flex size-8 items-center justify-center rounded-full bg-white/15 text-white transition hover:bg-white/25"
            >
              {muted ? <VolumeXIcon className="size-3.5" /> : <Volume2Icon className="size-3.5" />}
            </button>
            <button
              type="button"
              onClick={toggleFullscreen}
              aria-label="To'liq ekran"
              className="flex size-8 items-center justify-center rounded-full bg-white/15 text-white transition hover:bg-white/25"
            >
              <Maximize2Icon className="size-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
