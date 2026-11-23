import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'

export interface SelectOption {
  value: string
  label: string
}

interface Props {
  /** `id` подписи (элемент с этим id описывает поле для читалок и тестов). */
  labelId: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  disabled?: boolean
}

/**
 * Выпадающий список в стиле окна: встроенный `<select>` рисует белое системное меню,
 * которое не подстроить. Работает с клавиатурой (стрелки, Enter, Esc) и читалками экрана.
 */
export function Select({ labelId, value, options, onChange, disabled = false }: Props) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const listId = useId()
  const selected = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  )

  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  const choose = (index: number) => {
    const option = options[index]
    if (option) onChange(option.value)
    setOpen(false)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const last = options.length - 1
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        event.preventDefault()
        const step = event.key === 'ArrowDown' ? 1 : -1
        if (!open) {
          setActive(selected)
          setOpen(true)
        } else {
          setActive((index) => Math.min(last, Math.max(0, index + step)))
        }
        break
      }
      case 'Home':
      case 'End':
        if (open) {
          event.preventDefault()
          setActive(event.key === 'Home' ? 0 : last)
        }
        break
      case 'Enter':
      case ' ':
        if (open) {
          event.preventDefault()
          choose(active)
        }
        break
      case 'Escape':
        if (open) {
          event.preventDefault()
          event.stopPropagation()
          setOpen(false)
        }
        break
    }
  }

  return (
    <div className="select" ref={root}>
      <button
        type="button"
        className="select-button"
        role="combobox"
        aria-labelledby={labelId}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => {
          setActive(selected)
          setOpen((current) => !current)
        }}
        onKeyDown={onKeyDown}
      >
        <span className="select-value">{options[selected]?.label ?? ''}</span>
        <svg className="select-chevron" viewBox="0 0 24 24" aria-hidden>
          <path d="M6 9l6 6l6 -6" />
        </svg>
      </button>
      {open && (
        <ul className="select-list" role="listbox" id={listId} aria-labelledby={labelId}>
          {options.map((option, index) => (
            <li
              key={option.value}
              role="option"
              aria-selected={index === selected}
              className={`select-option${index === active ? ' active' : ''}${index === selected ? ' selected' : ''}`}
              onPointerEnter={() => setActive(index)}
              onClick={() => choose(index)}
            >
              {option.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
