import { useState } from 'react'
import type { FormEvent } from 'react'
import { DISCIPLINE_NAMES, SECTION_NAMES } from '../../shared/messages.ts'
import { DISCIPLINES } from '../../shared/types.ts'
import type { Discipline, Section } from '../../shared/types.ts'
import type { StaffApi, StoredResult } from '../api.ts'
import { ErrorText } from '../ui.tsx'
import { useAction } from '../hooks.ts'
import { ResultEditor } from './ResultEditor.tsx'

interface Props {
  api: StaffApi
  canEditLocked: boolean
}

export function SearchPanel({ api, canEditLocked }: Props) {
  const action = useAction()
  const [participant, setParticipant] = useState('')
  const [discipline, setDiscipline] = useState<Discipline | ''>('')
  const [section, setSection] = useState<Section | ''>('')
  const [rows, setRows] = useState<StoredResult[] | null>(null)

  async function search(event: FormEvent) {
    event.preventDefault()
    const found = await action.run(() =>
      api.results({ participant: participant.trim(), discipline, section }),
    )
    if (found) setRows(found)
  }

  return (
    <section className="stack">
      <form className="row card" onSubmit={(e) => void search(e)}>
        <label className="field">
          ID участника
          <input
            value={participant}
            onChange={(e) => setParticipant(e.target.value)}
            placeholder="NT07"
          />
        </label>
        <label className="field">
          Дисциплина
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value as Discipline | '')}
          >
            <option value="">Любая</option>
            {DISCIPLINES.map((code) => (
              <option key={code} value={code}>
                {DISCIPLINE_NAMES[code]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Секция
          <select value={section} onChange={(e) => setSection(e.target.value as Section | '')}>
            <option value="">Любая</option>
            <option value="bci">{SECTION_NAMES.bci}</option>
            <option value="physical">{SECTION_NAMES.physical}</option>
          </select>
        </label>
        <button type="submit" className="primary" disabled={action.busy}>
          Найти
        </button>
      </form>
      <ErrorText error={action.error} />
      {rows?.length === 0 && <p className="card">Ничего не найдено.</p>}
      {rows?.map((row) => (
        <ResultEditor
          key={row.id}
          api={api}
          row={row}
          canEditLocked={canEditLocked}
          onSaved={(saved) =>
            setRows((current) => current?.map((r) => (r.id === saved.id ? saved : r)) ?? null)
          }
        />
      ))}
    </section>
  )
}
