import { useState } from 'react'
import type { Discipline, Me } from '../shared/types.ts'
import type { StaffApi } from './api.ts'
import { useLoader } from './hooks.ts'
import { ConflictsPanel } from './judge/ConflictsPanel.tsx'
import { CorrectionsPanel } from './judge/CorrectionsPanel.tsx'
import { SearchPanel } from './judge/SearchPanel.tsx'
import { SummaryPanel } from './judge/SummaryPanel.tsx'
import { PageHead, StaffShell, Tabs } from './StaffShell.tsx'

type Tab = 'conflicts' | 'corrections' | 'search' | 'lock'

const TABS: { id: Tab; label: string; title: string; hint?: string }[] = [
  {
    id: 'conflicts',
    label: 'Конфликты',
    title: 'Конфликты результатов',
  },
  {
    id: 'corrections',
    label: 'Запросы на исправление',
    title: 'Запросы на исправление',
    hint: 'Волонтёры просят проверить результат сессии.',
  },
  {
    id: 'search',
    label: 'Поиск и правка',
    title: 'Поиск и правка результатов',
    hint: 'Найдите результат участника и исправьте его с указанием причины.',
  },
  {
    id: 'lock',
    label: 'Итоги',
    title: 'Подведение итогов',
    hint: 'Сверьте счётчики и чек-лист, зафиксируйте результаты и выгрузите таблицу в Excel.',
  },
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
      <PageHead
        title={TABS.find((t) => t.id === tab)?.title ?? ''}
        hint={TABS.find((t) => t.id === tab)?.hint}
      />
      {tab === 'conflicts' && <ConflictsPanel api={api} />}
      {tab === 'corrections' && (
        <CorrectionsPanel api={api} canEditLocked={canEditLocked} limits={limits} />
      )}
      {tab === 'search' && <SearchPanel api={api} canEditLocked={canEditLocked} limits={limits} />}
      {tab === 'lock' && (
        <SummaryPanel api={api} canForce={canEditLocked} onNavigate={setTab} />
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
