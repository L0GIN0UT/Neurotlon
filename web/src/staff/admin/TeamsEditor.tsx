import type { StaffApi, TeamInfo } from '../api.ts'
import { useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'
import { MAX_NAME, useTeamDraft } from './useTeamDraft.ts'

/** Название и цвет команды в шапке колонки: сохранение по Enter и по потере фокуса. */
export function TeamTitle({
  team,
  api,
  onSaved,
}: {
  team: TeamInfo
  api: StaffApi
  onSaved: () => void
}) {
  const draft = useTeamDraft(team, api, onSaved)
  return (
    <div className="tm-title">
      <div className="row">
        <input
          type="color"
          className="tm-color"
          aria-label={`Цвет команды ${team.number}`}
          value={draft.color.toLowerCase()}
          onChange={(e) => draft.setColor(e.target.value)}
          onBlur={() => void draft.save()}
        />
        <input
          className="tm-name-input grow"
          aria-label={`Название команды ${team.number}`}
          value={draft.name}
          maxLength={MAX_NAME}
          onChange={(e) => draft.setName(e.target.value)}
          onBlur={() => void draft.save()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void draft.save()
          }}
        />
      </div>
      <ErrorText error={draft.action.error} />
    </div>
  )
}

function TeamRow({
  team,
  api,
  onSaved,
}: {
  team: TeamInfo
  api: StaffApi
  onSaved: () => void
}) {
  const draft = useTeamDraft(team, api, onSaved)
  return (
    <li className="row">
      <label className="field grow">
        {`Название команды ${team.number}`}
        <input
          value={draft.name}
          maxLength={MAX_NAME}
          onChange={(e) => draft.setName(e.target.value)}
        />
      </label>
      <label className="field">
        {`Цвет команды ${team.number}`}
        <input
          type="color"
          value={draft.color.toLowerCase()}
          onChange={(e) => draft.setColor(e.target.value)}
        />
      </label>
      <button
        type="button"
        className="primary"
        disabled={draft.invalid || !draft.changed || draft.action.busy}
        onClick={() => void draft.save()}
        aria-label={`Сохранить команду ${team.number}`}
      >
        Сохранить
      </button>
      <ErrorText error={draft.action.error} />
    </li>
  )
}

/** Название и цвет команд: показываются на табло и в оверлее. Используется вкладкой жеребьёвки. */
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
