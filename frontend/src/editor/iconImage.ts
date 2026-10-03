// Converts an uploaded PNG/JPG/SVG into a small square PNG before upload.
// Only the processed icon is stored on the PC, never the original file.
// SVG is rasterised here, so no SVG (and none of its scripts) is ever served back.

export const ICON_EDGE = 256;
export const ACCEPTED_ICON_TYPES = ["image/png", "image/jpeg", "image/svg+xml"];
const MAX_SOURCE_BYTES = 10 * 1024 * 1024;

export class IconImageError extends Error {}

export async function toIconPng(file: File): Promise<Blob> {
  if (!ACCEPTED_ICON_TYPES.includes(file.type)) throw new IconImageError("Choose a PNG, JPG or SVG image.");
  if (file.size > MAX_SOURCE_BYTES) throw new IconImageError("That image is larger than 10 MB.");

  const url = URL.createObjectURL(file);
  try {
    const image = await loadImage(url);
    // SVGs without width/height report 0; treat them as square.
    const w = image.naturalWidth || ICON_EDGE;
    const h = image.naturalHeight || ICON_EDGE;
    // Vector art renders sharp at full size; bitmaps are never upscaled.
    const size = file.type === "image/svg+xml" ? ICON_EDGE : Math.min(ICON_EDGE, Math.max(w, h));

    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new IconImageError("This browser can't process images.");
    ctx.imageSmoothingQuality = "high";
    const fit = size / Math.max(w, h);
    const dw = w * fit;
    const dh = h * fit;
    ctx.drawImage(image, (size - dw) / 2, (size - dh) / 2, dw, dh);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new IconImageError("Couldn't convert the image."))), "image/png"),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new IconImageError("That file isn't a readable image."));
    image.src = src;
  });
}
