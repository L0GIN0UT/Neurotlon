import { useState } from 'react'
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

export function JudgeApp({ fetchFn }: { fetchFn?: typeof fetch }) {
  const [tab, setTab] = useState<Tab>('conflicts')
  return (
    <StaffShell title="Судья" allow={['judge', 'admin', 'superuser']} fetchFn={fetchFn}>
      {({ api, me }) => {
        const canEditLocked = me.role !== 'judge'
        return (
          <>
            <Tabs tabs={TABS} active={tab} onChange={setTab} />
            {tab === 'conflicts' && <ConflictsPanel api={api} />}
            {tab === 'corrections' && <CorrectionsPanel api={api} canEditLocked={canEditLocked} />}
            {tab === 'search' && <SearchPanel api={api} canEditLocked={canEditLocked} />}
            {tab === 'lock' && (
              <>
                <LockPanel api={api} canForce={canEditLocked} />
                <ExportLink />
              </>
            )}
          </>
        )
      }}
    </StaffShell>
  )
}
