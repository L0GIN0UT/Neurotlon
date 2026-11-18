import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api.ts'
import type { Api, Me } from '../api.ts'
import { errorText } from '../messages.ts'

interface Props {
  api: Api
  onLoggedIn: (me: Me) => void
}

export function Login({ api, onLoggedIn }: Props) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.login(login, password)
      onLoggedIn(await api.me())
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? 'Неверный логин или пароль'
          : errorText(e),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card stack" onSubmit={(e) => void submit(e)}>
      <h1>Вход волонтёра</h1>
      <label className="field">
        Логин
        <input
          value={login}
          onChange={(e) => setLogin(e.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          required
        />
      </label>
      <label className="field">
        Пароль
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <button type="submit" className="primary" disabled={busy}>
        Войти
      </button>
    </form>
  )
}
