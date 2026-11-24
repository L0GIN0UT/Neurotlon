import type { StaffApi, TeamInfo } from '../api.ts'
import { ColorPicker } from '../ColorPicker.tsx'
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
  onSaved: (team: TeamInfo) => void
}) {
  const draft = useTeamDraft(team, api, onSaved)
  return (
    <div className="tm-title">
      <div className="row">
        <ColorPicker
          label={`Цвет команды ${team.number}`}
          value={draft.color}
          onChange={(hex) => void draft.pickColor(hex)}
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
      <ErrorText error={draft.action.error ?? draft.notice} />
    </div>
  )
}
