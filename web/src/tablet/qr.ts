import jsQR from 'jsqr'

interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>
}
type BarcodeDetectorCtor = new (options: { formats: string[] }) => BarcodeDetectorLike

/** Читает QR из кадра: встроенный BarcodeDetector, иначе jsQR (входит в сборку). */
export function createQrReader(
  canvas: HTMLCanvasElement,
): (video: HTMLVideoElement) => Promise<string | null> {
  const Detector = (globalThis as { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector
  const detector = Detector ? new Detector({ formats: ['qr_code'] }) : null
  return async (video) => {
    if (video.videoWidth === 0) return null
    if (detector) {
      const found = await detector.detect(video)
      return found[0]?.rawValue ?? null
    }
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) return null
    context.drawImage(video, 0, 0)
    const image = context.getImageData(0, 0, canvas.width, canvas.height)
    return jsQR(image.data, image.width, image.height)?.data ?? null
  }
}
