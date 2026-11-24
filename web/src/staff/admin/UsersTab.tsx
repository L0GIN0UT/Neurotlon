import { useEffect, useRef, useState } from 'react'
import type { FocusEvent, FormEvent, KeyboardEvent as ReactKeyboardEvent } from 'react'
import { DisciplineIcon } from '../../shared/icons/DisciplineIcon.tsx'
import { DISCIPLINE_NAMES } from '../../shared/messages.ts'
import { DISCIPLINES } from '../../shared/types.ts'
import type { Discipline } from '../../shared/types.ts'
import type { NewUser, StaffApi, UserInfo } from '../api.ts'
import { ConfirmDialog, Dialog, ErrorText } from '../ui.tsx'
import { useAction, useLoader } from '../hooks.ts'
import './UsersTab.css'

const ROLE_NAMES: Record<string, string> = {
  admin: 'Админ',
  volunteer: 'Волонтёр',
}

const MIN_PASSWORD = 8

export function UsersTab({ api, meLogin }: { api: StaffApi; meLogin: string }) {
  const list = useLoader(() => api.users())
  const action = useAction()
  const [creating, setCreating] = useState(false)
  const [resetting, setResetting] = useState<UserInfo | null>(null)
  const [revoking, setRevoking] = useState<UserInfo | null>(null)
  const [disabling, setDisabling] = useState<UserInfo | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Суперпользователь скрыт в веб-админке и в счётчик не входит.
  const users = (list.data ?? []).filter((user) => user.role !== 'superuser')
  const activeCount = users.filter((user) => user.is_active).length

  async function toggle(user: UserInfo) {
    setNotice(null)
    const done = await action.run(() => api.patchUser(user.id, { is_active: !user.is_active }))
    setDisabling(null)
    if (done) list.reload()
  }

  async function revoke(user: UserInfo) {
    setNotice(null)
    const done = await action.run(() => api.revokeSessions(user.id).then(() => true))
    setRevoking(null)
    if (done) setNotice(`Сессии «${user.login}» завершены`)
  }

  return (
    <section className="stack users-tab">
      <div className="users-head">
        {list.data !== undefined ? (
          <p className="users-count">
            Пользователей: {users.length}, активных: {activeCount}
          </p>
        ) : (
          <span />
        )}
        <button
          type="button"
          className="primary"
          onClick={() => {
            setNotice(null)
            setCreating(true)
          }}
        >
          Добавить пользователя
        </button>
      </div>
      {notice && !action.error && <p role="status">{notice}</p>}
      <ErrorText error={action.error ?? list.error} />

      <ul className="users-list">
        {users.map((user) => (
          <UserCard
            key={user.id}
            user={user}
            busy={action.busy}
            isSelf={user.login === meLogin}
            onToggle={() => {
              setNotice(null)
              if (user.is_active) setDisabling(user)
              else void toggle(user)
            }}
            onReset={() => {
              setNotice(null)
              setResetting(user)
            }}
            onRevoke={() => {
              setNotice(null)
              setRevoking(user)
            }}
          />
        ))}
      </ul>

      {creating && (
        <CreateUser
          api={api}
          onClose={() => setCreating(false)}
          onDone={(login) => {
            setCreating(false)
            setNotice(`Аккаунт «${login}» создан`)
            list.reload()
          }}
        />
      )}
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
      {disabling && (
        <ConfirmDialog
          title="Отключить аккаунт?"
          message={`Аккаунт «${disabling.login}» не сможет войти, пока его не включат снова.`}
          confirmLabel="Отключить"
          busy={action.busy}
          onConfirm={() => void toggle(disabling)}
          onCancel={() => setDisabling(null)}
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

interface CardProps {
  user: UserInfo
  busy: boolean
  isSelf: boolean
  onToggle: () => void
  onReset: () => void
  onRevoke: () => void
}

function UserCard({ user, busy, isSelf, onToggle, onReset, onRevoke }: CardProps) {
  return (
    <li className="users-card">
      <span className="users-avatar" aria-hidden="true">
        {user.login.charAt(0).toUpperCase()}
      </span>
      <div className="users-main">
        <strong className="users-login">{user.login}</strong>
        <div className="users-chips">
          <span className="users-chip">{ROLE_NAMES[user.role] ?? user.role}</span>
          {user.discipline && (
            <span className="users-chip">
              <DisciplineIcon discipline={user.discipline} />
              {DISCIPLINE_NAMES[user.discipline]}
            </span>
          )}
          <span className={user.is_active ? 'users-chip on' : 'users-chip off'}>
            {user.is_active ? 'Активен' : 'Отключён'}
          </span>
        </div>
      </div>
      <div className="users-actions">
        {!(isSelf && user.is_active) && (
          <button
            type="button"
            className="small"
            disabled={busy}
            aria-label={user.is_active ? `Отключить ${user.login}` : `Включить ${user.login}`}
            onClick={onToggle}
          >
            {user.is_active ? 'Отключить' : 'Включить'}
          </button>
        )}
        <ActionMenu login={user.login} onReset={onReset} onRevoke={onRevoke} />
      </div>
    </li>
  )
}

interface MenuProps {
  login: string
  onReset: () => void
  onRevoke: () => void
}

function ActionMenu({ login, onReset, onRevoke }: MenuProps) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
        trigger.current?.focus()
      }
    }
    function onPointer(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [open])

  function pick(run: () => void) {
    setOpen(false)
    trigger.current?.focus()
    run()
  }

  function onMenuKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    )
    const index = items.indexOf(document.activeElement as HTMLElement)
    const target: Record<string, number> = {
      ArrowDown: (index + 1) % items.length,
      ArrowUp: (index - 1 + items.length) % items.length,
      Home: 0,
      End: items.length - 1,
    }
    const next = target[event.key]
    if (next === undefined) return
    event.preventDefault()
    items[next]?.focus()
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget
    if (next instanceof Node && !event.currentTarget.contains(next)) setOpen(false)
  }

  return (
    <div className="users-menu" ref={root} onBlur={onBlur}>
      <button
        type="button"
        className="small users-more"
        ref={trigger}
        aria-label={`Действия ${login}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">⋯</span>
      </button>
      {open && (
        <div
          className="users-popup"
          role="menu"
          aria-label={`Действия ${login}`}
          onKeyDown={onMenuKey}
        >
          <button type="button" role="menuitem" autoFocus onClick={() => pick(onReset)}>
            Сменить пароль
          </button>
          <button type="button" role="menuitem" className="danger" onClick={() => pick(onRevoke)}>
            Завершить сессии
          </button>
        </div>
      )}
    </div>
  )
}

interface PasswordFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  autoFocus?: boolean
}

function PasswordField({ label, value, onChange, autoFocus }: PasswordFieldProps) {
  const [shown, setShown] = useState(false)
  return (
    <div className="users-pw">
      <label className="field">
        {label}
        <input
          type={shown ? 'text' : 'password'}
          minLength={MIN_PASSWORD}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="new-password"
          autoFocus={autoFocus}
          required
        />
      </label>
      <button type="button" aria-pressed={shown} onClick={() => setShown((v) => !v)}>
        {shown ? 'Скрыть' : 'Показать'}
      </button>
    </div>
  )
}

interface CreateProps {
  api: StaffApi
  onClose: () => void
  onDone: (login: string) => void
}

function CreateUser({ api, onClose, onDone }: CreateProps) {
  const action = useAction()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<NewUser['role']>('volunteer')
  const [discipline, setDiscipline] = useState<Discipline>('darts')

  async function create(event: FormEvent) {
    event.preventDefault()
    const user: NewUser =
      role === 'volunteer' ? { login, password, role, discipline } : { login, password, role }
    if (await action.run(() => api.createUser(user))) onDone(login)
  }

  return (
    <Dialog title="Новый пользователь" onClose={onClose}>
      <form className="stack" onSubmit={(e) => void create(e)}>
        <label className="field">
          Логин
          <input
            value={login}
            maxLength={64}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="off"
            autoFocus
            required
          />
        </label>
        <PasswordField label={`Пароль (от ${MIN_PASSWORD} символов)`} value={password} onChange={setPassword} />
        <label className="field">
          Роль
          <select value={role} onChange={(e) => setRole(e.target.value as NewUser['role'])}>
            <option value="volunteer">Волонтёр</option>
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
        <ErrorText error={action.error} />
        <button type="submit" className="primary" disabled={action.busy}>
          Создать аккаунт
        </button>
      </form>
    </Dialog>
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
        <PasswordField label="Новый пароль" value={password} onChange={setPassword} autoFocus />
        <ErrorText error={action.error} />
        <button type="submit" className="primary" disabled={action.busy}>
          Сменить пароль
        </button>
      </form>
    </Dialog>
  )
}
