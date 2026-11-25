/**
 * WebGL2 compositor of the live try-on. Every frame, in one canvas:
 *
 * 1. the camera frame (video texture) — so the person and the garment are always from the
 *    same frame, no drift between a <video> element and an overlay;
 * 2. the garment layers as textured, deformed meshes (premultiplied alpha);
 * 3. occluders: soft capsules over hands / bare arms that redraw the camera pixels there, so
 *    the person's hands stay in front of the garment.
 */

import type { Capsule } from "./geometry";

export interface DrawLayer {
  texture: WebGLTexture;
  /** Vertex positions in camera pixels. */
  positions: Float32Array;
  uv: Float32Array;
  indices: Uint16Array;
}

export interface DrawFrame {
  layers: DrawLayer[];
  /** 0..1 — garment fade (tracking loss, side view). */
  alpha: number;
  /** Garment brightness multiplier from the scene light. */
  light: number;
  occluders: Capsule[];
}

const VERT_PIXELS = `#version 300 es
in vec2 a_pos;
in vec2 a_uv;
uniform vec2 u_res;
out vec2 v_uv;
out vec2 v_px;
void main() {
  v_uv = a_uv;
  v_px = a_pos;
  vec2 clip = a_pos / u_res * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}`;

const FRAG_VIDEO = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_tex;
out vec4 color;
void main() { color = vec4(texture(u_tex, v_uv).rgb, 1.0); }`;

const FRAG_GARMENT = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_alpha;
uniform float u_light;
out vec4 color;
void main() {
  vec4 c = texture(u_tex, v_uv); // premultiplied
  color = vec4(c.rgb * u_light, c.a) * u_alpha;
}`;

const FRAG_OCCLUDER = `#version 300 es
precision highp float;
in vec2 v_px;
uniform sampler2D u_tex;
uniform vec2 u_res;
uniform vec2 u_a;
uniform vec2 u_b;
uniform float u_r;
out vec4 color;
void main() {
  vec2 pa = v_px - u_a, ba = u_b - u_a;
  float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-4), 0.0, 1.0);
  float d = length(pa - ba * h);
  float a = 1.0 - smoothstep(u_r * 0.7, u_r, d);
  color = vec4(texture(u_tex, v_px / u_res).rgb * a, a);
}`;

function compile(gl: WebGL2RenderingContext, type: number, src: string) {
  const shader = gl.createShader(type)!;
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`shader: ${log}`);
  }
  return shader;
}

function program(gl: WebGL2RenderingContext, frag: string) {
  const p = gl.createProgram()!;
  const vs = compile(gl, gl.VERTEX_SHADER, VERT_PIXELS);
  const fs = compile(gl, gl.FRAGMENT_SHADER, frag);
  gl.attachShader(p, vs);
  gl.attachShader(p, fs);
  gl.bindAttribLocation(p, 0, "a_pos");
  gl.bindAttribLocation(p, 1, "a_uv");
  gl.linkProgram(p);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(`program: ${gl.getProgramInfoLog(p)}`);
  const uniforms = new Map<string, WebGLUniformLocation | null>();
  const u = (name: string) => {
    if (!uniforms.has(name)) uniforms.set(name, gl.getUniformLocation(p, name));
    return uniforms.get(name)!;
  };
  return { p, u };
}

