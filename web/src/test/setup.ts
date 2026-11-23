import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom не умеет воспроизводить видео; страницам станции нужен только вызов play()
HTMLMediaElement.prototype.play = () => Promise.resolve()

afterEach(() => {
  cleanup()
  localStorage.clear()
})
