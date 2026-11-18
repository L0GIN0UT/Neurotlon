import { useState } from 'react'
import type { StaffApi, TeamInfo } from '../api.ts'
import { useAction, useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'

const MAX_NAME = 24

function TeamRow({
  team,
  api,
  onSaved,
}: {
  team: TeamInfo
  api: StaffApi
  onSaved: () => void
}) {
  const [name, setName] = useState(team.name)
  const [color, setColor] = useState(team.color)
  const action = useAction()
  const trimmed = name.trim()
  const invalid = trimmed.length < 1 || trimmed.length > MAX_NAME
  const changed = trimmed !== team.name || color.toLowerCase() !== team.color.toLowerCase()

  async function save() {
    const saved = await action.run(() => api.patchTeam(team.id, trimmed, color))
    if (saved) onSaved()
  }

  return (
    <li className="row">
      <label className="field grow">
        {`Название команды ${team.number}`}
        <input value={name} maxLength={MAX_NAME} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        {`Цвет команды ${team.number}`}
        <input type="color" value={color.toLowerCase()} onChange={(e) => setColor(e.target.value)} />
      </label>
      <button
        type="button"
        className="primary"
        disabled={invalid || !changed || action.busy}
        onClick={() => void save()}
        aria-label={`Сохранить команду ${team.number}`}
      >
        Сохранить
      </button>
      <ErrorText error={action.error} />
    </li>
  )
}

/** Название и цвет команд: показываются на табло и в оверлее. */
export function TeamsEditor({ api, onSaved }: { api: StaffApi; onSaved: () => void }) {
  const teams = useLoader(() => api.teams())
  if (!teams.data || teams.data.teams.length === 0) return <ErrorText error={teams.error} />
  return (
    <div className="card stack no-print" aria-label="Команды">
      <h2>Команды</h2>
      <p>Название (1–{MAX_NAME} символов) и цвет видны на табло и в оверлее OBS.</p>
      <ul className="stack">
        {teams.data.teams.map((team) => (
          <TeamRow
            key={`${team.id}:${team.name}:${team.color}`}
            team={team}
            api={api}
            onSaved={() => {
              teams.reload()
              onSaved()
            }}
          />
        ))}
      </ul>
    </div>
  )
}
