import logo from '../station/assets/logo.png'
import { accentFor } from '../station/model.ts'
import { DisciplineIcon } from '../shared/icons/DisciplineIcon.tsx'
import { DISCIPLINE_NAMES } from '../shared/messages.ts'
import { DISCIPLINES } from '../shared/types.ts'
import type { CSSProperties } from 'react'
import type { QrMatrix } from '../staff/api.ts'
import { nameSizeMm } from './nameSize.ts'
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

export type PhotoState = 'pending' | 'ok' | 'error'

/** Сообщение страницы о том, загрузилась ли картинка: по нему «Печать» ждёт реальные `<img>`. */
export type PhotoReport = (url: string, ok: boolean) => void

export interface BadgePhoto {
  url: string
  state: PhotoState
}

function PhotoFrame({ photo, onPhoto }: { photo: BadgePhoto | null; onPhoto?: PhotoReport }) {
  if (photo !== null && photo.state !== 'error') {
    return (
      <div className="photo">
        <img
          className="photo-img"
          src={photo.url}
          alt=""
          onLoad={() => onPhoto?.(photo.url, true)}
          onError={() => onPhoto?.(photo.url, false)}
        />
      </div>
    )
  }
  return (
    <div className="photo">
      <Silhouette />
      {photo !== null ? (
        <span className="photo-fail" title="Фото не загрузилось">
          ! фото
        </span>
      ) : (
        <span>нет фото</span>
      )}
    </div>
  )
}

const SPONSOR_SLOTS = [0, 1, 2]
const SECTION_HEAD = [
  { id: 'bci', label: 'BCI' },
  { id: 'physical', label: 'Реальная' },
]

/** Бейдж 95×135 мм: номер, имя на табло, фото, QR. Команды, ФИО и категории на нём нет. */
export function Badge({
  matrix,
  name,
  photo,
  sponsors,
  onPhoto,
}: {
  matrix: QrMatrix
  name: string | null
  photo: BadgePhoto | null
  /** Показывать блок «Партнёры»; без него место забирает таблица результатов. */
  sponsors: boolean
  onPhoto?: PhotoReport
}) {
  const shownName = name?.trim() ?? ''
  return (
    <article className={`id-badge${sponsors ? '' : ' no-partners'}`} aria-label={`Бейдж ${matrix.code}`}>
      <div className="badge-top">
        <div className={`badge-head${shownName ? ' has-name' : ''}`}>
          <div className="badge-code">{matrix.code}</div>
          {shownName && (
            <div className="badge-name" style={{ fontSize: `${nameSizeMm(shownName)}mm` }}>
              {shownName}
            </div>
          )}
        </div>
        <img className="badge-logo" src={logo} alt="Нейротлон" />
        <PhotoFrame photo={photo} onPhoto={onPhoto} />
        <QrTile matrix={matrix} />
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

      {sponsors && (
        <div className="partners">
          <span className="partners-label">Партнёры</span>
          <div className="partners-slots">
            {SPONSOR_SLOTS.map((slot) => (
              <div key={slot} className="sponsor-slot" />
            ))}
          </div>
        </div>
      )}
    </article>
  )
}
