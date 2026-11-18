/** Совпадает ли адрес со страницей: `/admin` и `/admin/…`, но не `/administrator`. */
export function matches(pathname: string, path: string): boolean {
  return pathname === path || pathname.startsWith(`${path}/`)
}
