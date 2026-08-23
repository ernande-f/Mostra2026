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
const DURATION = 8;
const FRAME_COUNT = FPS * DURATION;
const SURFACE_STRENGTH = Math.min(
  1,
  Math.max(0, Number(process.env.SURFACE_STRENGTH ?? 0.58)),
);

const { data: source, info } = await sharp(inputPath)
  .ensureAlpha()
  .raw()
  .toBuffer({ resolveWithObject: true });

const { width, height, channels } = info;
await mkdir(outputDir, { recursive: true });

const bgOffset = (width - 1) * channels;
const background = [source[bgOffset], source[bgOffset + 1], source[bgOffset + 2]];
const rawEdges = new Array(height);
const planetMask = new Uint8Array(width * height);
const scale = width / 708;

function colorDistance(offset) {
  return (
    Math.abs(source[offset] - background[0]) +
    Math.abs(source[offset + 1] - background[1]) +
    Math.abs(source[offset + 2] - background[2])
  );
}

// Locate Saturn's right limb row by row. Four consecutive background pixels
// prevent the sparse stars from being mistaken for the silhouette boundary.
for (let y = 0; y < height; y += 1) {
  let edge = Math.round(width * 0.41);
  let quietRun = 0;
  for (let x = Math.round(width * 0.24); x < Math.round(width * 0.49); x += 1) {
    const distance = colorDistance((y * width + x) * channels);
    quietRun = distance <= 18 ? quietRun + 1 : 0;
    if (quietRun >= 4) {
      edge = x - 3;
      break;
    }
  }
  rawEdges[y] = edge;
}

const edges = rawEdges.map((edge, y) => {
  const values = [];
  for (let yy = Math.max(0, y - 6); yy <= Math.min(height - 1, y + 6); yy += 1) {
    values.push(rawEdges[yy]);
  }
  values.sort((a, b) => a - b);
  return values[Math.floor(values.length / 2)];
});

for (let y = 0; y < height; y += 1) {
  for (let x = 0; x < Math.max(0, edges[y] - Math.round(4 * scale)); x += 1) {
    planetMask[y * width + x] = 1;
  }
}

const palette = [
  [255, 224, 149],
  [247, 188, 86],
  [222, 131, 35],
  [255, 239, 188],
  [178, 90, 24],
  [118, 62, 35],
];

const features = Array.from({ length: 86 }, (_, index) => ({
  y: Math.round(height * (0.018 + (((index * 47) % 964) / 1000) * 0.964)),
  seed: (index * 0.61803398875) % 1,
  width: Math.round((12 + ((index * 17) % 46)) * scale),
  height: Math.max(1, Math.round((1 + ((index * 7) % 5)) * scale * 0.72)),
  color: palette[(index * 5) % palette.length],
  strength: 0.18 + ((index * 13) % 20) / 100,
}));

const longBands = [0.08, 0.17, 0.29, 0.42, 0.55, 0.68, 0.81, 0.92].map(
  (fraction, index) => ({
    y: Math.round(height * fraction),
    seed: (0.11 + index * 0.137) % 1,
    width: Math.round((62 + ((index * 19) % 34)) * scale),
    height: Math.max(2, Math.round((2 + (index % 3)) * scale * 0.68)),
    color: palette[(index + 1) % palette.length],
    strength: 0.2,
  }),
);

function blendPlanetPixel(buffer, x, y, color, alpha) {
  if (x < 0 || x >= width || y < 0 || y >= height) return;
  const pixelIndex = y * width + x;
  if (planetMask[pixelIndex] === 0) return;

  const offset = pixelIndex * channels;
  const inv = 1 - alpha;
  buffer[offset] = Math.round(buffer[offset] * inv + color[0] * alpha);
  buffer[offset + 1] = Math.round(buffer[offset + 1] * inv + color[1] * alpha);
  buffer[offset + 2] = Math.round(buffer[offset + 2] * inv + color[2] * alpha);
}

function drawRotatingStreak(buffer, feature, phase) {
  const theta = Math.PI * 2 * (feature.seed + phase - 0.25);
  const front = Math.cos(theta);
  if (front <= 0) return;

  const y = Math.min(height - 1, Math.max(0, feature.y));
  const edge = edges[y] - Math.round(5 * scale);
  const centerX = Math.round(width * 0.035);
  const radius = Math.max(Math.round(40 * scale), edge - centerX - Math.round(5 * scale));
  const center = centerX + radius * Math.sin(theta);
  const streakWidth = Math.max(
    Math.round(3 * scale),
    Math.round(feature.width * (0.12 + front * 0.88)),
  );
  const alpha =
    SURFACE_STRENGTH * feature.strength * (0.24 + Math.pow(front, 0.7) * 0.76);
  const startX = Math.round(center - streakWidth / 2);

  for (let yy = 0; yy < feature.height; yy += 1) {
    const inset = yy === 0 || yy === feature.height - 1 ? Math.round(scale) : 0;
    for (let xx = inset; xx < streakWidth - inset; xx += 1) {
      blendPlanetPixel(buffer, startX + xx, y + yy, feature.color, alpha);
    }
  }

  const shadowY = y + feature.height;
  for (let xx = Math.round(2 * scale); xx < streakWidth - Math.round(2 * scale); xx += 1) {
    blendPlanetPixel(
      buffer,
      startX + xx - Math.round(scale),
      shadowY,
      [91, 47, 30],
      alpha * 0.14,
    );
  }
}

for (let frame = 0; frame < FRAME_COUNT; frame += 1) {
  const phase = frame / FRAME_COUNT;
  const buffer = Buffer.from(source);

  // A restrained, loop-exact texture flex preserves the crisp limb while the
  // travelling streaks below establish a continuous direction of rotation.
  for (let y = 0; y < height; y += 1) {
    const edge = Math.max(1, edges[y] - Math.round(5 * scale));
    const broadFlow =
      Math.sin(phase * Math.PI * 2) *
      (8.5 * scale + Math.cos(y * 0.028) * 2.3 * scale);
    const fineFlow =
      Math.sin(phase * Math.PI * 4) * Math.cos(y * 0.051) * 1.7 * scale;

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

  for (const feature of longBands) drawRotatingStreak(buffer, feature, phase);
  for (const feature of features) drawRotatingStreak(buffer, feature, phase);

  const outputPath = path.join(outputDir, `frame-${String(frame).padStart(3, "0")}.png`);
  await sharp(buffer, { raw: { width, height, channels } }).png().toFile(outputPath);
}

console.log(
  `Generated ${FRAME_COUNT} seek-safe frames at ${FPS} fps in ${outputDir} ` +
    `(surface strength ${SURFACE_STRENGTH.toFixed(2)})`,
);
