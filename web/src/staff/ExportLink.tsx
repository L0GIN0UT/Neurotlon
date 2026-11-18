import { EXPORT_URL } from './api.ts'

export function ExportLink() {
  return (
    <section className="card stack">
      <h2>Экспорт сводной таблицы</h2>
      <p>
        Листы «Итоги» и «Участники» считаются тем же кодом, что и табло. Категорий в файле нет.
      </p>
      <a className="button primary" href={EXPORT_URL} download="neurotlon.xlsx">
        Скачать XLSX
      </a>
    </section>
  )
}
