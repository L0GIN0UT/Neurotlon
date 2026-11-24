import { useState } from 'react'
import type { StaffApi, TeamInfo } from '../api.ts'
import { useAction } from '../hooks.ts'

export const MAX_NAME = 24

/** Черновик названия и цвета команды; сохраняется только если что-то изменилось и название верно. */
export function useTeamDraft(team: TeamInfo, api: StaffApi, onSaved: () => void) {
  const [name, setName] = useState(team.name)
  const [color, setColor] = useState(team.color)
  const action = useAction()
  const trimmed = name.trim()
  const invalid = trimmed.length < 1 || trimmed.length > MAX_NAME
  const changed = trimmed !== team.name || color.toLowerCase() !== team.color.toLowerCase()

  async function save() {
    if (invalid || !changed || action.busy) return
    const saved = await action.run(() => api.patchTeam(team.id, trimmed, color))
    if (saved) onSaved()
  }

  return { name, setName, color, setColor, invalid, changed, save, action }
}
