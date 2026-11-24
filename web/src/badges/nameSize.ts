/** Размер шрифта имени, мм: чем длиннее имя, тем мельче; в колонке 36 мм оно умещается в две строки. */
export function nameSizeMm(name: string): number {
  const length = [...name].length
  if (length <= 9) return 3.6
  if (length <= 14) return 3.2
  if (length <= 19) return 2.9
  return 2.7
}
