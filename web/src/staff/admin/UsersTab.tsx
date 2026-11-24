import { useState } from 'react'
import type { FormEvent } from 'react'
import { DISCIPLINE_NAMES } from '../../shared/messages.ts'
import { DISCIPLINES } from '../../shared/types.ts'
import type { Discipline } from '../../shared/types.ts'
import type { NewUser, StaffApi, UserInfo } from '../api.ts'
import { ConfirmDialog, Dialog, ErrorText } from '../ui.tsx'
import { useAction, useLoader } from '../hooks.ts'

const ROLE_NAMES: Record<string, string> = {
  superuser: 'Суперпользователь',
  admin: 'Админ',
  judge: 'Судья',
  volunteer: 'Волонтёр',
}

const MIN_PASSWORD = 8

export function UsersTab({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.users())
  const action = useAction()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<NewUser['role']>('volunteer')
  const [discipline, setDiscipline] = useState<Discipline>('darts')
  const [resetting, setResetting] = useState<UserInfo | null>(null)
  const [revoking, setRevoking] = useState<UserInfo | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function create(event: FormEvent) {
    event.preventDefault()
    const user: NewUser =
      role === 'volunteer' ? { login, password, role, discipline } : { login, password, role }
    if (await action.run(() => api.createUser(user))) {
      setLogin('')
      setPassword('')
      setNotice(`Аккаунт «${login}» создан`)
      list.reload()
    }
  }

  async function toggle(user: UserInfo) {
    if (await action.run(() => api.patchUser(user.id, { is_active: !user.is_active }))) {
      list.reload()
    }
  }

  async function revoke(user: UserInfo) {
    const done = await action.run(() => api.revokeSessions(user.id).then(() => true))
    setRevoking(null)
    if (done) setNotice(`Сессии «${user.login}» завершены`)
  }

  return (
    <section className="stack">
      <form className="row card" onSubmit={(e) => void create(e)}>
        <label className="field">
          Логин
          <input value={login} maxLength={64} onChange={(e) => setLogin(e.target.value)} required />
        </label>
        <label className="field">
          Пароль (от {MIN_PASSWORD} символов)
          <input
            type="password"
            minLength={MIN_PASSWORD}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
          />
        </label>
        <label className="field">
          Роль
          <select value={role} onChange={(e) => setRole(e.target.value as NewUser['role'])}>
            <option value="volunteer">Волонтёр</option>
            <option value="judge">Судья</option>
            <option value="admin">Админ</option>
          </select>
        </label>
        {role === 'volunteer' && (
          <label className="field">
            Секция волонтёра
            <select
              value={discipline}
              onChange={(e) => setDiscipline(e.target.value as Discipline)}
            >
              {DISCIPLINES.map((code) => (
                <option key={code} value={code}>
                  {DISCIPLINE_NAMES[code]}
                </option>
              ))}
            </select>
          </label>
        )}
        <button type="submit" className="primary" disabled={action.busy}>
          Создать аккаунт
        </button>
      </form>
      {notice && <p role="status">{notice}</p>}
      <ErrorText error={action.error ?? list.error} />

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Логин</th>
              <th>Роль</th>
              <th>Секция</th>
              <th>Состояние</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {(list.data ?? []).map((user) => (
              <tr key={user.id}>
                <td>{user.login}</td>
                <td>{ROLE_NAMES[user.role]}</td>
                <td>{user.discipline ? DISCIPLINE_NAMES[user.discipline] : '—'}</td>
                <td>{user.is_active ? 'активен' : 'отключён'}</td>
                <td className="actions">
                  <button type="button" onClick={() => void toggle(user)}>
                    {user.is_active ? `Отключить ${user.login}` : `Включить ${user.login}`}
                  </button>
                  <button type="button" onClick={() => setResetting(user)}>
                    Сбросить пароль {user.login}
                  </button>
                  <button type="button" onClick={() => setRevoking(user)}>
                    Завершить сессии {user.login}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {resetting && (
        <ResetPassword
          api={api}
          user={resetting}
          onClose={() => setResetting(null)}
          onDone={() => {
            setNotice(`Пароль «${resetting.login}» изменён, сессии завершены`)
            setResetting(null)
          }}
        />
      )}
      {revoking && (
        <ConfirmDialog
          title="Завершить сессии?"
          message={`Аккаунт «${revoking.login}» будет разлогинен на всех устройствах.`}
          confirmLabel="Завершить сессии"
          busy={action.busy}
          onConfirm={() => void revoke(revoking)}
          onCancel={() => setRevoking(null)}
        />
      )}
    </section>
  )
}

interface ResetProps {
  api: StaffApi
  user: UserInfo
  onClose: () => void
  onDone: () => void
}

function ResetPassword({ api, user, onClose, onDone }: ResetProps) {
  const action = useAction()
  const [password, setPassword] = useState('')

  async function save(event: FormEvent) {
    event.preventDefault()
    if (await action.run(() => api.patchUser(user.id, { password }))) onDone()
  }

  return (
    <Dialog title={`Новый пароль ${user.login}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => void save(e)}>
        <label className="field">
          Новый пароль
          <input
            type="password"
            minLength={MIN_PASSWORD}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
          />
        </label>
        <ErrorText error={action.error} />
        <button type="submit" className="primary" disabled={action.busy}>
          Сменить пароль
        </button>
      </form>
    </Dialog>
  )
}
