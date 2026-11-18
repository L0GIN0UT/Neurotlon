import { useState } from 'react'
import { DisciplinesTab } from './admin/DisciplinesTab.tsx'
import { DrawTab } from './admin/DrawTab.tsx'
import { ParticipantsTab } from './admin/ParticipantsTab.tsx'
import { StationsTab } from './admin/StationsTab.tsx'
import { UsersTab } from './admin/UsersTab.tsx'
import { ExportLink } from './ExportLink.tsx'
import { StaffShell, Tabs } from './StaffShell.tsx'

type Tab = 'participants' | 'draw' | 'stations' | 'disciplines' | 'users' | 'export'

const TABS: { id: Tab; label: string }[] = [
  { id: 'participants', label: 'Участники' },
  { id: 'draw', label: 'Жеребьёвка' },
  { id: 'stations', label: 'Станции' },
  { id: 'disciplines', label: 'Дисциплины' },
  { id: 'users', label: 'Пользователи' },
  { id: 'export', label: 'Экспорт XLSX' },
]

export function AdminApp({ fetchFn }: { fetchFn?: typeof fetch }) {
  const [tab, setTab] = useState<Tab>('participants')
  return (
    <StaffShell title="Админка" allow={['admin', 'superuser']} fetchFn={fetchFn}>
      {({ api, me }) => (
        <>
          <Tabs
            // Вкладка «Пользователи» только для суперпользователя (сервер тоже закрывает её).
            tabs={TABS.filter((t) => t.id !== 'users' || me.role === 'superuser')}
            active={tab}
            onChange={setTab}
          />
          {tab === 'participants' && <ParticipantsTab api={api} />}
          {tab === 'draw' && <DrawTab api={api} />}
          {tab === 'stations' && <StationsTab api={api} />}
          {tab === 'disciplines' && <DisciplinesTab api={api} />}
          {tab === 'users' && me.role === 'superuser' && <UsersTab api={api} />}
          {tab === 'export' && <ExportLink />}
        </>
      )}
    </StaffShell>
  )
}
