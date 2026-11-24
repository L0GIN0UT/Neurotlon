import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { createFakeServer, json, problem } from '../../test/fakeServer.ts'
import type { FakeServer } from '../../test/fakeServer.ts'
import { createStaffApi } from '../api.ts'
import type { Participant } from '../api.ts'
import { PhotoDialog } from './PhotoDialog.tsx'

const PUT = 'PUT /participants/*/photo'
const DELETE = 'DELETE /participants/*/photo'

function person(extra: Partial<Participant> = {}): Participant {
  return {
    code: 'NT07',
    display_name: null,
    checked_in: false,
    checked_in_at: null,
    team: null,
    has_photo: false,
    photo_version: null,
    ...extra,
  }
}

// В jsdom нет canvas и URL.createObjectURL: подменяем их. Размер результата задаёт `jpegSize`,
// так проверяется и успешная отправка, и ветка «не удалось уложиться в лимит».
let jpegSize = 1000
const drawImage = vi.fn()

beforeEach(() => {
  jpegSize = 1000
  drawImage.mockClear()
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
    fillRect: vi.fn(),
    drawImage,
    fillStyle: '',
  })) as unknown as typeof HTMLCanvasElement.prototype.getContext
  HTMLCanvasElement.prototype.toBlob = function toBlob(callback: BlobCallback) {
    callback(new Blob([new Uint8Array(jpegSize)], { type: 'image/jpeg' }))
  }
  URL.createObjectURL = vi.fn(() => 'blob:photo-test')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  Reflect.deleteProperty(navigator, 'mediaDevices')
})

function setup(server: FakeServer, who: Participant = person()) {
  const onSaved = vi.fn()
  const view = render(
    <PhotoDialog
      api={createStaffApi({ fetchFn: server.fetchFn })}
      person={who}
      onClose={() => view.rerender(<></>)}
      onSaved={onSaved}
    />,
  )
  return { onSaved, ...view }
}

async function pickFile(name = 'Предпросмотр NT07') {
  const input = screen.getByLabelText('Файл фото') as HTMLInputElement
  fireEvent.change(input, { target: { files: [new File(['x'], 'me.png', { type: 'image/png' })] } })
  const img = await screen.findByAltText(name)
  Object.defineProperty(img, 'naturalWidth', { value: 4000 })
  Object.defineProperty(img, 'naturalHeight', { value: 3000 })
  fireEvent.load(img)
  return img
}

