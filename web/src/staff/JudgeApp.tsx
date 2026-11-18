import { useState } from 'react'
import type { Discipline, Me } from '../shared/types.ts'
import type { StaffApi } from './api.ts'
import { useLoader } from './hooks.ts'
import { ExportLink } from './ExportLink.tsx'
import { ConflictsPanel } from './judge/ConflictsPanel.tsx'
import { CorrectionsPanel } from './judge/CorrectionsPanel.tsx'
import { LockPanel } from './judge/LockPanel.tsx'
import { SearchPanel } from './judge/SearchPanel.tsx'
import { StaffShell, Tabs } from './StaffShell.tsx'

type Tab = 'conflicts' | 'corrections' | 'search' | 'lock'

const TABS: { id: Tab; label: string }[] = [
  { id: 'conflicts', label: 'Конфликты' },
  { id: 'corrections', label: 'Запросы на исправление' },
  { id: 'search', label: 'Поиск и правка' },
  { id: 'lock', label: 'Итоги' },
]

function JudgeTabs({ api, me }: { api: StaffApi; me: Me }) {
  const [tab, setTab] = useState<Tab>('conflicts')
  const settings = useLoader(() => api.disciplines())
  // Лимит очков за секцию нужен формам правки; пока не загружен (или не загрузился),
  // форма проверяет только потолок схемы, остальное проверяет сервер.
  const limits: Partial<Record<Discipline, number>> = Object.fromEntries(
    (settings.data ?? []).map((d) => [d.code, d.max_section_points]),
  )
  const canEditLocked = me.role !== 'judge'
  return (
    <>
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      {tab === 'conflicts' && <ConflictsPanel api={api} />}
      {tab === 'corrections' && (
        <CorrectionsPanel api={api} canEditLocked={canEditLocked} limits={limits} />
      )}
      {tab === 'search' && <SearchPanel api={api} canEditLocked={canEditLocked} limits={limits} />}
      {tab === 'lock' && (
        <>
          <LockPanel api={api} canForce={canEditLocked} />
          <ExportLink />
        </>
      )}
    </>
  )
}

export function JudgeApp({ fetchFn }: { fetchFn?: typeof fetch }) {
  return (
    <StaffShell title="Судья" allow={['judge', 'admin', 'superuser']} fetchFn={fetchFn}>
      {({ api, me }) => <JudgeTabs api={api} me={me} />}
    </StaffShell>
  )
}
