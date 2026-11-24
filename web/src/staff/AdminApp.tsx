import { useState } from 'react'
import { DisciplinesTab } from './admin/DisciplinesTab.tsx'
import { DrawTab } from './admin/DrawTab.tsx'
import { ParticipantsTab } from './admin/ParticipantsTab.tsx'
import { StationsTab } from './admin/StationsTab.tsx'
import { UsersTab } from './admin/UsersTab.tsx'
import { ExportLink } from './ExportLink.tsx'
import { PageHead, StaffShell, Tabs } from './StaffShell.tsx'

type Tab = 'participants' | 'draw' | 'stations' | 'disciplines' | 'users' | 'export'

const TABS: { id: Tab; label: string; title: string; hint: string }[] = [
  {
    id: 'participants',
    label: 'Участники',
    title: 'Участники',
    hint: 'ID, отметка о приходе, команды и баллы по дисциплинам.',
  },
  {
    id: 'draw',
    label: 'Жеребьёвка',
    title: 'Жеребьёвка и команды',
    hint: 'Разбивка пришедших на команды и пары; названия и цвета команд для табло.',
  },
  {
    id: 'stations',
    label: 'Станции',
    title: 'Станции',
    hint: 'Стенды зала: состояние связи и токены доступа.',
  },
  {
    id: 'disciplines',
    label: 'Дисциплины',
    title: 'Дисциплины',
    hint: 'Длительность игр, очки за победу и лимит очков за секцию.',
  },
  {
    id: 'users',
    label: 'Пользователи',
    title: 'Пользователи',
    hint: 'Судьи, волонтёры и администраторы.',
  },
  {
    id: 'export',
    label: 'Экспорт XLSX',
    title: 'Экспорт',
    hint: 'Выгрузка результатов в таблицу Excel.',
  },
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
          <PageHead
            title={TABS.find((t) => t.id === tab)?.title ?? ''}
            hint={TABS.find((t) => t.id === tab)?.hint}
          />
          {tab === 'participants' && <ParticipantsTab api={api} />}
          {tab === 'draw' && <DrawTab api={api} />}
          {tab === 'stations' && <StationsTab api={api} />}
          {tab === 'disciplines' && <DisciplinesTab api={api} />}
          {tab === 'users' && me.role === 'superuser' && <UsersTab api={api} meLogin={me.login} />}
          {tab === 'export' && <ExportLink />}
        </>
      )}
    </StaffShell>
  )
}
