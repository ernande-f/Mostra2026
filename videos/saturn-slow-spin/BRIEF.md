---
workflow: general-video
flow: automation
storyboard: no
message: "Saturn visibly spins in a beautiful, seamless pixel-art loop"
destination: animated-gif
aspect: 708x400
language: none
length: 6s
---

## Intent

Turn the supplied pixel-art image into an animated GIF. The large Saturn on the
left must visibly spin with a slow rotation effect while the ring system remains
spatially anchored. Preserve the source artwork's chunky pixel aesthetic and
make the result feel polished rather than mechanically warped.

## Assets

- User-supplied 708×400 PNG is the visual source of truth.
- `.media/video/video_001.webm` — lossless 12 fps derived surface-motion plate;
  Saturn's bands flow while the ring geometry remains fixed.

## Customizations

- Seamless loop.
- Slow planetary surface rotation, not a flat rotation of the entire image.
- Restrained ambient space polish that does not obscure the original art.
- Silent output.

## Notes

- Inferred run shape: one-shot automation with no storyboard because this is a
  single-scene loop.
- Inferred duration: 6 seconds, long enough for the spin to read as slow.
- Keep the final GIF at the source resolution unless optimization requires a
  visually lossless adjustment.
