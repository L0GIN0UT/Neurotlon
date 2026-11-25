import * as t from './texts.ts'
import type { SensorEntry } from './types.ts'

/** Делений приёма из четырёх: пороги для Bluetooth-RSSI в комнате. */
export function rssiBars(rssi: number | null): number {
  if (rssi === null) return 0
  if (rssi >= -55) return 4
  if (rssi >= -65) return 3
  if (rssi >= -75) return 2
  return 1
}

/** Текст состояния датчика роли: цвет только дополняет слова. */
export function linkStatus(d: SensorEntry): { text: string; tone: 'good' | 'warn' | 'bad' | 'muted' } {
  const l = t.SETUP.sensorsLink
  if (d.link === 'failed') return { text: l.failed, tone: 'bad' }
  if (d.link === 'lost' || !d.in_range) return { text: l.lost, tone: 'warn' }
  if (d.link === 'connecting') return { text: l.connecting, tone: 'muted' }
  if (d.link === 'connected') {
    if (d.contact === false) return { text: l.contactLost, tone: 'warn' }
    if (d.signal) return { text: l.signal, tone: 'good' }
    return { text: l.connected, tone: 'muted' }
  }
  return { text: l.idle, tone: 'muted' }
}