describe('PhotoDialog', () => {
  test('файл: предпросмотр, затем сохранение шлёт PUT с image/jpeg', async () => {
    const server = createFakeServer('admin')
    server.routes.set(PUT, () => new Response(null, { status: 204 }))
    const { onSaved } = setup(server)
    const save = screen.getByRole('button', { name: 'Сохранить' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    await pickFile()
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const call = server.calls.find((c) => c.key === PUT)
    expect(call?.contentType).toBe('image/jpeg')
    expect(call?.url.pathname).toBe('/api/v1/participants/NT07/photo')
    expect(call?.body).toBeInstanceOf(Blob)
    expect((call?.body as Blob | undefined)?.size).toBe(1000)
    // видимая часть 4000x3000 при 1x: высота целиком, ширина 2250, по центру
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 875, 0, 2250, 3000, 0, 0, 450, 600)
  })

  test('слишком тяжёлый результат не отправляется', async () => {
    jpegSize = 500 * 1024
    const server = createFakeServer('admin')
    setup(server)
    await pickFile()
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText('Фото слишком большое')).toBeDefined()
    expect(server.count(PUT)).toBe(0)
  })

  test('ошибка 413 от сервера показывается в окне, окно остаётся', async () => {
    const server = createFakeServer('admin')
    server.routes.set(PUT, () => problem(413, 'payload_too_large'))
    const { onSaved } = setup(server)
    await pickFile()
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText('Фото слишком большое')).toBeDefined()
    expect(onSaved).not.toHaveBeenCalled()
  })

  test('ошибка 422 показывается как «Нужен файл JPEG»', async () => {
    const server = createFakeServer('admin')
    server.routes.set(PUT, () => problem(422, 'unprocessable'))
    setup(server)
    await pickFile()
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText('Нужен файл JPEG')).toBeDefined()
  })

  test('удаление требует подтверждения и доступно только при наличии фото', async () => {
    const server = createFakeServer('admin')
    server.routes.set(DELETE, () => new Response(null, { status: 204 }))
    const first = setup(server)
    expect(screen.queryByRole('button', { name: 'Удалить фото' })).toBeNull()
    first.unmount()

    const { onSaved } = setup(server, person({ has_photo: true, photo_version: 5 }))
    expect(screen.getByAltText('Текущее фото NT07').getAttribute('src')).toBe(
      '/api/v1/participants/NT07/photo?v=5',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Удалить фото' }))
    expect(server.count(DELETE)).toBe(0)
    const confirm = await screen.findByRole('dialog', { name: 'Удалить фото' })
    fireEvent.click(within(confirm).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(server.count(DELETE)).toBe(1)
  })

  test('отмена подтверждения ничего не удаляет', async () => {
    const server = createFakeServer('admin')
    setup(server, person({ has_photo: true, photo_version: 5 }))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить фото' }))
    const confirm = await screen.findByRole('dialog', { name: 'Удалить фото' })
    fireEvent.click(within(confirm).getByRole('button', { name: 'Отмена' }))
    expect(server.count(DELETE)).toBe(0)
  })

  test('ошибка сети при удалении показывается в окне', async () => {
    const server = createFakeServer('admin')
    server.routes.set(DELETE, () => json({ title: 'x', code: 'server_error' }, 500))
    setup(server, person({ has_photo: true, photo_version: 5 }))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить фото' }))
    const confirm = await screen.findByRole('dialog', { name: 'Удалить фото' })
    fireEvent.click(within(confirm).getByRole('button', { name: 'Удалить' }))
    expect(await screen.findByRole('alert')).toBeDefined()
  })

  describe('камера', () => {
    function fakeCamera() {
      const track = { stop: vi.fn() }
      const stream = { getTracks: () => [track] } as unknown as MediaStream
      const getUserMedia = vi.fn((_constraints: MediaStreamConstraints) => Promise.resolve(stream))
      Object.defineProperty(navigator, 'mediaDevices', {
        value: { getUserMedia },
        configurable: true,
      })
      return { track, getUserMedia }
    }

    test('закрытие окна останавливает треки камеры', async () => {
      const { track, getUserMedia } = fakeCamera()
      const { unmount } = setup(createFakeServer('admin'))
      fireEvent.click(screen.getByRole('button', { name: 'Снять камерой' }))
      await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
      expect(getUserMedia.mock.calls[0]?.[0]).toMatchObject({ video: { facingMode: 'user' } })
      await screen.findByRole('button', { name: 'Сделать снимок' })
      await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1))
      expect(track.stop).not.toHaveBeenCalled()
      unmount()
      expect(track.stop).toHaveBeenCalled()
    })

    test('смена режима на файл останавливает камеру', async () => {
      const { track } = fakeCamera()
      setup(createFakeServer('admin'))
      fireEvent.click(screen.getByRole('button', { name: 'Снять камерой' }))
      await screen.findByRole('button', { name: 'Сделать снимок' })
      await waitFor(() => expect(track.stop).not.toHaveBeenCalled())
      await pickFile()
      expect(track.stop).toHaveBeenCalled()
    })

    test('отказ в доступе даёт понятный текст', async () => {
      Object.defineProperty(navigator, 'mediaDevices', {
        value: { getUserMedia: () => Promise.reject(new DOMException('no', 'NotAllowedError')) },
        configurable: true,
      })
      setup(createFakeServer('admin'))
      fireEvent.click(screen.getByRole('button', { name: 'Снять камерой' }))
      expect(await screen.findByText(/Нет доступа к камере/)).toBeDefined()
      expect(screen.queryByRole('button', { name: 'Сделать снимок' })).toBeNull()
    })

    test('без камеры в браузере показывает ошибку', () => {
      setup(createFakeServer('admin'))
      fireEvent.click(screen.getByRole('button', { name: 'Снять камерой' }))
      expect(screen.getByText('Камера недоступна в этом браузере')).toBeDefined()
    })
  })
})
