import { useRef, useState } from 'react'
import type { StaffApi, TeamInfo } from '../api.ts'
import { useAction } from '../hooks.ts'

export const MAX_NAME = 24

/**
 * Черновик названия и цвета команды. Пока человек ничего не менял, показываются значения
 * с сервера (их обновление не сбивает ввод); отправляется только изменённое и верное.
 */
export function useTeamDraft(team: TeamInfo, api: StaffApi, onSaved: (team: TeamInfo) => void) {
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  const [colorDraft, setColorDraft] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // Последняя отправленная пара: Enter и следующий за ним blur не шлют запрос дважды.
  const sent = useRef<string | null>(null)
  const action = useAction()

  const name = nameDraft ?? team.name
  const color = colorDraft ?? team.color
  const trimmed = name.trim()
  const invalid = trimmed.length < 1 || trimmed.length > MAX_NAME
  const changed = trimmed !== team.name || color.toLowerCase() !== team.color.toLowerCase()

  function setName(value: string) {
    setNameDraft(value)
    setNotice(null)
    sent.current = null
  }

  function setColor(value: string) {
    setColorDraft(value)
    sent.current = null
  }

  async function save() {
    if (!changed || action.busy) return
    if (invalid) {
      setNotice(`Название команды: от 1 до ${MAX_NAME} символов`)
      return
    }
    const pair = `${trimmed}\n${color.toLowerCase()}`
    if (sent.current === pair) return
    sent.current = pair
    const saved = await action.run(() => api.patchTeam(team.id, trimmed, color))
    if (saved) {
      setNameDraft(null)
      setColorDraft(null)
      onSaved(saved)
    } else {
      sent.current = null
    }
  }

  return { name, setName, color, setColor, invalid, changed, save, action, notice }
}
