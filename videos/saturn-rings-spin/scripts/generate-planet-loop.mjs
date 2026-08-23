import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const [inputPath, outputDir] = process.argv.slice(2);
const sharpModulePath = process.env.SHARP_MODULE_PATH;

if (!inputPath || !outputDir || !sharpModulePath) {
  throw new Error(
    "Usage: SHARP_MODULE_PATH=/path/to/sharp node generate-planet-loop.mjs input.png output-dir",
  );
}

const require = createRequire(import.meta.url);
const sharp = require(sharpModulePath);
const FPS = 12;
const DURATION = 6;
const FRAME_COUNT = FPS * DURATION;
const RING_STRENGTH = Math.min(1, Math.max(0, Number(process.env.RING_STRENGTH ?? 0.62)));

const { data: source, info } = await sharp(inputPath)
  .ensureAlpha()
  .raw()
  .toBuffer({ resolveWithObject: true });

const { width, height, channels } = info;
if (width !== 708 || height !== 400 || channels !== 4) {
  throw new Error(`Expected a 708x400 RGBA source, received ${width}x${height}x${channels}`);
}

await mkdir(outputDir, { recursive: true });

const bgOffset = (width - 1) * channels;
const background = [source[bgOffset], source[bgOffset + 1], source[bgOffset + 2]];
const rawEdges = new Array(height);
const planetMask = new Uint8Array(width * height);
const ringMask = new Uint8Array(width * height);

function colorDistance(offset) {
  return (
    Math.abs(source[offset] - background[0]) +
    Math.abs(source[offset + 1] - background[1]) +
    Math.abs(source[offset + 2] - background[2])
  );
}

for (let y = 0; y < height; y += 1) {
  let edge = 306;
  for (let x = 150; x < 322; x += 1) {
    if (colorDistance((y * width + x) * channels) <= 6) {
      edge = x;
      break;
    }
  }
  rawEdges[y] = edge;
}

const edges = rawEdges.map((edge, y) => {
  const values = [];
  for (let yy = Math.max(0, y - 4); yy <= Math.min(height - 1, y + 4); yy += 1) {
    values.push(rawEdges[yy]);
  }
  values.sort((a, b) => a - b);
  return values[Math.floor(values.length / 2)];
});

for (let y = 0; y < height; y += 1) {
  for (let x = 0; x < Math.max(0, edges[y] - 6); x += 1) {
    planetMask[y * width + x] = 1;
  }
}

// The source ring system begins just beyond Saturn's limb. Keep its geometry
// fixed and animate only the material already painted on those curves.
for (let y = 0; y < height; y += 1) {
  for (let x = 282; x < width; x += 1) {
    const pixelIndex = y * width + x;
    if (planetMask[pixelIndex] === 0 && colorDistance(pixelIndex * channels) > 18) {
      ringMask[pixelIndex] = 1;
    }
  }
}

const palette = [
  [255, 237, 168],
  [247, 217, 126],
  [239, 172, 94],
  [218, 143, 54],
  [255, 225, 147],
  [191, 112, 42],
];

const features = Array.from({ length: 42 }, (_, index) => ({
  y: 8 + ((index * 47) % 382),
  seed: (index * 0.61803398875) % 1,
  width: 14 + ((index * 17) % 42),
  height: 1 + ((index * 7) % 5),
  color: palette[(index * 5) % palette.length],
  strength: 0.38 + ((index * 13) % 24) / 100,
}));

const longBands = [42, 88, 137, 184, 236, 286, 342, 374].map((y, index) => ({
  y,
  seed: (0.11 + index * 0.137) % 1,
  width: 58 + ((index * 19) % 31),
  height: 3 + (index % 3),
  color: palette[(index + 1) % palette.length],
  strength: 0.32,
}));

function blendPixel(buffer, x, y, color, alpha) {
  if (x < 0 || x >= width || y < 0 || y >= height) return;
  const pixelIndex = y * width + x;
  if (planetMask[pixelIndex] === 0) return;

  const offset = pixelIndex * channels;
  const inv = 1 - alpha;
  buffer[offset] = Math.round(buffer[offset] * inv + color[0] * alpha);
  buffer[offset + 1] = Math.round(buffer[offset + 1] * inv + color[1] * alpha);
  buffer[offset + 2] = Math.round(buffer[offset + 2] * inv + color[2] * alpha);
}