export class GLRenderer {
  readonly gl: WebGL2RenderingContext;
  private video;
  private garment;
  private occluder;
  private posBuf: WebGLBuffer;
  private uvBuf: WebGLBuffer;
  private idxBuf: WebGLBuffer;
  private videoTex: WebGLTexture;
  private textures = new Set<WebGLTexture>();
  private width = 0;
  private height = 0;
  private disposed = false;

  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2", {
      alpha: false,
      antialias: true,
      premultipliedAlpha: true,
      preserveDrawingBuffer: false,
      powerPreference: "high-performance",
    });
    if (!gl) throw new Error("webgl2-unavailable");
    this.gl = gl;
    this.video = program(gl, FRAG_VIDEO);
    this.garment = program(gl, FRAG_GARMENT);
    this.occluder = program(gl, FRAG_OCCLUDER);
    this.posBuf = gl.createBuffer()!;
    this.uvBuf = gl.createBuffer()!;
    this.idxBuf = gl.createBuffer()!;
    this.videoTex = this.makeTexture(false);
  }

  private makeTexture(mipmaps: boolean) {
    const gl = this.gl;
    const tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    return tex;
  }

  /** GPU texture of a garment layer (premultiplied alpha, mipmapped). */
  createTexture(image: TexImageSource): WebGLTexture {
    const gl = this.gl;
    const tex = this.makeTexture(true);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.generateMipmap(gl.TEXTURE_2D);
    this.textures.add(tex);
    return tex;
  }

  deleteTexture(tex: WebGLTexture) {
    if (this.textures.delete(tex) && !this.disposed) this.gl.deleteTexture(tex);
  }

  private resize(w: number, h: number) {
    if (w === this.width && h === this.height) return;
    this.width = w;
    this.height = h;
    this.canvas.width = w;
    this.canvas.height = h;
  }

  private bindGeometry(positions: Float32Array, uv: Float32Array, indices: Uint16Array | null) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.uvBuf);
    gl.bufferData(gl.ARRAY_BUFFER, uv, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 0, 0);
    if (indices) {
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.idxBuf);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.DYNAMIC_DRAW);
    }
  }

  private quad(x0: number, y0: number, x1: number, y1: number) {
    const W = this.width;
    const H = this.height;
    return {
      pos: new Float32Array([x0, y0, x1, y0, x0, y1, x0, y1, x1, y0, x1, y1]),
      uv: new Float32Array([x0 / W, y0 / H, x1 / W, y0 / H, x0 / W, y1 / H, x0 / W, y1 / H, x1 / W, y0 / H, x1 / W, y1 / H]),
    };
  }

  /** Draws one composite frame from the current video frame. */
  draw(source: HTMLVideoElement, frame: DrawFrame | null) {
    if (this.disposed) return;
    const gl = this.gl;
    const w = source.videoWidth;
    const h = source.videoHeight;
    if (!w || !h) return;
    this.resize(w, h);
    gl.viewport(0, 0, w, h);

    // 1. camera frame
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
    gl.disable(gl.BLEND);
    gl.useProgram(this.video.p);
    gl.uniform2f(this.video.u("u_res"), w, h);
    gl.uniform1i(this.video.u("u_tex"), 0);
    const full = this.quad(0, 0, w, h);
    this.bindGeometry(full.pos, full.uv, null);
    gl.drawArrays(gl.TRIANGLES, 0, 6);

    if (!frame || frame.alpha <= 0.01 || frame.layers.length === 0) return;

    // 2. garment layers
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(this.garment.p);
    gl.uniform2f(this.garment.u("u_res"), w, h);
    gl.uniform1i(this.garment.u("u_tex"), 1);
    gl.uniform1f(this.garment.u("u_alpha"), frame.alpha);
    gl.uniform1f(this.garment.u("u_light"), frame.light);
    gl.activeTexture(gl.TEXTURE1);
    for (const layer of frame.layers) {
      gl.bindTexture(gl.TEXTURE_2D, layer.texture);
      this.bindGeometry(layer.positions, layer.uv, layer.indices);
      gl.drawElements(gl.TRIANGLES, layer.indices.length, gl.UNSIGNED_SHORT, 0);
    }

    // 3. hands / bare arms back in front of the garment
    if (frame.occluders.length === 0) return;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
    gl.useProgram(this.occluder.p);
    gl.uniform2f(this.occluder.u("u_res"), w, h);
    gl.uniform1i(this.occluder.u("u_tex"), 0);
    for (const c of frame.occluders) {
      const x0 = Math.max(0, Math.min(c.a.x, c.b.x) - c.r);
      const y0 = Math.max(0, Math.min(c.a.y, c.b.y) - c.r);
      const x1 = Math.min(w, Math.max(c.a.x, c.b.x) + c.r);
      const y1 = Math.min(h, Math.max(c.a.y, c.b.y) + c.r);
      if (x1 <= x0 || y1 <= y0) continue;
      gl.uniform2f(this.occluder.u("u_a"), c.a.x, c.a.y);
      gl.uniform2f(this.occluder.u("u_b"), c.b.x, c.b.y);
      gl.uniform1f(this.occluder.u("u_r"), c.r);
      const q = this.quad(x0, y0, x1, y1);
      this.bindGeometry(q.pos, q.uv, null);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
  }

  /** Frees every GPU resource and gives the context back to the browser. */
  dispose() {
    if (this.disposed) return;
    const gl = this.gl;
    this.textures.forEach((t) => gl.deleteTexture(t));
    this.textures.clear();
    gl.deleteTexture(this.videoTex);
    [this.posBuf, this.uvBuf, this.idxBuf].forEach((b) => gl.deleteBuffer(b));
    [this.video, this.garment, this.occluder].forEach(({ p }) => gl.deleteProgram(p));
    this.disposed = true;
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
}
