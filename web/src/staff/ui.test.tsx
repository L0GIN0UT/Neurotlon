import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, test, vi } from 'vitest'
import { ConfirmDialog, Dialog } from './ui.tsx'

function Host() {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Открыть
      </button>
      {open && (
        <Dialog title="Окно" onClose={() => setOpen(false)}>
          <input aria-label="Поле" />
        </Dialog>
      )}
    </div>
  )
}

test('окно: автофокус, Escape закрывает, фокус возвращается на открывший элемент', () => {
  render(<Host />)
  const opener = screen.getByRole('button', { name: 'Открыть' })
  opener.focus()
  fireEvent.click(opener)
  const dialog = screen.getByRole('dialog', { name: 'Окно' })
  expect(dialog.contains(document.activeElement)).toBe(true)
  expect(document.activeElement).toBe(screen.getByLabelText('Поле'))
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(opener)
})

test('окно: Tab и Shift+Tab не уходят за пределы окна', () => {
  render(<Host />)
  fireEvent.click(screen.getByRole('button', { name: 'Открыть' }))
  const dialog = screen.getByRole('dialog')
  const input = screen.getByLabelText('Поле')
  const close = screen.getByRole('button', { name: 'Закрыть' })
  close.focus()
  fireEvent.keyDown(close, { key: 'Tab' })
  expect(document.activeElement).toBe(input)
  fireEvent.keyDown(input, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(close)
  expect(dialog.contains(document.activeElement)).toBe(true)
})

test('подтверждение: Escape вызывает отмену, фокус на первой кнопке', () => {
  const onCancel = vi.fn()
  render(
    <ConfirmDialog title="Точно?" message="Текст" confirmLabel="Да" onConfirm={() => undefined} onCancel={onCancel} />,
  )
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Да' }))
  fireEvent.keyDown(screen.getByRole('dialog', { name: 'Точно?' }), { key: 'Escape' })
  expect(onCancel).toHaveBeenCalledTimes(1)
})
