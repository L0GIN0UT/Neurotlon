import { afterEach, describe, expect, it, vi } from 'vitest'
import { cameraConstraints, listCameras } from './camera.ts'

const stub = (devicesBefore: object[], devicesAfter: object[] = devicesBefore) => {
  const stop = vi.fn()
  const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] })
  const enumerateDevices = vi
    .fn()
    .mockResolvedValueOnce(devicesBefore)
    .mockResolvedValue(devicesAfter)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia, enumerateDevices } })
  return { getUserMedia, enumerateDevices, stop }
}

afterEach(() => vi.unstubAllGlobals())

describe('camera list', () => {
  it('lists only video inputs with their names', async () => {
    stub([
      { kind: 'videoinput', deviceId: 'a', label: 'Integrated Camera' },
      { kind: 'audioinput', deviceId: 'm', label: 'Mic' },
    ])
    expect(await listCameras()).toEqual([{ id: 'a', label: 'Integrated Camera' }])
  })

  it('opens and closes a camera once to learn the names when they are hidden', async () => {
    const { getUserMedia, stop } = stub(
      [{ kind: 'videoinput', deviceId: 'a', label: '' }],
      [{ kind: 'videoinput', deviceId: 'a', label: 'USB Webcam' }],
    )
    expect(await listCameras()).toEqual([{ id: 'a', label: 'USB Webcam' }])
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(stop).toHaveBeenCalled()
  })

  it('returns an empty list without media support or cameras', async () => {
    vi.stubGlobal('navigator', {})
    expect(await listCameras()).toEqual([])
    stub([])
    expect(await listCameras()).toEqual([])
  })
})

describe('camera constraints', () => {
  const two = [
    { kind: 'videoinput', deviceId: 'a', label: 'Integrated Camera' },
    { kind: 'videoinput', deviceId: 'b', label: 'USB Webcam' },
  ]

  it('picks the camera by name', async () => {
    stub(two)
    const constraints = await cameraConstraints('USB Webcam')
    expect(constraints.video).toMatchObject({ deviceId: { exact: 'b' } })
    expect(constraints.audio).toBe(false)
  })

  it('falls back to the default camera for no name or an unknown one', async () => {
    stub(two)
    expect((await cameraConstraints(null)).video).not.toHaveProperty('deviceId')
    stub(two)
    expect((await cameraConstraints('Gone Camera')).video).not.toHaveProperty('deviceId')
  })
})
