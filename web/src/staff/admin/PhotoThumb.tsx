import type { Participant } from '../api.ts'
import { photoUrl } from '../api.ts'

/** Силуэт вместо фото: векторный, цвета берутся из темы. */
export function PhotoPlaceholder() {
  return (
    <svg className="photo-silhouette" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="8.5" r="4" fill="currentColor" />
      <path d="M4 21c0-4.4 3.6-7.5 8-7.5s8 3.1 8 7.5z" fill="currentColor" />
    </svg>
  )
}

/** Круглая миниатюра участника для списка. */
export function PhotoThumb({ person }: { person: Participant }) {
  return person.has_photo ? (
    <img
      className="photo-thumb"
      src={photoUrl(person.code, person.photo_version)}
      alt=""
      loading="lazy"
      width={36}
      height={36}
    />
  ) : (
    <span className="photo-thumb photo-empty">
      <PhotoPlaceholder />
    </span>
  )
}
