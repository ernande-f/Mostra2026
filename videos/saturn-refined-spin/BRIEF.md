---
workflow: general-video
flow: automation
storyboard: no
message: "Saturn's atmospheric surface visibly rotates in a seamless cinematic pixel-art loop"
destination: animated-gif
aspect: 1668x943
language: none
length: 8s
---

## Intent

Apply a slow, visible rotation to Saturn in the supplied refined pixel-art
image. The planet's atmospheric bands and small surface details should travel
across the spherical volume while the silhouette remains stable. Preserve the
ring system and star field exactly as spatial anchors.

## Assets

- `.media/images/image_002.png` — user-supplied 1668×943 visual source of truth.
- `.media/video/video_002.webm` — lossless 12 fps derived surface-motion plate;
  only Saturn's painted surface moves while the rings and backdrop stay fixed.

## Customizations

- Seamless eight-second loop.
- Slow spherical surface rotation, not a flat rotation of the whole image.
- Restrained warm sheen contained to Saturn's visible disk.
- Silent output.

## Notes

- This is a specific edit to the existing single-scene Saturn workflow.
- Keep the final output at source resolution unless optimization requires a
  visually lossless adjustment.
