// Выбор камеры: список подключённых и поток по имени. Имя, а не deviceId: оно переживает
// очистку профиля окна, а deviceId браузер может выдать заново.

export interface CameraInfo {
  id: string
  label: string
}

const BASE_VIDEO = { width: { ideal: 1280 }, height: { ideal: 720 } }

const hasMedia = (): boolean =>
  typeof navigator !== 'undefined' && typeof navigator.mediaDevices?.enumerateDevices === 'function'

const videoInputs = (devices: MediaDeviceInfo[]): MediaDeviceInfo[] =>
  devices.filter((device) => device.kind === 'videoinput')

/** Подписи камер видны только после первого разрешённого доступа: открываем любую и сразу закрываем. */
async function unlockLabels(): Promise<void> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
    stream.getTracks().forEach((track) => track.stop())
  } catch {
    // нет камеры или доступ запрещён: список останется пустым
  }
}

export async function listCameras(): Promise<CameraInfo[]> {
  if (!hasMedia()) return []
  let inputs = videoInputs(await navigator.mediaDevices.enumerateDevices())
  if (inputs.length > 0 && inputs.some((device) => !device.label)) {
    await unlockLabels()
    inputs = videoInputs(await navigator.mediaDevices.enumerateDevices())
  }
  return inputs.map((device, index) => ({
    id: device.deviceId,
    label: device.label || `Камера ${index + 1}`,
  }))
}

/** Настройки видеопотока: нужная камера по имени, иначе камера по умолчанию. */
export async function cameraConstraints(name: string | null): Promise<MediaStreamConstraints> {
  if (name) {
    const match = (await listCameras()).find((camera) => camera.label === name)
    if (match) return { video: { ...BASE_VIDEO, deviceId: { exact: match.id } }, audio: false }
  }
  return { video: BASE_VIDEO, audio: false }
}
