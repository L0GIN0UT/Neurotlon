import logo from '../station/assets/logo.png'
import { accentFor } from '../station/model.ts'
import { DisciplineIcon } from '../shared/icons/DisciplineIcon.tsx'
import { DISCIPLINE_NAMES } from '../shared/messages.ts'
import { DISCIPLINES } from '../shared/types.ts'
import type { CSSProperties } from 'react'
import type { QrMatrix } from '../staff/api.ts'
import { qrPath, QUIET_MODULES, tileSideMm } from './qr.ts'

function QrTile({ matrix }: { matrix: QrMatrix }) {
  const side = tileSideMm(matrix.size)
  const units = matrix.size + 2 * QUIET_MODULES
  return (
    <div className="qr-frame">
      <i className="c tl" />
      <i className="c tr" />
      <i className="c bl" />
      <i className="c br" />
      <svg
        className="qr-tile"
        data-testid="qr-tile"
        style={{ width: `${side}mm`, height: `${side}mm` }}
        viewBox={`0 0 ${units} ${units}`}
        shapeRendering="crispEdges"
        role="img"
        aria-label={`QR ${matrix.code}`}
      >
        <rect width={units} height={units} fill="#fff" />
        <path d={qrPath(matrix)} fill="#000" />
      </svg>
    </div>
  )
}

function Silhouette() {
  return (
    <svg className="silhouette" viewBox="0 0 40 52" aria-hidden="true" focusable={false}>
      <circle cx="20" cy="19" r="8.5" />
      <path d="M4 52c0-12 7-19 16-19s16 7 16 19z" />
    </svg>
  )
}

const SPONSOR_SLOTS = [0, 1, 2]
const SECTION_HEAD = [
  { id: 'bci', label: 'BCI' },
  { id: 'physical', label: 'Реальная' },
]

/** Бейдж 95×135 мм. Команды, ФИО и категории на нём нет. */
export function Badge({ matrix }: { matrix: QrMatrix }) {
  return (
    <article className="id-badge" aria-label={`Бейдж ${matrix.code}`}>
      <div className="badge-top">
        <div className="badge-left">
          <div className="photo">
            <Silhouette />
            <span>нет фото</span>
          </div>
          <div className="badge-code">{matrix.code}</div>
        </div>
        <div className="badge-right">
          <img className="badge-logo" src={logo} alt="Нейротлон" />
          <QrTile matrix={matrix} />
        </div>
      </div>

      <table className="results">
        <thead>
          <tr>
            <th aria-label="Дисциплина" />
            {SECTION_HEAD.map((section) => (
              <th key={section.id}>{section.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DISCIPLINES.map((discipline) => (
            <tr key={discipline}>
              <th scope="row" style={{ '--accent': accentFor(discipline) } as CSSProperties}>
                <span className="ico" title={DISCIPLINE_NAMES[discipline]}>
                  <DisciplineIcon discipline={discipline} />
                </span>
              </th>
              {SECTION_HEAD.map((section) => (
                <td key={section.id}>
                  <span className="line" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="partners">
        <span className="partners-label">Партнёры</span>
        <div className="partners-slots">
          {SPONSOR_SLOTS.map((slot) => (
            <div key={slot} className="sponsor-slot" />
          ))}
        </div>
      </div>
    </article>
  )
}