function drawStreak(buffer, feature, phase) {
  const theta = Math.PI * 2 * (feature.seed + phase - 0.25);
  const front = Math.cos(theta);
  if (front <= 0) return;

  const edge = edges[Math.min(height - 1, Math.max(0, feature.y))];
  const centerX = 44;
  const radius = Math.max(24, edge - centerX - 8);
  const center = centerX + radius * Math.sin(theta);
  const streakWidth = Math.max(3, Math.round(feature.width * (0.18 + front * 0.82)));
  const alpha = feature.strength * (0.28 + Math.pow(front, 0.72) * 0.72);
  const startX = Math.round(center - streakWidth / 2);

  for (let yy = 0; yy < feature.height; yy += 1) {
    const inset = yy === 0 || yy === feature.height - 1 ? 1 : 0;
    for (let xx = inset; xx < streakWidth - inset; xx += 1) {
      blendPixel(buffer, startX + xx, feature.y + yy, feature.color, alpha);
    }
  }

  const shadowColor = [119, 73, 42];
  const shadowY = feature.y + feature.height;
  for (let xx = 2; xx < streakWidth - 2; xx += 1) {
    blendPixel(buffer, startX + xx - 2, shadowY, shadowColor, alpha * 0.16);
  }
}

function animateRings(buffer, phase) {
  const originX = 281;
  const originY = 100;

  for (let y = 0; y < height; y += 1) {
    for (let x = 282; x < width; x += 1) {
      const pixelIndex = y * width + x;
      if (ringMask[pixelIndex] === 0) continue;

      const dx = x - originX;
      const dy = y - originY;
      const distance = Math.hypot(dx, dy);
      const angle = Math.atan2(dy, dx);
      const grain = 0.76 + 0.24 * Math.sin(x * 0.173 + y * 0.311);

      // Integer temporal cycle counts make frame 72 meet frame 0 exactly.
      // The first wave creates bright packets that run along the painted arcs;
      // the second, wider wave keeps the flow organic instead of synchronized.
      const fastWave = Math.sin(
        Math.PI * 2 * (distance / 58 + angle * 0.82 - phase * 2),
      );
      const slowWave = Math.sin(
        Math.PI * 2 * (distance / 121 - angle * 0.31 - phase),
      );
      const packet = Math.max(0, (fastWave - 0.38) / 0.62) ** 2;
      const glow = Math.max(0, slowWave) * 0.22 + packet * 0.78;
      const shade = Math.max(0, -fastWave) * 0.12;

      const offset = pixelIndex * channels;
      const lightAlpha = RING_STRENGTH * glow * grain;
      const shadeAlpha = RING_STRENGTH * shade * grain;

      if (shadeAlpha > 0) {
        buffer[offset] = Math.round(buffer[offset] * (1 - shadeAlpha) + 83 * shadeAlpha);
        buffer[offset + 1] = Math.round(
          buffer[offset + 1] * (1 - shadeAlpha) + 65 * shadeAlpha,
        );
        buffer[offset + 2] = Math.round(
          buffer[offset + 2] * (1 - shadeAlpha) + 43 * shadeAlpha,
        );
      }

      if (lightAlpha > 0) {
        buffer[offset] = Math.round(buffer[offset] * (1 - lightAlpha) + 255 * lightAlpha);
        buffer[offset + 1] = Math.round(
          buffer[offset + 1] * (1 - lightAlpha) + 239 * lightAlpha,
        );
        buffer[offset + 2] = Math.round(
          buffer[offset + 2] * (1 - lightAlpha) + 158 * lightAlpha,
        );
      }
    }
  }
}

for (let frame = 0; frame < FRAME_COUNT; frame += 1) {
  const phase = frame / FRAME_COUNT;
  const buffer = Buffer.from(source);

  for (let y = 0; y < height; y += 1) {
    const edge = Math.max(1, edges[y] - 6);
    const broadFlow = Math.sin(phase * Math.PI * 2) * (9 + Math.cos(y * 0.061) * 2.8);
    const fineFlow = Math.sin(phase * Math.PI * 4) * Math.cos(y * 0.109) * 2.1;

    for (let x = 0; x < edge; x += 1) {
      const u = x / Math.max(1, edge - 1);
      const limbWeight = Math.sin(Math.PI * u) ** 2;
      const sampleX = Math.min(
        edge - 1,
        Math.max(0, Math.round(x + (broadFlow + fineFlow) * limbWeight)),
      );
      const sourceOffset = (y * width + sampleX) * channels;
      const outputOffset = (y * width + x) * channels;
      buffer[outputOffset] = source[sourceOffset];
      buffer[outputOffset + 1] = source[sourceOffset + 1];
      buffer[outputOffset + 2] = source[sourceOffset + 2];
    }
  }

  for (const feature of longBands) drawStreak(buffer, feature, phase);
  for (const feature of features) drawStreak(buffer, feature, phase);
  animateRings(buffer, phase);

  const outputPath = path.join(outputDir, `frame-${String(frame).padStart(3, "0")}.png`);
  await sharp(buffer, { raw: { width, height, channels } }).png().toFile(outputPath);
}

console.log(
  `Generated ${FRAME_COUNT} seek-safe frames at ${FPS} fps in ${outputDir} ` +
    `(ring strength ${RING_STRENGTH.toFixed(2)})`,
);
