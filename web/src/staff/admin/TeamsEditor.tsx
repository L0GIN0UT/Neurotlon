import type { StaffApi, TeamInfo } from '../api.ts'
import { ColorPicker } from '../ColorPicker.tsx'
import { useLoader } from '../hooks.ts'
import { ErrorText } from '../ui.tsx'
import { MAX_NAME, useTeamDraft } from './useTeamDraft.ts'

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
      <div className="field">
        <span>{`Цвет команды ${team.number}`}</span>
        <ColorPicker
          label={`Цвет команды ${team.number}`}
          value={draft.color}
          onChange={draft.setColor}
        />
      </div>
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
