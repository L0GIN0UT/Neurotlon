import { EXPORT_URL } from './api.ts'
import './judge/Summary.css'

export function ExportLink() {
  return (
    <section className="card summary-action">
      <div className="head">
        <svg
          className="icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 3v12M7 10l5 5 5-5M4 20h16" />
        </svg>
        <h2>Выгрузить таблицу</h2>
      </div>
      <p>Файл Excel (XLSX) со сводкой. Внутри два листа:</p>
      <ul>
        <li>«Итоги» — очки и места, считаются тем же кодом, что и табло;</li>
        <li>«Участники» — результаты каждого участника.</li>
      </ul>
      <p>Категорий в файле нет.</p>
      <a className="button primary push" href={EXPORT_URL} download="neurotlon.xlsx">
        Скачать XLSX
      </a>
    </section>
  )
}
